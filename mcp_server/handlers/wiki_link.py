"""Handler: wiki_link — add a bidirectional link between two wiki pages.

Updates the ``## Related`` section of both files, writing the forward
relation on the source and the inverse on the target. Idempotent.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_links import LinkEntry, RELATIONS, apply_link, inverse_of
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import (
    WikiMissing,
    read_page,
    write_page,
)

schema = {
    "description": (
        "Add a bidirectional link between two wiki pages: write the "
        "forward relation into the `## Related` section of the source page "
        "and the inverse relation into the target page, in one idempotent "
        "operation. Use this to record dependencies, derivations, "
        "supersession chains, or free-form `see also` connections between "
        "knowledge artefacts. Distinct from `wiki_write` (authors a page, "
        "doesn't link), `wiki_compile` (publishes drafts, doesn't link), "
        "and graph-relationship tools (this writes markdown sections, not "
        "DB edges). Mutates two .md files atomically. Latency ~30ms. "
        "Returns {from_path, to_path, forward_relation, inverse_relation}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["from_path", "to_path", "relation"],
        "properties": {
            "from_path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the source page (the page that owns "
                    "the forward relation). Example: 'decisions/0042-use-pgvector.md'."
                ),
                "examples": [
                    "decisions/0001-clean-architecture.md",
                    "concepts/wrrf-fusion.md",
                ],
            },
            "to_path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the target page (the page that "
                    "receives the inverse relation)."
                ),
                "examples": ["concepts/pgvector.md", "decisions/0007-pg-store.md"],
            },
            "relation": {
                "type": "string",
                "description": (
                    "Semantic relation written on the source page; the inverse "
                    "is written on the target. Pairs: depends_on/depended_on_by, "
                    "derives/derived_from, implements/implemented_by, "
                    "supersedes/superseded_by, plus the symmetric 'see_also'."
                ),
                "enum": sorted(RELATIONS.keys()),
                "default": "see_also",
                "examples": ["depends_on", "supersedes", "see_also"],
            },
        },
    },
}


def _update_page(rel_path: str, entry: LinkEntry) -> None:
    current = read_page(WIKI_ROOT, rel_path)
    if current is None:
        raise WikiMissing(rel_path)
    updated = apply_link(current, entry)
    write_page(WIKI_ROOT, rel_path, updated, mode="replace")


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    from_path = str(args.get("from_path") or "").strip()
    to_path = str(args.get("to_path") or "").strip()
    relation = str(args.get("relation") or "").strip()
    if not from_path or not to_path or not relation:
        return {"error": "from_path, to_path, and relation are required"}
    if relation not in RELATIONS:
        return {"error": f"unknown relation: {relation}"}

    try:
        _update_page(from_path, LinkEntry(relation=relation, target=to_path))
        _update_page(
            to_path, LinkEntry(relation=inverse_of(relation), target=from_path)
        )
    except WikiMissing as missing:
        return {"error": f"page not found: {missing}"}
    except (ValueError, OSError) as exc:
        return {"error": f"link failed: {exc}"}

    return {
        "from_path": from_path,
        "to_path": to_path,
        "relation": relation,
        "inverse": inverse_of(relation),
    }
