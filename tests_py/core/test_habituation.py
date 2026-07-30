"""Tests for core.habituation (E1 habituation & sensitization, Rankin 2009).

Covers the four operationalised Rankin criteria: (1) exponential response
decrement, (2) spontaneous recovery, (4) stimulus specificity, (8/9)
dishabituation / sensitization — plus edge cases and the combined write-gate
facing outcome.
"""

from __future__ import annotations

import math

import pytest

from mcp_server.core.habituation import (
    HABITUATION_RATE,
    MIN_RESPONSE_GAIN,
    SALIENCE_THRESHOLD,
    SENSITIZATION_DECAY_HOURS,
    SENSITIZATION_PEAK,
    SPONTANEOUS_RECOVERY_PER_HOUR,
    HabituationOutcome,
    effective_repeats,
    habituate_novelty,
    habituation_outcome_as_dict,
    is_salient,
    response_gain,
    sensitization_factor,
    stimulus_signature,
)


# ── Criterion 4: stimulus specificity via signature ──────────────────────────
def test_signature_normalises_formatting():
    a = stimulus_signature("Fixed the  BUG!!!")
    b = stimulus_signature("fixed the bug")
    assert a == b == "fixed the bug"


def test_signature_distinguishes_different_content():
    assert stimulus_signature("deploy the api") != stimulus_signature("delete the api")


def test_signature_empty():
    assert stimulus_signature("") == ""
    assert stimulus_signature(None) == ""


# ── Criterion 1: exponential response decrement ──────────────────────────────
def test_first_presentation_no_habituation():
    assert response_gain(0) == 1.0


def test_gain_decreases_monotonically_with_repeats():
    gains = [response_gain(n) for n in range(6)]
    assert all(gains[i] > gains[i + 1] for i in range(len(gains) - 1))


def test_gain_is_exponential_form():
    # gain(n) == exp(-rate * n) while above the floor.
    assert response_gain(1) == pytest.approx(math.exp(-HABITUATION_RATE))
    assert response_gain(2) == pytest.approx(math.exp(-2 * HABITUATION_RATE))


def test_gain_respects_floor():
    assert response_gain(1000) == MIN_RESPONSE_GAIN
    assert response_gain(50) >= MIN_RESPONSE_GAIN


def test_negative_repeat_count_treated_as_zero():
    assert response_gain(-5) == 1.0


# ── Criterion 2: spontaneous recovery ────────────────────────────────────────
def test_recovery_increases_gain_after_idle():
    fresh = response_gain(3, hours_since_last=0.0)
    rested = response_gain(3, hours_since_last=3.0)
    assert rested > fresh


def test_full_recovery_returns_to_baseline():
    # Enough idle time to erase all repeat credit -> gain back to 1.0.
    hrs = 10.0 / SPONTANEOUS_RECOVERY_PER_HOUR
    assert response_gain(3, hours_since_last=hrs) == pytest.approx(1.0)


def test_effective_repeats_never_negative():
    assert effective_repeats(1, hours_since_last=1000.0) == 0.0


def test_effective_repeats_none_hours_is_raw_count():
    assert effective_repeats(4, None) == 4.0


# ── Criteria 8/9: sensitization / dishabituation ─────────────────────────────
def test_salience_threshold():
    assert is_salient(SALIENCE_THRESHOLD)
    assert is_salient(0.95)
    assert not is_salient(SALIENCE_THRESHOLD - 0.01)


def test_no_salient_event_is_baseline():
    assert sensitization_factor(0.0, None) == 1.0
    assert sensitization_factor(1.0, None) == 1.0


def test_sensitization_peak_immediately_after_event():
    # Full salience, zero elapsed -> peak factor.
    assert sensitization_factor(1.0, 0.0) == pytest.approx(SENSITIZATION_PEAK)


def test_sensitization_scales_with_salience():
    assert sensitization_factor(0.5, 0.0) < sensitization_factor(1.0, 0.0)
    assert sensitization_factor(0.5, 0.0) > 1.0


