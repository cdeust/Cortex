"""Energy from a benchmark's own phase timeline (no sensor, no sudo)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.energy import external_phases as ep
from benchmarks.energy import run_external_energy as cli

IDLE = ep.Window("idle", "baseline", 0.0, 10.0)
WINDOWS = [
    ep.Window("ingest", "c1", 20.0, 40.0),
    ep.Window("recall", "c1:0", 40.0, 41.0),
    ep.Window("recall", "c1:1", 41.0, 42.0),
]
# (sample end timestamp, watts)
SAMPLES = [(5.0, 2.0), (30.0, 10.0), (40.5, 6.0), (42.0, 8.0)]


def test_load_windows_reads_the_journal_and_refuses_bad_timelines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "leg.phases.jsonl"
    path.write_text(
        json.dumps({"phase": "recall", "unit": 1, "wall_start": 1.0, "wall_end": 2.0})
        + "\n\n"
    )
    assert ep.load_windows(path) == [ep.Window("recall", "1", 1.0, 2.0)]
    path.write_text(
        json.dumps({"phase": "recall", "unit": "x", "wall_start": 3.0, "wall_end": 2.0})
    )
    with pytest.raises(ValueError, match="ends before"):
        ep.load_windows(path)
    path.write_text("")
    with pytest.raises(ValueError, match="no phases"):
        ep.load_windows(path)


def test_leg_energy_is_an_upper_bound_per_scored_query() -> None:
    leg = ep.leg_summary(SAMPLES, WINDOWS)
    assert leg["elapsed_s"] == 22.0
    assert leg["samples"] == 3
    assert leg["energy_j"] == pytest.approx(8.0 * 22.0)
    assert leg["scored_queries"] == 2
    assert leg["energy_j_per_query_upper_bound"] == pytest.approx(88.0)


def test_condition_without_samples_is_unmeasured_not_estimated() -> None:
    recall = ep.condition_summary(SAMPLES, WINDOWS, "recall")
    assert recall["samples"] == 2
    assert recall["energy_j"] == pytest.approx(7.0 * 2.0)
    short = [ep.Window("recall", "q", 43.0, 43.5)]
    unmeasured = ep.condition_summary(SAMPLES, short, "recall")
    assert unmeasured["energy_j"] is None
    assert "no sample" in str(unmeasured["unmeasured_reason"])


def test_summary_adds_idle_reference_and_sci_carbon() -> None:
    summary = ep.summarize(SAMPLES, WINDOWS, IDLE, (400.0, 0.001))
    assert summary["idle_mean_system_power_w"] == 2.0
    leg = summary["leg"]
    expected = 176.0 / 3_600_000 * 400.0 + 0.001 * 22.0
    assert leg["carbon_gco2eq"] == pytest.approx(expected)
    assert leg["carbon_gco2eq_per_query_upper_bound"] == pytest.approx(expected / 2)
    assert set(summary["conditions"]) == {"ingest", "recall"}


def test_idle_window_without_sample_is_refused() -> None:
    with pytest.raises(RuntimeError, match="idle window"):
        ep.idle_power(SAMPLES, ep.Window("idle", "b", 100.0, 101.0))


def test_cli_validates_before_any_sensor(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(
        [
            "--command",
            "bash benchmarks/reproduce.sh --only locomo",
            "--phases-file",
            "x.phases.jsonl",
            "--idle-seconds",
            "30",
            "--carbon-intensity",
            "50",
            "--embodied",
            "0",
            "--validate-only",
        ]
    )
    assert capsys.readouterr().out.strip() == str(cli.DEFAULT_SAMPLE_RATE_MS)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--command",
                " ",
                "--phases-file",
                "p",
                "--idle-seconds",
                "1",
                "--carbon-intensity",
                "1",
                "--embodied",
                "0",
                "--validate-only",
            ]
        )


def test_leg_without_sample_or_scored_query_is_refused() -> None:
    with pytest.raises(RuntimeError, match="no power sample or no scored query"):
        ep.leg_summary(SAMPLES, [ep.Window("recall", "q", 100.0, 101.0)])
    with pytest.raises(RuntimeError, match="no power sample or no scored query"):
        ep.leg_summary(SAMPLES, [ep.Window("ingest", "c1", 20.0, 40.0)])
