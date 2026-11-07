"""Print the W4-2 plan by default; --execute runs the four full cells sequentially."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import statistics
import uuid

from benchmarks.reranker_matrix.cache import durable_root, verify
from benchmarks.reranker_matrix.pins import cell
from mcp_server.shared.platform import resolve_bash

# source: ADR-0863
CELLS = ("l12-3x", "l12-2x", "l2-3x", "l2-2x")


def commands(output: Path) -> list[list[str]]:
    bash = resolve_bash()  # source: ADR-1101
    return [
        [
            bash,
            "benchmarks/reproduce.sh",
            "--no-ablation",
            "--reranker-cell",
            name,
            "--results-dir",
            str(output / name),
        ]
        for name in CELLS
    ]


def plan(output: Path) -> dict:
    return {
        "cells": [
            {"cell": name, "argv": argv}
            for name, argv in zip(CELLS, commands(output), strict=True)
        ],
        "changed_dimensions": [
            "post-SQL candidate prefix multiplier",
            "reranker model",
        ],
        "defaults_changed": False,
        "beam_floor": "UNAVAILABLE in reproduce.sh",
        "selection": "NONE: collect all cells and full floors before owner decision",
    }


def read_cell(directory: Path, returncode: int) -> dict:
    benchmarks = ("longmemeval-s", "locomo", "beam-100K")
    files = ["MANIFEST.json", "reranker-cell.json"] + [
        stem + suffix
        for stem in benchmarks
        for suffix in (".json", ".reranker-cell.json")
    ]
    present = {
        name: json.loads((directory / name).read_text())
        for name in files
        if (directory / name).is_file()
    }
    return {
        "returncode": returncode,
        "complete_artifacts": len(present) == len(files),
        "results": present,
        "reranker_work": {
            stem: measured_work(present.get(stem + ".reranker-cell.json", {}))
            for stem in benchmarks
        },
        "beam_floor": "UNAVAILABLE",
    }


def measured_work(evidence: dict) -> dict:
    records = evidence.get("reranks", [])
    if not records:
        return {"state": "not measured"}
    # source: ADR-0863
    return {
        "state": "measured",
        "calls": len(records),
        "candidates": sum(record["reranked_count"] for record in records),
        "wall_median_ns": statistics.median(record["wall_ns"] for record in records),
        "cpu_median_ns": statistics.median(record["cpu_ns"] for record in records),
    }


def consistent_inputs(results: dict) -> bool:
    identities = []
    for result in results.values():
        if not result["complete_artifacts"]:
            return False
        artifacts = result["results"]
        manifest, evidence = artifacts["MANIFEST.json"], artifacts["reranker-cell.json"]
        fields = (
            "git_sha",
            "longmemeval_dataset_sha256",
            "embedding_model_revision",
            "pg_image",
            "packages",
            "python",
        )
        identity = {name: manifest.get(name) for name in fields}
        identity.update(
            {
                "code": evidence.get("code_sha256"),
                "reranker_packages": evidence.get("packages"),
            }
        )
        identity["corpora"] = {
            name: artifacts[name + ".reranker-cell.json"].get("datasets")
            for name in ("locomo", "beam-100K")
        }
        if not all(identity["corpora"].values()):
            return False
        if any(value is None or value == "unresolved" for value in identity.values()):
            return False
        identities.append(identity)
    return bool(identities) and all(item == identities[0] for item in identities)


def execute(output: Path) -> dict:
    for name in ("l12-3x", "l2-3x"):
        verify(durable_root(), cell(name).model)
    output.mkdir(parents=True, exist_ok=False)
    metadata = plan(output)
    # source: ADR-0863
    run_id = "w4-2-" + uuid.uuid4().hex
    environment = dict(os.environ, CORTEX_BENCH_DETERMINISTIC_RUN_ID=run_id)
    metadata["deterministic_run_id"] = run_id
    results = {}
    for name, argv in zip(CELLS, commands(output), strict=True):
        with (output / f"{name}.log").open("w") as log:
            result = subprocess.run(
                argv, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        results[name] = read_cell(output / name, result.returncode)
        metadata["results"] = results
        metadata["same_inputs"] = consistent_inputs(results)
        (output / "matrix.json").write_text(json.dumps(metadata, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.execute:
        print(json.dumps(plan(output), indent=2))
        return
    result = execute(output)
    if not result["same_inputs"] or any(
        c["returncode"] or not c["complete_artifacts"]
        for c in result["results"].values()
    ):
        raise SystemExit(
            "one or more cells failed; all four outcomes retained in matrix.json"
        )


if __name__ == "__main__":
    main()
