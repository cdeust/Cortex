"""Helpers for the remember handler — gate evaluation, modulation, curation, storage.

Extracted to keep remember.py under 300 lines with all methods under 40 lines.
"""

from __future__ import annotations

import os
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
from mcp_server.core.dual_store_cls import classify_memory
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty,
    compute_entity_novelty,
    compute_novelty_score,
    compute_structural_novelty,
)
from mcp_server.core.predictive_coding_gate import gate_decision
from mcp_server.handlers import validate_memory
from mcp_server.handlers.remember_response import build_response
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure


def compute_similarities(
    embedding: Any,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> tuple[list[float], list[tuple]]:
    """Compute vector similarities for the top-5 nearest neighbors."""
    sims: list[float] = []
    vec_hits: list[tuple] = []
    if embedding:
        # heads_only: novelty must be scored against CURRENT knowledge —
        # against a dead superseded version, a legitimate re-write of the
        # corrected fact would be gated out as "not novel".
        vec_hits = store.search_vectors(
            embedding, top_k=5, min_heat=0.0, heads_only=True
        )
        for mid, _d in vec_hits:
            mem = store.get_memory(mid)
            if mem and mem.get("embedding"):
                sims.append(emb_engine.similarity(embedding, mem["embedding"]))
    return sims, vec_hits


def compute_template_normalized_similarities(
    content: str,
    vec_hits: list[tuple],
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> list[float] | None:
    """Re-score embedding-novelty candidates on template-normalized text.

    Pivot (i7d3, 2026-07-11 — narrowed from M-D1's original 3-point scope
    after a benchmark regression whose root cause was NOT this code but a
    shared bench-container concurrency hole; the pivot is kept anyway
    because it is strictly safer and now provably bench-neutral by
    construction — see module docstring and the incident note in
    core/capture_template_normalize.py). NEVER touches the ``embedding``
    column or any stored vector: this recomputes similarity purely to
    feed the write gate's ``emb_nov`` signal, using content re-fetched
    from ``store`` (already fetched by ``compute_similarities`` above,
    re-fetched here to keep this function pure of the caller's
    embedding-fetch loop) and encoded on the fly. The extra ``encode()``
    calls (up to 5, one per top-5 neighbor) are skipped entirely unless
    ``content`` actually matches the auto-capture or derived-fact
    template — for the ~92%/8% traffic split documented in the design
    (auto-capture / deliberate), this keeps the added latency scoped to
    exactly the class where template collision was measured (i6d2:
    0.95-0.99 cosine on DISTINCT auto-captured facts).

    Contract:
      pre:  ``content`` is the new memory's raw content; ``vec_hits`` is
            the (id, distance) list ``compute_similarities`` already
            retrieved via HNSW against the RAW stored embedding space
            (unaffected by this function — candidate retrieval stays on
            the untouched vector space).
      post: returns None when ``content`` does not match either template
            (the caller falls back to the raw ``sims`` from
            ``compute_similarities`` — normalization would be a no-op,
            so skipping it saves the extra encode() calls entirely).
            Otherwise returns one normalized-space cosine similarity per
            neighbor whose content could be fetched and encoded
            (silently drops a neighbor on fetch/encode failure — a
            missing signal degrades gracefully to fewer samples, never
            raises).
    """
    if not (is_auto_capture_template(content) or is_derived_fact_template(content)):
        return None
    new_norm = capture_template_normalize(content)
    new_emb = emb_engine.encode(new_norm)
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
    from mcp_server.core import knowledge_graph

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

    Routes the same content/entity/recent-memory evidence the flat path uses
    through the 3-level predictive hierarchy (Friston 2005) and returns the
    sigmoid ``novelty_score``, which is on the identical [0, 1] scale as
    ``compute_novelty_score`` — so the gate threshold and calibration EMA are
    unaffected by the choice of scorer. Schema level (L2) uses the neutral
    default schema_match here because schema matching runs after the gate
    (apply_modulations).

    MEASURED LIMITATION (benchmarks/gate_precision, 2026-06-11): this scorer
    does NOT separate novel content from duplicates of stored content —
    ROC-AUC 0.5514 vs 0.9998 for the flat path. The neutral L2 default makes
    its free energy a constant 1.5, flooring the score above the default
    threshold for all content, and no level sees embedding similarity to the
    nearest stored neighbor (the flat path's dominant duplicate signal).
    Kept behind WRITE_GATE_HIERARCHICAL=False pending an L0/L2 redesign;
    any change must re-run benchmarks/gate_precision/run_benchmark.py.
    """
    from mcp_server.core.hierarchical_predictive_coding import (
        compute_hierarchical_novelty,
    )
    from mcp_server.core.predictive_coding_signals import extract_sensory_features

    features = [
        extract_sensory_features(m["content"]) for m in recent if m.get("content")
    ]
    prediction = compute_hierarchical_novelty(content, ent_names, known, features)
    return prediction.novelty_score


def _compute_gate_decision(
    score: float,
    force: bool,
    content: str,
    tags: list[str],
    domain: str = "",
    write_class: str = "",
) -> tuple[bool, str, float]:
    """Determine whether to store based on novelty score and bypass rules.

    Returns (should_store, gate_reason, effective_threshold). The threshold
    is the calibration-adjusted value for the domain (Taleb AF-5 feedback
    loop); callers that observe the decision should feed it back via
    ``write_gate_calibration.record`` so the EMA converges to the target
    acceptance rate.

    ``write_class`` (issue #147 fix): threaded into ``determine_bypass`` so
    a resolved ``deliberate`` write is never rejected for low novelty, per
    the tool's documented contract.
    """
    bypass, bypass_reason = write_gate.determine_bypass(
        force, content, tags, write_class=write_class
    )
    settings = get_memory_settings()
    base_threshold = settings.WRITE_GATE_THRESHOLD
    # Calibrated threshold overrides the static setting once the per-domain
    # EMA has enough samples (see write_gate_calibration.effective_threshold).
    threshold = write_gate_calibration.effective_threshold(
        domain, default_threshold=base_threshold
    )
    should_store, gate_reason = gate_decision(score, threshold=threshold, bypass=bypass)
    if bypass_reason:
        gate_reason = bypass_reason
    return should_store, gate_reason, threshold


def evaluate_gate(
    content: str,
    tags: list[str],
    embedding: Any,
    force: bool,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
    domain: str = "",
    write_class: str = "",
) -> dict[str, Any]:
    """Compute all novelty signals and gate decision.

    Contract:
      pre:  content is a non-empty string; embedding is either None or a
            valid vector; ``domain`` is the resolved (normalised) domain
            for this write path; ``write_class`` is the ALREADY-RESOLVED
            class from ``core.write_class.classify_write_class`` (issue
            #147) — ``""`` only for callers/tests that don't care about
            the write-class contract; production callers always pass the
            resolved value (never ``""``).
      post: the returned dict contains ``should_store``, the observed
            ``gate_reason``, and the ``gate_threshold`` actually used for
            the decision. Side effect: the per-domain calibration EMA is
            updated via ``write_gate_calibration.record`` when the decision
            was NOT a bypass (bypasses are not informative for calibration).
            A resolved ``write_class == "deliberate"`` NEVER yields
            ``should_store is False`` (contract: deliberate writes are
            never novelty-rejected; near-duplicates are still merged/
            linked/superseded by ``try_curation`` afterward).
    """
    importance = thermodynamics.compute_importance(content, tags)
    sims, vec_hits = compute_similarities(embedding, store, emb_engine)
    # i7d3 pivot: template-normalized re-scoring feeds ONLY this novelty
    # signal — `sims`/`vec_hits` above (and the `embedding` written to
    # storage by the caller) are untouched raw-content vectors. See
    # compute_template_normalized_similarities's docstring.
    norm_sims = compute_template_normalized_similarities(
        content, vec_hits, store, emb_engine
    )
    emb_nov = compute_embedding_novelty(norm_sims if norm_sims is not None else sims)
    extracted, ent_names, known, ent_nov = compute_entity_info(content, store)
    temp_nov = write_gate.compute_temporal_novelty(sims, vec_hits, store.get_memory)
    # heads_only: structural novelty against current knowledge (same
    # rationale as compute_similarities above).
    # M-D1 §7.3: shape features are compared on the template-normalized
    # text — a corpus at 92% auto-captures of near-identical structural
    # shape (same header, same reference-line kind, same fence pattern)
    # was flooring structural novelty for the whole traffic class. The
    # stored `recent` contents are read-only here; nothing is mutated.
    recent = store.get_hot_memories(min_heat=0.0, limit=10, heads_only=True)
    struct_nov = compute_structural_novelty(
        capture_template_normalize(content),
        [capture_template_normalize(m["content"]) for m in recent if m.get("content")],
    )
    score = compute_novelty_score(emb_nov, ent_nov, temp_nov, struct_nov)
    if get_memory_settings().WRITE_GATE_HIERARCHICAL:
        score = _hierarchical_novelty_score(content, ent_names, known, recent)
    # E1 habituation & sensitization: damp the novelty of a repeated identical
    # low-salience input toward rejection (exponential response decrement,
    # Rankin 2009), and transiently amplify it just after a salient event
    # (dishabituation / sensitization). Non-fatal, behavior-preserving on a
    # first-seen signature, and ablatable via CORTEX_ABLATE_HABITUATION=1.
    score, habituation_info = write_gate.apply_habituation(
        score, content, importance, store
    )
    # A3 goal / task-set maintenance: while a goal (promoted from active
    # prospective triggers) is in play, favor goal-relevant inputs at the gate
    # with a small multiplicative novelty gain (Miller & Cohen 2001 task-set
    # biasing). No active goal / off-task input => gain 1.0 => score unchanged.
    # Non-fatal, ablatable via CORTEX_ABLATE_GOAL_MAINTENANCE=1. DESIGN
    # INFERENCE — a keyword/entity goal-match nudge, not a learned PFC controller.
    score, goal_info = write_gate.apply_goal_maintenance(
        score, content, ent_names, store
    )
    should_store, gate_reason, threshold = _compute_gate_decision(
        score, force, content, tags, domain=domain, write_class=write_class
    )
    # AF-5 feedback: record non-bypass decisions to drive the EMA. Bypasses
    # (force, error, decision, important_tag, deliberate write_class) carry
    # no calibration signal because the gate didn't actually decide on
    # novelty.
    settings = get_memory_settings()
    is_bypass = gate_reason in {
        "bypass",
        "forced",
        "bypass_error",
        "bypass_decision",
        "bypass_important_tag",
        "bypass_write_class_deliberate",
    }
    if not is_bypass:
        write_gate_calibration.record(
            domain,
            accepted=should_store,
            default_threshold=settings.WRITE_GATE_THRESHOLD,
        )
    return {
        "importance": importance,
        "sims": sims,
        "vec_hits": vec_hits,
        "emb_nov": emb_nov,
        "extracted": extracted,
        "ent_names": ent_names,
        "known": known,
        "ent_nov": ent_nov,
        "temp_nov": temp_nov,
        "struct_nov": struct_nov,
        "score": score,
        "should_store": should_store,
        "gate_reason": gate_reason,
        "gate_threshold": threshold,
        "habituation": habituation_info,
        "goal_maintenance": goal_info,
    }


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
    import json as _json

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
    except Exception as exc:
        # Same shape as the spread_activation incident: a broken SELECT
        # here is indistinguishable from "no existing block row", so the
        # caller silently falls through to inserting a DUPLICATE row
        # instead of superseding — must be observable, not just absorbed.
        silent_failure.note("remember_helpers.block_supersede_select", exc)
        return False, None

    if not rows:
        return False, None

    existing_id = rows[0]["id"] if isinstance(rows[0], dict) else rows[0][0]

    # Refresh content, embedding, tags, source; preserve heat and is_protected.
    import numpy as _np

    emb_bytes = None
    if embedding is not None:
        try:
            emb_bytes = _np.asarray(embedding, dtype=_np.float32).tobytes()
        except Exception:
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
    except Exception as exc:
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
        for cand_id, _d in store.search_vectors(embedding, top_k=3, min_heat=0.0):
            cand = store.get_memory(cand_id)
            if not cand or not cand.get("embedding"):
                continue
            # Head-check: never merge/link into (or supersede) a superseded
            # version — the write would be buried in a row the read path
            # excludes. No signal is lost: the chain head is near-identical
            # in embedding and remains in the candidate set. Mirrors the
            # write-path guards (validate_supersede_target rejects superseded
            # targets; supersede_atomic rebases via _current_chain_head).
            if cand.get("superseded_by_id") is not None:
                continue
            sim = emb_engine.similarity(embedding, cand["embedding"])
            overlap = curation.compute_textual_overlap(content, cand["content"]) > 0.5
            action = curation.decide_curation_action(sim, overlap)
            if action == "merge":
                # A near-duplicate that CONTRADICTS the existing fact is a
                # knowledge update, not a duplicate. Retain both rows and
                # record an explicit supersession edge instead of folding
                # the old content away (merge is destructive → would lose
                # "what did X say before?"). Contradiction signal is the
                # existing committed heuristic (negation mismatch / action
                # divergence) — no new constants introduced here.
                if curation.detect_contradictions(content, [cand]):
                    return "supersede", cand_id
                _do_merge(cand, cand_id, content, tags, heat, store, emb_engine)
                return "merge", cand_id
            if action == "link":
                return "link", cand_id
    except Exception:
        pass
    return "create", None


def _do_merge(
    cand: dict,
    cand_id: int,
    content: str,
    tags: list[str],
    heat: float,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> None:
    """Merge new content into an existing memory."""
    merged = curation.merge_contents(cand["content"], content)
    # i7d3 pivot: the stored embedding stays raw content, same as
    # remember.py's write path — see that module's comment for the
    # incident/decision this reverted.
    new_emb = emb_engine.encode(merged)
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
    # C1 source / reality monitoring: attribute the memory's epistemic origin
    # (perceived / told / inferred) from its content + ingestion pathway, so a
    # self-generated inference is not stored indistinguishably from a file-
    # grounded observation (Johnson, Hashtroudi & Lindsay 1993). Best-effort —
    # a classification failure must never block a write.
    #
    # I6-D6 note (kept, not neutralized — écriture initiale != grade): this
    # write is an EPISTEMIC-ORIGIN classification (perceived/told/inferred/
    # unknown, Johnson 1993), not a verifiability GRADE (verified/verifiable/
    # unverifiable, core/provenance.py). validate_memory.py is the sole writer
    # of the GRADE vocabulary and OVERWRITES whatever value is here the next
    # time it verifies this memory — so this column transiently holds C1's
    # epistemic tag for a freshly-written, not-yet-verified memory, and the
    # verifier's grade for a memory that has been through a validate_memory
    # pass. Neutralizing this write outright would silently disable the
    # confabulation gate (recall_helpers.annotate_source_attribution,
    # consolidation_engine promotion gate) — a live, tested, academically-
    # sourced feature (Johnson & Raye 1981) the I6-D6 design did not account
    # for (it landed on this column after the design's audit commit). See
    # /memories/engineer/inc6.5-provenance-verifier.md for the full rationale.
    try:
        from mcp_server.core import source_monitoring

        record["source_attribution"] = source_monitoring.classify_source(
            content, source_field=source
        ).attribution
    except Exception:
        record["source_attribution"] = "unknown"
    # E1 habituation: persist the normalised stimulus-identity key so that the
    # next presentation of this same content is counted as a repeat by the write
    # gate (signature_repeat_stats -> response decrement, Rankin 2009).
    # Best-effort — a signature failure must never block a write.
    try:
        from mcp_server.core import habituation

        record["stimulus_signature"] = habituation.stimulus_signature(content)
    except Exception:
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

    Tags, not a `relationships` row: `relationships.source_entity_id` /
    `target_entity_id` are `NOT NULL REFERENCES entities(id)` and cannot
    address a memory id. The prior implementation (`_link_if_needed`,
    replaced here) called `store.insert_relationship({"source_entity_id":
    mem_id, "target_entity_id": merged_id, ...})` inside a bare
    `except Exception: pass` — every "link" write raised the FK violation and
    was silently swallowed, so no link was ever persisted since this code's
    introduction. Fixed at the source: provenance is now embedded in the
    row's own tags at insert time (before the row exists, so no post-hoc
    update is needed either), reusing the `derived-src:<memory_id>`
    convention already established and live-proven by
    `handlers/consolidation/memify_derive.py` (INC6.1b).
    """
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


def _grade_content_best_effort(
    content: str, *, directory: str
) -> tuple[provenance.ProvenanceReport, str | None]:
    """Best-effort wrapper around ``validate_memory.grade_from_content``.

    Root cause (issue #147): ``grade_from_content``'s ``base_dir`` fallback
    calls ``os.getcwd()``, which raises ``FileNotFoundError`` when the
    process's current working directory no longer exists (e.g. a worktree
    the session was running in got cleaned up). Every OTHER enrichment step
    in this insert path (``source_attribution`` classification, the
    habituation signature) is already wrapped defensively; this call was
    the sole exception -- an unguarded I/O-adjacent call inside what the
    surrounding function's own contract calls a best-effort pass. Fixed at
    the source by matching the established local pattern instead of
    special-casing ``os.getcwd()``.

    Postcondition: NEVER raises. On success returns
    ``(grade_report, None)``. On any failure returns a fallback
    ``ProvenanceReport`` graded ``UNVERIFIABLE`` (the same "we don't know"
    default ``grade_provenance`` uses for zero extractable references) plus
    the failing exception's type name, so the caller can surface it as an
    observable tag instead of a silently absorbed enrichment.
    """
    try:
        base_dir = directory or os.getcwd()
    except OSError as exc:
        return (
            provenance.ProvenanceReport(
                memory_id=0, grade=provenance.UNVERIFIABLE, ref_counts={}
            ),
            type(exc).__name__,
        )
    try:
        return (
            validate_memory.grade_from_content(
                content, directory_context=directory, base_dir=base_dir
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 — grading must never block a write
        return (
            provenance.ProvenanceReport(
                memory_id=0, grade=provenance.UNVERIFIABLE, ref_counts={}
            ),
            type(exc).__name__,
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
    sims: list[float],
    vec_hits: list[tuple],
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
) -> dict[str, Any]:
    """Separate, store, and run post-storage operations.

    ``write_class`` (M-D2, 7.4): already resolved and validated by the
    caller (``handlers/remember.py``, the single choke point —
    ``mcp_server.core.write_class.validate_write_class`` +
    ``classify_write_class``) — this function trusts it and threads it
    straight into the insert record.
    """
    is_dec = thermodynamics.is_decision_content(content)
    stype = classify_memory(content, tags, directory)
    embedding, sep, interf = write_gate.apply_pattern_separation(
        embedding,
        sims,
        vec_hits,
        store,
        emb_engine,
    )
    # Link provenance is appended AFTER classify_memory so the link marker
    # tags never influence store_type classification, and BEFORE the record
    # is built so the pointer is written atomically with the row (no memory
    # id exists yet to update post-hoc).
    tags = _with_link_provenance(action, merged_id, tags)
    # M-D5 (7.5): grade this not-yet-inserted content's provenance with the
    # SAME local-only checks validate_memory's batch pass uses (no network
    # -- see validate_memory.grade_from_content). Persisted as an ADDITIVE
    # TAG (same no-post-hoc-update pattern as _with_link_provenance above),
    # never into `source_attribution` -- that column's grade vocabulary has
    # exactly one writer, validate_memory.py (I6-D6). A second writer there
    # would silently defeat the C1 confabulation gate
    # (core/source_monitoring.py::recall_confabulation_risk), which fires
    # only on the PERCEIVED epistemic tag C1's classify_source writes to
    # that same column below, in _build_insert_record -- see
    # /memories/engineer/inc6.5-provenance-verifier.md. Runs strictly AFTER
    # evaluate_gate() (called by remember.py before this function), so the
    # tag can never influence the novelty/gate decision -- bench-neutral by
    # construction, no G-bench required for this increment.
    grade_report, grading_error = _grade_content_best_effort(
        content, directory=directory
    )
    tags = [*tags, f"prov:{grade_report.grade}"]
    if grading_error is not None:
        # issue #147: grade_from_content's os.getcwd() fallback can raise
        # FileNotFoundError when the process cwd has been removed mid-session
        # (e.g. a worktree cleanup) -- unrelated to the DB and unrelated to
        # write_class. This step is documented as best-effort (like every
        # other enrichment in this function -- source_attribution above,
        # habituation signature below); it must never block the insert.
        # Surfaced as an observable tag rather than silently absorbed
        # (coding-standards.md: no silent fallbacks).
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
    # M-D5 (7.5): surface the write-time provenance grade (transient
    # feedback, never persisted into source_attribution -- see the tag
    # comment above) so the writer sees, in the SAME response, whether
    # their claim carries a checkable reference and can complete it by
    # superseding this memory if not.
    response["provenance"] = {
        "grade": grade_report.grade,
        "checkable_refs": grade_report.ref_counts,
        "hint": provenance.write_time_hint(grade_report, write_class),
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
        # The row actually superseded is the chain head the edge landed on —
        # equal to merged_id unless a concurrent race rebased the write.
        response["superseded_id"] = superseded_head
    return response


def _build_supersede_conflict(
    target_id: int, current_head_id: int | None
) -> dict[str, Any]:
    """Report a supersession that could not converge on a stable chain head.

    Reached only when ``store.supersede_atomic`` exhausts its bounded
    reconsolidation rebase: every attempt lost the compare-and-set to a
    concurrent writer moving the head. Because each attempt runs the insert and
    the edge inside ONE transaction, a lost attempt rolls the insert back —
    nothing is ever committed, so no row is orphaned and none is left
    disconnected. The caller still holds the content and the id of the current
    head, so it can rebase and retry (optimistic concurrency, 409-style). There
    is deliberately no delete and no orphan_memory_id: the atomic rollback makes
    both impossible, a stronger guarantee than the former rollback-over-orphan.
    """
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


# ── User-mood EMA hook (Bower 1981 mood-congruent recall, signal side) ──
# Engineering default; calibration pending future work — Bower (1981)
# "Mood and Memory" Am. Psychologist 36(2) prescribes mood-congruent
# recall qualitatively, not the time-constant of mood drift. No published
# psychophysics constant for the EMA decay of self-report mood at the
# session timescale was located (April 2026). Conservative default
# matches the structural form of other Cortex EMAs (write_gate_calibration).
# When a published value is found, replace this constant and cite.
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

    User-side definition (self-flagged risk addressed):
      Only source == "user" updates mood. System-generated memories
      (source ∈ {"tool", "consolidation", "import"}) and conversational
      transcripts (source == "session", which is mixed agent/user)
      do NOT mutate user_mood, because their content does not reflect
      the user's affective state at recall time.

      Ablation symmetry: when CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1,
      we also skip the write so the table doesn't accumulate signal
      that's then ignored downstream (clean ablation deltas).
    """
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
