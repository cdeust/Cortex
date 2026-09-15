"""Wiki drift detector — find existing pages that need re-authoring.

source: ADR-0301"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Final

from mcp_server.shared.wiki_source_paths import extract_document_paths

# Composition-root injection seam (core may not import os or perform I/O;
# issue #560): the real implementations live in
# mcp_server/infrastructure/wiki_drift_fs.py, wired once via
# configure_wiki_drift_filesystem (mcp_server/__main__.py for production,
# tests_py/conftest.py for the test session).
ReadPage = Callable[[str, str], "str | None"]
PageMtime = Callable[[str, str], float]
FileExistsUnder = Callable[[str, str], bool]
IterPages = Callable[[str], Iterable[str]]

_read_page: ReadPage | None = None
_page_mtime: PageMtime | None = None
_file_exists_provider: FileExistsUnder | None = None
_iter_pages: IterPages | None = None


def configure_wiki_drift_filesystem(
    *,
    read_page: ReadPage,
    page_mtime: PageMtime,
    file_exists_under: FileExistsUnder,
    iter_pages: IterPages,
) -> None:
    """Composition-root hook: register the real wiki-drift filesystem ops.

    source: ADR-0301 (issue #560)"""
    global _read_page, _page_mtime, _file_exists_provider, _iter_pages
    _read_page = read_page
    _page_mtime = page_mtime
    _file_exists_provider = file_exists_under
    _iter_pages = iter_pages


def _unconfigured(what: str) -> RuntimeError:
    return RuntimeError(
        f"wiki_drift {what} provider not configured — call "
        "configure_wiki_drift_filesystem() at the composition root first"
    )


@dataclass
class PageDrift:
    """A single page that needs re-authoring, with the reason recorded.

    source: ADR-0301
    """

    wiki_path: str  # relative to wiki root
    domain: str  # parsed from the path segment
    kind: str  # parsed from the path segment
    reasons: list[str] = field(default_factory=list)  # one of REASONS below
    missing_source_files: list[str] = field(default_factory=list)
    cited_source_files: list[str] = field(default_factory=list)
    last_updated: str = ""  # frontmatter `updated` value, if any
    age_days: float = 0.0


# source: ADR-0301
REASON_MISSING_SOURCE: Final[str] = "missing_source_file"
REASON_STALE: Final[str] = "stale_content"
REASON_OFF_TEMPLATE: Final[str] = "off_template"
REASON_MISSING_LINK: Final[str] = "missing_source_link"

# source: ADR-0301


_SOURCE_DOCUMENTING_KINDS: Final[frozenset[str]] = frozenset({"reference"})

# Default re-author window. Pages older than this whose body cites
# source files trigger a re-author job — the prose may still be true,
# but the LLM is asked to verify against the current code.
_DEFAULT_REAUTHOR_AGE_DAYS: Final[float] = 60.0


_FILE_PATH_RE = re.compile(
    r"\b([\w./\-]+\.(?:py|ts|tsx|js|jsx|go|rs|rb|java|kt|swift|cpp|cc|c|h|hpp|cs|sql))\b"
)


# source: ADR-0301


_WIKI_INTERNAL_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "adr",
        "adrs",
        "conventions",
        "explanation",
        "files",
        "guides",
        "how-to",
        "journal",
        "lessons",
        "notes",
        "reference",
        "rfc",
        "runbook",
        "specs",
        "tutorial",
    }
)


# source: ADR-0301


_TECHNOLOGY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "angular.js",
        "backbone.js",
        "chart.js",
        "d3.js",
        "day.js",
        "ember.js",
        "express.js",
        "moment.js",
        "next.js",
        "node.js",
        "nuxt.js",
        "p5.js",
        "react.js",
        "three.js",
        "vue.js",
    }
)


def _is_likely_source_path(token: str) -> bool:
    """Filter cited paths to those that plausibly point at the source
    tree, not at another wiki page.

    source: ADR-0301"""
    if not token or "://" in token:
        return False
    if token.lower() in _TECHNOLOGY_NAMES:
        return False
    first = token.split("/", 1)[0]
    if first in _WIKI_INTERNAL_PREFIXES:
        return False
    return True


# Required sections per kind. A page missing any of these is flagged as
# off-template — drift in *structure*, complementing the content drift.
_REQUIRED_SECTIONS: Final[dict[str, tuple[str, ...]]] = {
    "adr": (
        "## Status",
        "## Entry",
        "## Mandatory elements",
        "## How",
        "## Result",
        "## Serves",
    ),
    "explanation": ("## Context", "## Explanation"),
    "reference": ("## Scope", "## API"),
    "runbook": ("## Trigger", "## Diagnosis"),
}


