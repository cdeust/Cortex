"""Core write gate logic — novelty signals, bypass detection, oscillatory context.

Pure business logic for the memory write path. No I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp_server.core import capture_origin
from mcp_server.core import coupled_neuromodulation as coupled_nm
from mcp_server.core import (
    content_cues,
    goal_maintenance,
    habituation,
    knowledge_graph,
    oscillatory_clock,
    schema_engine,
    thermodynamics,
)
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.emotional_tagging import tag_memory_emotions
from mcp_server.core.neurogenesis import compute_interference_score
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty as _compute_embedding_novelty,
)
from mcp_server.core.predictive_coding_flat import (
    compute_entity_novelty as _compute_entity_novelty,
)
from mcp_server.core.predictive_coding_flat import (
    compute_structural_novelty as _compute_structural_novelty,
)
from mcp_server.core.predictive_coding_flat import (
    compute_temporal_novelty as _compute_temporal_novelty,
)
from mcp_server.core.predictive_coding_flat import (
    describe_signals as _describe_signals,
)
from mcp_server.core.schema_extraction import schema_from_dict as _schema_from_dict
from mcp_server.core.separation_core import (
    detect_interference_risk,
    orthogonalize_embedding,
)
from mcp_server.observability import silent_failure
import json as _json


def compute_embedding_novelty(
    embedding: Any,
    similarities: list[float],
) -> float:
    """Signal 1: embedding-space novelty."""
    return _compute_embedding_novelty(similarities)


def compute_entity_novelty(
    content: str,
    known_lookup: set[str],
) -> tuple[list[dict], list[str], set[str], float]:
    """Signal 2: entity novelty. Returns entities, names, known set, score."""
    extracted = knowledge_graph.extract_entities(content)
    names = [e["name"] for e in extracted]
    known: set[str] = set()
    for name in names:
        if name in known_lookup:
            known.add(name)
    score = _compute_entity_novelty(names, known)
    return extracted, names, known, score


def compute_temporal_novelty(
    similarities: list[float],
    vec_hits: list[tuple],
    get_memory: Any,
) -> float:
    """Signal 3: temporal novelty from most recent similar memory."""
    hours: float | None = None
    if similarities and vec_hits:
        best_idx = similarities.index(max(similarities))
        if best_idx < len(vec_hits):
            best_mem = get_memory(vec_hits[best_idx][0])
            # Temporal novelty asks "have we seen this in MY system
            # recently?" — that is elapsed-since-ingest, not
            # elapsed-since-the-original-event. Use ingested_at and fall
            # back to created_at for legacy rows.
            # Source: docs/benchmarks/e1-v3-locomo-smoke-finding.md.
            if best_mem and (best_mem.get("ingested_at") or best_mem.get("created_at")):
                ts = best_mem.get("ingested_at") or best_mem["created_at"]
                hours = _parse_hours_since(ts)
    return _compute_temporal_novelty(hours)


def _parse_hours_since(iso_str: str) -> float | None:
    """Parse ISO datetime string and return hours since then."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def compute_structural_novelty(
    content: str,
    recent_contents: list[str],
) -> float:
    """Signal 4: structural novelty against recent memories."""
    return _compute_structural_novelty(content, recent_contents)


