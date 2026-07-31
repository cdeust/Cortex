"""Three-way SQLite retrieval benchmark for the #169 zero-download fallback.

The production ``run_benchmark.py`` harness drives the PostgreSQL + pgvector
pipeline (``BenchmarkDB`` → ``PgMemoryStore``) and has no toggle for the
SQLite fallback path or for the embedding mode. Issue #169 changes exactly that
path, so this harness reuses the production harness's dataset loading and
scoring functions verbatim (``session_to_memory_content``,
``parse_longmemeval_date``, ``compute_heat_with_decay``, ``compute_mrr``,
``recall_at_k_binary``) but drives a fresh in-memory ``SqliteMemoryStore`` in
three embedding modes:

  (a) no-vector    — memories stored with no embedding; recall uses FTS + heat
      + recency only. The floor #169 must beat.
  (b) fallback     — deterministic algorithmic embeddings (shared.algorithmic_
      embedding), zero download.
  (c) sentence-transformers — the neural encoder, when present.

Adoption criterion (issue #169): the fallback (b) must beat the no-vector
baseline (a) materially. This harness reports whatever the numbers say.

Run:
    python3 benchmarks/longmemeval/run_sqlite_fallback_bench.py --limit 30

Bounded runs are the intended use (the neural path is untouched by #169, so
full floors are not required — see the PR). ``--limit`` and the git sha / date
are recorded in the emitted MANIFEST so the run is reproducible.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import mcp_server.infrastructure.embedding_engine as ee  # noqa: E402
import mcp_server.infrastructure.embedding_factory as ef  # noqa: E402
from benchmarks.longmemeval.run_benchmark import (  # noqa: E402
    compute_heat_with_decay,
    compute_mrr,
    parse_longmemeval_date,
    recall_at_k_binary,
    session_to_memory_content,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: E402

_MODES = ("no-vector", "fallback", "sentence-transformers")


def _install_engine(mode: str) -> ee.EmbeddingEngine | None:
    """Install the process-wide engine matching ``mode`` (or None for no-vector).

    For 'fallback' a zero-download engine is forced; for
    'sentence-transformers' the real model is loaded (skipped by the caller if
    absent). Returns the engine so the caller can encode queries with the SAME
    encoder that produced the stored vectors.
    """
    ee.reset_embedding_engine()  # clears the factory singleton
    if mode == "no-vector":
        return None
    if mode == "fallback":
        os.environ["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] = "1"
        eng = ee.EmbeddingEngine(model_name="no-such-model-169", dim=384)
    else:
        os.environ.pop("CORTEX_EMBEDDING_ZERO_DOWNLOAD", None)
        eng = ee.EmbeddingEngine(dim=384)
    # Install as the process-wide singleton the store reads for provenance
    # stamping / query-space filtering (issue #169 — the singleton lives in the
    # factory since the #173 seam split).
    ef._singleton = eng
    return eng


def _load_question(store: SqliteMemoryStore, item: dict, eng) -> dict[int, str]:
    """Load one question's haystack into ``store``; return memory_id → sid."""
    question_date = parse_longmemeval_date(item["question_date"])
    id_to_sid: dict[int, str] = {}
    # strict=True: all three lists come from the same haystack record and
    # are documented to correspond 1:1 by index.
    for session, sid, date_str in zip(
        item["haystack_sessions"],
        item["haystack_session_ids"],
        item["haystack_dates"],
        strict=True,
    ):
        content, _ = session_to_memory_content(session)
        date_iso = parse_longmemeval_date(date_str)
        heat = compute_heat_with_decay(date_iso, question_date)
        embedding = eng.encode(content) if eng is not None else None
        mid = store.insert_memory(
            {
                "content": content,
                "embedding": embedding,
                "created_at": date_iso,
                "heat": heat,
                "source": sid,
                "domain": "longmemeval",
            }
        )
        id_to_sid[mid] = sid
    return id_to_sid


def _eval_mode(mode: str, dataset: list[dict]) -> dict[str, float] | None:
    """Run one embedding mode over ``dataset``; return {mrr, recall10, elapsed}.

    Returns None when the mode is unavailable (neural model absent).
    """
    eng = _install_engine(mode)
    if mode == "sentence-transformers" and (eng is None or eng.mode != "neural"):
        return None
    mrrs: list[float] = []
    r10s: list[float] = []
    t0 = time.monotonic()
    for item in dataset:
        store = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
        try:
            id_to_sid = _load_question(store, item, eng)
            q_emb = eng.encode(item["question"]) if eng is not None else None
            results = store.recall_memories(
                item["question"], q_emb, domain="longmemeval", max_results=10
            )
            retrieved = [id_to_sid.get(r["memory_id"], "") for r in results]
            answer_sids = item["answer_session_ids"]
            mrrs.append(compute_mrr(retrieved, answer_sids))
            r10s.append(recall_at_k_binary(retrieved, answer_sids))
        finally:
            store.close()
    return {
        "mrr": sum(mrrs) / len(mrrs) if mrrs else 0.0,
        "recall10": sum(r10s) / len(r10s) if r10s else 0.0,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "n": len(dataset),
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 — "git" resolved via PATH, standard practice; argv is a hardcoded literal list
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _print_table(results: dict[str, dict | None]) -> None:
    print("\n=== LongMemEval-S · SQLite three-way (issue #169) ===")
    print(f"{'mode':<24}{'MRR':>10}{'Recall@10':>12}{'elapsed':>10}")
    for mode in _MODES:
        r = results.get(mode)
        if r is None:
            print(f"{mode:<24}{'n/a':>10}{'n/a':>12}{'n/a':>10}")
        else:
            print(
                f"{mode:<24}{r['mrr']:>10.3f}{r['recall10']:>11.1%}"
                f"{r['elapsed_s']:>9.1f}s"
            )
    base = results.get("no-vector")
    fb = results.get("fallback")
    if base and fb:
        d_mrr = fb["mrr"] - base["mrr"]
        d_r10 = fb["recall10"] - base["recall10"]
        verdict = "BEATS" if (d_mrr > 0 or d_r10 > 0) else "DOES NOT BEAT"
        print(
            f"\nfallback vs no-vector: ΔMRR={d_mrr:+.3f} ΔR@10={d_r10:+.1%} "
            f"→ fallback {verdict} no-vector baseline"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="Questions (0=all)")
    parser.add_argument("--results-out", type=str, default=None)
    args = parser.parse_args()

    data_path = Path(__file__).parent / "longmemeval_s.json"
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        sys.exit(1)
    with data_path.open() as f:
        dataset = json.load(f)
    if args.limit > 0:
        dataset = dataset[: args.limit]

    results: dict[str, dict | None] = {}
    for mode in _MODES:
        print(f"[running] {mode} over {len(dataset)} questions ...")
        results[mode] = _eval_mode(mode, dataset)
    ee.reset_embedding_engine()

    _print_table(results)

    manifest = {
        "benchmark": "longmemeval_s_sqlite_fallback_169",
        "git_sha": _git_sha(),
        "date": datetime.now(timezone.utc).isoformat(),
        "limit": args.limit,
        "n_questions": len(dataset),
        "results": results,
    }
    if args.results_out:
        out = Path(args.results_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(manifest, indent=2))
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
