"""Benchmark loaders for E2a subsampling.

Each loader returns (items, probes) where:
- items[i] is one memory ready to load via the production write path,
  carrying a stable ``source_key`` that the scorer matches against
  retrieved sources.
- probes[i] is one query whose ground truth is the set of source keys
  that should be retrieved.

Items are deterministically shuffled by the caller-provided seed so a
prefix of length N is the seed-stable subsample.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SubsampleItem:
    memory: dict
    source_key: str


@dataclass
class QueryProbe:
    query: str
    target_source_keys: list[str]


def load_longmemeval(seed: int) -> tuple[list[SubsampleItem], list[QueryProbe]]:
    """LongMemEval-S: one memory per haystack session; one probe per question."""
    from benchmarks.longmemeval.run_benchmark import (
        parse_longmemeval_date,
        session_to_memory_content,
    )

    data_path = _ROOT / "benchmarks" / "longmemeval" / "longmemeval_s.json"
    with open(data_path) as f:
        dataset = json.load(f)
    seen: dict[str, SubsampleItem] = {}
    probes: list[QueryProbe] = []
    for item in dataset:
        for sess, sid, date_str in zip(
            item["haystack_sessions"],
            item["haystack_session_ids"],
            item["haystack_dates"],
        ):
            if sid in seen:
                continue
            content, user_content = session_to_memory_content(sess, sid)
            iso = parse_longmemeval_date(date_str)
            seen[sid] = SubsampleItem(
                memory={
                    "content": content,
                    "user_content": user_content,
                    "created_at": iso,
                    "source": sid,
                    "tags": ["longmemeval"],
                },
                source_key=sid,
            )
        probes.append(
            QueryProbe(
                query=item["question"], target_source_keys=item["answer_session_ids"]
            )
        )
    items = list(seen.values())
    random.Random(seed).shuffle(items)
    return items, probes


def load_locomo(seed: int) -> tuple[list[SubsampleItem], list[QueryProbe]]:
    """LoCoMo: one memory per session across all conversations."""
    from benchmarks.locomo.data import (
        extract_sessions,
        load_locomo as _load_locomo_data,
        parse_evidence_refs,
    )

    data_path = _ROOT / "benchmarks" / "locomo" / "locomo10.json"
    data = _load_locomo_data(str(data_path))
    items: list[SubsampleItem] = []
    probes: list[QueryProbe] = []
    for conv_idx, conv in enumerate(data):
        sessions = extract_sessions(conv["conversation"])
        for s in sessions:
            sid_str = f"locomo_{conv_idx}_session_{s['session_idx']}"
            items.append(
                SubsampleItem(
                    memory={
                        "content": s["content"],
                        "user_content": s.get("user_content", ""),
                        "created_at": s.get("date", ""),
                        "source": sid_str,
                        "tags": ["locomo"],
                    },
                    source_key=sid_str,
                )
            )
        for qa in conv["qa"]:
            refs = parse_evidence_refs(qa.get("evidence", []))
            target_sids = list({ref[0] for ref in refs})
            target_keys = [f"locomo_{conv_idx}_session_{si}" for si in target_sids]
            if not target_keys:
                continue
            probes.append(
                QueryProbe(query=qa["question"], target_source_keys=target_keys)
            )
    random.Random(seed).shuffle(items)
    return items, probes


def _beam_question_targets(q: dict, turn_id_to_key: dict[int, str]) -> list[str]:
    """Resolve a BEAM probing question's source_chat_ids to source keys."""
    raw_ids = q.get("source_chat_ids", [])
    src_ids: list[int] = []
    if isinstance(raw_ids, dict):
        for v in raw_ids.values():
            if isinstance(v, list):
                src_ids.extend(v)
    elif isinstance(raw_ids, list):
        src_ids = [i for i in raw_ids if isinstance(i, int)]
    return [turn_id_to_key[t] for t in src_ids if t in turn_id_to_key]


def load_beam_100k(seed: int) -> tuple[list[SubsampleItem], list[QueryProbe]]:
    """BEAM-100K: one memory per (user, assistant) turn pair via turns_to_memories."""
    from benchmarks.beam.data import (
        extract_conversation_turns,
        load_beam_dataset,
        parse_probing_questions,
        turns_to_memories,
    )

    ds = load_beam_dataset("100K")
    items: list[SubsampleItem] = []
    probes: list[QueryProbe] = []
    for conv_idx, conversation in enumerate(ds):
        chat = conversation.get("chat", "")
        turns = extract_conversation_turns(chat)
        memories = turns_to_memories(turns)
        turn_id_to_key: dict[int, str] = {}
        for ti, t in enumerate(turns):
            tid = t.get("id", ti)
            turn_id_to_key[tid] = f"beam_{conv_idx}_turn_{tid}"
        for mi, mem in enumerate(memories):
            key = f"beam_{conv_idx}_mem_{mi}"
            mem = {**mem, "source": key, "tags": ["beam"]}
            items.append(SubsampleItem(memory=mem, source_key=key))
        raw_pq = conversation.get("probing_questions", "{}")
        questions = parse_probing_questions(raw_pq)
        for ability, qs in questions.items():
            qs_list = qs if isinstance(qs, list) else [qs]
            for q in qs_list:
                if not isinstance(q, dict):
                    continue
                query = q.get("question", "")
                if not query:
                    continue
                target_keys = _beam_question_targets(q, turn_id_to_key)
                if not target_keys:
                    continue
                probes.append(QueryProbe(query=query, target_source_keys=target_keys))
    random.Random(seed).shuffle(items)
    return items, probes


LOADERS = {
    "longmemeval-s": load_longmemeval,
    "locomo": load_locomo,
    "beam-100K": load_beam_100k,
}
