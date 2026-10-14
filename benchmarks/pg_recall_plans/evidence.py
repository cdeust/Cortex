"""Summarize real auto_explain output without treating outer Function Scan as proof."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from statistics import median

from benchmarks.pg_recall_plans.fixture import MIN_ROWS
from benchmarks.pg_recall_plans.sql import REPETITIONS, case_labels

# source: ADR-0854
MAX_BUFFERS = 10_000
# source: ADR-0854
MAX_LATENCY_MS = 200
REQUIRED_INDEXES = {
    "idx_memories_embedding",
    "idx_memories_content_tsv",
    "idx_memories_content_trgm",
}


def plan_nodes(plan: dict) -> list[dict]:
    return [plan] + [
        node for child in plan.get("Plans", []) for node in plan_nodes(child)
    ]


def parse_plans(raw: str) -> dict[str, list[dict]]:
    """Nested statements are logged before the labelled outer aggregate."""
    decoder = json.JSONDecoder()
    pending: list[dict] = []
    groups = {}
    for match in re.finditer(r"plan:\s*\n", raw):
        entry, _ = decoder.raw_decode(raw[match.end() :].lstrip())
        pending.append(entry)
        label = re.search(r"'case', '([^']+)'", entry.get("Query Text", ""))
        if label:
            if label[1] in groups:
                raise ValueError(f"duplicate plan case: {label[1]}")
            groups[label[1]] = pending
            pending = []
    if not groups:
        raise ValueError(
            "no labelled nested auto_explain plans; cannot claim index use"
        )
    return groups


def summarize_group(entries: list[dict]) -> dict:
    outer = entries[-1]["Plan"]
    nodes = [node for entry in entries for node in plan_nodes(entry["Plan"])]
    indexes = sorted({n["Index Name"] for n in nodes if "Index Name" in n})
    buffers = outer.get("Shared Hit Blocks", 0) + outer.get("Shared Read Blocks", 0)
    latency = outer["Actual Total Time"]
    return {
        "indexes": indexes,
        "shared_hits_plus_reads": buffers,
        "temp_read": outer.get("Temp Read Blocks", 0),
        "temp_written": outer.get("Temp Written Blocks", 0),
        "executor_ms": latency,
        "limits_pass": buffers <= MAX_BUFFERS and latency <= MAX_LATENCY_MS,
        "index_requirement_pass": REQUIRED_INDEXES.issubset(indexes),
        "cte_scans": [
            {k: n[k] for k in ("CTE Name", "Actual Rows", "Actual Loops") if k in n}
            for n in nodes
            if n.get("Node Type") == "CTE Scan"
        ],
    }


def observations(raw: str) -> dict[str, list[dict]]:
    rows = {}
    for item in json_records(raw):
        if "case" not in item:
            continue
        if item["case"] in rows:
            raise ValueError(f"duplicate result case: {item['case']}")
        rows[item["case"]] = item["rows"]
    return rows


def json_records(raw: str) -> list[dict]:
    """Read successive JSON values; PostgreSQL json_agg may span physical lines."""
    decoder = json.JSONDecoder()
    records = []
    offset = 0
    while offset < len(raw):
        if raw[offset].isspace():
            offset += 1
            continue
        value, offset = decoder.raw_decode(raw, offset)
        if not isinstance(value, dict):
            raise ValueError("expected a PostgreSQL JSON object")
        records.append(value)
    return records


def measurement_context(raw: str) -> dict:
    contexts = [
        item["experiment"] for item in json_records(raw) if "experiment" in item
    ]
    if len(contexts) != 1:
        raise ValueError("expected one observed experiment context")
    context = contexts[0]
    if not isinstance(context, dict):
        raise ValueError("expected an observed experiment context object")
    rows = context.get("fixture_rows")
    clock = context.get("snapshot_now")
    if (
        type(rows) is not int
        or rows < MIN_ROWS
        or not isinstance(clock, str)
        or not clock
    ):
        raise ValueError("missing or invalid fixture cardinality/transaction clock")
    return {
        **context,
        "corpus_scope": (
            "Only this fixture size was exercised; larger corpora are unmeasured."
        ),
        "repetitions": list(REPETITIONS),
        "discarded_performance_repetitions": [REPETITIONS[0]],
        "retained_performance_repetitions": list(REPETITIONS[1:]),
    }


def compare_rows(before: list[dict], after: list[dict]) -> dict:
    """Report every changed field; no unsourced numeric equivalence tolerance."""
    left = canonical_rows(before)
    right = canonical_rows(after)
    shared = left.keys() & right.keys()
    changed = {
        str(key): {
            field: [left[key][field], right[key][field]]
            for field in left[key]
            if left[key][field] != right[key][field]
        }
        for key in shared
        if left[key] != right[key]
    }
    return {
        "missing": sorted(left.keys() - right.keys()),
        "added": sorted(right.keys() - left.keys()),
        "changed": changed,
        "rows_equal": left == right,
        # The frozen reference has no tie-breaker (ADR-1106 added one to the
        # production function): report ordering separately, not as a false
        # semantic failure when every row and score is identical.
        "order_equal": list(left) == list(right),
    }


def canonical_rows(rows: list[dict]) -> dict:
    """PostgreSQL NaN compares equal to itself, unlike Python float NaN.

    source: ADR-0854
    """
    # source: ADR-0854
    return {
        row["memory_id"]: {
            key: "NaN" if isinstance(value, float) and math.isnan(value) else value
            for key, value in row.items()
        }
        for row in rows
    }


def validate_cases(groups: dict, rows: dict) -> list[str]:
    expected = case_labels("before") + case_labels("after")
    if list(groups) != expected or list(rows) != expected:
        raise ValueError("missing, unexpected or out-of-order repetition cases")
    return expected


def aggregate_group(samples: list[dict]) -> dict:
    """First-discarded statistics; no averaging of a failed index requirement."""
    metrics = ("executor_ms", "shared_hits_plus_reads", "temp_read", "temp_written")
    return {
        "sample_count": len(samples),
        "statistics": {
            metric: {
                "median": median(p[metric] for p in samples),
                "min": min(p[metric] for p in samples),
                "max": max(p[metric] for p in samples),
            }
            for metric in metrics
        },
        "all_limits_pass": all(p["limits_pass"] for p in samples),
        "all_index_requirements_pass": all(
            p["index_requirement_pass"] for p in samples
        ),
    }


def aggregate_plans(plans: dict) -> dict:
    grouped: dict[str, list[dict]] = {}
    for label, plan in plans.items():
        case, _, repetition = label.rpartition("-r")
        if int(repetition) != REPETITIONS[0]:
            grouped.setdefault(case, []).append(plan)
    return {case: aggregate_group(samples) for case, samples in grouped.items()}


def compare_repetitions(rows: dict) -> dict:
    return {
        label.removeprefix("before-"): compare_rows(
            rows[label], rows[label.replace("before-", "after-", 1)]
        )
        for label in case_labels("before")
    }


def plan_gate(comparisons: dict, aggregates: dict) -> bool:
    exact_pass = all(
        comparison["rows_equal"]
        for case, comparison in comparisons.items()
        if case.startswith("exact-")
    )
    normal = [aggregates[f"after-normal-{s}"] for s in ("global", "scoped")]
    return exact_pass and all(
        p["all_limits_pass"] and p["all_index_requirements_pass"] for p in normal
    )


def write_summary(directory: Path) -> bool:
    groups = parse_plans((directory / "nested-plans.log").read_text())
    raw = (directory / "results.jsonl").read_text()
    rows = observations(raw)
    context = measurement_context(raw)
    context["case_order"] = validate_cases(groups, rows)
    plans = {name: summarize_group(entries) for name, entries in groups.items()}
    aggregates = aggregate_plans(plans)
    comparisons = compare_repetitions(rows)
    passed = plan_gate(comparisons, aggregates)
    report = {
        "measurement": context,
        "plans": plans,
        "aggregates": aggregates,
        "comparisons": comparisons,
        "plan_gate_pass": passed,
        "quality_floors": "NOT RUN: use full reproduce.sh; BEAM has no runner floor",
    }
    (directory / "summary.json").write_text(json.dumps(report, indent=2))
    return passed
