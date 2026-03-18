"""Lightweight YAML frontmatter parser for memory files.

Only supports flat key-value pairs (no nested YAML, no arrays, no multi-line).
Memory frontmatter is always flat key-value pairs written by Claude Code itself.
"""

from __future__ import annotations

import re
from typing import NamedTuple

_FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$")
_KV_RE = re.compile(r"^(\w[\w\s]*?):\s*(.+)$")


class FrontmatterResult(NamedTuple):
    meta: dict[str, str]
    body: str


def parse_yaml_frontmatter(content: str | None) -> FrontmatterResult:
    """Parse YAML frontmatter from a markdown string.

    Returns (meta, body) where meta keys are lowercased.
    If no frontmatter found, meta is empty and body is the full content.
    """
    if not content:
        return FrontmatterResult(meta={}, body="")

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return FrontmatterResult(meta={}, body=content.strip())

    meta: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        kv = _KV_RE.match(line)
        if kv:
            meta[kv.group(1).strip().lower()] = kv.group(2).strip()

    return FrontmatterResult(meta=meta, body=match.group(2).strip())
