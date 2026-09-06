"""Validate and aggregate measured PostToolUse timings; never executes hooks.

Usage: python scripts/aggregate_hook_timings.py --before before.json \
    --after after.json --plugin-before plugin-before.json \
    --plugin-after plugin-after.json --output comparison.json

Each input JSON report contains entrypoint ('module' or 'launcher'), python,
platform, plugin_sha256, and cases: [{payload: {...}, samples: [...]}]. Each
sample contains repetition (0..3), module (fully qualified), exit_code,
user_seconds, system_seconds, wall_seconds, and max_rss_native.
Alternatively provide time_log instead of those four metrics: the parser
reads a real macOS /usr/bin/time -l stderr log, with LC_ALL=C.

source: tasks/codex-green-remediation-plan.md §3/W2-1: four repetitions,
first excluded; identical Read/Bash payloads and environment before/after.
Sum user+system CPU across the hooks actually routed for each repetition.
The wall sum is sequential work, NOT Claude latency: matching hooks run in
parallel. Keep individual peak RSS values; their sum is not a measured peak.
Routing source: https://code.claude.com/docs/en/hooks#matcher-patterns.
Only the exact-name / pipe-separated matchers used here are supported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

# source: remediation plan §3, four repetitions and the first discarded.
REPETITIONS = 4
_PREFIX = "mcp_server.hooks."
MODULES = {
    _PREFIX + name
    for name in (
        "post_tool_capture",
        "preemptive_context",
        "pipeline_impact_bump",
        "post_commit_reindex",
    )
}
_METRICS = ("user_seconds", "system_seconds", "wall_seconds", "max_rss_native")


def read_time_log(path: Path) -> dict:
    """Parse BSD time's measured values; reject ambiguous or missing output.

    source: apple-oss-distributions/shell_cmds, time/time.c (real/user/sys
    summary and maximum resident set size output under -l).
    """
    raw = path.read_text()
    duration = r"([0-9]+(?:\.[0-9]+)?)"
    summary = re.findall(
        rf"^\s*{duration}\s+real\s+{duration}\s+user\s+{duration}\s+sys\s*$",
        raw,
        re.MULTILINE,
    )
    rss = re.findall(r"^\s*([0-9]+)\s+maximum resident set size\s*$", raw, re.MULTILINE)
    if len(summary) != 1 or len(rss) != 1:
        raise ValueError(f"Missing or ambiguous BSD time measurements: {path}")
    wall, user, system = map(float, summary[0])
    return {
        "wall_seconds": wall,
        "user_seconds": user,
        "system_seconds": system,
        "max_rss_native": int(rss[0]),
    }


def _measured_sample(sample: dict) -> dict:
    if "time_log" not in sample:
        return sample
    if any(metric in sample for metric in _METRICS):
        raise ValueError("Supply either a raw timing log or explicit metrics, not both")
    return {**sample, **read_time_log(Path(sample["time_log"]))}


def selected_modules(plugin: dict, tool: str) -> set[str]:
    """Resolve this plugin's exact matchers without executing its shell strings."""
    selected = set()
    configured = []
    for group in plugin["hooks"]["PostToolUse"]:
        matcher = group.get("matcher", "*")
        if matcher not in ("", "*") and not re.fullmatch(
            r"[A-Za-z_]+(?:\|[A-Za-z_]+)*", matcher
        ):
            raise ValueError(f"Unsupported matcher: {matcher!r}")
        matches = matcher in ("", "*") or tool in matcher.split("|")
        for handler in group["hooks"]:
            names = re.findall(r"mcp_server\.hooks\.[a-z_]+", handler["command"])
            if len(names) != 1 or handler.get("type") != "command":
                raise ValueError("Expected one module per command hook")
            configured.extend(names)
            if matches:
                selected.add(names[0])
    if set(configured) != MODULES or len(configured) != len(MODULES):
        raise ValueError("Missing, unexpected or duplicate PostToolUse hook")
    return selected


