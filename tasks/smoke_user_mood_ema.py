"""Smoke: VADER → user_mood EMA hook + MOOD_CONGRUENT_RERANK delta.

End-to-end signal path on a stub store (no live PG required):

  1. remember() with a positive-valence message → user_mood drifts positive
  2. remember() with a negative-valence message → user_mood drifts back
  3. mood_congruent_rerank with the EMA-driven mood produces score deltas
     vs the same call with user_mood=None
  4. CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1 short-circuits (identity)

Run:
    uv run python tasks/smoke_user_mood_ema.py
"""

from __future__ import annotations

import os

from mcp_server.core.recall_pipeline import mood_congruent_rerank
from mcp_server.handlers.remember_helpers import (
    MOOD_EMA_ALPHA,
    update_user_mood_ema,
)
from mcp_server.shared.vader import vader_compound


class _MoodStore:
    def __init__(self) -> None:
        self.valence: float | None = None

    def get_user_mood(self) -> float | None:
        return self.valence

    def set_user_mood(self, valence: float, arousal: float = 0.0) -> None:
        self.valence = max(-1.0, min(1.0, float(valence)))


def _candidates() -> list[dict]:
    """Five candidates in increasing emotional_valence."""
    return [
        {
            "memory_id": i,
            "content": f"mem {i}",
            "score": 1.0 / (i + 1),
            "heat": 0.5,
            "tags": [],
            "domain": "smoke",
            "created_at": "2026-04-30T00:00:00Z",
            "emotional_valence": v,
        }
        for i, v in enumerate([-0.9, -0.5, 0.0, +0.5, +0.9])
    ]


def main() -> None:
    print(f"MOOD_EMA_ALPHA = {MOOD_EMA_ALPHA}")
    store = _MoodStore()

    pos_msg = "Wonderful breakthrough! I am thrilled and delighted with this success."
    neg_msg = "This is terrible. I hate this awful broken garbage. Frustrated and angry."

    print(f"\n[1] vader_compound(positive) = {vader_compound(pos_msg):+.4f}")
    print(f"    vader_compound(negative) = {vader_compound(neg_msg):+.4f}")

    print("\n[2] EMA progression — positive then negative messages:")
    print(f"    initial mood:               {store.valence}")
    new = update_user_mood_ema(pos_msg, source="user", store=store)
    print(f"    after positive (user):      {new:+.4f}")
    new = update_user_mood_ema(pos_msg, source="user", store=store)
    print(f"    after positive (user):      {new:+.4f}")
    new = update_user_mood_ema(neg_msg, source="user", store=store)
    print(f"    after negative (user):      {new:+.4f}")

    print("\n[3] Source gating — non-user sources do NOT update mood:")
    pre = store.valence
    for src in ("tool", "consolidation", "import", "session"):
        result = update_user_mood_ema(pos_msg, source=src, store=store)
        print(f"    source={src:14s} → returned {result}, mood still {store.valence:+.4f}")
    assert store.valence == pre, "non-user source must not mutate mood"

    print("\n[4] Drive mood strongly positive for rerank delta test:")
    for _ in range(5):
        update_user_mood_ema(pos_msg, source="user", store=store)
    print(f"    mood after 5 positive iters: {store.valence:+.4f}")

    cands = _candidates()
    baseline = mood_congruent_rerank(cands, user_mood=None)
    active = mood_congruent_rerank(cands, user_mood=store.valence)
    base_scores = {c["memory_id"]: c["score"] for c in baseline}
    active_scores = {c["memory_id"]: c["score"] for c in active}

    print("\n[5] mood_congruent_rerank deltas (positive mood):")
    print(f"    {'id':>3}  {'valence':>8}  {'baseline':>10}  {'active':>10}  {'Δ':>10}")
    for cid in sorted(base_scores):
        v = next(c["emotional_valence"] for c in cands if c["memory_id"] == cid)
        bs, as_ = base_scores[cid], active_scores[cid]
        print(f"    {cid:>3}  {v:+8.2f}  {bs:>10.6f}  {as_:>10.6f}  {as_-bs:>+10.6f}")

    delta_congruent = active_scores[4] - base_scores[4]   # high +valence
    delta_incongruent = active_scores[0] - base_scores[0]  # high -valence
    print(
        f"\n    Δ congruent  (id=4, valence +0.9): {delta_congruent:+.6f}"
        f"\n    Δ incongruent(id=0, valence -0.9): {delta_incongruent:+.6f}"
    )
    assert delta_congruent > delta_incongruent, "mood-congruent must gain more"
    assert base_scores != active_scores, "rerank must produce a non-identity delta"
    print("    ✓ mood-congruent candidate gains MORE than incongruent")
    print("    ✓ rerank produces score deltas (NOT identity)")

    print("\n[6] Ablation symmetry — CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1:")
    abl_store = _MoodStore()
    os.environ["CORTEX_ABLATE_MOOD_CONGRUENT_RERANK"] = "1"
    try:
        result = update_user_mood_ema(pos_msg, source="user", store=abl_store)
        assert result is None, "EMA write must be skipped when ablated"
        assert abl_store.valence is None, "store must be untouched"
        print(f"    EMA hook returned {result}, store.valence = {abl_store.valence}")
        # And rerank itself short-circuits
        active_abl = mood_congruent_rerank(cands, user_mood=+0.7)
        assert active_abl == cands, "rerank must be identity when ablated"
        print("    ✓ rerank stage returns identity when ablated")
    finally:
        os.environ.pop("CORTEX_ABLATE_MOOD_CONGRUENT_RERANK", None)

    print("\n✓ smoke OK — VADER → user_mood EMA hook is wired and signal-fed.")


if __name__ == "__main__":
    main()
