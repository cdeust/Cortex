"""REGRESSION GUARD A1 (read-only): the committed supersede gate forms ZERO
edges on LME-S KU *after structure-aware decomposition* into chunks.

Promoted from /tmp probe 2026-06-13 (investigation session fba48610). Locks the
second falsification layer of the CLOSED KU-via-supersession thread.

Candidate A premise (Mem0 arxiv 2504.19413 / Supermemory): the jaccard>0.5 gate
is calibrated for atomic facts, not whole 50-turn sessions. The session-level
guard proved 0 edges; this re-runs the EXACT same gate over the production
decomposer's chunks (memory_decomposer.decompose_memory, turn-pair chunks)
instead of whole sessions, to rule out that decomposition alone unlocks edges.

Gate (identical to remember_helpers.py:344-360):
    cosine sim >= 0.85 (curation.MERGE_THRESHOLD)
    AND jaccard word-overlap > 0.5
    AND curation.detect_contradictions(new, [cand]) non-empty

Cross-session pairs only (KU supersession updates a fact across sessions).
No DB writes, no recall change.

PASS criterion (proven 2026-06-13, finding 4197880): full_gate == 0.
Exit 0 on PASS, 1 on regression (any edge forms).

Run: Cortex/.venv/bin/python3 benchmarks/supersession_gate/guard_chunk_granularity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from mcp_server.core import curation  # noqa: E402
from mcp_server.core.memory_decomposer import decompose_memory  # noqa: E402
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: E402

# source: structural — an edge needs a pair of chunks to compare
_MIN_CHUNKS_FOR_PAIR = 2

# Cap on the worked examples printed for a regression.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_EXAMPLES = 8

DATA = REPO / "benchmarks/longmemeval/longmemeval_s.json"
MERGE_THRESHOLD = curation.MERGE_THRESHOLD  # 0.85
OVERLAP_MIN = 0.5  # remember_helpers.py:349 — compute_textual_overlap(...) > 0.5


def session_text(session: list[dict]) -> str:
    return "\n".join(
        f"[{t.get('role', 'user')}]: {t.get('content', '')}" for t in session
    )


def main() -> int:
    data = json.load(Path(DATA).open())
    ku = [x for x in data if x["question_type"] == "knowledge-update"]
    eng = EmbeddingEngine()

    tot_pairs = 0
    sim_pass = 0
    sim_overlap_pass = 0
    full_gate = 0
    edges_touch_answer = 0
    per_q_edges: list[int] = []
    max_sim_seen = 0.0
    total_chunks = 0
    examples: list[str] = []

    for qi, item in enumerate(ku):
        sessions = item["haystack_sessions"]
        sids = item["haystack_session_ids"]
        answer_sids = set(item["answer_session_ids"])

        # Decompose every session into chunks; remember each chunk's origin sid.
        chunk_texts: list[str] = []
        chunk_sid: list[str] = []
        # strict=True: sessions/sids are both read from the same
        # haystack record's parallel fields.
        for sess, sid in zip(sessions, sids, strict=True):
            stext = session_text(sess)
            chunks = decompose_memory(stext)
            for c in chunks:
                chunk_texts.append(c["content"])
                chunk_sid.append(sid)
        total_chunks += len(chunk_texts)

        if len(chunk_texts) < _MIN_CHUNKS_FOR_PAIR:
            per_q_edges.append(0)
            continue

        blobs = eng.encode_batch(chunk_texts)
        vecs = [np.frombuffer(b, dtype=np.float32) if b else None for b in blobs]

        q_edges = 0
        n = len(chunk_texts)
        for i in range(n):
            if vecs[i] is None:
                continue
            for j in range(i + 1, n):
                if vecs[j] is None:
                    continue
                if chunk_sid[i] == chunk_sid[j]:
                    continue  # cross-session only (KU updates across sessions)
                tot_pairs += 1
                sim = float(np.dot(vecs[i], vecs[j]))
                if sim > max_sim_seen:
                    max_sim_seen = sim
                if sim < MERGE_THRESHOLD:
                    continue
                sim_pass += 1
                overlap = curation.compute_textual_overlap(
                    chunk_texts[i], chunk_texts[j]
                )
                if overlap <= OVERLAP_MIN:
                    continue
                sim_overlap_pass += 1
                c_ij = curation.detect_contradictions(
                    chunk_texts[i], [{"id": j, "content": chunk_texts[j]}]
                )
                c_ji = curation.detect_contradictions(
                    chunk_texts[j], [{"id": i, "content": chunk_texts[i]}]
                )
                if c_ij or c_ji:
                    full_gate += 1
                    q_edges += 1
                    touch = chunk_sid[i] in answer_sids or chunk_sid[j] in answer_sids
                    if touch:
                        edges_touch_answer += 1
                    if len(examples) < _MAX_EXAMPLES:
                        examples.append(
                            f"Q{qi} sids({chunk_sid[i]},{chunk_sid[j]}) sim={sim:.3f} "
                            f"overlap={overlap:.3f} ans_touch={touch}"
                        )
        per_q_edges.append(q_edges)
        if (qi + 1) % 20 == 0:
            print(
                f"  [{qi + 1}/{len(ku)}] cumulative edges={full_gate} "
                f"chunks={total_chunks}",
                file=sys.stderr,
            )

    print("=" * 64)
    print("GUARD A1: supersede gate on DECOMPOSED chunks (LME-S KU)")
    print("=" * 64)
    print(f"KU questions                 : {len(ku)}")
    print(f"Total chunks (decomposed)    : {total_chunks}")
    print(f"Cross-session chunk pairs    : {tot_pairs}")
    print(
        f"max cosine sim seen          : {max_sim_seen:.4f}  "
        f"(gate needs >= {MERGE_THRESHOLD})"
    )
    print(f"pairs sim>=0.85              : {sim_pass}")
    print(f"  + jaccard overlap>0.5      : {sim_overlap_pass}")
    print(f"  + contradiction (FULL)     : {full_gate}   <-- edges that would form")
    print(f"edges touching answer sess   : {edges_touch_answer}")
    qn = [e for e in per_q_edges if e > 0]
    print(f"questions with >=1 edge      : {len(qn)} / {len(ku)}")
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
            "REGRESSION: chunk-granularity supersede edges now form where the "
            "2026-06-13 falsification proved zero. Re-open the KU-via-supersession "
            "investigation (Cortex finding 4197880) before trusting the gate.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
