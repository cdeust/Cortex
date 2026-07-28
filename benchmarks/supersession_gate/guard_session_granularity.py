"""REGRESSION GUARD (read-only): the committed supersede gate forms ZERO edges
on LME-S knowledge-update questions at SESSION granularity.

Promoted from /tmp probe 2026-06-13 (investigation session fba48610). The
KU-via-supersession thread is CLOSED, proven no-op at the metric level; this
guard locks the first falsification layer so a future change to the supersede
gate (remember_helpers.py:344-360) or its thresholds cannot silently start
forming session-level edges without a maintainer noticing.

Replicates the EXACT production supersede condition — for each KU question,
over its haystack sessions:

    candidate is a top-k vector neighbor
    AND cosine sim >= 0.85 (curation.MERGE_THRESHOLD)
    AND jaccard word-overlap > 0.5 (remember_helpers.py:349)
    AND curation.detect_contradictions(new, [cand]) is non-empty

Computes the UNORDERED pairwise UPPER BOUND on edges (sequential insertion can
only form a subset). No DB writes, no recall change.

PASS criterion (proven 2026-06-13, finding 4197865): full_gate == 0.
Exit 0 on PASS, 1 on regression (any edge forms).

Run: Cortex/.venv/bin/python3 benchmarks/supersession_gate/guard_session_granularity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from mcp_server.core import curation  # noqa: E402
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: E402

DATA = REPO / "benchmarks/longmemeval/longmemeval_s.json"
MERGE_THRESHOLD = curation.MERGE_THRESHOLD  # 0.85
OVERLAP_MIN = 0.5  # remember_helpers.py:349 — compute_textual_overlap(...) > 0.5

# Cap on the worked examples printed for a regression.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_EXAMPLES = 5


def session_text(session: list[dict]) -> str:
    return "\n".join(
        f"[{t.get('role', 'user')}]: {t.get('content', '')}" for t in session
    )


def main() -> int:
    data = json.load(open(DATA))
    ku = [x for x in data if x["question_type"] == "knowledge-update"]
    eng = EmbeddingEngine()

    tot_pairs = 0
    sim_pass = 0  # sim >= 0.85
    sim_overlap_pass = 0  # + jaccard > 0.5
    full_gate = 0  # + contradiction  == would-supersede
    edges_touch_answer = 0
    per_q_edges: list[int] = []
    max_sim_seen = 0.0
    examples: list[str] = []

    for qi, item in enumerate(ku):
        sessions = item["haystack_sessions"]
        sids = item["haystack_session_ids"]
        answer_sids = set(item["answer_session_ids"])
        texts = [session_text(s) for s in sessions]
        blobs = eng.encode_batch(texts)
        vecs = [np.frombuffer(b, dtype=np.float32) if b else None for b in blobs]

        q_edges = 0
        n = len(sessions)
        for i in range(n):
            if vecs[i] is None:
                continue
            for j in range(i + 1, n):
                if vecs[j] is None:
                    continue
                tot_pairs += 1
                sim = float(np.dot(vecs[i], vecs[j]))  # both normalized at encode
                if sim > max_sim_seen:
                    max_sim_seen = sim
                if sim < MERGE_THRESHOLD:
                    continue
                sim_pass += 1
                overlap = curation.compute_textual_overlap(texts[i], texts[j])
                if overlap <= OVERLAP_MIN:
                    continue
                sim_overlap_pass += 1
                # contradiction in EITHER direction (newer is the "new_content")
                c_ij = curation.detect_contradictions(
                    texts[i], [{"id": j, "content": texts[j]}]
                )
                c_ji = curation.detect_contradictions(
                    texts[j], [{"id": i, "content": texts[i]}]
                )
                if c_ij or c_ji:
                    full_gate += 1
                    q_edges += 1
                    touch = sids[i] in answer_sids or sids[j] in answer_sids
                    if touch:
                        edges_touch_answer += 1
                    if len(examples) < _MAX_EXAMPLES:
                        examples.append(
                            f"Q{qi} sids({sids[i]},{sids[j]}) sim={sim:.3f} "
                            f"overlap={overlap:.3f} ans_touch={touch}"
                        )
        per_q_edges.append(q_edges)
        if (qi + 1) % 20 == 0:
            print(
                f"  [{qi + 1}/{len(ku)}] cumulative would-supersede edges={full_gate}",
                file=sys.stderr,
            )

    print("=" * 64)
    print("GUARD: supersede-gate edge formation on LME-S KU (SESSION granularity)")
    print("=" * 64)
    print(f"KU questions               : {len(ku)}")
    print(f"Total session pairs tested : {tot_pairs}")
    print(
        f"max cosine sim seen        : {max_sim_seen:.4f}  "
        f"(gate needs >= {MERGE_THRESHOLD})"
    )
    print(f"pairs sim>=0.85            : {sim_pass}")
    print(f"  + jaccard overlap>0.5    : {sim_overlap_pass}")
    print(f"  + contradiction (FULL)   : {full_gate}   <-- edges that would form")
    print(f"edges touching answer sess : {edges_touch_answer}")
    qn = [e for e in per_q_edges if e > 0]
    print(f"questions with >=1 edge    : {len(qn)} / {len(ku)}")
    if examples:
        print("examples:")
        for e in examples:
            print("  " + e)

    # Regression gate: proven finding is full_gate == 0.
    expected = 0
    ok = full_gate == expected
    print("-" * 64)
    print(f"PASS criterion: full_gate == {expected}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} (full_gate={full_gate})")
    if not ok:
        print(
            "REGRESSION: session-granularity supersede edges now form where the "
            "2026-06-13 falsification proved zero. Re-open the KU-via-supersession "
            "investigation (Cortex finding 4197865) before trusting the gate.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
