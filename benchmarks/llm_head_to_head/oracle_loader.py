"""Condition D — Oracle. Gold-supporting turns from BEAM source_chat_ids.

Protocol §2.D: for each question, retrieve the gold-supporting turns
DIRECTLY from the BEAM ``source_chat_ids`` field. No ranking model in
the loop. This bounds the best-case answer accuracy — anything above D
is hallucination.

precondition: the item's ``source_chat_ids`` are global turn IDs (post-
  flatten by ``extract_10m_chat`` — see ``data_loader.py``).
postcondition: returns the turn texts in original conversation order;
  unknown ids are silently skipped (BEAM occasionally references ids
  outside the flattened range — counted in the manifest's diagnostics).
invariant: condition D never queries a retrieval index, never embeds
  the question. The oracle is by construction better than or equal to
  any retriever; if D < C in the eventual run, that's a bug, not a
  finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.llm_head_to_head.data_loader import BeamItem, turn_lookup


@dataclass(frozen=True)
class OraclePassage:
    turn_id: int
    role: str
    content: str
    time_anchor: str


def build_oracle_context(item: BeamItem) -> list[OraclePassage]:
    """Look up gold-supporting turns for one item.

    pre:
      - ``item.source_chat_ids`` is a tuple of global turn ids.
      - ``item.turns`` contains the corresponding turn dicts (may have
        gaps; oracle skips unknowns).
    post:
      - returned list is sorted by turn_id ascending (original order).
      - empty list when ``source_chat_ids`` is empty (abstention items).
    """
    lookup = turn_lookup(item)
    passages: list[OraclePassage] = []
    for tid in item.source_chat_ids:
        turn = lookup.get(tid)
        if not turn:
            continue
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        passages.append(
            OraclePassage(
                turn_id=tid,
                role=turn.get("role", "user"),
                content=content,
                time_anchor=turn.get("time_anchor", "") or "",
            )
        )
    # Sort by turn id to preserve original order regardless of the
    # source_chat_ids order in the dataset.
    passages.sort(key=lambda p: p.turn_id)
    return passages


def passages_to_context(passages: list[OraclePassage], separator: str = "\n") -> str:
    """Render oracle passages into the answer prompt's CONTEXT block.

    pre: passages are in original conversation order.
    post: empty string when passages is empty (abstention case); else
      one ``[Date: …] [role]: content`` line per passage.
    """
    lines: list[str] = []
    for p in passages:
        prefix = f"[Date: {p.time_anchor}] " if p.time_anchor else ""
        lines.append(f"{prefix}[{p.role}]: {p.content}")
    return separator.join(lines)
