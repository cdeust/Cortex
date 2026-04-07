"""Wiki path contract — pure functions, no I/O.

Defines the directory layout for the read-only Markdown projection of
Cortex memory state. All paths are relative to a caller-supplied root so
this module stays in the core layer (no filesystem coupling).

Layout:
    <root>/INDEX.md
    <root>/<domain_id>/INDEX.md
    <root>/<domain_id>/schemas/<schema_id>.md          (slice 2)
    <root>/<domain_id>/chains/<chain_id>.md            (slice 4)
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


def slugify(value: str) -> str:
    """Stable filesystem-safe slug. Deterministic, lowercased."""
    if not value:
        return "unknown"
    cleaned = _SAFE.sub("-", value.strip().lower()).strip("-")
    return cleaned or "unknown"


def global_index_path() -> PurePosixPath:
    """Top-level INDEX.md (lists all domains)."""
    return PurePosixPath("INDEX.md")


def domain_index_path(domain_id: str) -> PurePosixPath:
    """Per-domain INDEX.md."""
    return PurePosixPath(slugify(domain_id)) / "INDEX.md"


def schema_page_path(domain_id: str, schema_id: str) -> PurePosixPath:
    """Per-schema page (slice 2+)."""
    return PurePosixPath(slugify(domain_id)) / "schemas" / f"{slugify(schema_id)}.md"


def chain_page_path(domain_id: str, chain_id: str) -> PurePosixPath:
    """Per-causal-chain page (slice 4+)."""
    return PurePosixPath(slugify(domain_id)) / "chains" / f"{slugify(chain_id)}.md"
