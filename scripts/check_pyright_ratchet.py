"""Pyright per-rule ratchet gate.

Compares current pyright error counts (grouped by rule) against a committed
compact baseline and fails ONLY when a rule listed as ``--blocking`` exceeds
its baseline count. Non-blocking rules are reported but never fail the build,
so the type-check backlog can be burned down rule-by-rule while a rule that
has already reached its floor can never silently regress.

Why a compact ``{rule: count}`` baseline instead of the raw ``--outputjson``?
The raw dump is ~200 KB of volatile ranges/messages; a per-rule count map is a
few lines, reviewable in a PR diff, and is all the gate actually needs.

Usage::

    # regenerate the committed baseline from a fresh run:
    pyright --outputjson mcp_server/ > pyright-current.json
    python scripts/check_pyright_ratchet.py pyright-current.json \
        typecheck-baseline.json --write-baseline

    # gate (CI): fail if any blocking rule regressed past its baseline:
    python scripts/check_pyright_ratchet.py pyright-current.json \
        typecheck-baseline.json \
        --blocking reportOptionalMemberAccess reportOptionalSubscript

``current`` is the raw output of ``pyright --outputjson``.
``baseline`` is the compact ``{rule: count}`` map this script writes.
"""

from __future__ import annotations

import argparse
import json
import sys


def count_errors_by_rule(pyright_output: dict) -> dict[str, int]:
    """Tally error-severity diagnostics by their pyright rule name."""
    counts: dict[str, int] = {}
    for diagnostic in pyright_output.get("generalDiagnostics", []):
        if diagnostic.get("severity") != "error":
            continue
        rule = diagnostic.get("rule", "<no-rule>")
        counts[rule] = counts.get(rule, 0) + 1
    return counts


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def report(
    current: dict[str, int],
    baseline: dict[str, int],
    blocking: set[str],
) -> list[str]:
    """Print a per-rule delta table; return the regressed blocking rules."""
    regressed: list[str] = []
    for rule in sorted(set(current) | set(baseline)):
        now = current.get(rule, 0)
        was = baseline.get(rule, 0)
        marker = ""
        if rule in blocking and now > was:
            marker = "  <-- BLOCKING REGRESSION"
            regressed.append(rule)
        elif now < was:
            marker = f"  (-{was - now} improved)"
        elif now > was:
            marker = f"  (+{now - was})"
        gate = "[blocking]" if rule in blocking else "[tracked] "
        print(f"  {gate} {rule}: {now} (baseline {was}){marker}")
    return regressed


def write_baseline(current: dict[str, int], path: str) -> int:
    """Overwrite the baseline file from the current counts (sorted, stable)."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(dict(sorted(current.items())), handle, indent=2)
        handle.write("\n")
    total = sum(current.values())
    print(f"Wrote baseline ({total} errors across {len(current)} rules) -> {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pyright per-rule ratchet gate")
    parser.add_argument("current", help="pyright --outputjson output file")
    parser.add_argument("baseline", help="compact {rule: count} baseline file")
    parser.add_argument(
        "--blocking",
        nargs="*",
        default=[],
        help="rules that fail the build when their count exceeds baseline",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="overwrite the baseline from the current run and exit 0",
    )
    args = parser.parse_args()

    current = count_errors_by_rule(load_json(args.current))

    if args.write_baseline:
        return write_baseline(current, args.baseline)

    try:
        baseline = load_json(args.baseline)
    except FileNotFoundError:
        print(f"FATAL: baseline {args.baseline} not found; run --write-baseline first")
        return 2

    total, baseline_total = sum(current.values()), sum(baseline.values())
    print(f"Pyright ratchet — current {total} errors vs baseline {baseline_total}")
    regressed = report(current, baseline, set(args.blocking))

    if regressed:
        print(f"\nFAIL: blocking rule(s) regressed past baseline: {sorted(regressed)}")
        return 1
    print("\nPASS: no blocking rule regressed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
