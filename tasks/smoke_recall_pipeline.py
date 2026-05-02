"""Smoke test: confirm each ablation env-var produces a measurable delta
on a `pg_recall.recall()` call routed through a stub store/embeddings.

For each mechanism: run baseline (all enabled), then run ablated (one
disabled), and compare candidate ID order + scores.

Zero delta on a wired mechanism = wiring failure.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager

import numpy as np

from mcp_server.core.pg_recall import recall


def _emb(dim: int, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v.tobytes()


class _Embeddings:
    dimensions = 384

    def encode(self, text: str) -> bytes:
        h = abs(hash(text)) % (2**31)
        return _emb(self.dimensions, h)


class _Store:
    """Stub PgMemoryStore implementing the methods recall() touches."""

    def __init__(self, n: int = 12) -> None:
        self.n = n
        self._mems: dict[int, dict] = {}
        for i in range(n):
            tokens = ["alpha", "beta", "gamma", "delta", "epsilon"]
            content = f"mem {i} " + " ".join(tokens[: (i % 5) + 1])
            # Spread emotional_valence across [-0.9, +0.9] so the
            # EMOTIONAL_RETRIEVAL / MOOD_CONGRUENT_RERANK stages have a
            # non-degenerate signal to act on. Without varied valence the
            # rerank is a uniform-distance no-op even when enabled.
            valence = round(((i % 7) / 3.0) - 1.0, 3)  # ∈ [-1.0, +1.0]
            self._mems[i] = {
                "id": i,
                "memory_id": i,
                "content": content,
                "embedding": _emb(384, i + 7),
                "heat": 0.5 + 0.05 * i,
                "domain": "smoke",
                "tags": ["alpha"] if i % 2 == 0 else ["beta"],
                "created_at": "2026-04-30T00:00:00Z",
                "importance": 0.5,
                "surprise_score": 0.0,
                "store_type": "episodic",
                "emotional_valence": valence,
            }
        # SA returns a memory NOT in the WRRF top-K to test injection
        self._mems[99] = {
            "id": 99,
            "memory_id": 99,
            "content": "graph-only memory alpha beta gamma extra",
            "embedding": _emb(384, 999),
            "heat": 0.6,
            "domain": "smoke",
            "tags": ["alpha"],
            "created_at": "2026-04-30T00:00:00Z",
            "importance": 0.5,
            "surprise_score": 0.0,
            "store_type": "episodic",
        }

    def recall_memories(self, **kwargs) -> list[dict]:
        # Return base candidates (mid 0..9) sorted by heat desc as the
        # WRRF stand-in. Memory 99 is NOT in this output — only SA can
        # surface it.
        ids = sorted(range(self.n), key=lambda i: -self._mems[i]["heat"])
        return [
            {
                "memory_id": i,
                "content": self._mems[i]["content"],
                "score": 1.0 / (rank + 1),
                "heat": self._mems[i]["heat"],
                "domain": "smoke",
                "tags": self._mems[i]["tags"],
                "created_at": self._mems[i]["created_at"],
                "importance": 0.5,
                "surprise_score": 0.0,
                "store_type": "episodic",
                "emotional_valence": self._mems[i]["emotional_valence"],
            }
            for rank, i in enumerate(ids)
        ]

    # Session-level mood for MOOD_CONGRUENT_RERANK smoke. Real production
    # PgMemoryStore does not expose this method (April 2026); the smoke
    # store simulates the future API so the stage produces a delta.
    def get_user_mood(self) -> float:
        return 0.7

    def get_memory(self, mid: int) -> dict | None:
        return self._mems.get(mid)

    def spread_activation_memories(self, **kwargs):
        # Return memory 99 (not in WRRF) plus a low-weight reference to mid 0
        return [(99, 0.95), (0, 0.20)]

    def search_by_tag_vector(self, *args, **kwargs):
        return []


@contextmanager
def _ablate(env_name: str | None):
    if env_name is None:
        yield
        return
    prev = os.environ.get(env_name)
    os.environ[env_name] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = prev


def _run(env_name: str | None) -> tuple[list[int], list[float], float]:
    store = _Store()
    embs = _Embeddings()
    t0 = time.perf_counter()
    with _ablate(env_name):
        # Query carries a clear positive VADER compound ("fixed deployed
        # excellent") so EMOTIONAL_RETRIEVAL is non-neutral and ablation
        # produces a measurable delta. Domain tokens (alpha/beta/gamma)
        # keep HDC and SA paths active.
        out = recall(
            query="alpha beta gamma extra fixed deployed excellent",
            store=store,
            embeddings=embs,
            top_k=10,
            rerank=False,  # disable FlashRank to isolate pipeline effects
        )
    dt = time.perf_counter() - t0
    return [c["memory_id"] for c in out], [round(c["score"], 6) for c in out], dt


def main() -> None:
    print("=== Recall pipeline smoke ===")
    base_ids, base_scores, base_dt = _run(None)
    print(f"baseline ids: {base_ids}")
    print(f"baseline scores: {base_scores}")
    print(f"baseline latency: {base_dt * 1000:.2f} ms")

    mechs = [
        "CORTEX_ABLATE_HOPFIELD",
        "CORTEX_ABLATE_HDC",
        "CORTEX_ABLATE_SPREADING_ACTIVATION",
        "CORTEX_ABLATE_DENDRITIC_CLUSTERS",
        "CORTEX_ABLATE_EMOTIONAL_RETRIEVAL",
        "CORTEX_ABLATE_MOOD_CONGRUENT_RERANK",
    ]
    deltas = {}
    for env in mechs:
        ids, scores, dt = _run(env)
        ids_diff = ids != base_ids
        scores_diff = scores != base_scores
        deltas[env] = {
            "ids_changed": ids_diff,
            "scores_changed": scores_diff,
            "latency_ms": round(dt * 1000, 2),
            "ids": ids,
            "scores": scores,
        }
        print(f"\n{env}: ids_changed={ids_diff} scores_changed={scores_diff}")
        print(f"  ids: {ids}")
        print(f"  latency: {dt * 1000:.2f} ms")

    # All six must produce a non-trivial delta.
    failures = [
        k for k, v in deltas.items() if not (v["ids_changed"] or v["scores_changed"])
    ]
    print("\n=== Summary ===")
    print(
        json.dumps(
            {"baseline_latency_ms": round(base_dt * 1000, 2), **deltas}, indent=2
        )
    )
    if failures:
        print(f"\nFAIL: zero-delta mechanisms (wiring bug): {failures}")
        raise SystemExit(1)
    print("\nPASS: all 6 mechanisms produce observable deltas.")


if __name__ == "__main__":
    main()
