"""Replay data types — shared across replay submodules.

Pure data classes with no logic beyond defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReplayDirection(Enum):
    """Direction of replay sequence."""

    FORWARD = "forward"
    REVERSE = "reverse"


@dataclass
class ReplayEvent:
    """A single memory in a replay sequence."""

    memory_id: int
    content: str
    heat: float = 0.0
    created_at: str = ""
    entities: list[str] = field(default_factory=list)
    causal_edges: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ReplaySequence:
    """An ordered sequence of memories replayed during an SWR burst.

    Attributes:
        events: Ordered memories in the sequence.
        direction: Forward or reverse replay.
        priority_score: Heat/variance heuristic — higher = higher priority.
        stdp_pairs: Entity pairs for STDP updates (source, target, delta_t).
        schema_update_signal: How much this replay should update schemas.
    """

    events: list[ReplayEvent] = field(default_factory=list)
    direction: ReplayDirection = ReplayDirection.FORWARD
    priority_score: float = 0.0
    stdp_pairs: list[tuple[int, int, float]] = field(default_factory=list)
    schema_update_signal: float = 0.0


@dataclass
class ReplayResult:
    """Result of a full SWR replay cycle."""

    sequences_generated: int = 0
    memories_replayed: int = 0
    stdp_updates: list[tuple[int, int, float]] = field(default_factory=list)
    schema_signals: list[dict] = field(default_factory=list)
    forward_count: int = 0
    reverse_count: int = 0
