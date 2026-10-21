"""Phase 5.3 — Safe view DSL executor.

source: ADR-0318"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_server.shared.wiki_view_yamlish import parse_yamlish


# ── Whitelists ────────────────────────────────────────────────────────

_TABLE_WHITELIST: dict[str, str] = {
    "pages": "wiki.pages",
    "concepts": "wiki.concepts",
    "drafts": "wiki.drafts",
    "claim_events": "wiki.claim_events",
    "links": "wiki.links",
    "citations": "wiki.citations",
    "memos": "wiki.memos",
}

# Per-table allowed columns for filter / order / select
_COLUMN_WHITELIST: dict[str, set[str]] = {
    "pages": {
        "id",
        "memory_id",
        "concept_id",
        "rel_path",
        "slug",
        "kind",
        "title",
        "domain",
        "status",
        "lifecycle_state",
        "heat",
        "access_count",
        "citation_count",
        "backlink_count",
        "is_stale",
        "tended",
        "planted",
        "last_accessed_at",
        "last_cited_at",
        "archived_at",
    },
    "concepts": {
        "id",
        "label",
        "status",
        "saturation_rate",
        "saturation_streak",
        "first_seen_at",
        "last_property_at",
        "promoted_page_id",
    },
    "drafts": {
        "id",
        "concept_id",
        "memory_id",
        "title",
        "kind",
        "status",
        "confidence",
        "synth_model",
        "created_at",
        "reviewed_at",
        "published_page_id",
    },
    "claim_events": {
        "id",
        "memory_id",
        "session_id",
        "claim_type",
        "confidence",
        "supersedes",
        "extracted_at",
    },
    "links": {"src_page_id", "dst_slug", "dst_page_id", "link_kind"},
    "citations": {"id", "page_id", "session_id", "domain", "memory_id", "cited_at"},
    "memos": {
        "id",
        "subject_type",
        "subject_id",
        "decision",
        "confidence",
        "author",
        "created_at",
    },
}

# source: ADR-0318 (rows returned when a view names no limit)
_DEFAULT_LIMIT = 50
# source: ADR-0318 (upper bound on any view's limit)
_MAX_LIMIT = 500


@dataclass(frozen=True)
class CompiledView:
    """Output of compile_view: ready-to-execute parameterised SQL."""

    sql: str
    params: list[Any]
    errors: list[str]
    table: str


def compiled_view_ok(compiled: "CompiledView") -> bool:
    """Return whether compilation produced no errors.

    source: ADR-0318
    """
    return not compiled.errors


# ── Compiler ─────────────────────────────────────────────────────────


def _normalise_where(where_block: Any) -> dict[str, Any]:
    """Coerce the where: section to a flat dict[col, value-or-list].

    Special suffix conventions:
      <col>_min: float    → col >= value
      <col>_max: float    → col <= value
      <col>_after: ts     → col > value
      <col>_before: ts    → col < value
    Plain values produce equality (or IN for lists).
    """
    if not isinstance(where_block, dict):
        return {}
    return where_block


_OPERATORS = {
    "_min": ">=",
    "_max": "<=",
    "_after": ">",
    "_before": "<",
}


def _compile_where(
    where: dict[str, Any], allowed_cols: set[str]
) -> tuple[list[str], list[Any], list[str]]:
    fragments: list[str] = []
    params: list[Any] = []
    errors: list[str] = []
    for k, v in where.items():
        op = "="
        col = k
        for suffix, sql_op in _OPERATORS.items():
            if k.endswith(suffix):
                col = k[: -len(suffix)]
                op = sql_op
                break
        if col not in allowed_cols:
            errors.append(f"unknown column: {k!r}")
            continue
        if isinstance(v, list):
            if op != "=":
                errors.append(f"list value not supported for operator {op} on {k}")
                continue
            placeholders = ", ".join(["%s"] * len(v))
            fragments.append(f"{col} IN ({placeholders})")
            params.extend(v)
        elif v is None:
            fragments.append(f"{col} IS NULL")
        else:
            fragments.append(f"{col} {op} %s")
            params.append(v)
    return fragments, params, errors


def _projection(select: Any, allowed_cols: set[str], errors: list[str]) -> str:
    """SELECT list restricted to the whitelist when given, else ``*``."""
    if not (isinstance(select, list) and select):
        return "*"
    proj_cols = [c for c in select if c in allowed_cols]
    if not proj_cols:
        errors.append("select list contains no allowed columns")
        proj_cols = ["id"]
    return ", ".join(proj_cols)


def _order_clause(
    parsed: dict[str, Any], allowed_cols: set[str], errors: list[str]
) -> str:
    """ORDER BY one whitelisted column, or nothing."""
    order_col = parsed.get("order_by")
    direction = (parsed.get("direction") or "desc").lower()
    if not order_col:
        return ""
    if order_col not in allowed_cols:
        errors.append(f"unknown order_by column: {order_col!r}")
        return ""
    if direction not in ("asc", "desc"):
        errors.append(f"direction must be 'asc' or 'desc', got {direction!r}")
        direction = "desc"
    return f" ORDER BY {order_col} {direction.upper()} NULLS LAST"


def _limit(value: Any, errors: list[str]) -> int:
    limit = value or _DEFAULT_LIMIT
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        errors.append(f"limit must be an integer, got {limit!r}")
        limit = _DEFAULT_LIMIT
    return max(1, min(_MAX_LIMIT, limit))


def compile_view(text: str) -> CompiledView:
    """Compile a cortex-query block into parameterised SQL."""
    parsed = parse_yamlish(text)
    errors: list[str] = []
    table = (parsed.get("table") or "pages").strip()
    if table not in _TABLE_WHITELIST:
        return CompiledView(
            sql="", params=[], errors=[f"unknown table: {table!r}"], table=table
        )
    real_table = _TABLE_WHITELIST[table]
    allowed_cols = _COLUMN_WHITELIST[table]
    proj = _projection(parsed.get("select"), allowed_cols, errors)
    where_frags, where_params, where_errs = _compile_where(
        _normalise_where(parsed.get("where")), allowed_cols
    )
    errors.extend(where_errs)
    order_clause = _order_clause(parsed, allowed_cols, errors)
    limit = _limit(parsed.get("limit"), errors)
    where_clause = (" WHERE " + " AND ".join(where_frags)) if where_frags else ""
    sql = f"SELECT {proj} FROM {real_table}{where_clause}{order_clause} LIMIT %s"  # noqa: S608 — source: ADR-0318
    return CompiledView(
        sql=sql, params=where_params + [limit], errors=errors, table=table
    )


__all__ = ["CompiledView", "compile_view", "compiled_view_ok"]