def test_sensitization_decays_to_baseline():
    assert sensitization_factor(1.0, SENSITIZATION_DECAY_HOURS) == pytest.approx(1.0)
    assert sensitization_factor(1.0, SENSITIZATION_DECAY_HOURS + 5) == 1.0


def test_sensitization_monotonic_decay():
    vals = [sensitization_factor(1.0, h) for h in [0.0, 1.0, 3.0, 5.0]]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_sensitization_negative_hours_baseline():
    assert sensitization_factor(1.0, -2.0) == 1.0


# ── Combined outcome: habituate_novelty ──────────────────────────────────────
def test_first_time_novelty_unchanged():
    out = habituate_novelty(0.8, "brand new thing", repeat_count=0)
    assert isinstance(out, HabituationOutcome)
    assert out.modulated_novelty == pytest.approx(0.8)
    assert out.combined_gain == pytest.approx(1.0)
    assert out.suppressed is False


def test_repeated_low_salience_is_suppressed():
    out = habituate_novelty(0.8, "same log line", repeat_count=4)
    assert out.modulated_novelty < 0.8
    assert out.response_gain < 1.0
    assert out.suppressed is True


def test_salient_event_amplifies_novelty():
    out = habituate_novelty(
        0.5, "unseen content", repeat_count=0, salience=1.0, hours_since_salient=0.0
    )
    assert out.modulated_novelty > 0.5
    assert out.sensitization > 1.0
    assert out.suppressed is False


def test_dishabituation_salient_event_offsets_habituation():
    habituated = habituate_novelty(0.6, "repeat", repeat_count=4)
    dishab = habituate_novelty(
        0.6, "repeat", repeat_count=4, salience=1.0, hours_since_salient=0.0
    )
    assert dishab.modulated_novelty > habituated.modulated_novelty


def test_modulated_novelty_clamped():
    out = habituate_novelty(
        0.95, "x", repeat_count=0, salience=1.0, hours_since_salient=0.0
    )
    assert 0.0 <= out.modulated_novelty <= 1.0


def test_recovery_reduces_suppression_over_time():
    fresh = habituate_novelty(0.8, "same", repeat_count=4, hours_since_last=0.0)
    rested = habituate_novelty(0.8, "same", repeat_count=4, hours_since_last=4.0)
    assert rested.modulated_novelty > fresh.modulated_novelty


def test_outcome_as_dict_roundtrip():
    out = habituate_novelty(0.7, "abc def", repeat_count=2)
    d = habituation_outcome_as_dict(out)
    assert set(d) == {
        "signature",
        "modulated_novelty",
        "response_gain",
        "sensitization",
        "combined_gain",
        "effective_repeats",
        "suppressed",
    }
    assert d["signature"] == "abc def"


def test_zero_novelty_stays_zero():
    out = habituate_novelty(
        0.0, "x", repeat_count=0, salience=1.0, hours_since_salient=0.0
    )
    assert out.modulated_novelty == 0.0


def test_habituation_outcome_as_dict_full_shape_and_rounding():
    # Every float carries a 5th decimal digit so round(x, 4) vs round(x, 5)
    # and vs round(x, None) (int truncation) are all observably different
    # (issue #282 mutation-testing gap: habituate_novelty's own output
    # values above only had 1-2 significant decimals, which rounds
    # identically at every precision this dict serializes to).
    out = HabituationOutcome(
        signature="sig",
        modulated_novelty=0.512345,
        response_gain=0.698765,
        sensitization=1.287654,
        combined_gain=0.712345,
        effective_repeats=2.198765,
        suppressed=True,
    )
    d = habituation_outcome_as_dict(out)
    assert d == {
        "signature": "sig",
        "modulated_novelty": round(0.512345, 4),
        "response_gain": round(0.698765, 4),
        "sensitization": round(1.287654, 4),
        "combined_gain": round(0.712345, 4),
        "effective_repeats": round(2.198765, 4),
        "suppressed": True,
    }
