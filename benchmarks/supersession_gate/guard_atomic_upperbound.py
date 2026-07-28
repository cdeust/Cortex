"""REGRESSION GUARD A2 (read-only): UPPER BOUND on supersede-gate firing over
ATOMIC facts cleanly extracted from the genuine KU update pairs.

Promoted from /tmp probe 2026-06-13 (investigation session fba48610). Locks the
third (decisive-mechanism) falsification layer of the CLOSED
KU-via-supersession thread.

These 12 (old, new) pairs are the atomic facts a Mem0/Supermemory-style LLM
extractor would pull from each KU question's two answer sessions — hand-extracted
faithfully (the agent acting as the A2 extractor, which IS the A2 mechanism:
non-deterministic LLM fact extraction). This is the UPPER BOUND on A2: the real
update pair, cleanly extracted, with all session noise removed.

Gate (identical to remember_helpers.py):
    cosine sim >= 0.85 (curation.MERGE_THRESHOLD)
    AND curation.compute_textual_overlap > 0.5      (jaccard)
    AND curation.detect_contradictions non-empty

Proven finding (2026-06-13, finding 4197901): even at this clean upper bound the
jaccard sub-gate is SOLVED (6/12 pass sim+overlap) but detect_contradictions is
BLIND to numeric/value swaps ("three" -> "four", "27:12" -> "25:50"), so 0/12
fire the full gate. The contradiction detector — not the embedding or jaccard —
is the binding constraint that makes supersession a no-op.

PASS criterion: fired == 0  (contradiction detector remains blind to value swaps;
matches the proven upper bound). A NON-zero result is NOT necessarily a bug — it
means detect_contradictions gained value-swap sensitivity, which would re-open
the A2 path. Either way a maintainer must look: exit 0 on PASS (fired==0),
1 on deviation.

Run: Cortex/.venv/bin/python3 benchmarks/supersession_gate/guard_atomic_upperbound.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from mcp_server.core import curation  # noqa: E402
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: E402

MERGE_THRESHOLD = curation.MERGE_THRESHOLD  # 0.85
OVERLAP_MIN = 0.5

# (qi, question, old_fact, new_fact) — atomic facts, A2 extractor output.
PAIRS = [
    (
        0,
        "5K personal best",
        "My personal best time in the charity 5K run is 27:12.",
        "My personal best time in the charity 5K run is 25:50.",
    ),
    (
        1,
        "Korean restaurants tried",
        "I have tried three Korean restaurants in my city.",
        "I have tried four Korean restaurants in my city.",
    ),
    (
        2,
        "Rachel relocation",
        "Rachel recently moved to Chicago.",
        "Rachel just moved back to the suburbs again.",
    ),
    (
        3,
        "Wells Fargo pre-approval",
        "I got pre-approved for $350,000 from Wells Fargo.",
        "I got pre-approved for $400,000 from Wells Fargo.",
    ),
    (
        4,
        "Yoga frequency",
        "I have been doing yoga twice a week.",
        "I attend yoga classes three times a week.",
    ),
    (
        5,
        "Mom grocery list method",
        "My mom is still stuck on her old paper grocery list.",
        "My mom is using the same grocery list app as me now.",
    ),
    (
        6,
        "Ocean sculpture hours",
        "I have spent around 5-6 hours on my abstract ocean sculpture.",
        "I have already put 10-12 hours into my abstract ocean sculpture.",
    ),
    (7, "Bikes owned", "I currently have three bikes.", "I currently have four bikes."),
    (
        8,
        "Cocktail class day",
        "I have a cocktail-making class on Thursday.",
        "I have a cocktail-making class on Fridays.",
    ),
    (
        9,
        "Recent family trip",
        "My recent family trip was to Hawaii.",
        "We just went to Paris as a family last month.",
    ),
    (
        10,
        "Old sneaker storage",
        "I have been keeping my old sneakers under my bed for storage.",
        "I am storing my old sneakers in a shoe rack now.",
    ),
    (
        11,
        "Short stories written",
        "I have written four short stories since I started writing regularly.",
        "I have completed seven short stories since I started writing regularly.",
    ),
]


def main() -> int:
    eng = EmbeddingEngine()
    fired = 0
    sim_pass = 0
    sim_overlap_pass = 0
    print("=" * 78)
    print("GUARD A2: gate over cleanly-extracted ATOMIC update pairs (upper bound)")
    print("=" * 78)
    print(f"{'qi':>2} {'topic':<26} {'sim':>6} {'jacc':>6} {'contra':>7} {'FIRES':>6}")
    print("-" * 78)
    for qi, topic, old, new in PAIRS:
        bo, bn = eng.encode_batch([old, new])
        vo = np.frombuffer(bo, dtype=np.float32)
        vn = np.frombuffer(bn, dtype=np.float32)
        sim = float(np.dot(vo, vn))
        jacc = curation.compute_textual_overlap(old, new)
        contra = curation.detect_contradictions(new, [{"id": 1, "content": old}])
        c_ok = bool(contra)
        s_ok = sim >= MERGE_THRESHOLD
        j_ok = jacc > OVERLAP_MIN
        if s_ok:
            sim_pass += 1
        if s_ok and j_ok:
            sim_overlap_pass += 1
        gate = s_ok and j_ok and c_ok
        if gate:
            fired += 1
        print(
            f"{qi:>2} {topic:<26} {sim:>6.3f} {jacc:>6.3f} "
            f"{str(c_ok):>7} {str(gate):>6}"
        )
    print("-" * 78)
    n = len(PAIRS)
    print(f"sim>=0.85                 : {sim_pass}/{n}")
    print(f"  + jaccard>0.5           : {sim_overlap_pass}/{n}")
    print(f"  + contradiction (FIRES) : {fired}/{n}   <-- A2 upper-bound hit rate")

    # Regression gate: proven upper bound is fired == 0 (contradiction detector
    # blind to value swaps). Any deviation means the binding constraint changed.
    expected = 0
    ok = fired == expected
    print("-" * 78)
    print(
        f"PASS criterion: fired == {expected}  "
        f"(detect_contradictions blind to value swaps)"
    )
    print(f"RESULT: {'PASS' if ok else 'FAIL'} (fired={fired}/{n})")
    if not ok:
        print(
            "DEVIATION: detect_contradictions now fires on cleanly-extracted value "
            "swaps. This is the binding constraint the 2026-06-13 investigation "
            "(Cortex finding 4197901) identified — the A2 supersession path may now "
            "have signal. Re-open before assuming supersession is still a no-op.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
