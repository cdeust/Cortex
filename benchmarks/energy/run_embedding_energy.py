"""Validate the energy protocol before importing optional model dependencies.

source: ADR-0822"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent.parent
# source: ADR-0822
DEFAULT_BATCH_SIZE = 32
# source: ADR-0822
DEFAULT_SAMPLE_RATE_MS = 5000
# source: ADR-0822
MIN_REPETITIONS = 2


def _nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=_nonnegative_float, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--sample-rate-ms", type=int, default=DEFAULT_SAMPLE_RATE_MS)
    parser.add_argument("--external-power-file", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--carbon-intensity",
        type=_nonnegative_float,
        required=True,
        help="region-specific electricity intensity I, in gCO2eq/kWh; no default",
    )
    parser.add_argument(
        "--embodied",
        type=_nonnegative_float,
        required=True,
        help="allocated embodied emission rate, gCO2eq/s; M = rate * phase seconds",
    )
    args = parser.parse_args(argv)
    if args.duration_seconds <= 0 or args.repetitions < MIN_REPETITIONS:
        parser.error("duration must be positive and repetitions >= 2")
    if args.batch_size <= 0 or args.sample_rate_ms <= 0:
        parser.error("batch-size and sample-rate-ms must be positive")
    if not args.validate_only and args.external_power_file is None:
        parser.error(
            "--external-power-file is required; use run.sh to start the sensor"
        )
    return args


def _run(args: argparse.Namespace) -> dict[str, object]:
    # source: ADR-0822
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import benchmarks.lib._composition_root_wiring  # noqa: PLC0415,F401 — source: issue #560

    # Deferred: these modules require NumPy and the optional embedding stack.
    from benchmarks.energy import measurement, workload  # noqa: PLC0415

    workload.wait_for_stream(args)
    engine = workload.load_engine()
    max_abs_delta = workload.verify_equivalence(engine, args.batch_size)
    phases = workload.run_phases(engine, args)
    raw_power = args.external_power_file.read_bytes()
    samples = measurement.parse_power_samples(
        raw_power.decode("utf-8"), max(phase.wall_end for phase in phases)
    )
    rows = measurement.apply_power_samples(phases, samples)
    summary = {
        mode: measurement.summarize(rows, mode, args) for mode in ("scalar", "batch")
    }
    return measurement.write_report(args, (rows, summary), (raw_power, max_abs_delta))


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.validate_only:
        print(args.sample_rate_ms)
        return
    print(json.dumps(_run(args), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
