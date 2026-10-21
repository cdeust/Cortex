"""The minimal YAML-ish parser of the wiki view DSL (no PyYAML dependency).

Split from ``wiki_view_dsl`` (ADR-1112 increment 2 moved the DSL to
``shared`` so the store broker compiles views itself).

source: ADR-0318"""

from __future__ import annotations

import re
from typing import Any


# ── YAML-ish parser ──────────────────────────────────────────────────
#
# Same minimal style as the rest of Cortex (no PyYAML dep). Supports:
#   key: value               # scalar  # noqa: ERA001 -- YAML-ish syntax doc, not code
#   key: [a, b, c]           # inline list  # noqa: ERA001 -- syntax doc, not code
#   key:                     # nested dict (one level only)
#     inner_key: value  # noqa: ERA001 -- YAML-ish syntax doc, not code
#     inner_key2: value  # noqa: ERA001 -- YAML-ish syntax doc, not code

# source: ADR-0318
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# source: ADR-0318 (longer lines are ignored, never parsed)
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


def _parse_nested(lines: list[str], i: int) -> tuple[dict[str, Any], int]:
    """The indented ``key: value`` lines from ``i``; returns the dict and
    the index of the first line after it."""
    nested: dict[str, Any] = {}
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
    return nested, i


def parse_yamlish(text: str) -> dict[str, Any]:
    """Parse the cortex-query block.

    No regex-based line parsing — uses str.partition and simple
    character checks. Immune to polynomial-redos by construction.
    """
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#") or _is_indented(line):
            continue
        parsed = _parse_kv_line(line)
        if parsed is None:
            continue
        key, value_str = parsed
        if value_str:
            out[key] = _coerce_scalar(value_str)
            continue
        # Empty value → expect nested dict on indented lines
        out[key], i = _parse_nested(lines, i)
    return out
