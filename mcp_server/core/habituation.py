"""Habituation & sensitization (E1) — response decrement to repeated stimuli.

Habituation is the simplest form of learning: when a stimulus is presented
repeatedly, the response to it wanes. It is not sensory fatigue and not motor
exhaustion — it is a learned, stimulus-specific down-weighting that recovers
when the stimulus stops, and that a strong or novel event can reverse
(dishabituation) or transiently amplify (sensitization). Cortex has a novelty-
driven write gate but no memory of *how often it has already seen this same
thing*: a low-salience input that repeats identically N times produces the same
novelty verdict on the Nth pass as on the first, so near-duplicate churn is
admitted again and again. That is precisely the bloat habituation exists to
suppress.

Neuroscience basis (DOI verified against Crossref):
  - Rankin, Abrams, Barry, Bhatnagar, Clayton, Colombo, Coppola, Geyer,
    Glanzman, Marsland, McSweeney, Wilson, Wu & Thompson (2009), "Habituation
    revisited: an updated and revised description of the behavioral
    characteristics of habituation," Neurobiology of Learning and Memory
    92:135-138 (doi:10.1016/j.nlm.2008.09.012). The consensus criteria of
    habituation. The four this module operationalises, by their numbering in
    that paper:
      (1) Repeated stimulation produces a progressive decrease in response,
          often to an asymptote; the decrement is frequently exponential.
      (2) Spontaneous recovery: if the stimulus is withheld, the response
          recovers over time.
      (4) Stimulus specificity: habituation to one stimulus does not transfer
          to a sufficiently different one.
      (8/9) Dishabituation / sensitization: presentation of a strong or novel
          stimulus restores (dishabituates) the habituated response, and a
          salient event can transiently raise responsiveness to other inputs.

Design (pure business logic — no I/O). Two competing scalar gains multiply the
gate's existing novelty score:

  RESPONSE GAIN (habituation) — an exponential decrement over the count of
      prior near-identical presentations of the *same* stimulus signature
      (criterion 1), floored so a repeat is damped but never silenced. The
      effective repeat count is first discounted by the idle time since the
      last presentation (criterion 2, spontaneous recovery), so a signature not
      seen for a while behaves as if partially or fully recovered. Specificity
      (criterion 4) is delegated to the caller's signature key: two inputs
      share a habituation history only if they share a signature.

  SENSITIZATION FACTOR — after a salient event (importance above a threshold),
      responsiveness to subsequent inputs is transiently raised above baseline
      (criteria 8/9), decaying back to 1.0 over a fixed window. This both
      restores a habituated response (dishabituation) and briefly amplifies
      novelty for related inputs, so a salient burst is not itself suppressed
      by an unrelated habituation history.

The combined gain (response_gain * sensitization_factor) multiplies novelty:
< 1 suppresses a repeated low-salience input toward rejection (bloat control);
> 1 amplifies novelty just after a salient event.

Honesty note (zetetic standard, matching attentional_control.py /
source_monitoring.py): this is a heuristic decay over a repeat counter, not a
learned model of the stimulus. The decrement rate, the response floor, the
recovery rate, the sensitization amplitude, its decay window, and the salience
threshold are all fixed engineering constants, not parameters fit against a
behavioral dataset — Rankin's paper is a qualitative criteria list, not a
parameterised model, so no source supplies these numbers. The exponential form
and the recovery/specificity/sensitization *directions* follow the criteria;
the magnitudes are hand-tuned. Stimulus identity is whatever signature the
caller supplies (this module normalises text to a signature but does not
itself embed or cluster). Time is supplied by the caller as elapsed hours;
this module reads no clock and touches no store. It shares the NE-channel's
adaptation idea (neuromodulation_channels.NE_HABITUATION_RATE) but operates on
a different axis — per-stimulus response-gain over a repeat count, not the
arousal channel's error-driven adaptation scalar — so the two do not overlap.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ── Constants (fixed engineering values — see the honesty note) ───────────────

# Criterion 1: exponential response decrement per repeat. gain = exp(-rate * n).
# 0.35 gives a visible but gentle decrement — ~0.70 after one repeat, ~0.50
# after two — so a genuinely novel re-encounter is damped, not erased.
HABITUATION_RATE = 0.35

# Response floor: repetition damps novelty but never silences it. Even a heavily
# repeated stimulus keeps 15% of its novelty so the gate can still admit it if
# some other signal (importance, an entity) is strong.
MIN_RESPONSE_GAIN = 0.15

# Criterion 2: spontaneous recovery. Effective repeat count decays by this many
# "repeats worth" of credit per idle hour, so a signature unseen for ~1.4 h
# recovers roughly one repeat of responsiveness; unseen long enough, it is fully
# recovered (effective repeats -> 0).
SPONTANEOUS_RECOVERY_PER_HOUR = 0.7

# Criteria 8/9: a salient event raises responsiveness transiently. Peak factor
# applied immediately after the event (a 60% amplification at full salience).
SENSITIZATION_PEAK = 1.6

# Sensitization decays linearly back to 1.0 over this window (hours). A salient
# burst amplifies related inputs for a bounded time, not permanently.
SENSITIZATION_DECAY_HOURS = 6.0

# Importance at/above which an event counts as "salient" enough to sensitize.
SALIENCE_THRESHOLD = 0.7

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]")


# ── Stimulus signature (criterion 4: specificity) ─────────────────────────────


def stimulus_signature(content: str) -> str:
    """Normalise content to a stimulus-identity key for specificity matching.

    Two inputs share a habituation history only if they share a signature.
    Normalisation lowercases, strips punctuation, and collapses whitespace so
    trivially-reformatted repeats of the same content collide, while genuinely
    different content does not. This is a deliberately coarse, exact-after-
    normalisation key — it does not cluster semantically (that is the caller's
    job if a softer notion of "same stimulus" is wanted).
    """
    s = _NONWORD_RE.sub(" ", (content or "").lower())
    return _WS_RE.sub(" ", s).strip()


# ── Component gains ───────────────────────────────────────────────────────────


def effective_repeats(repeat_count: int, hours_since_last: float | None) -> float:
    """Repeat count discounted by spontaneous recovery (criterion 2).

    ``repeat_count`` is the number of prior presentations of this signature.
    Idle time since the last presentation returns "repeats worth" of credit at
    SPONTANEOUS_RECOVERY_PER_HOUR, so a long-unseen signature behaves as if
    partially or fully recovered. Never returns below 0.
    """
    n = max(0, repeat_count)
    if hours_since_last is None or hours_since_last <= 0.0:
        return float(n)
    recovered = SPONTANEOUS_RECOVERY_PER_HOUR * hours_since_last
    return max(0.0, n - recovered)


def response_gain(repeat_count: int, hours_since_last: float | None = None) -> float:
    """Habituation response gain in [MIN_RESPONSE_GAIN, 1.0] (criteria 1 & 2).

    First presentation (effective repeats 0) returns 1.0 — no habituation on a
    stimulus never seen before. Each subsequent near-identical presentation
    decrements the gain exponentially toward the floor. Spontaneous recovery is
    folded in via ``hours_since_last``.
    """
    n = effective_repeats(repeat_count, hours_since_last)
    gain = math.exp(-HABITUATION_RATE * n)
    return max(MIN_RESPONSE_GAIN, min(1.0, gain))


def is_salient(importance: float, threshold: float = SALIENCE_THRESHOLD) -> bool:
    """True iff an event's importance clears the sensitization threshold."""
    return importance >= threshold


