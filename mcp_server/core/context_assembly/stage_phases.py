"""Phase builders for the three-phase stage-aware assembler.

``stage_assembler.StageAwareContextAssembler`` orchestrates; the work of
each phase — selecting the items and rendering them into text that fits
the phase's share of the token budget — lives here.

The packing rule is the point of this module. A phase used to skip any
item that did not fit the remaining budget, which contradicted the
assembler's own contract ("may truncate individual chunks but never
reduces the count of selected items") and silently dropped exactly the
long, information-dense memories the retrieval stack had just ranked
highest. ``pack_within_budget`` instead gives every item a share of the
budget (``budget.proportional_share``, the Swift ContextDecomposer rule)
and hands the over-share ones to the domain-aware condensers in
``condensers.py`` — the reduction those condensers were written for and
had no call site for until this module.

Pure: no I/O, no store access. Callers inject every external lookup.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.context_assembly.budget import (
    estimate_tokens,
    proportional_share,
)
from mcp_server.core.context_assembly.condensers import condense_memory_content


def _tags_of(memory: dict[str, Any]) -> list[str]:
    """Tag hints for the condenser dispatch; [] when absent or malformed."""
    tags = memory.get("tags")
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []


def pack_within_budget(
    memories: list[dict[str, Any]],
    token_budget: int | None,
) -> tuple[list[str], int]:
    """Render ``memories`` as text under ``token_budget``, condensing.

    Every input memory produces exactly one output string — an item is
    condensed, never dropped, so ``len(texts) == len(memories)`` holds
    for any budget. ``token_budget is None`` means "no budget": contents
    are returned verbatim.

    The output fits ``token_budget`` except where the per-item floor
    binds: with ``n`` items the ceiling is ``max(token_budget, n *
    MIN_ITEM_SHARE_TOKENS)``, because the share rule never starves an
    item below the floor at which condensation stops meaning anything.
    Callers that must not overshoot bound ``n`` (the assembler caps it
    at ``max_chunks_per_phase``).

    Returns ``(texts, tokens_used)`` where ``tokens_used`` is the
    estimated token count of the rendered texts.
    """
    if token_budget is None:
        texts = [str(m.get("content", "")) for m in memories]
        return texts, sum(estimate_tokens(t) for t in texts)

    texts = []
    remaining = max(0, token_budget)
    used = 0
    for i, memory in enumerate(memories):
        content = str(memory.get("content", ""))
        share = proportional_share(remaining, len(memories) - i)
        if estimate_tokens(content) <= share:
            rendered = content
        else:
            rendered = condense_memory_content(content, share, tags=_tags_of(memory))
        texts.append(rendered)
        spent = estimate_tokens(rendered)
        used += spent
        remaining = max(0, remaining - spent)
    return texts, used


def phase_budget(token_budget: int | None, proportion: float) -> int | None:
    """This phase's slice of the total budget; None propagates as None."""
    if token_budget is None:
        return None
    return int(token_budget * proportion)


def render_own_stage(
    selected: list[dict[str, Any]],
    token_budget: int | None,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Phase 1 — own-stage text plus the selected-memory records.

    The records carry the ORIGINAL content: they are the retrieval
    record downstream evaluators score against, and must not inherit the
    reader-facing condensation applied to the text.
    """
    texts, used = pack_within_budget(selected, token_budget)
    records = [
        {
            "memory_id": memory.get("memory_id"),
            "content": memory.get("content", ""),
            "score": memory.get("score", 0.0),
            "phase": 1,
        }
        for memory in selected
    ]
    return "\n\n".join(texts).strip(), used, records


def render_adjacent(
    scored: list[tuple[dict[str, Any], float]],
    token_budget: int | None,
    max_chunks: int,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Phase 2 — cross-stage text for the top ``max_chunks`` PPR hits."""
    top = scored[:max_chunks]
    memories = [memory for memory, _ in top]
    texts, used = pack_within_budget(memories, token_budget)
    records = [
        {
            "memory_id": memory.get("memory_id") or memory.get("id"),
            "content": memory.get("content", ""),
            "score": float(score),
            "phase": 2,
        }
        for memory, score in top
    ]
    return "\n\n".join(texts).strip(), used, records


def render_summaries(
    summaries: list[tuple[str, str]],
    token_budget: int | None,
) -> tuple[str, int, list[str]]:
    """Phase 3 — ``[stage] summary`` lines for the uncovered stages.

    Returns ``(text, tokens_used, stage_ids)``; ``stage_ids`` names the
    stages that reached the output, in order.
    """
    labelled = [
        {"content": f"[{stage_id}] {summary}"} for stage_id, summary in summaries
    ]
    texts, used = pack_within_budget(labelled, token_budget)
    return (
        "\n\n".join(texts).strip(),
        used,
        [stage_id for stage_id, _ in summaries],
    )
