"""Measure a benchmark run's energy from the phase timeline it writes itself.

Run through ``run.sh`` with ``ENERGY_ENTRY=run_external_energy.py`` so the one
privileged sensor (powermetrics) keeps its existing lifecycle; this entry and
the benchmark it launches stay unprivileged. The benchmark must write
``<stem>.phases.jsonl`` (``--results-out`` on the LongMemEval, LoCoMo and BEAM
runners does), and ``--phases-file`` names that file.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), item (e).
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

REPO = Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.energy.run_embedding_energy import (  # noqa: E402
    DEFAULT_SAMPLE_RATE_MS,
    _nonnegative_float,
)

if TYPE_CHECKING:
    from benchmarks.energy.external_phases import Window


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True, help="benchmark command line")
    parser.add_argument("--phases-file", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=_nonnegative_float, required=True)
    parser.add_argument("--sample-rate-ms", type=int, default=DEFAULT_SAMPLE_RATE_MS)
    parser.add_argument("--external-power-file", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--carbon-intensity", type=_nonnegative_float, required=True)
    parser.add_argument("--embodied", type=_nonnegative_float, required=True)
    args = parser.parse_args(argv)
    if args.idle_seconds <= 0 or args.sample_rate_ms <= 0:
        parser.error("idle-seconds and sample-rate-ms must be positive")
    if not shlex.split(args.command):
        parser.error("--command is empty")
    if not args.validate_only and args.external_power_file is None:
        parser.error(
            "--external-power-file is required; use run.sh to start the sensor"
        )
    return args


def _idle_window(args: argparse.Namespace) -> Window:
    """Sleep ``--idle-seconds`` and return that window as the idle reference."""
    from benchmarks.energy.external_phases import Window  # noqa: PLC0415

    start = time.time()
    time.sleep(args.idle_seconds)
    return Window("idle", "baseline", start, time.time())


def _write_report(args: argparse.Namespace, summary: dict, raw_power: bytes) -> Path:
    from benchmarks.energy.measurement import _manifest  # noqa: PLC0415

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_dir = REPO / "benchmarks" / "results" / "energy" / f"external-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)
    result = {
        "functional_unit": "one scored retrieval query",
        "boundary": "CPU+GPU+ANE power during the benchmark's own phases",
        "command": args.command,
        "phases_file": str(args.phases_file),
        "idle_seconds": args.idle_seconds,
        "sample_rate_ms": args.sample_rate_ms,
        "carbon_intensity_gco2eq_per_kwh": args.carbon_intensity,
        "embodied_rate_gco2eq_per_second": args.embodied,
        "summary": summary,
    }
    (out_dir / "powermetrics.txt").write_bytes(raw_power)
    shutil.copyfile(args.phases_file, out_dir / "phases.jsonl")
    for name, payload in (("results.json", result), ("MANIFEST.json", _manifest())):
        (out_dir / name).write_text(
            json.dumps(payload, indent=2, allow_nan=False) + "\n"
        )
    return out_dir


def _run(args: argparse.Namespace) -> dict[str, object]:
    from benchmarks.energy import external_phases, measurement, workload  # noqa: PLC0415

    workload.wait_for_stream(
        argparse.Namespace(
            duration_seconds=args.idle_seconds,
            sample_rate_ms=args.sample_rate_ms,
            external_power_file=args.external_power_file,
        )
    )
    idle = _idle_window(args)
    subprocess.run(shlex.split(args.command), check=True)  # noqa: S603 — operator command
    windows = external_phases.load_windows(args.phases_file)
    raw_power = args.external_power_file.read_bytes()
    samples = measurement.parse_power_samples(
        raw_power.decode("utf-8"), max(w.wall_end for w in windows)
    )
    summary = external_phases.summarize(
        samples, windows, idle, (args.carbon_intensity, args.embodied)
    )
    out_dir = _write_report(args, summary, raw_power)
    return {"result_dir": str(out_dir), "summary": summary}


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.validate_only:
        print(args.sample_rate_ms)
        return
    print(json.dumps(_run(args), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