def determine_bypass(
    force: bool,
    content: str,
    tags: list[str],
    write_class: str = "",
    origin: str = capture_origin.ORIGIN_UNKNOWN,
) -> tuple[bool, str | None]:
    """Determine if write gate should be bypassed and why.

    ``origin`` (issue #365) is the CHANNEL the content arrived through, from
    ``core/capture_origin.classify_capture_origin`` — never inferred from the
    content. Content-derived bypasses (``bypass_error`` / ``bypass_decision``)
    are refused when the origin may not claim them, because those two are read
    out of the content itself and are therefore exactly what off-machine text
    would forge to install itself in durable, cross-session memory. ``force``
    and a ``deliberate`` write class are out-of-band human signals and stay
    valid at any origin. Defaults to ``ORIGIN_UNKNOWN``, which is permissive,
    so existing callers are unaffected; the untrusted path passes its real
    origin explicitly.

    ``write_class`` (M-D2, issue #147): a resolved ``deliberate`` write is
    NEVER rejected by the novelty gate — this is the tool's documented
    contract (near-duplicates are still merged/linked/superseded by
    ``try_curation`` afterward; bypassing the gate here only skips the
    REJECT verdict, it does not skip curation, which reads ``force``
    independently). ``write_class`` defaults to ``""`` (no bypass) so the
    unit tests exercising the content/tag/force bypass paths in isolation
    are unaffected; the real call site (``remember_helpers._compute_gate_decision``)
    always passes the already-resolved class (never ``""`` — see
    ``core/write_class.classify_write_class``'s postcondition: the return
    value is always one of ``ALL_WRITE_CLASSES``).

    Checked LAST (after the more specific content/tag bypasses): most
    ``remember`` calls resolve to ``deliberate`` by default (any source not
    in the auto/derived/mechanical sets — see ``write_class`` module
    docstring), so checking it first would mask every content-based
    ``bypass_error``/``bypass_decision``/``bypass_important_tag`` reason
    behind the generic ``bypass_write_class_deliberate`` one. Ordering it
    last preserves the more informative diagnostic reason where one
    applies, while still guaranteeing every deliberate write bypasses
    (falling through to the deliberate check when none of the more
    specific conditions matched).
    """
    # A deliberate write class is an out-of-band signal a human supplied, and
    # such a write bypasses regardless (the `write_class == "deliberate"` arm
    # below). Refusing it the SPECIFIC content reason would therefore change no
    # outcome — only the diagnostic, masking bypass_error behind the generic
    # bypass_write_class_deliberate and undoing the ordering issue #147
    # deliberately chose. So the origin allowlist governs whether content may
    # BUY a bypass it would not otherwise get, not how an already-granted one
    # is labelled.
    content_bypass_allowed = (
        capture_origin.may_bypass_write_gate_on_content(origin)
        or write_class == "deliberate"
    )
    is_error = content_bypass_allowed and thermodynamics.is_error_content(content)
    is_decision = content_bypass_allowed and thermodynamics.is_decision_content(content)
    has_important = bool({"important", "critical"} & {t.lower() for t in tags})

    if force:
        return True, "forced"
    if is_error:
        return True, "bypass_error"
    if is_decision:
        return True, "bypass_decision"
    if has_important:
        return True, "bypass_important_tag"
    if write_class == "deliberate":
        return True, "bypass_write_class_deliberate"
    return False, None


def build_rejection_response(
    embedding_novelty: float,
    entity_novelty: float,
    temporal_novelty: float,
    structural_novelty: float,
    novelty_score: float,
    gate_reason: str,
    importance: float,
) -> dict[str, Any]:
    """Build response when write gate rejects the memory."""
    return {
        "stored": False,
        "action": "rejected",
        "reason": gate_reason,
        "novelty": _describe_signals(
            embedding_novelty,
            entity_novelty,
            temporal_novelty,
            structural_novelty,
            novelty_score,
        ),
        "importance": round(importance, 4),
    }


