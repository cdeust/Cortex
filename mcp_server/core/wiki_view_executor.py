"""Phase 5.3 — Safe view DSL executor.

A view is a YAML-shaped query block inside a wiki/_views/*.md page:

    ```cortex-query
    table: pages
    where:
      kind: spec
      lifecycle_state: [active, evergreen]
      status: budding
      heat_min: 0.5
    order_by: heat
    direction: desc
    limit: 20
    ```

This module parses the YAML, validates fields against a whitelist,
and produces a parameterised SQL query. Never builds SQL by string
concatenation of user input — every value goes through bind params,
every column name comes from a hardcoded whitelist.

Pure logic — returns (sql, params, errors). The handler executes
the query and returns rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


@dataclass(frozen=True)
class CompiledView:
    """Output of compile_view: ready-to-execute parameterised SQL."""

    sql: str
    params: list[Any]
    errors: list[str]
    table: str

    @property
    def ok(self) -> bool:
        return not self.errors


# ── YAML-ish parser ──────────────────────────────────────────────────
#
# Same minimal style as the rest of Cortex (no PyYAML dep). Supports:
#   key: value               # scalar
#   key: [a, b, c]           # inline list
#   key:                     # nested dict (one level only)
#     inner_key: value
#     inner_key2: value

# Keys are matched with a tight anchored pattern that cannot backtrack
# quadratically: `[A-Za-z_][A-Za-z0-9_]*` on bounded input. For the
# actual line parsing we use str.partition(":") which has no regex
# complexity at all. This replaces a pair of earlier regexes flagged by
# CodeQL (py/polynomial-redos alerts #51, #52, #53) where `\s*` before
# `(.*)` could combine with `[\w]*` under adversarial input.
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Cap line length before regex ever touches the string — defence in
# depth against any input that slipped past the view-file discipline.
_MAX_LINE_LEN = 2000


def _parse_kv_line(line: str) -> tuple[str, str] | None:
    """Parse ``key: value`` from a line without regex backtracking.

    Returns None if the line isn't a valid key: value pair. Indentation
    info is carried via ``line.lstrip() != line``; callers check that
    separately.
    """
    if len(line) > _MAX_LINE_LEN:
        return None
    stripped = line.strip()
    if ":" not in stripped:
        return None
    key, _, value = stripped.partition(":")
    key = key.strip()
    value = value.strip()
    if not _KEY_RE.match(key):
        return None
    return key, value


def _coerce_scalar(s: str):
    s = s.strip()
    if not s:
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in ("null", "none", "~"):
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(x) for x in inner.split(",")]
    if s.startswith(("'", '"')) and s.endswith(s[0]):
        return s[1:-1]
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _is_indented(line: str) -> bool:
    """Line starts with whitespace (indicates nested-dict value)."""
    return line != "" and line[0] in (" ", "\t")


def _parse_yamlish(text: str) -> dict[str, Any]:
    """Parse the cortex-query block.

    No regex-based line parsing — uses str.partition and simple
    character checks. Immune to polynomial-redos by construction.
    """
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level (non-indented) key:value
        if _is_indented(line):
            i += 1
            continue
        parsed = _parse_kv_line(line)
        if parsed is None:
            i += 1
            continue
        key, value_str = parsed
        if value_str:
            out[key] = _coerce_scalar(value_str)
            i += 1
            continue
        # Empty value → expect nested dict on indented lines
        nested: dict[str, Any] = {}
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                i += 1
                continue
            if not _is_indented(nxt):
                break
            sub = _parse_kv_line(nxt)
            if sub is not None:
                nested[sub[0]] = _coerce_scalar(sub[1])
            i += 1
        out[key] = nested
    return out


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


def compile_view(text: str) -> CompiledView:
    """Compile a cortex-query block into parameterised SQL."""
    parsed = _parse_yamlish(text)
    errors: list[str] = []

    table = (parsed.get("table") or "pages").strip()
    if table not in _TABLE_WHITELIST:
        return CompiledView(
            sql="",
            params=[],
            errors=[f"unknown table: {table!r}"],
            table=table,
        )
    real_table = _TABLE_WHITELIST[table]
    allowed_cols = _COLUMN_WHITELIST[table]

    # SELECT projection — restrict to whitelist when given, else *
    select = parsed.get("select")
    if isinstance(select, list) and select:
        proj_cols = [c for c in select if c in allowed_cols]
        if not proj_cols:
            errors.append("select list contains no allowed columns")
            proj_cols = ["id"]
        proj = ", ".join(proj_cols)
    else:
        proj = "*"

    where_frags, where_params, where_errs = _compile_where(
        _normalise_where(parsed.get("where")), allowed_cols
    )
    errors.extend(where_errs)

    # ORDER BY — single column from the whitelist
    order_col = parsed.get("order_by")
    direction = (parsed.get("direction") or "desc").lower()
    order_clause = ""
    if order_col:
        if order_col not in allowed_cols:
            errors.append(f"unknown order_by column: {order_col!r}")
        else:
            if direction not in ("asc", "desc"):
                errors.append(f"direction must be 'asc' or 'desc', got {direction!r}")
                direction = "desc"
            order_clause = f" ORDER BY {order_col} {direction.upper()} NULLS LAST"

    limit = parsed.get("limit") or _DEFAULT_LIMIT
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        errors.append(f"limit must be an integer, got {limit!r}")
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    where_clause = (" WHERE " + " AND ".join(where_frags)) if where_frags else ""
    sql = f"SELECT {proj} FROM {real_table}{where_clause}{order_clause} LIMIT %s"
    params = where_params + [limit]
    return CompiledView(sql=sql, params=params, errors=errors, table=table)


__all__ = ["CompiledView", "compile_view"]
