"""Exact flat-gate bound before embedding, with reusable observed inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp_server.core import write_gate, write_gate_calibration
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.novelty_modulation import NoveltyModulation, apply_modulation
from mcp_server.core.predictive_coding_flat import compute_novelty_score
from mcp_server.infrastructure.memory_config import get_memory_settings


@dataclass(frozen=True)
class GateOptions:
    force: bool
    domain: str
    write_class: str
    origin: str


@dataclass(frozen=True)
class GateRequest:
    content: str
    tags: list[str]
    store: Any
    options: GateOptions


@dataclass(frozen=True)
class GateObservation:
    signals: dict[str, Any]
    modulations: tuple[NoveltyModulation, NoveltyModulation]
    thresholds: tuple[float, float]


def prepare_gate(
    request: GateRequest, observe: Callable[[GateRequest], GateObservation]
) -> GateObservation | None:
    """Keep unsupported modes and every existing bypass on the eager path."""
    if get_memory_settings().WRITE_GATE_HIERARCHICAL:
        return None
    if is_mechanism_disabled(Mechanism.PREDICTIVE_CODING):
        return None
    bypass, _ = write_gate.determine_bypass(
        request.options.force,
        request.content,
        request.tags,
        write_class=request.options.write_class,
        origin=request.options.origin,
    )
    return None if bypass else observe(request)


def modulate_score(
    score: float, observed: GateObservation
) -> tuple[float, dict | None, dict | None]:
    """Preserve habituation then goal order and their two separate clamps."""
    score, habituation_info = apply_modulation(score, observed.modulations[0])
    score, goal_info = apply_modulation(score, observed.modulations[1])
    return score, habituation_info, goal_info


def bound_rejection(
    request: GateRequest, observed: GateObservation
) -> dict[str, Any] | None:
    """Reject only when the maximum attainable novelty is strictly too low.

    source: ADR-0439"""
    signals = observed.signals
    upper = compute_novelty_score(1.0, signals["ent_nov"], 1.0, signals["struct_nov"])
    upper, _, _ = modulate_score(upper, observed)
    threshold, default_threshold = observed.thresholds
    if not upper < threshold:
        return None
    write_gate_calibration.record(
        request.options.domain,
        accepted=False,
        default_threshold=default_threshold,
    )
    return {
        "stored": False,
        "action": "rejected",
        "reason": (
            f"below_threshold (novelty_upper_bound={upper:.3f}, threshold={threshold})"
        ),
        "novelty": {
            "embedding_novelty": None,
            "temporal_novelty": None,
            "entity_novelty": round(signals["ent_nov"], 4),
            "structural_novelty": round(signals["struct_nov"], 4),
            "novelty_upper_bound": upper,
        },
        "importance": round(signals["importance"], 4),
    }