def apply_oscillatory_context(
    store: Any,
    heat: float,
) -> tuple[float, float, float, Any]:
    """Apply oscillatory phase gating. Returns (heat, theta, encoding_mod, state)."""

    osc_state = oscillatory_clock.OscillatoryState()
    theta_phase = 0.0
    encoding_mod = 1.0
    try:
        saved = store.load_oscillatory_state()
        if saved:
            osc_state = oscillatory_clock.state_from_dict(_json.loads(saved))
        osc_state = oscillatory_clock.advance_theta(osc_state, 1)
        theta_phase = osc_state.theta_phase
        encoding_mod = oscillatory_clock.compute_encoding_strength(theta_phase)
        heat = min(1.0, heat * encoding_mod)
        store.save_oscillatory_state(
            _json.dumps(oscillatory_clock.state_to_dict(osc_state)),
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.oscillatory_context")
        silent_failure.note("write_gate.oscillatory_context", exc)
    return heat, theta_phase, encoding_mod, osc_state


def apply_neuromodulation(
    content: str,
    new_entity_names: list[str],
    known_entity_names: set[str],
    theta_phase: float,
    osc_state: Any,
    schema_match: float,
    importance: float,
    heat: float,
) -> tuple[float, float, dict | None]:
    """Apply coupled neuromodulation. Returns (heat, importance, composite)."""
    try:
        is_err = thermodynamics.is_error_content(content)
        # Language-aware success cue (issue #158) — same coverage rules as
        # the decision/error detectors; see content_cues module docstring.
        is_succ = content_cues.is_success_cue(content)
        novel_ent = len([n for n in new_entity_names if n not in known_entity_names])
        signals = coupled_nm.OperationSignals(
            error_encountered=is_err,
            error_resolved=is_succ,
            novel_entities=novel_ent,
            total_entities=len(new_entity_names),
            theta_phase=theta_phase,
            ach_from_theta=osc_state.ach_level,
            schema_match=schema_match,
            memory_importance=importance,
        )
        nm_state = coupled_nm.update_state(coupled_nm.NeuromodulatoryState(), signals)
        composite = coupled_nm.compute_composite_modulation(nm_state)
        heat = min(1.0, max(0.0, heat * composite["heat_modulation"]))
        importance = min(1.0, max(0.0, importance * composite["importance_modulation"]))
        return heat, importance, composite
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.neuromodulation")
        silent_failure.note("write_gate.neuromodulation", exc)
        return heat, importance, None


def apply_emotional_tagging(
    content: str,
    importance: float,
    heat: float,
    valence: float,
) -> tuple[float, float, float, dict | None]:
    """Apply emotional tagging. Returns (importance, heat, valence, tag)."""
    try:
        tag = tag_memory_emotions(content)
        if tag["is_emotional"]:
            importance = min(1.0, importance * tag["importance_boost"])
            heat = min(1.0, heat * tag.get("decay_resistance", 1.0))
            valence = tag["valence"]
        return importance, heat, valence, tag
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.emotional_tagging")
        silent_failure.note("write_gate.emotional_tagging", exc)
        return importance, heat, valence, None


def _collect_existing_embeddings(
    vec_hits: list[tuple],
    store: Any,
    embeddings: Any,
) -> list[list[float]]:
    """Collect embedding vectors for the top similar memories."""
    existing_embs: list[list[float]] = []
    for mid, _dist in (vec_hits or [])[:5]:
        mem_data = store.get_memory(mid)
        if mem_data and mem_data.get("embedding"):
            emb_list = embeddings.to_list(mem_data["embedding"])
            if emb_list:
                existing_embs.append(emb_list)
    return existing_embs


# Only a separation that actually moved the embedding (index above this
# epsilon) replaces the original vector.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_SEPARATION_INDEX = 0.01


def apply_pattern_separation(
    embedding: Any,
    similarities: list[float],
    vec_hits: list[tuple],
    store: Any,
    embeddings: Any,
) -> tuple[Any, float, float]:
    """Apply DG orthogonalization. Returns (embedding, sep_index, interference)."""
    sep_index = 0.0
    interference = 0.0
    try:
        if not (embedding and similarities):
            return embedding, sep_index, interference
        existing_embs = _collect_existing_embeddings(vec_hits, store, embeddings)
        if not existing_embs:
            return embedding, sep_index, interference
        new_emb_list = embeddings.to_list(embedding)
        if not new_emb_list:
            return embedding, sep_index, interference
        risks = detect_interference_risk(new_emb_list, existing_embs)
        if risks:
            interfering = [existing_embs[idx] for idx, _ in risks]
            separated, sep_index = orthogonalize_embedding(
                new_emb_list, interfering, strength=0.3
            )
            if sep_index > _MIN_SEPARATION_INDEX:
                embedding = embeddings.from_list(separated)
        interference = compute_interference_score(new_emb_list, existing_embs)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.pattern_separation")
        silent_failure.note("write_gate.pattern_separation", exc)
    return embedding, sep_index, interference


def match_schema(
    domain: str,
    entity_names: list[str],
    tags: list[str],
    store: Any,
) -> tuple[float, str | None]:
    """Find best matching schema. Returns (score, schema_id)."""
    try:
        domain_schemas = store.get_schemas_for_domain(domain)
        if domain_schemas:
            schemas = [_schema_from_dict(s) for s in domain_schemas]
            best, score = schema_engine.find_best_matching_schema(
                entity_names,
                tags,
                schemas,
            )
            if best:
                return score, best.schema_id
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.schema_match")
        silent_failure.note("write_gate.schema_match", exc)
    return 0.0, None


def read_active_goal(store: Any) -> Any:
    """Promote the store's active prospective triggers into a sustained goal (A3).

    Defensive store reader mirroring pg_recall._get_active_goal / _get_user_mood:
    looks for ``get_active_prospective_memories()`` on the store (the same method
    query_methodology uses to fire triggers) and hands the trigger dicts to
    ``goal_maintenance.build_goal_from_triggers``. This is the promotion step
    A3 rests on — the momentary prospective triggers become the held task-set
    that biases this write.

    Returns ``goal_maintenance.EMPTY_GOAL`` (inactive → identity re-weight) when
    the store is None, lacks the reader, has no active triggers, or the read
    fails. Per the source-discipline rule we never fabricate a goal signal.
    """
    if store is None or not hasattr(store, "get_active_prospective_memories"):
        return goal_maintenance.EMPTY_GOAL
    try:
        triggers = store.get_active_prospective_memories()
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.active_goal_read")
        silent_failure.note("write_gate.active_goal_read", exc)
        return goal_maintenance.EMPTY_GOAL
    try:
        return goal_maintenance.build_goal_from_triggers(triggers)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.active_goal_build")
        silent_failure.note("write_gate.active_goal_build", exc)
        return goal_maintenance.EMPTY_GOAL


def apply_goal_maintenance(
    novelty_score: float,
    content: str,
    entity_names: list[str],
    store: Any,
    *,
    directory: str = "",
) -> tuple[float, dict | None]:
    """A3 goal / task-set maintenance over the write gate's novelty score.

    While a goal/task-set is active (promoted from the store's active
    prospective triggers via ``read_active_goal``), a goal-relevant input has
    its novelty scaled up by a small multiplicative gain
    (``goal_maintenance.goal_write_gain`` = ``1 + weight·relevance``) so it
    clears the write threshold slightly more easily — the Miller & Cohen (2001)
    task-set biasing processing toward goal-relevant information. Returns
    ``(modulated_novelty, outcome_dict)``; ``outcome_dict`` is None when the
    mechanism is ablated, no goal is active, or the pass fails.

    Behavior-preserving by default: with no active goal the gain is exactly 1.0,
    so ``novelty_score`` is returned unchanged and existing callers are
    unaffected. An off-task input under an active goal (relevance 0) is likewise
    unchanged — only genuinely goal-relevant inputs are favored.

    Non-fatal: any error returns the input novelty untouched. Disabled via
    CORTEX_ABLATE_GOAL_MAINTENANCE=1.

    DESIGN INFERENCE: the goal-match is a deterministic keyword/entity/directory
    overlap re-weight promoted from the prospective trigger surface, not a
    learned PFC task-set controller (see goal_maintenance module docstring).
    """
    if is_mechanism_disabled(Mechanism.GOAL_MAINTENANCE):
        return novelty_score, None
    try:
        goal = read_active_goal(store)
        if not goal_maintenance.goal_vector_is_active(goal):
            return novelty_score, None
        relevance = goal_maintenance.goal_relevance(
            goal, content, entities=entity_names, directory=directory
        )
        gain = goal_maintenance.goal_write_gain(
            goal, content, entities=entity_names, directory=directory
        )
        if gain == 1.0:
            # Goal active but this input is off-task (relevance 0) — no effect,
            # so this is a no-op indistinguishable from having no goal at all.
            return novelty_score, None
        modulated = max(0.0, min(1.0, novelty_score * gain))
        return modulated, {
            "goal": goal_maintenance.goal_vector_as_dict(goal),
            "relevance": round(relevance, 4),
            "gain": round(gain, 4),
            "modulated_novelty": round(modulated, 4),
        }
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.goal_maintenance")
        silent_failure.note("write_gate.goal_maintenance", exc)
        return novelty_score, None


def apply_habituation(
    novelty_score: float,
    content: str,
    importance: float,
    store: Any,
) -> tuple[float, dict | None]:
    """E1 habituation & sensitization over the write gate's novelty score.

    Progressively suppresses repeated low-salience identical inputs (the
    exponential response decrement of Rankin 2009) and transiently sensitizes
    the gate for related inputs just after a salient event. Returns
    ``(modulated_novelty, outcome_dict)``; ``outcome_dict`` is None when the
    mechanism is ablated or the pass fails.

    Behavior-preserving by default: a first-seen signature (repeat_count 0) and
    no recent salient event yield a combined gain of 1.0, so ``novelty_score``
    is returned unchanged and existing callers are unaffected unless the repeat
    pattern actually triggers.

    Non-fatal: any error in the store read or computation returns the input
    novelty untouched. Disabled via CORTEX_ABLATE_HABITUATION=1.
    """
    if is_mechanism_disabled(Mechanism.HABITUATION):
        return novelty_score, None
    try:
        signature = habituation.stimulus_signature(content)
        repeat_count, hours_since_last = 0, None
        salience, hours_since_salient = 0.0, None
        if hasattr(store, "signature_repeat_stats"):
            repeat_count, hours_since_last = store.signature_repeat_stats(signature)
        # The current write's own importance is the salience source: a salient
        # write dishabituates itself and briefly sensitizes related inputs
        # (Rankin criteria 8/9). hours_since_salient=0.0 = the event is now.
        if habituation.is_salient(importance):
            salience, hours_since_salient = importance, 0.0
        outcome = habituation.habituate_novelty(
            novelty_score,
            content,
            repeat_count=repeat_count,
            hours_since_last=hours_since_last,
            salience=salience,
            hours_since_salient=hours_since_salient,
        )
        return outcome.modulated_novelty, habituation.habituation_outcome_as_dict(
            outcome
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("write_gate.habituation")
        silent_failure.note("write_gate.habituation", exc)
        return novelty_score, None
