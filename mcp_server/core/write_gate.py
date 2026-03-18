"""Core write gate logic — novelty signals, bypass detection, oscillatory context.

Pure business logic for the memory write path. No I/O.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from mcp_server.core import knowledge_graph
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty as _compute_embedding_novelty,
    compute_entity_novelty as _compute_entity_novelty,
    compute_structural_novelty as _compute_structural_novelty,
    compute_temporal_novelty as _compute_temporal_novelty,
    describe_signals as _describe_signals,
)
from mcp_server.core import thermodynamics
from mcp_server.core import oscillatory_clock
from mcp_server.core.separation_core import (
    detect_interference_risk,
    orthogonalize_embedding,
)
from mcp_server.core.neurogenesis import compute_interference_score
from mcp_server.core import schema_engine
from mcp_server.core.schema_extraction import schema_from_dict as _schema_from_dict
from mcp_server.core import coupled_neuromodulation as coupled_nm
from mcp_server.core.emotional_tagging import tag_memory_emotions

_SUCCESS_KW = re.compile(
    r"\b(fixed|resolved|succeeded|passed|completed|done)\b", re.IGNORECASE
)


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
            if best_mem and best_mem.get("created_at"):
                hours = _parse_hours_since(best_mem["created_at"])
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
) -> tuple[bool, str | None]:
    """Determine if write gate should be bypassed and why."""
    is_error = thermodynamics.is_error_content(content)
    is_decision = thermodynamics.is_decision_content(content)
    has_important = bool({"important", "critical"} & {t.lower() for t in tags})

    if force:
        return True, "forced"
    if is_error:
        return True, "bypass_error"
    if is_decision:
        return True, "bypass_decision"
    if has_important:
        return True, "bypass_important_tag"
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
    import json as _json

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
    except Exception:
        pass
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
        is_succ = bool(_SUCCESS_KW.search(content))
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
    except Exception:
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
    except Exception:
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
            if sep_index > 0.01:
                embedding = embeddings.from_list(separated)
        interference = compute_interference_score(new_emb_list, existing_embs)
    except Exception:
        pass
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
    except Exception:
        pass
    return 0.0, None
