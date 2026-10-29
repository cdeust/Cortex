"""Issue #706 fixed synthetic-corpus hook/tool comparison on isolated SQLite.

Run only on hosted CI. Each prompt starts a fresh hook process; tool recall is
warm, as in the issue's audit. Each arm receives a copy of the same seeded DB,
so replay/heat writes cannot benefit the other arm. This is a new synthetic
corpus, not a reproduction of the unavailable original audit fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time


# source: issue #706 compares injection at the installed three-memory cap.
_INJECTION_K = 3


def copy_database(source: Path, target: Path) -> None:
    """SQLite backup includes committed WAL pages (SQLite backup API)."""
    with sqlite3.connect(source) as original, sqlite3.connect(target) as copied:
        original.backup(copied)


def configure_paths(root: Path, database: Path) -> None:
    os.environ["CORTEX_CLAUDE_DIR"] = str(root)
    os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    os.environ["CORTEX_MEMORY_DB_PATH"] = str(database)
    os.environ["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = str(database)
    os.environ.pop("CLAUDE_PROJECT_ROOT", None)
    os.environ.pop("CORTEX_ROOT_AGENT_TOPIC", None)


def seed(database: Path, corpus: list[dict]) -> dict:
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — benchmark selects codebase before imports
    from mcp_server.infrastructure.embedding_engine import get_embedding_engine  # noqa: PLC0415 — benchmark selects codebase before imports
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: PLC0415 — benchmark selects codebase before imports
    from mcp_server.core.reranker import ensure_reranker_loaded, model_sha256  # noqa: PLC0415 — benchmark selects codebase before imports

    wire_composition_root()
    embeddings = get_embedding_engine()
    embeddings.download_model()
    vectors = [embeddings.encode(case["memory"]) for case in corpus]
    if embeddings.mode != "neural":
        raise RuntimeError("parity measurement requires neural embeddings")
    status = ensure_reranker_loaded()
    if status.state != "loaded":
        raise RuntimeError(f"parity measurement requires FlashRank: {status}")
    with_store = SqliteMemoryStore(db_path=str(database))
    try:
        if not with_store._has_vec:
            raise RuntimeError("parity measurement requires sqlite-vec")
        for case, vector in zip(corpus, vectors, strict=True):
            with_store.insert_memory(
                {
                    "content": case["memory"],
                    "embedding": vector,
                    "heat": 0.8,
                    "capture_origin": "deliberate",
                    "directory_context": "/corpus",
                    "tags": [],
                }
            )
    finally:
        with_store.close()
    from auto_recall_scores import query_encoder_agreement  # noqa: PLC0415 -- selected codebase is already wired

    return {
        "hook_query_encoder": query_encoder_agreement(corpus),
        "embedding_model": embeddings.model_name,
        "embedding_revision": embeddings.revision,
        "reranker_sha256": model_sha256(),
    }


async def tool_query(database: Path, query: str) -> tuple[list[str], float]:
    from mcp_server.handlers import recall  # noqa: PLC0415 — benchmark selects codebase before imports
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: PLC0415 — benchmark selects codebase before imports

    store = SqliteMemoryStore(db_path=str(database))
    recall._store = store
    started = time.perf_counter()
    try:
        result = await recall._handler_impl(
            {
                "query": query,
                "max_results": 10,
                "min_heat": 0.15,
                "directory": "/corpus",
            }
        )
        return [m["content"] for m in result["memories"]], time.perf_counter() - started
    finally:
        recall._store = None
        store.close()


def hook_query(codebase: Path, database: Path, query: str) -> tuple[str, float, str]:
    env = os.environ.copy()
    env["CORTEX_MEMORY_DB_PATH"] = str(database)
    env["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = str(database)
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.auto_recall"],
        input=json.dumps({"prompt": query, "cwd": "/corpus"}),
        text=True,
        capture_output=True,
        env=env,
        cwd=codebase,
        check=True,
    )
    return result.stdout, time.perf_counter() - started, result.stderr


async def measure(codebase: Path, root: Path, corpus: list[dict]) -> list[dict]:
    source = root / "seed.db"
    rows = []
    for index, case in enumerate(corpus):
        tool_db, hook_db = root / "tool.db", root / "hook.db"
        for target in (tool_db, hook_db):
            if target.exists():
                target.unlink()
            copy_database(source, target)
        tool, tool_seconds = await tool_query(tool_db, case["query"])
        hook, hook_seconds, diagnostics = hook_query(codebase, hook_db, case["query"])
        marker = case["memory"].split(":")[0]
        rank = next((i + 1 for i, text in enumerate(tool) if marker in text), None)
        row = {
            "case": index,
            "tool_rank": rank,
            "hook_hit": marker in hook,
            "tool_seconds": tool_seconds,
            "hook_seconds": hook_seconds,
            "hook_stdout": hook,
            "hook_stderr": diagnostics,
        }
        rows.append(row)
        print(json.dumps(row), flush=True)
    return rows


def measure_negatives(codebase: Path, root: Path) -> list[dict]:
    """Record abstention on prompts outside the fixed fixture's subject matter."""
    # source: explicit negative controls for the committed paraphrase fixture.
    queries = (
        "Describe the quark composition of a neutral kaon.",
        "Explain the metre in an ancient Sumerian epic.",
        "What is the conjugacy class structure of the monster group?",
    )
    rows = []
    for query in queries:
        target = root / "negative.db"
        if target.exists():
            target.unlink()
        copy_database(root / "seed.db", target)
        output, seconds, diagnostics = hook_query(codebase, target, query)
        rows.append(
            {
                "query": query,
                "hook_stdout": output,
                "hook_stderr": diagnostics,
                "hook_seconds": seconds,
            }
        )
    return rows