def sensitization_factor(
    salience: float,
    hours_since_salient: float | None,
) -> float:
    """Transient responsiveness boost after a salient event (criteria 8/9).

    Returns a factor >= 1.0: peak (scaled by ``salience`` in [0,1]) immediately
    after the event, decaying linearly to 1.0 over SENSITIZATION_DECAY_HOURS.
    With no recorded salient event (``hours_since_salient`` is None) or once the
    window has elapsed, returns the baseline 1.0.
    """
    if hours_since_salient is None or hours_since_salient < 0.0:
        return 1.0
    if hours_since_salient >= SENSITIZATION_DECAY_HOURS:
        return 1.0
    s = max(0.0, min(1.0, salience))
    remaining = 1.0 - (hours_since_salient / SENSITIZATION_DECAY_HOURS)
    peak_boost = (SENSITIZATION_PEAK - 1.0) * s
    return 1.0 + peak_boost * remaining


# ── Combined outcome (write-gate facing) ──────────────────────────────────────


@dataclass
class HabituationOutcome:
    """The result of one habituation/sensitization pass over a novelty score.

    ``signature``          — the stimulus-identity key this decision used.
    ``modulated_novelty``  — the input novelty after applying the combined gain,
                             clamped to [0, 1]. This is what the gate compares
                             to its threshold.
    ``response_gain``      — the habituation component (<= 1.0; criteria 1 & 2).
    ``sensitization``      — the sensitization component (>= 1.0; criteria 8/9).
    ``combined_gain``      — response_gain * sensitization, the factor applied.
    ``effective_repeats``  — recovery-discounted repeat count used.
    ``suppressed``         — True iff the pass pushed novelty down (gain < 1),
                             i.e. a habituated repeat the gate is now likelier
                             to reject. The bloat-control signal.
    """

    signature: str
    modulated_novelty: float
    response_gain: float
    sensitization: float
    combined_gain: float
    effective_repeats: float
    suppressed: bool


