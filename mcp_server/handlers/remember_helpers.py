"""Helpers for the remember handler — gate evaluation, modulation, curation, storage.

Extracted to keep remember.py under 300 lines with all methods under 40 lines.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import curation, thermodynamics, write_gate, write_post_store
from mcp_server.core.dual_store_cls import classify_memory
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty,
    compute_entity_novelty,
    compute_novelty_score,
    compute_structural_novelty,
)
from mcp_server.core.predictive_coding_gate import gate_decision
from mcp_server.handlers.remember_response import build_response
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore


def compute_similarities(
    embedding: Any,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> tuple[list[float], list[tuple]]:
    """Compute vector similarities for the top-5 nearest neighbors."""
    sims: list[float] = []
    vec_hits: list[tuple] = []
    if embedding:
        vec_hits = store.search_vectors(embedding, top_k=5, min_heat=0.0)
        for mid, _d in vec_hits:
            mem = store.get_memory(mid)
            if mem and mem.get("embedding"):
                sims.append(emb_engine.similarity(embedding, mem["embedding"]))
    return sims, vec_hits


def compute_entity_info(
    content: str, store: MemoryStore
) -> tuple[list[dict], list[str], set[str], float]:
    """Extract entities and compute entity novelty score."""
    from mcp_server.core import knowledge_graph

    extracted = knowledge_graph.extract_entities(content)
    names = [e["name"] for e in extracted]
    known: set[str] = {n for n in names if store.get_entity_by_name(n)}
    return extracted, names, known, compute_entity_novelty(names, known)


def _compute_gate_decision(
    score: float,
    force: bool,
    content: str,
    tags: list[str],
) -> tuple[bool, str]:
    """Determine whether to store based on novelty score and bypass rules."""
    bypass, bypass_reason = write_gate.determine_bypass(force, content, tags)
    settings = get_memory_settings()
    should_store, gate_reason = gate_decision(
        score, threshold=settings.WRITE_GATE_THRESHOLD, bypass=bypass
    )
    if bypass_reason:
        gate_reason = bypass_reason
    return should_store, gate_reason


def evaluate_gate(
    content: str,
    tags: list[str],
    embedding: Any,
    force: bool,
    store: MemoryStore,
    emb_engine: EmbeddingEngine,
) -> dict[str, Any]:
    """Compute all novelty signals and gate decision."""
    importance = thermodynamics.compute_importance(content, tags)
    sims, vec_hits = compute_similarities(embedding, store, emb_engine)
    emb_nov = compute_embedding_novelty(sims)
    extracted, ent_names, known, ent_nov = compute_entity_info(content, store)
    temp_nov = write_gate.compute_temporal_novelty(sims, vec_hits, store.get_memory)
    recent = store.get_hot_memories(min_heat=0.0, limit=10)
    struct_nov = compute_structural_novelty(
        content, [m["content"] for m in recent if m.get("content")]
    )
    score = compute_novelty_score(emb_nov, ent_nov, temp_nov, struct_nov)
    should_store, gate_reason = _compute_gate_decision(score, force, content, tags)
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
            sim = emb_engine.similarity(embedding, cand["embedding"])
            overlap = curation.compute_textual_overlap(content, cand["content"]) > 0.5
            action = curation.decide_curation_action(sim, overlap)
            if action == "merge":
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
    etag = mod.get("emotional_tag")
    record["arousal"] = round(etag["arousal"], 4) if etag and "arousal" in etag else 0.0
    record["dominant_emotion"] = (
        etag.get("dominant_emotion", "neutral") if etag else "neutral"
    )
    if created_at:
        record["created_at"] = created_at
        record["stage_entered_at"] = created_at
    return record


def _link_if_needed(
    action: str, merged_id: int | None, mem_id: int, store: MemoryStore
) -> None:
    """Insert a derived_from relationship for link actions."""
    if action == "link" and merged_id:
        try:
            store.insert_relationship(
                {
                    "source_entity_id": mem_id,
                    "target_entity_id": merged_id,
                    "relationship_type": "derived_from",
                    "weight": 1.0,
                }
            )
        except Exception:
            pass


def _run_post_store(
    mem_id: int,
    content: str,
    directory: str,
    domain: str,
    extracted: list[dict],
    ent_names: list[str],
    mod: dict,
    store: MemoryStore,
) -> tuple[list[int], list[dict], dict | None]:
    """Run post-insert operations: triggers, entities, tagging, engram."""
    settings = get_memory_settings()
    tids = write_post_store.extract_triggers(content, directory, store)
    write_post_store.persist_entities(
        extracted, domain, content, store, memory_id=mem_id
    )
    tagged = write_post_store.run_synaptic_tagging(
        mem_id, mod["importance"], ent_names, store
    )
    slot = write_post_store.allocate_engram_slot(mem_id, settings, store)
    return tids, tagged, slot


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
) -> dict[str, Any]:
    """Separate, store, and run post-storage operations."""
    is_dec = thermodynamics.is_decision_content(content)
    stype = classify_memory(content, tags, directory)
    embedding, sep, interf = write_gate.apply_pattern_separation(
        embedding,
        sims,
        vec_hits,
        store,
        emb_engine,
    )
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
    )
    record["agent_context"] = agent_context
    record["is_global"] = is_global
    mem_id = store.insert_memory(record)
    _link_if_needed(action, merged_id, mem_id, store)
    tids, tagged, slot = _run_post_store(
        mem_id,
        content,
        directory,
        domain,
        extracted,
        ent_names,
        mod,
        store,
    )
    return build_response(
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
