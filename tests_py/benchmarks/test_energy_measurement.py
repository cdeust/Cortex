"""Algebraic fixtures for energy/carbon units; no physical measurement occurs."""

from argparse import Namespace
import json
from pathlib import Path

import pytest

from benchmarks.energy import measurement
from benchmarks.energy.workload import Phase


def test_carbon_formula_per_thousand_tokens():
    # Synthetic unit check: 1 kWh, I=2 g/kWh, M=3 g, 2000 tokens -> 2.5 g/1k.
    assert measurement.carbon_per_1k_tokens(3_600_000, 2000, 2, 3) == 2.5
    assert measurement.carbon_per_1k_tokens(3_600_000, 1000, 2, 3) == 5


@pytest.mark.parametrize("tokens", [0, -1])
def test_carbon_formula_refuses_invalid_denominator(tokens):
    with pytest.raises(ValueError, match="token count"):
        measurement.carbon_per_1k_tokens(1, tokens, 1, 1)


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
@pytest.mark.parametrize("position", [0, 2, 3])
def test_carbon_formula_refuses_invalid_inputs(value, position):
    args = [1, 1, 1, 1]
    args[position] = value
    with pytest.raises(ValueError, match="finite and nonnegative"):
        measurement.carbon_per_1k_tokens(*args)


def test_summary_uses_actual_token_counts_and_embodied_phase_duration():
    args = Namespace(carbon_intensity=2, embodied=3)
    phase = Phase("scalar", 0, 0, 2, 2, 4, tokens=2000)
    row = measurement.MeasuredPhase(phase, 1, 1_800_000, 0)
    summary = measurement.summarize([row, row], "scalar", args)
    assert summary["tokens_total"] == 4000
    assert summary["energy_j_per_1k_tokens_mean"] == 1_800_000
    # One kWh * 2 g/kWh + (3 g/s * 2 s) = 8 g for 2000 tokens.
    assert summary["carbon_gco2eq_per_1k_tokens_mean"] == 4


def test_power_parser_requires_combined_boundary():
    text = (
        "*** Sampled system activity (Sun, 06 Sep 2026 12:00:00 +0000) ***\n"
        "Combined Power (CPU + GPU + ANE): 2000 mW\n"
    )
    samples = measurement.parse_power_samples(text)
    assert len(samples) == 1
    assert samples[0][1] == 2
    with pytest.raises(ValueError, match="lacks Combined Power"):
        measurement.parse_power_samples(
            text.replace("Combined Power (CPU + GPU + ANE)", "CPU Power")
        )
    with pytest.raises(ValueError, match="no combined"):
        measurement.parse_power_samples("")


def test_power_samples_are_applied_to_corresponding_idle_phase():
    idle = Phase("idle", 0, 0, 1, 1, 0)
    scalar = Phase("scalar", 0, 2, 4, 2, 4, tokens=10)
    rows = measurement.apply_power_samples([idle, scalar], [(0.5, 2), (3, 1)])
    assert rows[0].raw_system_energy_j == 2
    assert rows[0].idle_power_w == 2
    assert rows[0].dynamic_energy_j == -2  # No silent clamp of idle noise.
    with pytest.raises(RuntimeError, match="no power samples in phase scalar"):
        measurement.apply_power_samples([idle, scalar], [(0.5, 2)])


def test_only_incomplete_final_sample_outside_phases_is_ignored():
    complete = (
        "*** Sampled system activity (Sun, 06 Sep 2026 12:00:00 +0000) ***\n"
        "Combined Power (CPU + GPU + ANE): 2000 mW\n"
    )
    partial = (
        "\n*** Sampled system activity (Sun, 06 Sep 2026 12:00:01 +0000) ***\n"
        "CPU Power: 1000 mW\n"
    )
    expected = measurement.parse_power_samples(complete)
    phase_end = expected[0][0]
    with pytest.warns(RuntimeWarning, match="outside measured phases"):
        assert (
            measurement.parse_power_samples(complete + partial, phase_end) == expected
        )
    with pytest.raises(ValueError, match="lacks Combined Power"):
        measurement.parse_power_samples(complete + partial, phase_end + 1)
    with pytest.raises(ValueError, match="lacks Combined Power"):
        measurement.parse_power_samples(partial + complete, phase_end)


def test_report_preserves_raw_power_and_explicit_units(tmp_path, monkeypatch):
    monkeypatch.setattr(measurement, "REPO", tmp_path)
    monkeypatch.setattr(measurement, "_manifest", lambda: {"fixture": True})
    args = Namespace(
        carbon_intensity=2,
        embodied=3,
        duration_seconds=2,
        repetitions=2,
        batch_size=4,
        sample_rate_ms=1,
    )
    phase = Phase("scalar", 0, 0, 2, 2, 4, tokens=2000)
    row = measurement.MeasuredPhase(phase, 1, 1_800_000, 0)
    raw = b"synthetic raw sensor fixture\n"
    result = measurement.write_report(args, ([row], {}), (raw, 0))
    output = Path(result["result_dir"])
    assert (output / "powermetrics.txt").read_bytes() == raw
    data = json.loads((output / "results.json").read_text())
    assert data["carbon_intensity_gco2eq_per_kwh"] == 2
    assert data["embodied_rate_gco2eq_per_second"] == 3
    assert data["rows"][0]["embodied_gco2eq"] == 6
    assert data["rows"][0]["carbon_gco2eq_per_1k_tokens"] == 4
    assert "1000 model input tokens" in data["functional_units"]
