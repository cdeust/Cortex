"""Generic memory condenser: dispatch by content shape (issue #228 split
4/4).

Extracted from ``condensers.py`` (§4.1 — the original file was 391 lines,
over this repo's 300-line cap) with zero behaviour change. See
``condensers.py`` for the shared module docstring and re-export facade.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.condense_code import (
    _has_code_blocks,
    condense_assistant_message,
    condense_code_block,
)
from mcp_server.core.context_assembly.condense_structured import (
    _MIN_ARROWS_FOR_TRIPLES,
    condense_entity_triples,
)
from mcp_server.core.context_assembly.condense_text import (
    condense_timeline_event,
    condense_user_message,
)


def condense_memory_content(
    content: str,
    token_budget: int,
    *,
    tags: list[str] | None = None,
) -> str:
    """Auto-dispatch to the right condenser based on content shape.

    Args:
        content: the memory's textual content.
        token_budget: target token count for the output.
        tags: optional tag hints (e.g. ["code", "decision"]) to bias
            dispatch. When provided, takes precedence over heuristic.
    """
    # EQUIVALENT MUTANT (#228): `<=` → `<`. Every route below opens with
    # this same guard on this exact (content, token_budget) pair and
    # returns content verbatim, so the boundary case agrees either way.
    if estimate_tokens(content) <= token_budget:
        return content

    by_tag = _dispatch_by_tag(content, token_budget, tags or [])
    if by_tag is not None:
        return by_tag
    return _dispatch_by_shape(content, token_budget)


def _dispatch_by_tag(content: str, token_budget: int, tags: list[str]) -> str | None:
    """Explicit tag hints, checked before any content-shape heuristic."""
    if "code" in tags or "file" in tags:
        return condense_code_block(content, token_budget)
    if "timeline" in tags or "event" in tags:
        return condense_timeline_event(content, token_budget)
    return None


def _dispatch_by_shape(content: str, token_budget: int) -> str:
    """Heuristic dispatch by content shape when no tag hint matched."""
    if _has_code_blocks(content):
        return condense_assistant_message(content, token_budget)
    if content.count("→") + content.count("->") >= _MIN_ARROWS_FOR_TRIPLES:
        return condense_entity_triples(content, token_budget)
    if content.lstrip().startswith("[user]:") or content.lstrip().startswith(
        "[assistant]:"
    ):
        # Cortex memory format
        if "[assistant]:" in content:
            return condense_assistant_message(content, token_budget)
        return condense_user_message(content, token_budget)
    # Default: treat as prose user message
    return condense_user_message(content, token_budget)
