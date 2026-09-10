"""Filesystem decision retrieval: exact identity first, scoped Boolean text lane.

source: ADR-0387"""

from __future__ import annotations

from typing import Any

from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.core.scoring import tokenize
from mcp_server.core.tabular_encoding import (
    encode_within_budget,
    parse_format,
    reserved_budget,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.project_wiki import resolve_wiki_root
from mcp_server.infrastructure.wiki_decision_index import (
    decision_index,
    lookup_decision,
)
from mcp_server.infrastructure.wiki_pages_listing import list_pages
from mcp_server.infrastructure.wiki_store import read_page
from mcp_server.shared.wiki_decision_ids import parse_decision_id

SCOPE_PROPERTIES = {
    "project_root": {
        "type": "string",
        "description": (
            "Project with an explicitly configured tracked wiki; "
            "never inferred from domain."
        ),
    },
    "exact_id": {
        "type": "boolean",
        "default": False,
        "description": (
            "Require query to be an exact ADR-NNNN identity; "
            "missing IDs never fall back to semantic search."
        ),
    },
}


def _record(root: Any, path: str, content: str, identity: str) -> dict[str, Any]:
    return {
        "id": f"wiki:{identity}",
        "content": content,
        "path": path,
        "root": str(root),
        "source": "wiki",
        "match_type": "exact_id",
    }


def exact_lookup(args: dict[str, Any]) -> dict[str, Any] | None:
    """Return None only for ordinary semantic queries, never failed exact IDs."""
    query = str(args.get("query") or "").strip()
    number = parse_decision_id(query)
    if number is None and not args.get("exact_id"):
        return None
    result: dict[str, Any] = {"memories": [], "count": 0, "intent": "entity"}
    if number is None:
        return {**result, "status": "invalid_id", "reason": "Expected ADR-NNNN."}
    try:
        root = resolve_wiki_root(args.get("project_root"), WIKI_ROOT)
        path = lookup_decision(root, query)
        content = read_page(root, path) if path else None
    except (ValueError, OSError) as exc:
        return {**result, "status": "error", "reason": str(exc)}
    if content is None or path is None:
        return {
            **result,
            "status": "not_found",
            "reason": f"No canonical page for {query}.",
        }
    record = _record(root, path, content, query)
    offset = max(0, int(args.get("content_offset") or 0))
    record.update(content=content[offset:], content_length=len(content), offset=offset)
    return {**result, "memories": [record], "count": 1, "status": "ok"}


def bounded_exact(result: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Preserve identity and offset when large pages require another exact call."""
    cap = get_memory_settings().MAX_RESPONSE_CHARS
    result = bound_payload(result, [ListTarget("memories")], reserved_budget(cap))
    result["count"] = len(result["memories"])
    return encode_within_budget(
        result, "memories", parse_format(args.get("format")), cap
    )


def search_wiki(args: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Search only the explicitly selected project's authored wiki pages."""
    if not args.get("project_root"):
        return []
    terms = set(tokenize(str(args.get("query") or "")))
    if not terms:
        return []
    root = resolve_wiki_root(args["project_root"], WIKI_ROOT)
    identities = {path: token for token, path in decision_index(root).items()}
    results = []
    for path in sorted(list_pages(root)):
        content = read_page(root, path)
        if content is None or not terms.issubset(set(tokenize(path + " " + content))):
            continue
        record = _record(root, path, content, identities.get(path, path))
        record["match_type"] = "all_query_tokens"
        results.append(record)
        if len(results) >= limit:
            break
    return results
