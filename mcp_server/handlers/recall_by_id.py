"""Bounded single-memory retrieval with connection-rooted access scope."""

from typing import Any

from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.core.tabular_encoding import (
    encode_within_budget,
    parse_format,
    reserved_budget,
)
from mcp_server.infrastructure.memory_config import root_agent_topic
from mcp_server.infrastructure.memory_store import MemoryStore


def fetch_by_id(
    store: MemoryStore, args: dict[str, Any], budget_chars: int
) -> dict[str, Any]:
    """Fetch a scoped memory and page its content within the host budget.

    The composition root resolves the budget. Copy the stored row before
    slicing; reserved_budget leaves room for the self-describing format.
    """
    memory_id = int(args["memory_id"])
    content_offset = int(args.get("content_offset") or 0)
    fmt = parse_format(args.get("format"))
    stored = store.get_memory(memory_id)
    # Connection-rooted fetch must not disclose another agent's content or ID.
    # Unlike search's existing agent boost, this new ID surface enforces scope.
    root = root_agent_topic()
    if stored is None or (root is not None and stored.get("agent_context") != root):
        return encode_within_budget(
            {"memories": [], "count": 0, "intent": "general"},
            "memories",
            fmt,
            budget_chars,
        )
    # Copy before mutating: truncation must never write back into
    # whatever object the store handed us.
    memory = {**stored}
    content = memory.get("content") or ""
    if content_offset > 0:
        memory["content"] = content[content_offset:]
    memory["content_length"] = len(content)
    memory["content_offset"] = content_offset
    resp = {"memories": [memory], "count": 1, "intent": "general"}
    # Bound against the RESERVED budget so appending the self-describing
    # ``format`` field below cannot push the payload past the host cap.
    resp = bound_payload(
        resp,
        [ListTarget("memories", weight_key="score")],
        reserved_budget(budget_chars),
    )
    return encode_within_budget(resp, "memories", fmt, budget_chars)
