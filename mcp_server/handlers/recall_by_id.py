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
    """Fetch one memory by id — the retrieval path for truncated results.

    The composition root supplies its resolved budget. ``content_offset``
    pages through contents larger than the response
    budget: the slice starts there, ``content_length`` carries the full
    size, and ``bound_payload`` marks the slice ``truncated`` if it
    still overflows. ``fmt`` is honored for a self-describing response, but a
    single-item list rarely benefits from tabular encoding — the budget
    re-check in ``encode_within_budget`` keeps whichever form fits.
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