def summary(rows: list[dict], budget: float) -> dict:
    return {
        "queries": len(rows),
        "tool_hits_at_3": sum(
            r["tool_rank"] is not None and r["tool_rank"] <= _INJECTION_K for r in rows
        ),
        "tool_hits_at_10": sum(r["tool_rank"] is not None for r in rows),
        "tool_mrr": statistics.mean(
            1 / r["tool_rank"] if r["tool_rank"] else 0 for r in rows
        ),
        "hook_hits_at_3": sum(r["hook_hit"] for r in rows),
        "hook_mean_seconds": statistics.mean(r["hook_seconds"] for r in rows),
        "hook_max_seconds": max(r["hook_seconds"] for r in rows),
        "tool_mean_seconds": statistics.mean(r["tool_seconds"] for r in rows),
        "configured_hook_budget_seconds": budget,
        "hook_over_budget_observations": sum(r["hook_seconds"] > budget for r in rows),
    }


def check_results(
    results: dict, rows: list[dict], negatives: list[dict], expect_gap: bool
) -> None:
    """Require the hosted positive and negative retrieval controls."""
    if expect_gap:
        assert results["hook_hits_at_3"] < results["tool_hits_at_3"], results
    else:
        assert all(not row["hook_stdout"] for row in negatives), negatives
        assert results["tool_hits_at_3"] > 0, results
        assert results["hook_hits_at_3"] >= results["tool_hits_at_3"], results
        assert all("auto recall degraded" not in r["hook_stderr"] for r in rows)
    # Latency is reported, not used as a machine-load-dependent test verdict.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codebase", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expect-gap", action="store_true")
    args = parser.parse_args()
    codebase = args.codebase.resolve()
    sys.path.insert(0, str(codebase))
    fixture = Path(__file__).parent / "fixtures" / "auto_recall_paraphrases.json"
    corpus = json.loads(fixture.read_text())
    with tempfile.TemporaryDirectory(prefix="auto-recall-parity-") as temporary:
        root = Path(temporary)
        configure_paths(root, root / "seed.db")
        models = seed(root / "seed.db", corpus)
        # Downloads happen in preflight, never in the hook's measured window.
        os.environ["CORTEX_RERANKER_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        rows = asyncio.run(measure(codebase, root, corpus))
        negatives = measure_negatives(codebase, root)
        from auto_recall_scores import measure_scores  # noqa: PLC0415 -- selected codebase is already wired

        raw_scores = measure_scores(corpus, negatives)
    manifest = json.loads((codebase / ".claude-plugin/plugin.json").read_text())
    budget = manifest["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"]
    results = summary(rows, budget)
    revision = subprocess.check_output(
        ["git", "-C", str(codebase), "rev-parse", "HEAD"], text=True
    ).strip()
    report = {
        "code_sha": revision,
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "negative_queries": negatives,
        "models": models,
        "raw_ce_scores": raw_scores,
        "summary": results,
        "rows": rows,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(results, indent=2), flush=True)
    check_results(results, rows, negatives, args.expect_gap)


if __name__ == "__main__":
    main()
