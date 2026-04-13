"""Wiki path contract — pure functions, no I/O.

The wiki is an authored long-form Markdown layer. Pages live under a
supplied wiki root; this module only computes paths so the core layer
stays filesystem-agnostic.

Layout::

    <root>/adr/NNNN-<slug>.md         architecture decision records
    <root>/specs/<slug>.md            feature specs / PRDs / design docs
    <root>/files/<path-slug>.md       per-file documentation
    <root>/notes/<slug>.md            free-form notes / investigations
    <root>/.generated/INDEX.md        auto-regenerated table of contents
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

PAGE_KINDS = (
    "adr",
    "specs",
    "guides",
    "reference",
    "conventions",
    "lessons",
    "notes",
    "journal",
    "files",
)

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")
_MAX_SLUG_LEN = 80


def slugify(value: str, *, max_len: int = _MAX_SLUG_LEN) -> str:
    """Stable filesystem-safe slug. Deterministic, lowercased, length-capped."""
    if not value:
        return "unknown"
    cleaned = _SAFE.sub("-", value.strip().lower()).strip("-")
    if not cleaned:
        return "unknown"
    return cleaned[:max_len].rstrip("-") or "unknown"


def file_path_slug(file_path: str) -> str:
    """Slugify a source-file path into a single token suitable for files/.

    ``src/auth/login.py`` → ``src-auth-login-py``.
    """
    return slugify(file_path.replace("/", "-").replace("\\", "-"))


def adr_filename(number: int, slug: str) -> str:
    """Canonical ADR filename: NNNN-slug.md (4-digit zero-padded)."""
    return f"{number:04d}-{slug}.md"


def domain_page_path(kind: str, domain: str, slug: str) -> str:
    """Generate a domain-scoped page path: <kind>/<domain>/<slug>.md."""
    if kind not in PAGE_KINDS:
        raise ValueError(f"unknown wiki page kind: {kind}")
    safe_domain = slugify(domain, max_len=40) if domain else "_general"
    return f"{kind}/{safe_domain}/{slug}.md"


def page_path(kind: str, filename: str) -> PurePosixPath:
    """Path relative to the wiki root for a page of a given kind."""
    if kind not in PAGE_KINDS:
        raise ValueError(f"unknown wiki page kind: {kind}")
    return PurePosixPath(kind) / filename


def index_path() -> PurePosixPath:
    """Path of the single auto-generated table of contents."""
    return PurePosixPath(".generated") / "INDEX.md"


def parse_page_path(path: str) -> tuple[str, str] | None:
    """Given a path like ``adr/0001-foo.md`` return ``(kind, filename)``.

    Returns None for unrecognised paths (including the generated INDEX).
    """
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] not in PAGE_KINDS:
        return None
    return parts[0], parts[-1]
