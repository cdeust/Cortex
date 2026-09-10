"""Wiki path contract — pure functions, no I/O.

source: ADR-0682

Layout::

    source: ADR-0682"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# source: ADR-0682

MODERN_PAGE_KINDS = (
    "tutorial",
    "how-to",
    "reference",
    "explanation",
    "adr",
    "runbook",
    "rfc",
    "journal",
)

# source: ADR-0682


LEGACY_PAGE_KINDS = (
    "specs",
    "guides",
    "conventions",
    "lessons",
    "notes",
    "files",
)

# source: ADR-0682


PAGE_KINDS = MODERN_PAGE_KINDS + LEGACY_PAGE_KINDS

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")
_MAX_SLUG_LEN = 80
# source: ADR-0682


_TRAILING_MD_EXT = re.compile(r"(?:\.md)+$", re.IGNORECASE)


def slugify(value: str, *, max_len: int = _MAX_SLUG_LEN) -> str:
    """Stable filesystem-safe slug. Deterministic, lowercased, length-capped.

    Postcondition: the returned slug never ends with ``.md`` (or any chain
    of ``.md`` suffixes). Callers may safely append ``.md`` without
    risking ``.md.md``.
    """
    if not value:
        return "unknown"
    cleaned = _SAFE.sub("-", value.strip().lower()).strip("-")
    if not cleaned:
        return "unknown"
    cleaned = _TRAILING_MD_EXT.sub("", cleaned).rstrip(".-") or "unknown"
    return cleaned[:max_len].rstrip("-.") or "unknown"


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


# source: ADR-0682

_MIN_PAGE_PATH_PARTS = 2


def parse_page_path(path: str) -> tuple[str, str] | None:
    """Given a path like ``adr/0001-foo.md`` return ``(kind, filename)``.

    Returns None for unrecognised paths (including the generated INDEX).
    """
    parts = PurePosixPath(path).parts
    if len(parts) < _MIN_PAGE_PATH_PARTS or parts[0] not in PAGE_KINDS:
        return None
    return parts[0], parts[-1]
