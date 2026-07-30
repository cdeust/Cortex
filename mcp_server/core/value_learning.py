"""Value learning — reinforcement-learning value + credit assignment (B2).

Cortex already computes a dopamine reward-prediction error
(``neuromodulation_channels.compute_dopamine_rpe``) but uses it only to
modulate the LTP rate of the memory currently being written. Nothing *accrues*
value over time, and nothing assigns credit backward from a session's outcome to
the memories that were actually used to produce it. This module adds that
missing layer: a learned scalar value per memory, updated by a temporal-
difference rule from session outcomes, with eligibility-trace credit assignment.

Neuroscience / RL basis (all DOIs verified against Crossref):
  - Schultz, Dayan & Montague (1997), "A neural substrate of prediction and
    reward," Science 275:1593-1599 (doi:10.1126/science.275.5306.1593). Dopamine
    encodes a temporal-difference reward-prediction error δ = reward - V. We
    reuse the SAME actual-reward mapping the DA-RPE already uses
    (positive -> 0.7 + 0.3·importance, negative -> 0.2 - 0.1·importance,
    neutral -> 0.5) so the value layer and the neuromodulator agree on "reward."
  - Sutton & Barto (1998), "Reinforcement Learning: An Introduction," MIT Press.
    The TD(λ) value update V ← V + α·δ and eligibility traces: a memory used
    earlier in the recall set that led to a good outcome still gets credit,
    discounted by how long ago / how far down the recall list it was used.
  - Mnih et al. (2015), "Human-level control through deep reinforcement
    learning," Nature 518:529-533 (doi:10.1038/nature14236). TD-error learning
    of a value function at scale; the same error signal Cortex already computes,
    here turned into a persistent per-item value rather than a transient
    modulation gain.

Scope / honesty note (zetetic standard, matching dual_store_cls.py and
procedural_memory.py): this is a tabular TD(0)/TD(λ) value estimator over
individual memories — a running, reward-weighted estimate — not a deep value
network. The papers motivate the design; Mnih 2015's contribution
(function approximation over raw pixels) is explicitly NOT implemented. The
value is a scalar bookkeeping signal, and the eligibility trace is a simple
geometric decay over recall rank, not a full TD(λ) backup through a trajectory.

Boundary with existing machinery: this does NOT replace ``compute_dopamine_rpe``
(which stays the per-write LTP modulator). It consumes the same reward mapping
and produces a separate, persistent ``value`` that feeds retention (high-value
memories resist decay) and retrieval priority. Pure business logic — no I/O.
Handlers pass in the recalled-memory ids + session outcome and persist the
returned value updates.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Tuning constants ────────────────────────────────────────────────────────
# TD learning rate: V <- V + alpha * (reward - V). Matches the combined
# alpha*beta = 0.1 used by compute_dopamine_rpe so the value layer learns at the
# same pace as the dopamine baseline it shadows (Daw 2011 range [0.01-0.25]).
VALUE_ALPHA: float = 0.1

# Eligibility-trace decay across the recall set (Sutton & Barto TD(lambda)).
# The k-th memory in a recall list of relevance-ranked results receives credit
# scaled by TRACE_LAMBDA**k — the top hit is most responsible for the outcome,
# later hits progressively less. 0.8 gives a gentle decay (5th item ~0.41).
TRACE_LAMBDA: float = 0.8

# Value is bounded to [0, 1] to stay commensurate with the other [0,1] memory
# signals (importance, confidence, schema_match_score) it will be blended with.
VALUE_MIN: float = 0.0
VALUE_MAX: float = 1.0

# Neutral / prior value for a memory that has never received a reward signal.
# 0.5 = "unknown, assume average" — the same neutral the DA-RPE uses.
VALUE_PRIOR: float = 0.5


# Reward mapping — IDENTICAL to neuromodulation_channels.compute_dopamine_rpe so
# the value layer and the dopamine signal never disagree on what "reward" means.
# Kept as a local constant set rather than an import to keep this module free of
# neuromodulation coupling; the shared source of truth is documented here and
# guarded by a test that asserts equality with the DA-RPE mapping.
def outcome_to_reward(
    outcome_positive: bool,
    outcome_negative: bool,
    memory_importance: float,
) -> float:
    """Map a session outcome to a scalar reward in [0, 1].

    Mirrors ``compute_dopamine_rpe``'s reward mapping exactly:
      positive -> 0.7 + 0.3·importance
      negative -> 0.2 - 0.1·importance
      neutral  -> 0.5
    """
    if outcome_positive:
        return 0.7 + memory_importance * 0.3
    if outcome_negative:
        return 0.2 - memory_importance * 0.1
    return 0.5


# ── Data model ──────────────────────────────────────────────────────────────
@dataclass
class ValueUpdate:
    """A computed value change for one memory, ready to persist.

    ``memory_id``      — the memory whose value is being updated.
    ``old_value``      — value before the update (VALUE_PRIOR if never seen).
    ``new_value``      — value after the TD update, clamped to [0, 1].
    ``delta``          — the reward-prediction error δ = reward - V (signed).
    ``eligibility``    — the trace weight this memory received (top hit = 1.0).
    ``effective_alpha``— alpha·eligibility, the actual step size applied.

    Data only — deliberately no methods. mutmut's mutation generator
    categorically excludes the body of any `@dataclass`-decorated class
    (`mutmut/mutation/file_mutation.py:236`), so logic placed on methods
    here would carry zero mutation coverage no matter how the test loader
    names the module (issue #262 3rd pass; issue #282). ``value_update_as_dict``
    below carries the same logic as a free function instead.
    """

    memory_id: int
    old_value: float
    new_value: float
    delta: float
    eligibility: float
    effective_alpha: float


def value_update_as_dict(update: ValueUpdate) -> dict:
    return {
        "memory_id": update.memory_id,
        "old_value": round(update.old_value, 4),
        "new_value": round(update.new_value, 4),
        "delta": round(update.delta, 4),
        "eligibility": round(update.eligibility, 4),
        "effective_alpha": round(update.effective_alpha, 4),
    }


# ── TD value update (Schultz / Sutton & Barto) ──────────────────────────────
def td_update(
    current_value: float,
    reward: float,
    *,
    alpha: float = VALUE_ALPHA,
    eligibility: float = 1.0,
) -> tuple[float, float]:
    """One temporal-difference value update for a single memory.

    ``V ← V + (alpha·eligibility)·(reward − V)`` (Sutton & Barto; the δ = reward
    − V term is Schultz's reward-prediction error). Returns
    ``(new_value, delta)`` where ``delta`` is the *unweighted* prediction error
    (reward − V) — the signed learning signal — and ``new_value`` is clamped to
    [0, 1].
    """
    delta = reward - current_value
    step = alpha * eligibility
    new_value = current_value + step * delta
    new_value = max(VALUE_MIN, min(VALUE_MAX, new_value))
    return new_value, delta


# ── Credit assignment with eligibility traces ───────────────────────────────
def assign_credit(
    recalled: list[dict],
    outcome_positive: bool,
    outcome_negative: bool,
    *,
    alpha: float = VALUE_ALPHA,
    trace_lambda: float = TRACE_LAMBDA,
) -> list[ValueUpdate]:
    """Distribute credit for a session outcome across the memories it used.

    ``recalled`` is the ordered recall set that produced the session's result —
    most-relevant first — where each entry is a dict with at least:
      - ``id`` / ``memory_id``: the memory id
      - ``value`` (optional): its current learned value (VALUE_PRIOR if absent)
      - ``importance`` (optional): used by the reward mapping (default 0.5)

    Each memory at rank ``k`` (0-based) gets an eligibility trace
    ``trace_lambda**k`` — the top hit is fully responsible for the outcome, later
    hits progressively less (Sutton & Barto eligibility traces). The reward is
    the shared DA-RPE mapping, and each memory's value is TD-updated by its own
    trace-weighted step. Returns one ``ValueUpdate`` per recalled memory, in the
    same order.

    A neutral session (neither positive nor negative) still produces updates —
    reward 0.5 pulls every value gently toward the neutral prior, which is the
    correct behaviour: a memory used in an unremarkable session should regress
    toward average, not hold an inflated value.
    """
    updates: list[ValueUpdate] = []
    for rank, mem in enumerate(recalled):
        mem_id = mem.get("memory_id", mem.get("id"))
        if mem_id is None:
            continue
        current = _current_value(mem)
        importance = _clamp01(mem.get("importance", 0.5), default=0.5)
        reward = outcome_to_reward(outcome_positive, outcome_negative, importance)
        eligibility = trace_lambda**rank
        new_value, delta = td_update(
            current, reward, alpha=alpha, eligibility=eligibility
        )
        updates.append(
            ValueUpdate(
                memory_id=mem_id,
                old_value=current,
                new_value=new_value,
                delta=delta,
                eligibility=eligibility,
                effective_alpha=alpha * eligibility,
            )
        )
    return updates


# ── Value as a retention / retrieval priority signal ────────────────────────
def retention_bonus(value: float, *, max_bonus: float = 0.5) -> float:
    """Map a learned value to a multiplicative retention bonus in [1, 1+max].

    A high-value memory (proven to contribute to good outcomes) should resist
    decay. Returns a factor >= 1.0 that a decay/heat computation can multiply in:
    value 0.5 (neutral) -> 1.0 (no effect); value 1.0 -> 1+max_bonus; value 0 ->
    still 1.0 (low value never *accelerates* forgetting here — that is the
    decay/interference machinery's job, not the value layer's).
    """
    v = _clamp01(value, default=VALUE_PRIOR)
    return 1.0 + max_bonus * max(0.0, (v - VALUE_PRIOR) / (VALUE_MAX - VALUE_PRIOR))


def retrieval_priority(
    base_score: float, value: float, *, weight: float = 0.15
) -> float:
    """Blend a learned value into a retrieval relevance score.

    ``score' = base_score · (1 + weight·(value − prior))`` — a memory worth more
    than average gets a small ranking boost, one worth less a small penalty,
    proportional to how far its value is from the neutral prior. ``weight`` is
    deliberately small so value nudges rather than dominates content relevance.
    """
    v = _clamp01(value, default=VALUE_PRIOR)
    return base_score * (1.0 + weight * (v - VALUE_PRIOR))


# ── Helpers ─────────────────────────────────────────────────────────────────
def _current_value(mem: dict) -> float:
    raw = mem.get("value")
    if raw is None:
        return VALUE_PRIOR
    return _clamp01(raw, default=VALUE_PRIOR)


def _clamp01(x, *, default: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))
