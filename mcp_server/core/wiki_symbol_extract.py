"""Phase 2 (ADR-0046) — extract symbol references from wiki page text.

A wiki page may cite code symbols in three forms:

    1. Backtick-wrapped function or method call:    ``foo()`` / ``Bar.baz()``
    2. Dotted qualified name (no parens):           ``module.Class.method``
    3. Explicit ``{path}::{qualname}`` annotation inserted by extractors.

This module returns the *normalized candidate set* — a deduplicated list
of qualified names that Cortex will ask AP to verify (via ``get_symbol``).

Pure logic — no AP calls, no I/O. The caller feeds page text; we return
strings. Two signals can be combined by the handler before verification:

    - this module's best-effort pattern extraction
    - claim-evidence records the extractor already attached to the page

False positives are cheap — AP returns ``not_found`` for unknown symbols
and the verdict module applies a threshold, so noisy candidates don't
flag a page as stale on their own.
"""

from __future__ import annotations

import re

# A qualified name segment: Python/TS/Rust-style identifier. We reject
# leading digits and single-letter fragments to cut false positives from
# file extensions and English words.
_IDENT = r"[A-Za-z_][A-Za-z_0-9]{1,}"

# ``foo()`` or ``Class.method()`` inside backticks. We require parens so
# plain English sentences like `memory` don't get flagged.
_BACKTICK_CALL = re.compile(r"`([A-Za-z_][\w.]*(?:\(\)|\([^`]{0,60}\)))`")

# Dotted chain of at least two identifier segments: ``a.b`` / ``a.b.c`` —
# any length. Must be on a word boundary so ``app.py`` (file suffix)
# doesn't match (handled by the extension blacklist below).
_DOTTED = re.compile(rf"\b({_IDENT}(?:\.{_IDENT}){{1,}})\b")

# File extensions and common English bigrams that look dotted but aren't
# code symbols. Extend if false positives appear.
_FILE_SUFFIXES = frozenset(
    {
        "py",
        "js",
        "ts",
        "tsx",
        "jsx",
        "md",
        "json",
        "yaml",
        "yml",
        "toml",
        "sql",
        "go",
        "rs",
        "rb",
        "java",
        "cpp",
        "c",
        "h",
        "hpp",
        "sh",
        "txt",
        "csv",
        "ini",
        "cfg",
        "lock",
        "log",
    }
)


def _strip_call_args(s: str) -> str:
    """``foo(x, y)`` → ``foo``; leave bare ``foo`` untouched."""
    idx = s.find("(")
    return s[:idx] if idx >= 0 else s


def _looks_like_file(qname: str) -> bool:
    """Reject dotted chains whose last segment is a file extension."""
    tail = qname.rsplit(".", 1)[-1].lower()
    return tail in _FILE_SUFFIXES


def extract_symbol_refs(text: str) -> list[str]:
    """Return distinct qualified-name candidates mentioned in ``text``.

    Candidates are deduplicated preserving first-occurrence order.
    Single-identifier names and file-path-like dots are filtered out —
    we only keep multi-segment qualnames, which is AP's minimum for
    a resolvable symbol.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []

    for m in _BACKTICK_CALL.finditer(text):
        q = _strip_call_args(m.group(1))
        if "." not in q:
            # Single function inside backticks — still useful; AP can
            # match by trailing name.
            if q in seen:
                continue
            seen.add(q)
            out.append(q)
            continue
        if _looks_like_file(q):
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)

    for m in _DOTTED.finditer(text):
        q = m.group(1)
        if _looks_like_file(q):
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)

    return out


def harvest_page_symbols(
    page: dict,
    claim_evidence_symbols: list[str] | None = None,
) -> list[str]:
    """Merge best-effort extraction with claim-evidence symbol refs.

    ``page`` shape mirrors what the wiki store returns: ``{lead, sections}``.
    Sections may be a dict (name→body) or a list of {heading, body} dicts.

    The return list is a stable, deduplicated union of:
      * high-signal claim-evidence symbol refs (if provided);
      * pattern matches in the page lead and every section body.
    """
    refs: list[str] = []
    seen: set[str] = set()

    for q in claim_evidence_symbols or []:
        if q and q not in seen:
            seen.add(q)
            refs.append(q)

    def _add(chunk: str) -> None:
        for q in extract_symbol_refs(chunk):
            if q not in seen:
                seen.add(q)
                refs.append(q)

    _add(page.get("lead") or "")
    sections = page.get("sections") or {}
    if isinstance(sections, dict):
        for body in sections.values():
            _add(str(body))
    elif isinstance(sections, list):
        for s in sections:
            body = s.get("body") if isinstance(s, dict) else getattr(s, "body", "")
            _add(str(body))
    return refs


__all__ = ["extract_symbol_refs", "harvest_page_symbols"]
