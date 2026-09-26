"""Paired LongMemEval-S comparison of two SQLite fusion rules.

Each question is ingested once into a throwaway SQLite store and recalled under
the rank-based fusion of commit 61cca3e0 (RRF, k=60) and under the current
max-normalised score fusion, each with and without the reranker. A recall
reinforces the memories it returns (heat, access count), so the store is
restored from an in-memory snapshot before every arm. Results are
appended to a JSONL file, one line per question, so a crashed run resumes.

source: docs/agent-guidance.md (benchmarks are passthrough to production)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ["CORTEX_BENCH_BACKEND"] = "sqlite"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmarks.longmemeval.run_benchmark import (  # noqa: E402
    compute_heat_with_decay,
    compute_mrr,
    parse_longmemeval_date,
    recall_at_k_binary,
    session_to_memory_content,
)
from benchmarks.lib.bench_db import BenchmarkDB  # noqa: E402
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: E402

RRF_COMMIT = "61cca3e0"  # source: last commit before the score-fusion port
SEARCH_PATH = "mcp_server/infrastructure/sqlite_store_search.py"  # source: this repo
FUSION_METHODS = (
    "recall_memories",
    "_signal_vector",
    "_signal_fts",
    "_signal_heat",
    "_signal_recency",
)  # source: the methods the port changed
ARMS = (
    ("rrf", True),
    ("score", True),
    ("rrf", False),
    ("score", False),
)  # source: (fusion, rerank); the first two are the production pipeline


def _load_rrf_methods() -> dict:
    source = subprocess.run(
        ["git", "show", f"{RRF_COMMIT}:{SEARCH_PATH}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rrf_sqlite_store_search.py"
        path.write_text(source)
        spec = importlib.util.spec_from_file_location("rrf_control", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return {n: getattr(module.SqliteSearchMixin, n) for n in FUSION_METHODS}


def _select(methods: dict) -> None:
    for name, fn in methods.items():
        setattr(SqliteMemoryStore, name, fn)


def _load_memories(item: dict) -> list[dict]:
    question_date = parse_longmemeval_date(item["question_date"])
    memories = []
    for session, sid, date_str in zip(
        item["haystack_sessions"],
        item["haystack_session_ids"],
        item["haystack_dates"],
        strict=True,
    ):
        content, user_content = session_to_memory_content(session, sid)
        date_iso = parse_longmemeval_date(date_str)
        memories.append(
            {
                "content": content,
                "user_content": user_content,
                "created_at": date_iso,
                "heat": compute_heat_with_decay(date_iso, question_date),
                "source": sid,
                "tags": [item["question_type"]],
            }
        )
    return memories


def _native(db: BenchmarkDB) -> sqlite3.Connection:
    return db._store._conn._real._registry.connection()


def _snapshot(db: BenchmarkDB) -> sqlite3.Connection:
    copy = sqlite3.connect(":memory:")
    _native(db).backup(copy)
    return copy


def _restore(db: BenchmarkDB, snapshot: sqlite3.Connection) -> None:
    snapshot.backup(_native(db))


def _first_hit_rank(retrieved: list[str], answers: list[str]) -> int:
    answer_set = set(answers)
    for rank, sid in enumerate(retrieved, 1):
        if sid in answer_set:
            return rank
    return 0


def _done_ids(out: Path) -> set[str]:
    if not out.exists():
        return set()
    return {json.loads(line)["question_id"] for line in out.read_text().splitlines()}


def run(data_path: str, out: Path, start: int, limit: int) -> None:
    dataset = json.load(open(data_path))
    dataset = dataset[start : start + limit] if limit else dataset[start:]
    score_methods = {n: getattr(SqliteMemoryStore, n) for n in FUSION_METHODS}
    rrf_methods = _load_rrf_methods()
    done = _done_ids(out)
    with BenchmarkDB(require_reranker=True, backend="sqlite") as db:
        for index, item in enumerate(dataset, start):
            if item["question_id"] in done:
                continue
            db.clear()
            _, source_map = db.load_memories(_load_memories(item), domain="longmemeval")
            arms = {}
            snapshot = _snapshot(db)
            for fusion, rerank in ARMS:
                _restore(db, snapshot)
                _select(rrf_methods if fusion == "rrf" else score_methods)
                db._momentum_state = {"momentum": 0.5}
                results = db.recall(
                    item["question"], top_k=10, domain="longmemeval", rerank=rerank
                )
                sids = [source_map.get(r["memory_id"], "") for r in results]
                arms[f"{fusion}_rerank{int(rerank)}"] = {
                    "retrieved": sids,
                    "first_hit_rank": _first_hit_rank(sids, item["answer_session_ids"]),
                    "mrr": compute_mrr(sids, item["answer_session_ids"]),
                    "recall10": recall_at_k_binary(sids, item["answer_session_ids"]),
                }
            snapshot.close()
            record = {
                "index": index,
                "question_id": item["question_id"],
                "question_type": item["question_type"],
                "answer_session_ids": item["answer_session_ids"],
                "arms": arms,
            }
            with open(out, "a") as handle:
                handle.write(json.dumps(record) + "\n")
            print(
                f"[{index}] {item['question_type']} "
                + " ".join(f"{k}={v['mrr']:.2f}" for k, v in arms.items()),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", default=str(Path(__file__).parent / "longmemeval_s.json")
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    run(args.data, Path(args.out), args.start, args.limit)
