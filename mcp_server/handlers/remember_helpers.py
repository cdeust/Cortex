"""Helpers for the remember handler — gate evaluation, modulation, curation, storage.

source: ADR-0438"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from mcp_server.core import (
    curation,
    provenance,
    thermodynamics,
    write_gate,
    write_gate_calibration,
    write_post_store,
)
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.capture_template_normalize import (
    capture_template_normalize,
    is_auto_capture_template,
    is_derived_fact_template,
)
from mcp_server.shared.vader import vader_compound
from mcp_server.shared.memory_rows import MemoryReader, MemoryRows
from mcp_server.handlers.remember_prepared import ObservedNeighbors
from mcp_server.core.dual_store_cls import classify_memory
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty,
    compute_entity_novelty,
    compute_novelty_score,
    compute_structural_novelty,
)
from mcp_server.core.predictive_coding_gate import gate_decision
from mcp_server.handlers import validate_memory
from mcp_server.handlers.remember_preflight import (
    GateObservation,
    GateOptions,
    GateRequest,
    modulate_score,
)
from mcp_server.handlers.remember_response import build_response
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure
from mcp_server.core import capture_origin
from mcp_server.core import knowledge_graph, source_monitoring, habituation
from mcp_server.core.hierarchical_predictive_coding import compute_hierarchical_novelty
from mcp_server.core.predictive_coding_signals import extract_sensory_features
import json as _json
import numpy as _np


# source: ADR-0438
_TEXTUAL_OVERLAP_THRESHOLD = 0.5


def compute_similarities(
    embedding: Any,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> tuple[list[float], list[tuple]]:
    """Compute vector similarities for the top-5 nearest neighbors."""
    sims, hits, _rows = _similarities_with_rows(embedding, store, emb_engine)
    return sims, hits


def _similarities_with_rows(
    embedding: Any, store: MemoryStore, emb_engine: EmbeddingEngine
) -> tuple[list[float], list[tuple], MemoryRows]:
    """Observe complete neighbors once for raw, normalized and temporal signals."""
    sims: list[float] = []
    vec_hits: list[tuple] = []
    memories = MemoryRows({})
    if embedding:
        # source: ADR-0438
        vec_hits = store.search_vectors(
            embedding, top_k=5, min_heat=0.0, heads_only=True
        )
        memories = MemoryRows.read(store, [mid for mid, _d in vec_hits])
        for mid, _d in vec_hits:
            emb = (memories.get_memory(mid) or {}).get("embedding")
            if emb is not None and len(emb):
                sims.append(emb_engine.similarity(embedding, emb))
    return sims, vec_hits, memories


def compute_template_normalized_similarities(
    content: str,
    vec_hits: list[tuple],
    store: MemoryReader,
    emb_engine: EmbeddingEngine,
) -> list[float] | None:
    """Preserve the scalar normalized-space scoring contract exactly.

    source: ADR-0438"""
    if not (is_auto_capture_template(content) or is_derived_fact_template(content)):
        return None
    new_emb = emb_engine.encode(capture_template_normalize(content))
    if not new_emb:
        return None
    norm_sims: list[float] = []
    for mid, _d in vec_hits:
        mem = store.get_memory(mid)
        if not mem or not mem.get("content"):
            continue
        neighbor_emb = emb_engine.encode(capture_template_normalize(mem["content"]))
        if neighbor_emb:
            norm_sims.append(emb_engine.similarity(new_emb, neighbor_emb))
    return norm_sims


def compute_entity_info(
    content: str, store: MemoryStore
) -> tuple[list[dict], list[str], set[str], float]:
    """Extract entities and compute entity novelty score."""

    extracted = knowledge_graph.extract_entities(content)
    names = [e["name"] for e in extracted]
    known: set[str] = {n for n in names if store.get_entity_by_name(n)}
    return extracted, names, known, compute_entity_novelty(names, known)


def _hierarchical_novelty_score(
    content: str,
    ent_names: list[str],
    known: set[str],
    recent: list[dict],
) -> float:
    """Hierarchical free-energy novelty score in [0, 1].

    source: ADR-0438"""

    features = [
        extract_sensory_features(m["content"]) for m in recent if m.get("content")
    ]
    prediction = compute_hierarchical_novelty(content, ent_names, known, features)
    return prediction.novelty_score


def evaluate_gate(
    content: str,
    tags: list[str],
    embedding: Any,
    force: bool,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
    domain: str = "",
    write_class: str = "",
    origin: str = capture_origin.ORIGIN_UNKNOWN,
) -> dict[str, Any]:
    """Compute all novelty signals and gate decision.

    Contract:
      pre:  content is a non-empty string; embedding is either None or a
            valid vector; ``domain`` is the resolved (normalised) domain
            for this write path; ``write_class`` is the ALREADY-RESOLVED
            class from ``core.write_class.classify_write_class`` — ``""`` only for
            callers/tests that don't care about
            the write-class contract; production callers always pass the
            resolved value (never ``""``).
      post: the returned dict contains ``should_store``, the observed
            ``gate_reason``, and the ``gate_threshold`` actually used for
            the decision. Side effect: the per-domain calibration EMA is
            updated via ``write_gate_calibration.record`` when the decision
            was NOT a bypass .
            A resolved ``write_class == "deliberate"`` NEVER yields
            ``should_store is False`` (contract: deliberate writes are
            never novelty-rejected; near-duplicates are still merged/
            linked/superseded by ``try_curation`` afterward).

    source: ADR-0438"""
    request = GateRequest(
        content, tags, store, GateOptions(force, domain, write_class, origin)
    )
    return evaluate_observed_gate(request, None, embedding, emb_engine)


def observe_gate(request: GateRequest) -> GateObservation:
    """Read embedding-independent evidence once for both bound and fallback."""
    content, store = request.content, request.store
    importance = thermodynamics.compute_importance(content, request.tags)
    extracted, names, known, entity = compute_entity_info(content, store)
    # source: ADR-0438
    recent = store.get_hot_memories(min_heat=0.0, limit=10, heads_only=True)
    structural = compute_structural_novelty(
        capture_template_normalize(content),
        [capture_template_normalize(m["content"]) for m in recent if m.get("content")],
    )
    modulations = (
        write_gate.prepare_habituation(content, importance, store),
        write_gate.prepare_goal_maintenance(content, names, store),
    )
    default = get_memory_settings().WRITE_GATE_THRESHOLD
    threshold = write_gate_calibration.effective_threshold(
        request.options.domain,
        default_threshold=default,
    )
    return GateObservation(
        {
            "importance": importance,
            "extracted": extracted,
            "ent_names": names,
            "known": known,
            "ent_nov": entity,
            "struct_nov": structural,
            "recent": recent,
        },
        modulations,
        (threshold, default),
    )


def _observed_decision(
    request: GateRequest, score: float, observed: GateObservation
) -> tuple[bool, str]:
    options = request.options
    bypass, bypass_reason = write_gate.determine_bypass(
        options.force,
        request.content,
        request.tags,
        write_class=options.write_class,
        origin=options.origin,
    )
    should_store, reason = gate_decision(
        score, threshold=observed.thresholds[0], bypass=bypass
    )
    if bypass_reason:
        reason = bypass_reason
    if not bypass:
        write_gate_calibration.record(
            options.domain,
            accepted=should_store,
            default_threshold=observed.thresholds[1],
        )
    return should_store, reason


def _finish_observed_gate(
    request: GateRequest, observed: GateObservation, vector_signals: dict
) -> dict[str, Any]:
    signals = {k: v for k, v in observed.signals.items() if k != "recent"}
    signals.update(vector_signals)
    score = compute_novelty_score(
        signals["emb_nov"],
        signals["ent_nov"],
        signals["temp_nov"],
        signals["struct_nov"],
    )
    if get_memory_settings().WRITE_GATE_HIERARCHICAL:
        score = _hierarchical_novelty_score(
            request.content,
            signals["ent_names"],
            signals["known"],
            observed.signals["recent"],
        )
    score, habituation_info, goal_info = modulate_score(score, observed)
    should_store, reason = _observed_decision(request, score, observed)
    return {
        **signals,
        "score": score,
        "should_store": should_store,
        "gate_reason": reason,
        "gate_threshold": observed.thresholds[0],
        "habituation": habituation_info,
        "goal_maintenance": goal_info,
    }


def evaluate_observed_gate(
    request: GateRequest,
    observed: GateObservation | None,
    embedding: Any,
    emb_engine: EmbeddingEngine,
) -> dict[str, Any]:
    """Compute actual vector signals; reuse any preflight evidence unchanged."""
    content, store = request.content, request.store
    sims, hits, memories = _similarities_with_rows(embedding, store, emb_engine)
    normalized = compute_template_normalized_similarities(
        content, hits, memories, emb_engine
    )
    embedding_novelty = compute_embedding_novelty(
        normalized if normalized is not None else sims
    )
    if observed is None:
        observed = observe_gate(request)
    temporal = write_gate.compute_temporal_novelty(sims, hits, memories.get_memory)
    return _finish_observed_gate(
        request,
        observed,
        {
            "sims": sims,
            "vec_hits": hits,
            "emb_nov": embedding_novelty,
            "temp_nov": temporal,
            "neighbors": ObservedNeighbors(sims, hits, memories),
        },
    )


def apply_modulations(
    content: str,
    tags: list[str],
    heat: float,
    importance: float,
    valence: float,
    domain: str,
    ent_names: list[str],
    known: set[str],
    store: MemoryStore,
) -> dict[str, Any]:
    """Apply oscillatory, schema, neuromodulation, and emotional tagging."""
    heat, theta, enc_mod, osc = write_gate.apply_oscillatory_context(store, heat)
    sm, sid = write_gate.match_schema(domain, ent_names, tags, store)
    heat, importance, nm = write_gate.apply_neuromodulation(
        content,
        ent_names,
        known,
        theta,
        osc,
        sm,
        importance,
        heat,
    )
    importance, heat, valence, etag = write_gate.apply_emotional_tagging(
        content,
        importance,
        heat,
        valence,
    )
    return {
        "heat": heat,
        "importance": importance,
        "valence": valence,
        "theta": theta,
        "enc_mod": enc_mod,
        "schema_match": sm,
        "schema_id": sid,
        "neuro_mod": nm,
        "emotional_tag": etag,
    }


def try_block_replica_upsert(
    content: str,
    embedding: Any,
    tags: list[str],
    source: str,
    store: MemoryStore,
) -> tuple[bool, int | None]:
    """Upsert a memory-replica block by its vpath: identity tag.

    Precondition:  tags contains 'memory-replica' AND at least one tag
                   starting with 'vpath:'.
    Postcondition: if an existing row with the same vpath: (and same
                   scope: if present) exists, that row's content,
                   embedding, tags, source, and updated_at/ingested_at
                   are refreshed in place; is_protected and heat_base
                   fields of the existing row are preserved (block keeps
                   its thermal state). Returns (True, existing_id).
                   If no existing row, returns (False, None) so the
                   caller proceeds with a normal insert.
    Invariant:     non-replica writes (tags without 'memory-replica')
                   never reach this branch; one row per block file is
                   maintained.
    # contract: zetetic-team-subagents memory/contract.md §8b
    """

    tag_set = {str(t) for t in tags}
    if "memory-replica" not in tag_set:
        return False, None

    vpath_tags = [t for t in tag_set if t.startswith("vpath:")]
    if not vpath_tags:
        return False, None

    vpath_tag = vpath_tags[0]  # single vpath: per block

    # Build JSONB containment predicate for vpath.
    try:
        vpath_json = _json.dumps([vpath_tag])
        rows = store._execute(
            "SELECT id FROM memories "
            "WHERE tags @> %s::jsonb "
            "AND tags @> '[\"memory-replica\"]'::jsonb "
            "LIMIT 1",
            (vpath_json,),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("remember_helpers.block_supersede_select")
        # source: ADR-0438
        silent_failure.note("remember_helpers.block_supersede_select", exc)
        return False, None

    if not rows:
        return False, None

    existing_id = rows[0]["id"]

    # Refresh content, embedding, tags, source; preserve heat and is_protected.

    emb_bytes = None
    if embedding is not None:
        try:
            emb_bytes = _np.asarray(embedding, dtype=_np.float32).tobytes()
        except (ValueError, TypeError):
            emb_bytes = None

    try:
        if emb_bytes is not None:
            store._execute(
                "UPDATE memories "
                "SET content = %s, embedding = %s::vector, "
                "    tags = %s::jsonb, source = %s, "
                "    last_accessed = NOW() "
                "WHERE id = %s",
                (content, emb_bytes, _json.dumps(tags), source, existing_id),
            )
        else:
            store._execute(
                "UPDATE memories "
                "SET content = %s, "
                "    tags = %s::jsonb, source = %s, "
                "    last_accessed = NOW() "
                "WHERE id = %s",
                (content, _json.dumps(tags), source, existing_id),
            )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("remember_helpers.block_supersede_update")
        silent_failure.note("remember_helpers.block_supersede_update", exc)
        return False, None

    return True, existing_id


def try_curation(
    content: str,
    embedding: Any,
    force: bool,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
    tags: list[str],
    heat: float,
) -> tuple[str, int | None]:
    """Decide curation action: create, merge, or link."""
    try:
        if not embedding or force:
            return "create", None
        hits = store.search_vectors(embedding, top_k=3, min_heat=0.0)
        # source: ADR-0438
        rows = (
            MemoryRows.read(store, [mid for mid, _d in hits])
            if hits
            else MemoryRows({})
        )
        for cand_id, _d in hits:
            cand = rows.get_memory(cand_id)
            if not cand or not cand.get("embedding"):
                continue
            # source: ADR-0438
            if cand.get("superseded_by_id") is not None:
                continue
            sim = emb_engine.similarity(embedding, cand["embedding"])
            overlap = (
                curation.compute_textual_overlap(content, cand["content"])
                > _TEXTUAL_OVERLAP_THRESHOLD
            )
            action = curation.decide_curation_action(sim, overlap)
            if action == "merge":
                # source: ADR-0438
                if curation.detect_contradictions(content, [cand]):
                    return "supersede", cand_id
                _do_merge(cand, cand_id, content, embedding, heat, store, emb_engine)
                return "merge", cand_id
            if action == "link":
                return "link", cand_id
    except Exception as exc:  # noqa: BLE001 — dedup failure degrades to plain create
        silent_failure.note("remember_helpers.curation_dedup", exc)
    return "create", None


def _do_merge(
    cand: dict,
    cand_id: int,
    content: str,
    embedding: Any,
    heat: float,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> None:
    """Merge new content into an existing memory."""
    merged = curation.merge_contents(cand["content"], content)
    # source: ADR-0438
    new_emb = embedding if merged == content else emb_engine.encode(merged)
    store.update_memory_compression(
        cand_id, merged, new_emb, cand.get("compression_level", 0)
    )
    store.update_memory_heat(cand_id, max(cand.get("heat", 0), heat))


def _build_insert_record(
    content: str,
    embedding: Any,
    tags: list[str],
    source: str,
    domain: str,
    directory: str,
    mod: dict,
    novelty_score: float,
    is_dec: bool,
    stype: str,
    sep: float,
    interf: float,
    created_at: str | None = None,
    supersedes_id: int | None = None,
) -> dict[str, Any]:
    """Build the memory record dict for insertion."""
    domain = domain.lower().strip() if domain else ""
    record = {
        "content": content,
        "embedding": embedding,
        "tags": tags,
        "source": source,
        "domain": domain,
        "directory_context": directory,
        "heat": mod["heat"],
        "surprise_score": novelty_score,
        "importance": mod["importance"],
        "emotional_valence": mod["valence"],
        "is_protected": is_dec,
        "store_type": stype,
        "consolidation_stage": "labile",
        "theta_phase_at_encoding": mod["theta"],
        "encoding_strength": mod["enc_mod"],
        "separation_index": sep,
        "interference_score": interf,
        "schema_match_score": mod["schema_match"],
        "schema_id": mod["schema_id"],
        "hippocampal_dependency": 1.0,
    }
    # source: ADR-0438
    try:
        record["source_attribution"] = source_monitoring.classify_source(
            content, source_field=source
        ).attribution
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("remember_helpers.source_attribution", exc)
        record["source_attribution"] = "unknown"
    # E1 habituation: persist the normalised stimulus-identity key so that the
    # next presentation of this same content is counted as a repeat by the write
    # gate (signature_repeat_stats -> response decrement, Rankin 2009).
    # Best-effort — a signature failure must never block a write.
    try:
        record["stimulus_signature"] = habituation.stimulus_signature(content)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("remember_helpers.stimulus_signature", exc)
        record["stimulus_signature"] = ""
    etag = mod.get("emotional_tag")
    record["arousal"] = round(etag["arousal"], 4) if etag and "arousal" in etag else 0.0
    record["dominant_emotion"] = (
        etag.get("dominant_emotion", "neutral") if etag else "neutral"
    )
    if created_at:
        record["created_at"] = created_at
        record["stage_entered_at"] = created_at
    if supersedes_id is not None:
        record["supersedes_id"] = supersedes_id
    return record


def _with_link_provenance(
    action: str, merged_id: int | None, tags: list[str]
) -> list[str]:
    """Append link provenance to a to-be-created memory's tags.

        Precondition: `tags` is about to be written on a NEW row (this is called
        before `store.insert_memory`/`store.supersede_atomic`, so no memory id
        exists yet for the row being built); `action`/`merged_id` come from
        `try_curation`'s "link" decision (near-duplicate, not merged/superseded).
        Postcondition: when `action == "link"` and `merged_id` is set, returns
        `tags` plus a `link-derived` category tag and a `derived-src:<merged_id>`
        pointer to the memory this row is a near-duplicate/derivative of;
        otherwise returns `tags` unchanged.

    source: ADR-0438"""
    if action != "link" or not merged_id:
        return tags
    return [*tags, "link-derived", f"derived-src:{merged_id}"]


def _run_post_store(
    mem_id: int,
    content: str,
    directory: str,
    domain: str,
    extracted: list[dict],
    ent_names: list[str],
    mod: dict,
    store: MemoryStore,
    source: str = "",
) -> tuple[list[int], list[dict], dict | None]:
    """Run post-insert operations: triggers, entities, tagging, engram."""
    settings = get_memory_settings()
    tids = write_post_store.extract_triggers(content, directory, store, source=source)
    write_post_store.persist_entities(
        extracted, domain, content, store, memory_id=mem_id
    )
    tagged = write_post_store.run_synaptic_tagging(
        mem_id, mod["importance"], ent_names, store
    )
    slot = write_post_store.allocate_engram_slot(mem_id, settings, store)
    return tids, tagged, slot


@dataclass
class _GradeContext:
    """Result of a best-effort write-time provenance grading pass.

    source: ADR-0438"""

    report: provenance.ProvenanceReport
    grading_error: str | None
    resolution_root: str
    resolution_root_explicit: bool
    resolution_root_exists: bool


def _fallback_grade_context(
    *, resolution_root: str, resolution_root_explicit: bool, error_type: str
) -> _GradeContext:
    return _GradeContext(
        report=provenance.ProvenanceReport(
            memory_id=0, grade=provenance.UNVERIFIABLE, ref_counts={}
        ),
        grading_error=error_type,
        resolution_root=resolution_root,
        resolution_root_explicit=resolution_root_explicit,
        resolution_root_exists=bool(resolution_root) and os.path.isdir(resolution_root),
    )


def _grade_content_best_effort(content: str, *, directory: str) -> _GradeContext:
    """Best-effort wrapper around ``validate_memory.grade_from_content``.

    Postcondition: NEVER raises. Returns a ``_GradeContext`` with
    ``resolution_root_explicit == bool(directory)``. On failure, returns a fallback
    ``ProvenanceReport`` graded ``UNVERIFIABLE`` and the exception type name.

    source: ADR-0438"""
    root_explicit = bool(directory)
    try:
        base_dir = directory or os.getcwd()
    except OSError as exc:
        return _fallback_grade_context(
            resolution_root="",
            resolution_root_explicit=root_explicit,
            error_type=type(exc).__name__,
        )
    root_exists = os.path.isdir(base_dir)
    try:
        report = validate_memory.grade_from_content(
            content, directory_context=directory, base_dir=base_dir
        )
    except Exception as exc:  # noqa: BLE001 — grading must never block a write
        return _fallback_grade_context(
            resolution_root=base_dir,
            resolution_root_explicit=root_explicit,
            error_type=type(exc).__name__,
        )
    return _GradeContext(
        report=report,
        grading_error=None,
        resolution_root=base_dir,
        resolution_root_explicit=root_explicit,
        resolution_root_exists=root_exists,
    )


def insert_and_post_process(
    content: str,
    embedding: Any,
    tags: list[str],
    source: str,
    domain: str,
    directory: str,
    action: str,
    merged_id: int | None,
    neighbors: ObservedNeighbors,
    ent_names: list[str],
    extracted: list[dict],
    mod: dict,
    novelty_score: float,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
    agent_context: str = "",
    is_global: bool = False,
    created_at: str | None = None,
    write_class: str = "deliberate",
    origin: str = capture_origin.ORIGIN_UNKNOWN,
) -> dict[str, Any]:
    """Separate, store, and run post-storage operations.

    ``write_class`` (M-D2, 7.4): already resolved and validated by the
    caller (``handlers/remember.py``, the single choke point —
    ``mcp_server.shared.write_class.validate_write_class`` +
    ``classify_write_class``) — this function trusts it and threads it
    straight into the insert record.
    """
    is_dec = thermodynamics.is_decision_content(content)
    stype = classify_memory(content, tags, directory)
    embedding, sep, interf = write_gate.apply_pattern_separation(
        embedding,
        neighbors.similarities,
        neighbors.hits,
        neighbors.rows,
        emb_engine,
    )
    # source: ADR-0438
    tags = _with_link_provenance(action, merged_id, tags)
    # source: ADR-0438
    grade_ctx = _grade_content_best_effort(content, directory=directory)
    grade_report, grading_error = grade_ctx.report, grade_ctx.grading_error
    tags = [*tags, f"prov:{grade_report.grade}"]
    if grading_error is not None:
        # source: ADR-0438
        tags = [*tags, f"prov-grading-failed:{grading_error}"]
    record = _build_insert_record(
        content,
        embedding,
        tags,
        source,
        domain,
        directory,
        mod,
        novelty_score,
        is_dec,
        stype,
        sep,
        interf,
        created_at=created_at,
        supersedes_id=merged_id if action == "supersede" else None,
    )
    record["agent_context"] = agent_context
    record["is_global"] = is_global
    record["write_class"] = write_class
    # source: ADR-0438
    record["capture_origin"] = origin
    superseded_head: int | None = None
    if action == "supersede" and merged_id is not None:
        # Atomic insert + supersession edge (biomimetic reconsolidation): the
        # new row and the head's back-pointer commit as ONE transaction, so a
        # lost compare-and-set rolls the insert back — never an orphaned,
        # disconnected row. On a race the write rebases onto the current head;
        # only pathological contention returns a conflict (nothing committed).
        mem_id, superseded_head = store.supersede_atomic(record, merged_id)
        if mem_id is None:
            return _build_supersede_conflict(merged_id, superseded_head)
    else:
        mem_id = store.insert_memory(record)
    tids, tagged, slot = _run_post_store(
        mem_id,
        content,
        directory,
        domain,
        extracted,
        ent_names,
        mod,
        store,
        source=source,
    )
    response = build_response(
        mem_id,
        action,
        stype,
        domain,
        mod,
        novelty_score,
        tids,
        extracted,
        slot,
        tagged,
        sep,
        interf,
    )
    # M-D2 (7.4): surface the resolved write class so the caller can
    # confirm what was actually persisted (explicit arg or the
    # source-fallback default).
    response["write_class"] = write_class
    # source: ADR-0438
    response["provenance"] = {
        "grade": grade_report.grade,
        "checkable_refs": grade_report.ref_counts,
        "reason": grade_report.reason,
        "dead_refs": grade_report.dead_refs[:3],
        "hint": provenance.write_time_hint(
            grade_report,
            write_class,
            resolution_root=grade_ctx.resolution_root,
            resolution_root_explicit=grade_ctx.resolution_root_explicit,
            resolution_root_exists=grade_ctx.resolution_root_exists,
        ),
    }
    # C1 source / reality monitoring: surface the stored epistemic attribution
    # so the caller can see whether this memory was perceived / told / inferred.
    # Flag the confabulation risk — an inferred memory carries no external
    # grounding and should not later be cited as observed fact (Johnson 1993).
    attribution = record.get("source_attribution", "unknown")
    response["source_attribution"] = attribution
    if attribution == "inferred":
        response["confabulation_risk"] = True
    if action == "supersede" and merged_id is not None:
        # source: ADR-0438
        response["superseded_id"] = superseded_head
    return response


def _build_supersede_conflict(
    target_id: int, current_head_id: int | None
) -> dict[str, Any]:
    """Report a supersession that could not converge on a stable chain head.

    source: ADR-0438"""
    return {
        "stored": False,
        "action": "superseded_conflict",
        "reason": "supersede_chain_head_moving",
        "supersede_target_id": target_id,
        "current_head_id": current_head_id,
    }


def validate_supersede_target(
    supersedes_raw: Any, store: MemoryStore
) -> tuple[int | None, dict[str, Any] | None]:
    """Resolve and validate an explicit supersession target.

    Returns (supersedes_id, None) when the target is a valid chain head,
    (None, rejection_response) when the argument is malformed, the target
    is missing, or the target is already superseded — an existing chain is
    never forked silently. The head-ness read here is advisory; the
    compare-and-set in the store is the authority under concurrency.
    """
    if supersedes_raw is None:
        return None, None
    try:
        supersedes_id = int(supersedes_raw)
    except (TypeError, ValueError):
        supersedes_id = 0
    if supersedes_id <= 0:
        return None, {
            "stored": False,
            "action": "rejected",
            "reason": "invalid_supersedes_id",
        }
    target = store.get_memory(supersedes_id)
    if target is None:
        return None, {
            "stored": False,
            "action": "rejected",
            "reason": "supersede_target_not_found",
            "supersede_target_id": supersedes_id,
        }
    if target.get("superseded_by_id") is not None:
        return None, {
            "stored": False,
            "action": "rejected",
            "reason": "supersede_target_already_superseded",
            "supersede_target_id": supersedes_id,
            "current_superseded_by_id": target.get("superseded_by_id"),
        }
    return supersedes_id, None


# source: ADR-0438
MOOD_EMA_ALPHA: float = 0.3


def update_user_mood_ema(
    content: str,
    source: str,
    store: MemoryStore,
) -> float | None:
    """EMA-update the user's session-level mood from VADER on user content.

        Contract:
          pre:  content is a hardened, non-empty string; source is one of the
                remember.py source enum values; store exposes get_user_mood /
                set_user_mood (real PgMemoryStore or duck-compatible stub).
          post: when source == "user" AND MOOD_CONGRUENT_RERANK is NOT ablated,
                user_mood.valence is upserted to
                    (1 - α) * old + α * vader_compound(content)
                with α = MOOD_EMA_ALPHA, old defaulting to 0.0 when the row
                is absent. Returns the new valence on update, or None when
                skipped (non-user source, ablated, or store missing API).
                Never raises — failures are swallowed and reported as None.

        Source-discipline notes:
          - VADER compound: Hutto & Gilbert, ICWSM 2014.
          - Mood-congruent recall: Bower 1981 Am. Psychologist 36(2).
          - α = 0.3: engineering default (see module-level comment above).

          Ablation symmetry: when CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1,
          we also skip the write so the table doesn't accumulate signal
          that's then ignored downstream (clean ablation deltas).

    source: ADR-0438"""
    if source != "user":
        return None
    if is_mechanism_disabled(Mechanism.MOOD_CONGRUENT_RERANK):
        return None
    if not hasattr(store, "set_user_mood") or not hasattr(store, "get_user_mood"):
        return None
    try:
        compound = vader_compound(content)
        old = store.get_user_mood()
        old_valence = 0.0 if old is None else float(old)
        new_valence = (1.0 - MOOD_EMA_ALPHA) * old_valence + MOOD_EMA_ALPHA * compound
        # Clamp defensively; set_user_mood clamps too, but we want the
        # returned value to match what was persisted.
        new_valence = max(-1.0, min(1.0, new_valence))
        store.set_user_mood(new_valence)
        return new_valence
    except Exception:  # noqa: BLE001 — non-load-bearing; mood is a soft signal
        return None
