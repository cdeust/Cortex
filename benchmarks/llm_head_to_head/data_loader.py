"""BEAM-10M data loader — 196 items, source_chat_ids → gold-supporting turns.

Reuses ``benchmarks.beam.data`` (the existing 196-item discovery + chat-id
flattening). This module is the SINGLE source of truth for "what items are
in the protocol universe" — every condition builder receives items from
``load_items()`` so they all see the same questions in the same order.

precondition: HuggingFace ``datasets`` package installed; network reachable
  on first run (cached afterwards) per ``benchmarks/beam/data.py::load_beam_dataset``.
postcondition: ``load_items()`` returns exactly 196 BeamItem records when
  the BEAM-10M split is reachable. Item count mismatch → raises ValueError
  per protocol §5 ("This is the universe"). Order is dataset-iteration
  order — deterministic across runs because the HF dataset is content-
  addressed.
invariant: source_chat_ids on each item are GLOBAL turn IDs (post-flatten
  by ``extract_10m_chat``), matching what's in the conversation `turns`
  list. The gold-supporting-turn lookup in ``oracle_loader.py`` depends
  on this.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Re-use the existing BEAM loader without modifying it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.beam.data import (  # noqa: E402
    extract_10m_chat,
    extract_conversation_turns,
    load_beam_dataset,
    parse_probing_questions,
    turns_to_memories,
)


# Pre-registered universe size from protocol §5 (Tavakoli et al. 2026, Table 2).
EXPECTED_ITEM_COUNT = 196

# pre-registered RNG seeds (protocol §10 manifest, §11.5 anti-cheating).
SHUFFLE_SEED_BASE = 20260501
JUDGE_SHUFFLE_BASE = 20260501  # same base, per-question delta in judge.py
BOOTSTRAP_SEED = 20260503


@dataclass(frozen=True)
class BeamItem:
    """One BEAM-10M probing question + its conversation context.

    Equality is on ``question_id`` only so the same item from two loads
    is deduplicated correctly.
    """

    question_id: str
    conversation_idx: int
    ability: str
    question: str
    gold_answer: str
    source_chat_ids: tuple[int, ...]
    # Conversation context, copied by reference at construction time. The
    # ``turns`` list is the GLOBAL-id-numbered flat list produced by
    # ``extract_10m_chat`` + ``extract_conversation_turns``.
    turns: list[dict] = field(default_factory=list, hash=False, compare=False)
    memories: list[dict] = field(default_factory=list, hash=False, compare=False)

    def __hash__(self) -> int:
        return hash(self.question_id)


def _flatten_source_ids(raw: object) -> tuple[int, ...]:
    """source_chat_ids may be list[int] or dict-of-lists. Flatten to tuple[int].

    pre: raw is whatever BEAM emits in ``probing_questions[ability][i]``.
    post: returns a tuple of int turn IDs (possibly empty for abstention).
    """
    if isinstance(raw, dict):
        out: list[int] = []
        for v in raw.values():
            if isinstance(v, list):
                out.extend(i for i in v if isinstance(i, int))
            elif isinstance(v, int):
                out.append(v)
        return tuple(out)
    if isinstance(raw, list):
        return tuple(i for i in raw if isinstance(i, int))
    return ()


def iter_items(split: str = "10M") -> Iterator[BeamItem]:
    """Yield BeamItems in dataset-iteration order.

    pre: split == "10M" for the protocol (other splits accepted for smoke
      tests but emit a warning to stderr).
    post: each yielded item's ``turns`` and ``memories`` are non-empty
      iff the underlying conversation had probing_questions; empties are
      skipped.
    """
    if split != "10M":
        print(
            f"[data_loader] WARNING: split={split} is not the pre-registered "
            "10M universe; results not protocol-valid.",
            file=sys.stderr,
        )

    ds = load_beam_dataset(split)
    for conv_idx, conversation in enumerate(ds):
        # BEAM-10M aggregates 10 sub-plans into one ~10M-token convo.
        if split == "10M":
            chat = extract_10m_chat(conversation)
        else:
            chat = conversation.get("chat", "")

        turns = extract_conversation_turns(chat)
        memories = turns_to_memories(turns)
        if not turns:
            continue

        raw_pq = conversation.get("probing_questions", "{}")
        questions = parse_probing_questions(raw_pq)
        if not questions:
            continue

        for ability, qs in questions.items():
            if not isinstance(qs, list):
                qs = [qs]
            for q_idx, q in enumerate(qs):
                if not isinstance(q, dict):
                    continue
                question_text = q.get("question", "")
                if not question_text:
                    continue
                yield BeamItem(
                    question_id=f"conv{conv_idx:03d}-{ability}-{q_idx:02d}",
                    conversation_idx=conv_idx,
                    ability=ability,
                    question=question_text,
                    gold_answer=q.get("answer", "") or "",
                    source_chat_ids=_flatten_source_ids(q.get("source_chat_ids", [])),
                    turns=turns,
                    memories=memories,
                )


def load_items(split: str = "10M", strict: bool = True) -> list[BeamItem]:
    """Materialise all items into a list. Verifies the universe size.

    pre: ``strict=True`` enforces the 196-item invariant from protocol §5.
    post: returns ``EXPECTED_ITEM_COUNT`` items in dataset-iteration order
      when ``strict=True`` and split=="10M". Mismatch → ValueError. When
      ``strict=False`` (smoke / dry-run), accepts any count and warns.
    """
    items = list(iter_items(split))
    if strict and split == "10M" and len(items) != EXPECTED_ITEM_COUNT:
        raise ValueError(
            f"BEAM-10M item count mismatch: expected {EXPECTED_ITEM_COUNT} "
            f"per protocol §5 (Tavakoli et al. 2026), got {len(items)}. "
            "Universe drift requires a protocol addendum, not a silent run."
        )
    if not strict and len(items) != EXPECTED_ITEM_COUNT:
        print(
            f"[data_loader] non-strict: got {len(items)} items "
            f"(expected {EXPECTED_ITEM_COUNT}). Use only for dry-run/smoke.",
            file=sys.stderr,
        )
    return items


def turn_lookup(item: BeamItem) -> dict[int, dict]:
    """Map global turn-id → turn dict, for oracle retrieval.

    pre: ``item.turns`` is the global-numbered flat list.
    post: returned dict has one entry per turn; key == turn['id'].
    """
    return {t["id"]: t for t in item.turns if isinstance(t.get("id"), int)}
