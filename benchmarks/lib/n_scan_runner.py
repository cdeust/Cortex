"""N-scan harness: synthetic-corpus retrieval at varying corpus sizes.

Per N, runs two conditions: cortex_full (production) and cortex_flat
(env vars CORTEX_DECAY_DISABLED=1, CORTEX_HEAT_CONSTANT=0.5,
CORTEX_CONSOLIDATION_DISABLED=1; loaded memories forced to heat=0.5 so the
condition is observable even when no consumer reads those vars yet).
Uses DB cortex_n_scan (operator must createdb it once) so production data
is never touched. Outputs JSON per (N,cond) + summary.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force CPU embeddings — same convention as longmemeval/run_benchmark.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from benchmarks.lib.bench_db import BenchmarkDB  # noqa: E402

TEMPLATES_PATH = Path(__file__).parent / "n_scan_templates.txt"
RESULTS_DIR = _ROOT / "benchmarks" / "results" / "n_scan"
DEFAULT_DB_URL = "postgresql://localhost:5432/cortex_n_scan"

# source: arbitrary fixed vocabularies for reproducible seeded runs.
ENTITIES = [f"Entity{i:03d}" for i in range(50)]
TOOLS = ["psql", "ruff", "mypy", "pytest", "uv", "git", "docker", "make"]
FILES = [f"src/module_{i:02d}.py" for i in range(20)]
ERRORS = [
    "ConnectionRefused",
    "TypeError",
    "ValueError",
    "DeadlockDetected",
    "TimeoutError",
    "NullPointerException",
    "AssertionError",
]
ACTIONS = [
    "deployment",
    "migration",
    "rollout",
    "import",
    "indexing",
    "validation",
    "benchmarking",
]
COMPONENTS = ["core", "infra", "handlers", "shared", "server", "hooks"]
VALUES = ["10", "25", "50", "100", "1.5", "2x", "0.95", "5"]

DISTRACTOR_FRACTION = 0.05  # source: spec.
MIN_QUERIES = 5  # source: spec.


@dataclass
class CorpusItem:
    text: str
    metadata: dict
    query: str
    ground_truth_idx: int  # index into the corpus list


# ── Template loading & filling ───────────────────────────────────────────


def _load_templates() -> list[tuple[str, str]]:
    """Return list of (kind, template) parsed from n_scan_templates.txt."""
    out: list[tuple[str, str]] = []
    for line in TEMPLATES_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, tmpl = line.partition("|")
        if not tmpl:
            continue
        out.append((kind.strip(), tmpl.strip()))
    return out


def _fill(template: str, rng: random.Random) -> tuple[str, dict[str, str]]:
    """Substitute placeholders. Return (text, slot_dict)."""
    slots: dict[str, str] = {
        "entity": rng.choice(ENTITIES),
        "tool": rng.choice(TOOLS),
        "file": rng.choice(FILES),
        "error": rng.choice(ERRORS),
        "action": rng.choice(ACTIONS),
        "value": rng.choice(VALUES),
        "component": rng.choice(COMPONENTS),
    }
    text = template
    for slot, val in slots.items():
        text = text.replace("{" + slot + "}", val)
    return text, slots


def _query_for(text: str, slots: dict[str, str], rng: random.Random) -> str:
    """Build a query from the most-distinguishing slots (entity/error/file)."""
    parts = [slots.get("entity", ""), slots.get("error", ""), slots.get("file", "")]
    parts = [p for p in parts if p]
    if not parts:
        parts = [slots.get("tool", ""), slots.get("component", "")]
    rng.shuffle(parts)
    return "What do we know about " + " and ".join(parts) + "?"


_PARAPHRASE_SWAPS = [
    ("because", "since"),
    ("Decided to", "We decided to"),
    ("Chose", "Picked"),
    ("Encountered", "Hit"),
    ("Approved", "Greenlit"),
    ("Standardized on", "Settled on"),
]


def _paraphrase(text: str) -> str:
    """Generate a near-duplicate distractor by light surface edits."""
    for a, b in _PARAPHRASE_SWAPS:
        if a in text:
            return text.replace(a, b, 1)
    return "Note: " + text


# ── Corpus generation ───────────────────────────────────────────────────


def synth_corpus(n: int, seed: int) -> list[CorpusItem]:
    """Generate corpus of size n with one GT answer per query.

    Pre: n>=1. Post: list of length n; ~5% are paraphrase distractors of
    an earlier item; each item's query has itself as ground truth.
    Invariant: 0 <= ground_truth_idx < n.
    """
    rng = random.Random(seed)
    templates = _load_templates()
    items: list[CorpusItem] = []
    for i in range(n):
        kind, tmpl = rng.choice(templates)
        text, slots = _fill(tmpl, rng)
        query = _query_for(text, slots, rng)
        items.append(
            CorpusItem(
                text=text,
                metadata={"kind": kind, "slots": slots, "synth_idx": i},
                query=query,
                ground_truth_idx=i,
            )
        )
    # Replace ~5% with paraphrases of an earlier item; original stays at gt_idx.
    n_distract = max(0, int(n * DISTRACTOR_FRACTION))
    positions = rng.sample(range(1, n), min(n_distract, n - 1)) if n > 1 else []
    for pos in positions:
        src = rng.randrange(0, pos)
        items[pos] = CorpusItem(
            text=_paraphrase(items[src].text),
            metadata={"kind": "distractor", "of": src, "synth_idx": pos},
            query=items[pos].query,
            ground_truth_idx=items[pos].ground_truth_idx,
        )
    return items


# ── Conditions ──────────────────────────────────────────────────────────


def _apply_condition(condition: str) -> dict[str, str | None]:
    """Set env vars for a condition; return saved env for restore."""
    saved: dict[str, str | None] = {}
    if condition == "cortex_flat":
        for key, val in (
            ("CORTEX_DECAY_DISABLED", "1"),
            ("CORTEX_HEAT_CONSTANT", "0.5"),
            ("CORTEX_CONSOLIDATION_DISABLED", "1"),
        ):
            saved[key] = os.environ.get(key)
            os.environ[key] = val
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _heat_for(condition: str, default: float = 1.0) -> float:
    """Heat for inserted memories (flat=0.5 forces observable effect)."""
    return (
        0.5 if condition == "cortex_flat" else default
    )  # source: spec CORTEX_HEAT_CONSTANT=0.5


# ── Run one (n, condition) trial ────────────────────────────────────────


@dataclass
class TrialResult:
    n: int
    condition: str
    r_at_10: float
    r_at_1: float
    mrr: float
    wall_per_query_ms: float
    rss_peak_mb: float
    seed: int
    n_queries: int


def _select_query_indices(n_corpus: int, n_queries: int, seed: int) -> list[int]:
    rng = random.Random(seed * 31 + 7)
    if n_corpus <= n_queries:
        return list(range(n_corpus))
    return rng.sample(range(n_corpus), n_queries)


def _build_memories(corpus: list[CorpusItem], heat: float) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "content": item.text,
            "user_content": item.text,
            "created_at": now,
            "heat": heat,
            "source": f"synth_{item.metadata['synth_idx']}",
            "tags": ["n_scan", item.metadata["kind"]],
        }
        for item in corpus
    ]


def _evaluate(
    db: BenchmarkDB,
    corpus: list[CorpusItem],
    source_map: dict[int, str],
    query_indices: list[int],
) -> tuple[float, float, float, float]:
    """Return (r_at_10, r_at_1, mrr, wall_per_query_ms)."""
    hits10 = hits1 = 0
    rr_sum = 0.0
    wall_sum = 0.0
    for qi in query_indices:
        item = corpus[qi]
        gt_source = f"synth_{item.ground_truth_idx}"
        t0 = time.monotonic()
        results = db.recall(item.query, top_k=10, domain="n_scan")
        wall_sum += (time.monotonic() - t0) * 1000.0
        retrieved_sources = [source_map.get(r["memory_id"], "") for r in results]
        if gt_source in retrieved_sources:
            hits10 += 1
            rank = retrieved_sources.index(gt_source) + 1
            rr_sum += 1.0 / rank
            if rank == 1:
                hits1 += 1
    n = max(1, len(query_indices))
    return hits10 / n, hits1 / n, rr_sum / n, wall_sum / n


def run_trial(
    n: int, condition: str, seed: int, n_queries: int, db_url: str
) -> TrialResult:
    """Run one (n, condition) trial.

    Pre: n>=1, condition in {full,flat}, n_queries>=1, db_url is benchmark-only.
    Post: TrialResult; database left empty (cleanup in finally).
    """
    print(f"  [n={n} cond={condition} seed={seed}] generating corpus ...")
    corpus = synth_corpus(n, seed)
    query_indices = _select_query_indices(len(corpus), n_queries, seed)
    saved_env = _apply_condition(condition)
    saved_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        with BenchmarkDB(database_url=db_url) as db:
            memories = _build_memories(corpus, _heat_for(condition))
            print(f"  [n={n} cond={condition}] inserting {len(memories)} memories ...")
            _, source_map = db.load_memories(memories, domain="n_scan")
            r10, r1, mrr, wall_per_q = _evaluate(db, corpus, source_map, query_indices)
    finally:
        wall_total = time.monotonic() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if saved_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_db_url
        _restore_env(saved_env)
    print(
        f"  [n={n} cond={condition}] r@10={r10:.3f} r@1={r1:.3f} mrr={mrr:.3f} "
        f"({wall_per_q:.1f}ms/q wall_total={wall_total:.1f}s)"
    )
    return TrialResult(
        n=n,
        condition=condition,
        r_at_10=r10,
        r_at_1=r1,
        mrr=mrr,
        wall_per_query_ms=wall_per_q,
        rss_peak_mb=peak / (1024 * 1024),
        seed=seed,
        n_queries=len(query_indices),
    )


# ── Output ──────────────────────────────────────────────────────────────


def _save_trial(out_dir: Path, result: TrialResult) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.n}_{result.condition}.json"
    payload = {
        "n": result.n,
        "condition": result.condition,
        "seed": result.seed,
        "n_queries": result.n_queries,
        "r_at_10": round(result.r_at_10, 6),
        "r_at_1": round(result.r_at_1, 6),
        "mrr": round(result.mrr, 6),
        "wall_per_query_ms": round(result.wall_per_query_ms, 3),
        "rss_peak_mb": round(result.rss_peak_mb, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": 384,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _write_summary_csv(out_dir: Path, results: list[TrialResult]) -> Path:
    path = out_dir / "summary.csv"
    cols = [
        "n",
        "condition",
        "r_at_10",
        "r_at_1",
        "mrr",
        "wall_per_query_ms",
        "rss_peak_mb",
        "seed",
    ]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            w.writerow(
                [
                    r.n,
                    r.condition,
                    r.r_at_10,
                    r.r_at_1,
                    r.mrr,
                    r.wall_per_query_ms,
                    r.rss_peak_mb,
                    r.seed,
                ]
            )
    return path


# ── CLI ─────────────────────────────────────────────────────────────────


def _conditions_iter(quick: bool) -> Iterator[str]:
    yield "cortex_full"
    if not quick:
        yield "cortex_flat"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, nargs="+", required=True)
    p.add_argument("--queries", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--db-url", default=DEFAULT_DB_URL)
    args = p.parse_args()
    if args.queries < MIN_QUERIES:
        raise SystemExit(f"--queries must be >= {MIN_QUERIES}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / timestamp
    n_values = [min(args.n)] if args.quick else list(args.n)
    print(f"== n-scan :: n={n_values} queries={args.queries} seed={args.seed} ==")
    print(f"   db_url={args.db_url} output_dir={out_dir.relative_to(_ROOT)}")
    results: list[TrialResult] = []
    for n in n_values:
        for cond in _conditions_iter(args.quick):
            try:
                result = run_trial(n, cond, args.seed, args.queries, args.db_url)
            except Exception as exc:
                print(f"  [n={n} cond={cond}] FAILED: {exc!r}")
                continue
            saved_path = _save_trial(out_dir, result)
            print(f"    -> {saved_path.relative_to(_ROOT)}")
            results.append(result)
    if results:
        csv_path = _write_summary_csv(out_dir, results)
        print(f"summary: {csv_path.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