def _extract_cited_paths(body: str) -> list[str]:
    """Pull every source-file-shaped token out of a page body.

    Returns a deduplicated list preserving first-seen order. Empty when
    the page cites nothing (a pure-prose page; no source-file invariant
    to check).
    """
    seen: dict[str, None] = {}
    for m in _FILE_PATH_RE.finditer(body):
        token = m.group(1).lstrip("./")
        if not _is_likely_source_path(token):
            continue
        seen.setdefault(token, None)
    return list(seen)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Lightweight YAML frontmatter parser — enough to read ``updated``.

    Returns ``(metadata, body)`` where metadata is a flat dict of string
    values (no nested structure parsing). Empty dict + full text when
    the page has no frontmatter.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


# source: ADR-0301
# source: ADR-0301
_KIND_DOMAIN_PATH_PARTS = 3


def _kind_and_domain_from_path(rel_path: str) -> tuple[str, str]:
    """Path ``adr/cortex/0042-foo.md`` → ``("adr", "cortex")``.

    Returns ``("", "")`` for paths that don't follow the
    kind/domain/filename layout.
    """
    parts = rel_path.split("/")
    if len(parts) < _KIND_DOMAIN_PATH_PARTS:
        return "", ""
    return parts[0], parts[1]


def _file_exists_under(source_root: str, cited: str) -> bool:
    """Does ``cited`` resolve to an actual file under ``source_root``?

    source: ADR-0301"""
    if _file_exists_provider is None:
        raise _unconfigured("file_exists_under")
    return _file_exists_provider(source_root, cited)


def _required_sections_for(kind: str) -> tuple[str, ...]:
    return _REQUIRED_SECTIONS.get(kind, ())


def audit_page_drift(
    wiki_root: str,
    page_rel_path: str,
    source_root: str | None,
    *,
    max_age_days: float = _DEFAULT_REAUTHOR_AGE_DAYS,
    now: float | None = None,
) -> PageDrift | None:
    """Inspect one wiki page for drift. Returns None when the page is
    in sync.

    source: ADR-0301"""
    if _read_page is None or _page_mtime is None:
        raise _unconfigured("read_page/page_mtime")
    text = _read_page(wiki_root, page_rel_path)
    if text is None:
        return None

    kind, domain = _kind_and_domain_from_path(page_rel_path)
    meta, body = _parse_frontmatter(text)
    cited = _extract_cited_paths(body)

    drift = PageDrift(
        wiki_path=page_rel_path,
        domain=domain,
        kind=kind,
        cited_source_files=cited,
        last_updated=meta.get("updated", ""),
    )

    # source: ADR-0301

    if source_root is not None and cited:
        missing = [c for c in cited if not _file_exists_under(source_root, c)]
        if missing:
            drift.reasons.append(REASON_MISSING_SOURCE)
            drift.missing_source_files = missing[:10]

    # source: ADR-0301

    page_mtime = _page_mtime(wiki_root, page_rel_path)
    now_ts = now if now is not None else time.time()
    drift.age_days = (now_ts - page_mtime) / 86400.0 if page_mtime else 0.0
    if drift.age_days > max_age_days and cited:
        # Only consider it stale if there's something verifiable (cited
        # source files). A pure-prose page that hasn't been edited in
        # months may still be correct.
        drift.reasons.append(REASON_STALE)

    # source: ADR-0301

    required = _required_sections_for(kind)
    if required:
        missing_sections = [s for s in required if s not in body]
        if missing_sections:
            drift.reasons.append(REASON_OFF_TEMPLATE)

    # source: ADR-0301

    if kind in _SOURCE_DOCUMENTING_KINDS and not extract_document_paths(meta):
        groundable = source_root is not None and any(
            _file_exists_under(source_root, c) for c in cited
        )
        if not groundable:
            drift.reasons.append(REASON_MISSING_LINK)

    return drift if drift.reasons else None


def audit_wiki_drift(
    wiki_root: str,
    source_root_resolver,
    *,
    max_age_days: float = _DEFAULT_REAUTHOR_AGE_DAYS,
    limit: int | None = None,
    domain_filter: str | None = None,
) -> list[PageDrift]:
    """Walk every wiki page and return those that need re-authoring.

    source: ADR-0301"""
    if _iter_pages is None:
        raise _unconfigured("iter_pages")
    drifts: list[PageDrift] = []
    for rel in _iter_pages(wiki_root):
        kind, domain = _kind_and_domain_from_path(rel)
        if not domain or not kind:
            continue
        if domain_filter and domain != domain_filter:
            continue
        src_root = source_root_resolver(domain) if domain else None
        d = audit_page_drift(wiki_root, rel, src_root, max_age_days=max_age_days)
        if d is not None:
            drifts.append(d)
            if limit is not None and len(drifts) >= limit:
                return drifts
    return drifts