def habituation_outcome_as_dict(outcome: "HabituationOutcome") -> dict:
    """A free function, not a method: mutmut categorically excludes the
    body of any `@dataclass`-decorated class (`mutmut/mutation/
    file_mutation.py:236`), so logic placed on `HabituationOutcome` methods
    would carry zero mutation coverage no matter how the test loader names
    the module (issue #262 3rd pass; issue #282).
    """
    return {
        "signature": outcome.signature,
        "modulated_novelty": round(outcome.modulated_novelty, 4),
        "response_gain": round(outcome.response_gain, 4),
        "sensitization": round(outcome.sensitization, 4),
        "combined_gain": round(outcome.combined_gain, 4),
        "effective_repeats": round(outcome.effective_repeats, 4),
        "suppressed": outcome.suppressed,
    }


def habituate_novelty(
    novelty: float,
    content: str,
    repeat_count: int,
    hours_since_last: float | None = None,
    salience: float = 0.0,
    hours_since_salient: float | None = None,
) -> HabituationOutcome:
    """Apply habituation + sensitization to a novelty score.

    ``novelty``              — the gate's combined novelty in [0, 1].
    ``content``              — raw stimulus text (signed via stimulus_signature).
    ``repeat_count``         — prior presentations of this signature (caller-
                               supplied from the store; 0 = first time).
    ``hours_since_last``     — idle time since the last presentation of this
                               signature (drives spontaneous recovery); None if
                               unknown / never seen.
    ``salience``             — importance of the most recent salient event in
                               [0, 1] (0 = none).
    ``hours_since_salient``  — elapsed hours since that salient event; None if
                               there was none.

    Habituation (gain <= 1) suppresses repeated low-salience inputs toward
    rejection; sensitization (factor >= 1) transiently amplifies novelty after
    a salient event. The two multiply. Returns a HabituationOutcome; the caller
    uses ``modulated_novelty`` for the gate decision.
    """
    sig = stimulus_signature(content)
    rgain = response_gain(repeat_count, hours_since_last)
    sfactor = sensitization_factor(salience, hours_since_salient)
    combined = rgain * sfactor
    modulated = max(0.0, min(1.0, novelty * combined))
    eff = effective_repeats(repeat_count, hours_since_last)
    return HabituationOutcome(
        signature=sig,
        modulated_novelty=modulated,
        response_gain=rgain,
        sensitization=sfactor,
        combined_gain=combined,
        effective_repeats=eff,
        suppressed=combined < 1.0,
    )
