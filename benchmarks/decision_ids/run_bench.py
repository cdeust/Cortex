"""Measure exact wiki-identity known-item retrieval coverage.

source: ADR-0819
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import AsyncMock, Mock, patch

from mcp_server.composition_root import wire_composition_root  # noqa: E402 — source: issue #560

wire_composition_root()

from mcp_server.handlers import recall, unified_search  # noqa: E402
from mcp_server.infrastructure.wiki_decision_index import write_decision_index  # noqa: E402

# source: ADR-0819
BASELINE_REF = "e81735de3eb2248c134980008b2485d7d2a6dcc9"
# source: ADR-0819
KNOWN_IDS = ("ADR-0001", "ADR-0055", "ADR-0056", "ADR-2019", "ADR-9999")


def _seed(project: Path) -> None:
    wiki = project / "wiki"
    (wiki / "adr").mkdir(parents=True)
    (wiki / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "project": "known-item-benchmark",
                "pages": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads((wiki / "manifest.json").read_text())
    for identifier in KNOWN_IDS:
        page = wiki / "adr" / f"{identifier[4:]}-known-item.md"
        page.write_text(
            f"# {identifier}\n\nCanonical wiki-only decision.\n", encoding="utf-8"
        )
        manifest["pages"][identifier] = {
            "path": str(page.relative_to(wiki)),
            "mirror": "ADR-" + page.name,
        }
    (wiki / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    write_decision_index(wiki)


def _baseline_handler():
    root = Path(__file__).resolve().parents[2]
    source = subprocess.run(
        [
            "git",
            "show",
            f"{BASELINE_REF}:mcp_server/handlers/unified_search.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    namespace = {"__name__": "decision_ids_baseline"}
    exec(compile(source, f"{BASELINE_REF}:unified_search.py", "exec"), namespace)
    namespace["recall_handler"] = AsyncMock(return_value={"memories": []})
    namespace["is_enabled"] = lambda: False
    return namespace["handler"]


async def _measure(handler, project: Path) -> dict:
    ranks = []
    for identifier in KNOWN_IDS:
        response = await handler({"query": identifier, "project_root": str(project)})
        ids = [item["id"] for item in response.get("results", [])][:10]
        expected = f"wiki:{identifier}"
        ranks.append(ids.index(expected) + 1 if expected in ids else None)
    return {
        "n_queries": len(ranks),
        "ranks": ranks,
        "recall_at_1": sum(rank == 1 for rank in ranks) / len(ranks),
        "mrr_at_10": sum(1 / rank if rank else 0 for rank in ranks) / len(ranks),
    }


def _block_backends(stack: ExitStack) -> dict:
    targets = {
        "embedding": (recall, "get_embedding_engine", Mock),
        "memory_store": (recall, "_get_store", Mock),
        "ap": (unified_search, "WorkflowGraphASTSource", Mock),
        "semantic_recall": (unified_search, "recall_handler", AsyncMock),
    }
    return {
        name: stack.enter_context(
            patch.object(
                module,
                attribute,
                factory(side_effect=AssertionError(name + " call")),
            )
        )
        for name, (module, attribute, factory) in targets.items()
    }


async def run_benchmark() -> dict:
    with tempfile.TemporaryDirectory(prefix="cortex-decision-ids-") as directory:
        project = Path(directory)
        _seed(project)
        before = await _measure(_baseline_handler(), project)
        with ExitStack() as stack:
            probes = _block_backends(stack)
            after = await _measure(unified_search.handler, project)
            calls = {name: probe.call_count for name, probe in probes.items()}
    passed = (
        after["recall_at_1"] == 1
        and after["mrr_at_10"] == 1
        and not any(calls.values())
    )
    return {
        "benchmark": "decision_ids",
        "scope": "wiki-only known-item source coverage; no PG ranking claim",
        "baseline_ref": BASELINE_REF,
        "known_ids": KNOWN_IDS,
        "before": before,
        "after": after,
        "exact_path_calls": calls,
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run_benchmark())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