def _sample_key(sample: dict) -> tuple[int, str]:
    repetition = sample["repetition"]
    if type(repetition) is not int or repetition not in range(REPETITIONS):
        raise ValueError("Repetition must be an integer in 0..3")
    if type(sample["exit_code"]) is not int or sample["exit_code"] != 0:
        raise ValueError("Failed hook measurement")
    for metric in _METRICS:
        value = sample[metric]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid measured value for {metric}")
    return repetition, sample["module"]


def aggregate_case(case: dict, plugin: dict) -> dict:
    payload = case["payload"]
    modules = selected_modules(plugin, payload["tool_name"])
    indexed = {}
    for sample in case["samples"]:
        sample = _measured_sample(sample)
        key = _sample_key(sample)
        if key in indexed:
            raise ValueError(f"Duplicate sample: {key}")
        indexed[key] = sample
    expected = {(rep, module) for rep in range(REPETITIONS) for module in modules}
    if set(indexed) != expected:
        raise ValueError(
            "Samples must cover every routed hook exactly once per repetition"
        )
    repetitions = []
    for rep in range(REPETITIONS):
        rows = [indexed[(rep, module)] for module in sorted(modules)]
        repetitions.append(
            {
                "repetition": rep,
                "discarded": rep == 0,
                "cpu_seconds": sum(
                    row["user_seconds"] + row["system_seconds"] for row in rows
                ),
                "wall_seconds_sum": sum(row["wall_seconds"] for row in rows),
                "hooks": rows,
            }
        )
    return {"payload": payload, "modules": sorted(modules), "repetitions": repetitions}


def _case_key(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_report(report: dict, plugin_path: Path) -> dict[str, dict]:
    raw = plugin_path.read_bytes()
    if report["plugin_sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("Plugin fingerprint does not match its supplied snapshot")
    if report["entrypoint"] not in ("module", "launcher"):
        raise ValueError("Specify direct module or launcher measurement explicitly")
    plugin = json.loads(raw)
    cases = {}
    for case in report["cases"]:
        key = _case_key(case["payload"])
        if key in cases:
            raise ValueError("Duplicate payload case")
        cases[key] = aggregate_case(case, plugin)
    if {case["payload"]["tool_name"] for case in cases.values()} != {"Read", "Bash"}:
        raise ValueError("The §3 protocol requires both Read and Bash payloads")
    return cases


def compare_reports(before: dict, after: dict, plugins: tuple[Path, Path]) -> dict:
    for field in ("entrypoint", "python", "platform"):
        if (
            not isinstance(before[field], str)
            or not before[field]
            or before[field] != after[field]
        ):
            raise ValueError(f"Before/after {field} must match")
    old = validate_report(before, plugins[0])
    new = validate_report(after, plugins[1])
    if old.keys() != new.keys():
        raise ValueError("Before/after payloads must be identical")
    comparisons = []
    for key in old:
        pairs = zip(old[key]["repetitions"], new[key]["repetitions"], strict=True)
        deltas = [
            {
                "repetition": left["repetition"],
                "cpu_seconds_after_minus_before": right["cpu_seconds"]
                - left["cpu_seconds"],
            }
            for left, right in pairs
            if not left["discarded"]
        ]
        comparisons.append(
            {"before": old[key], "after": new[key], "retained_deltas": deltas}
        )
    return {
        "entrypoint": before["entrypoint"],
        "python": before["python"],
        "platform": before["platform"],
        "cases": comparisons,
        "wall_note": "Wall sums are sequential work, not parallel Claude hook latency.",
        "rss_note": "Per-hook native RSS retained; no aggregate peak is inferred.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "plugin-before", "plugin-after", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare_reports(
            json.loads(args.before.read_text()),
            json.loads(args.after.read_text()),
            (args.plugin_before, args.plugin_after),
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        parser.error(str(exc))
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
