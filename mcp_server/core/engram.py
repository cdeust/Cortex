"""Engram slot allocation — competitive memory storage based on excitability.

Implements the Josselyn & Frankland (2007) / Rashid et al. (2016) model:
neurons (slots) compete via CREB-like excitability. High-excitability slots
win the competition and memories stored nearby in time share the same slot,
creating automatic temporal linking with zero explicit logic.

The 6-hour half-life for excitability decay is derived from Rashid et al. (2016)
experimental data: CREB levels were elevated at 1.5h, 3h, and 6h post-training,
returning to baseline by 18h. A 6h half-life fits this decay envelope.

Constants without published values (hand-tuned):
    boost_amount=0.5 — No published CREB boost magnitude exists; tuned for
        reasonable overlap between temporally proximate memories.
    inhibition_factor=0.25 — Biological lateral inhibition is PV+ interneuron-
        mediated winner-take-all competition, not distance-based. The radius
        model with fixed inhibition factor is an engineering approximation that
        captures the competitive allocation effect.

References:
    Josselyn SA, Frankland PW (2007) Memory allocation: mechanisms and function.
    Rashid AJ et al. (2016) Competition between engrams influences fear memory
        formation and recall. Science 353:383-387
    Josselyn SA, Tonegawa S (2020) Memory engrams: Recalling the past and
        imagining the future. Science 367:eaaw4325

Pure business logic — no I/O. Receives slot data and returns allocation decisions.
Storage operations are handled by the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone


def compute_decayed_excitability(
    stored_excitability: float,
    last_activated: str | None,
    half_life_hours: float = 6.0,
) -> float:
    """Apply exponential decay to stored excitability.

    E(t) = E0 * 2^(-elapsed_hours / half_life)

    Default half_life=6.0h from Rashid et al. (2016): CREB elevated at 1.5h,
    3h, 6h; baseline by 18h. Returns 0.0 if no activation time or zero
    excitability.
    """
    if last_activated is None or stored_excitability <= 0.0:
        return 0.0
    try:
        last_dt = datetime.fromisoformat(last_activated)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0

    now = datetime.now(timezone.utc)
    elapsed_hours = max(0.0, (now - last_dt).total_seconds() / 3600.0)
    return stored_excitability * (2.0 ** (-elapsed_hours / half_life_hours))


def find_best_slot(
    slots: list[dict],
    half_life_hours: float = 6.0,
) -> tuple[int, float]:
    """Find the most excitable slot for memory allocation.

    Args:
        slots: List of {slot_index, excitability, last_activated} dicts.
        half_life_hours: Excitability decay half-life.

    Returns:
        (best_slot_index, best_excitability).
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.ENGRAM_ALLOCATION):
        # No-op: baseline allocation -- always slot 0 with neutral excitability.
        return 0, 0.5

    best_slot = 0
    best_exc = -1.0

    for slot in slots:
        exc = compute_decayed_excitability(
            slot.get("excitability", 0.5),
            slot.get("last_activated"),
            half_life_hours,
        )
        if exc > best_exc:
            best_exc = exc
            best_slot = slot["slot_index"]

    return best_slot, best_exc


def compute_boost(
    current_excitability: float,
    boost_amount: float = 0.5,
) -> float:
    """Boost excitability after slot activation. Capped at 1.0.

    boost_amount is hand-tuned (no published CREB boost magnitude).
    """
    return min(current_excitability + boost_amount, 1.0)


def compute_lateral_inhibition(
    activated_slot: int,
    num_slots: int,
    all_excitabilities: dict[int, float],
    inhibition_factor: float = 0.25,
    inhibition_radius: int = 2,
) -> dict[int, float]:
    """Compute lateral inhibition: reduce excitability of neighboring slots.

    NOTE: Biological lateral inhibition is PV+ interneuron-mediated
    winner-take-all, not distance-based with a fixed radius. This radius
    model is an engineering approximation. Both inhibition_factor and
    inhibition_radius are hand-tuned.

    Returns dict of {slot_index: new_excitability} for affected slots.
    """
    updates: dict[int, float] = {}
    for offset in range(-inhibition_radius, inhibition_radius + 1):
        if offset == 0:
            continue
        neighbor = activated_slot + offset
        if neighbor < 0 or neighbor >= num_slots:
            continue
        current = all_excitabilities.get(neighbor, 0.5)
        new_exc = max(current - inhibition_factor, 0.0)
        updates[neighbor] = new_exc
    return updates


def compute_slot_statistics(
    slots: list[dict],
    occupancy: dict[int, int],
    half_life_hours: float = 6.0,
) -> dict:
    """Compute aggregate slot statistics.

    Returns dict with total_slots, occupied_slots, avg_excitability,
    max_excitability, slot_distribution.
    """
    excitabilities = []
    for slot in slots:
        exc = compute_decayed_excitability(
            slot.get("excitability", 0.5),
            slot.get("last_activated"),
            half_life_hours,
        )
        excitabilities.append(exc)

    occupied = len(occupancy)
    avg_exc = sum(excitabilities) / len(excitabilities) if excitabilities else 0.0
    max_exc = max(excitabilities) if excitabilities else 0.0

    return {
        "total_slots": len(slots),
        "occupied_slots": occupied,
        "avg_excitability": round(avg_exc, 4),
        "max_excitability": round(max_exc, 4),
        "slot_distribution": occupancy,
    }
