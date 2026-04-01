"""SWR replay execution — sequence building and STDP pair extraction.

Builds temporal and causal replay sequences from memory traces, then
extracts entity pairs for spike-timing-dependent plasticity updates.

Biological replay compresses temporal sequences by 15-20x during SWR events
(Davidson et al. 2009, Neuron 63:497-507). This module uses entity-overlap-
based sequence building rather than population burst dynamics, and applies
the compression ratio (20x, upper end of published range) to STDP timing.

References:
    Foster DJ, Wilson MA (2006) Reverse replay of behavioural sequences
        in hippocampal place cells during the awake state. Nature 440:680-683
    Diba K, Buzsaki G (2007) Forward and reverse hippocampal place-cell
        sequences during ripples. Nature Neurosci 10:1241-1242
    Davidson TJ, Kloosterman F, Wilson MA (2009) Hippocampal replay of
        extended experience. Neuron 63:497-507

Pure business logic — no I/O.
"""

from __future__ import annotations

import json

from mcp_server.core.replay_types import (
    ReplayDirection,
    ReplayEvent,
)

# ── Constants ────────────────────────────────────────────────────────────

_MAX_SEQUENCE_LENGTH = 8
_MIN_SEQUENCE_LENGTH = 2
_STDP_REPLAY_SCALE = 0.5
# Davidson et al. (2009) report 15-20x compression during SWR replay.
# Using 20x (upper bound) since our sequences are shorter than biological ones.
_COMPRESSION_RATIO = 20.0


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_tags(tags) -> list[str]:
    """Safely parse tags that might be string or list."""
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except (ValueError, TypeError):
            return []
    return []


def _get_entity_set(mem: dict) -> set[str]:
    """Extract entity set from a memory dict's tags field."""
    tags = _parse_tags(mem.get("tags", []))
    return set(tags) if tags else set()


def _has_relationship(id_a: int, id_b: int, relationships: list[dict]) -> bool:
    """Check if two memory IDs are connected via entity relationships."""
    for rel in relationships:
        src = rel.get("source_entity_id")
        tgt = rel.get("target_entity_id")
        if (src == id_a and tgt == id_b) or (src == id_b and tgt == id_a):
            return True
    return False


def _mem_to_event(mem: dict) -> ReplayEvent:
    """Convert a memory dict to a ReplayEvent."""
    return ReplayEvent(
        memory_id=mem["id"],
        content=mem.get("content", ""),
        heat=mem.get("heat", 0.0),
        created_at=mem.get("created_at", ""),
        entities=_parse_tags(mem.get("tags", [])),
    )


# ── Temporal Sequence ────────────────────────────────────────────────────


def build_temporal_sequence(
    memories: list[dict],
    max_length: int = _MAX_SEQUENCE_LENGTH,
) -> list[ReplayEvent]:
    """Build a temporal sequence from memories ordered by creation time.

    Memories are sorted chronologically and converted to ReplayEvents.
    This is the basic building block for both forward and reverse replay.
    """
    sorted_mems = sorted(memories, key=lambda m: m.get("created_at", ""))
    return [_mem_to_event(m) for m in sorted_mems[:max_length]]


# ── Causal Sequence ──────────────────────────────────────────────────────


def build_causal_sequence(
    seed_memory: dict,
    related_memories: list[dict],
    relationships: list[dict],
    direction: ReplayDirection = ReplayDirection.FORWARD,
    max_length: int = _MAX_SEQUENCE_LENGTH,
) -> list[ReplayEvent]:
    """Build a causal chain by following entity relationships from a seed.

    For forward replay, follow edges forward in time.
    For reverse replay, follow edges backward.
    """
    if not seed_memory:
        return []

    chain_ids = _build_chain_ids(
        seed_memory,
        related_memories,
        relationships,
        direction,
        max_length,
    )
    mem_by_id = {m["id"]: m for m in [seed_memory] + related_memories}

    return [_mem_to_event(mem_by_id[mid]) for mid in chain_ids if mid in mem_by_id]


def _build_chain_ids(
    seed_memory: dict,
    related_memories: list[dict],
    relationships: list[dict],
    direction: ReplayDirection,
    max_length: int,
) -> list[int]:
    """Walk candidates to build an ordered chain of memory IDs."""
    chain = [seed_memory["id"]]
    visited = {seed_memory["id"]}
    seed_entities = _get_entity_set(seed_memory)
    seed_time = seed_memory.get("created_at", "")

    candidates = _sort_candidates(related_memories, direction)

    for mem in candidates:
        if len(chain) >= max_length:
            break
        if mem["id"] in visited:
            continue
        if not _is_valid_candidate(
            mem, seed_time, seed_entities, seed_memory["id"], relationships, direction
        ):
            continue

        chain.append(mem["id"])
        visited.add(mem["id"])
        seed_entities = seed_entities | _get_entity_set(mem)

    return chain


def _sort_candidates(
    memories: list[dict],
    direction: ReplayDirection,
) -> list[dict]:
    """Sort candidate memories by time, reversed for reverse replay."""
    sorted_mems = sorted(memories, key=lambda m: m.get("created_at", ""))
    if direction == ReplayDirection.REVERSE:
        sorted_mems = list(reversed(sorted_mems))
    return sorted_mems


def _is_valid_candidate(
    mem: dict,
    seed_time: str,
    seed_entities: set[str],
    seed_id: int,
    relationships: list[dict],
    direction: ReplayDirection,
) -> bool:
    """Check whether a candidate memory belongs in the causal chain."""
    mem_time = mem.get("created_at", "")

    if direction == ReplayDirection.FORWARD and mem_time < seed_time:
        return False
    if direction == ReplayDirection.REVERSE and mem_time > seed_time:
        return False

    mem_entities = _get_entity_set(mem)
    has_overlap = bool(seed_entities & mem_entities)
    has_rel = _has_relationship(seed_id, mem["id"], relationships)

    return has_overlap or has_rel


# ── STDP Pairs ───────────────────────────────────────────────────────────


def compute_replay_stdp_pairs(
    events: list[ReplayEvent],
    direction: ReplayDirection,
    scale: float = _STDP_REPLAY_SCALE,
    compression_ratio: float = _COMPRESSION_RATIO,
) -> list[tuple[int, int, float]]:
    """Extract entity pairs for STDP updates from a replay sequence.

    During replay, sequential memories activate entities in order.
    Replay is compressed ~20x (Davidson et al. 2009); timing is scaled
    accordingly to model compressed STDP windows.
    """
    pairs: list[tuple[int, int, float]] = []

    for i in range(len(events) - 1):
        base_dt = (i + 1) * scale / compression_ratio
        pairs.extend(
            _entity_pairs_for_step(events[i], events[i + 1], direction, base_dt)
        )

    return pairs


def _entity_pairs_for_step(
    curr: ReplayEvent,
    next_ev: ReplayEvent,
    direction: ReplayDirection,
    base_dt: float,
) -> list[tuple[int, int, float]]:
    """Generate STDP pairs between two consecutive replay events."""
    pairs: list[tuple[int, int, float]] = []

    for src_ent in curr.entities:
        for tgt_ent in next_ev.entities:
            if src_ent == tgt_ent:
                continue
            src_hash = hash(src_ent) & 0x7FFFFFFF
            tgt_hash = hash(tgt_ent) & 0x7FFFFFFF

            if direction == ReplayDirection.FORWARD:
                pairs.append((src_hash, tgt_hash, base_dt))
            else:
                pairs.append((tgt_hash, src_hash, base_dt))

    return pairs
