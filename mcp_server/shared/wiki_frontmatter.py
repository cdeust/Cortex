"""Wiki page frontmatter parser + PageDocument model — pure, deterministic.

Parses YAML-style frontmatter (``---``…``---``) into a plain dict so
handlers can round-trip metadata without depending on a YAML library, and
renders a ``PageDocument`` back to markdown text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class PageDocument:
    """Parsed representation of a wiki page."""

    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_frontmatter(fm: dict[str, object]) -> str:
    """Emit a minimal YAML-ish frontmatter block. Sorted keys, scalars only.

    Lists are rendered inline (``[a, b, c]``). Nested dicts are not
    supported — keep metadata flat.
    """
    if not fm:
        return ""
    lines = ["---"]
    for key in sorted(fm):
        value = fm[key]
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(v) for v in value) + "]"
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _strip_inline_list(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [item.strip() for item in inner.split(",") if item.strip()]


# source: structural — a quoted scalar needs both an opening and a closing
# quote character, so it is at least two characters long.
_MIN_QUOTED_SCALAR_LEN = 2


def _clean_scalar_value(key: str, raw_stripped: str) -> str:
    """Normalize a non-list frontmatter scalar value.

    precondition: ``raw_stripped`` is the whitespace-trimmed text found
    after the FIRST ``:`` on a frontmatter line (i.e. ``line.partition(":")``
    already removed exactly one ``<key>:`` label); ``raw_stripped`` is
    non-empty and is not an inline ``[...]`` list (both handled by the
    caller before this is reached).
    postcondition: returns ``raw_stripped`` with (a) a duplicated leading
    ``"<key>: "`` label removed, at most once, matched case-insensitively
    against ``key`` — this repairs content where the author's own
    frontmatter emission echoed the key a second time inside its value
    (observed on disk: ``title: title: "Public API surface: ..."``,
    written verbatim by an LLM-authored page routed through
    ``write_governed_page``, which persists caller-supplied markdown
    without re-deriving frontmatter); (b) one matching pair of surrounding
    quote characters (``"`` or ``'``) removed, mirroring the quote-stripping
    the block-list branch (``items.append(...strip("\"'"))``, above) and
    ``_strip_inline_list`` already perform for list values — the scalar
    branch previously had no equivalent, so a value legitimately quoted
    per YAML convention because it contains a colon (e.g.
    ``title: "Public API surface: automatised-pipeline"``) kept its
    literal quote characters. A value that merely starts with the key
    name as a normal word (e.g. ``title: titleist golf clubs``) is
    unaffected — the duplicate-label check requires the exact
    ``"<key>:"`` token, not just a shared prefix.
    """
    value = raw_stripped
    dup_prefix = f"{key}:"
    if value.lower().startswith(dup_prefix.lower()):
        value = value[len(dup_prefix) :].strip()
    if (
        len(value) >= _MIN_QUOTED_SCALAR_LEN
        and value[0] == value[-1]
        and value[0] in "\"'"
    ):
        value = value[1:-1]
    return value


def _collect_block_list(lines: list[str], start: int) -> tuple[list[str], int]:
    """Peek ahead from ``start`` for indented ``  - item`` lines.

    Returns ``(items, next_idx)`` — ``next_idx`` is the first line past the
    collected block (unchanged from ``start`` when no items were found, so
    the caller can distinguish "block list" from "empty scalar").
    """
    items: list[str] = []
    j = start
    while j < len(lines):
        peek = lines[j]
        if peek.strip() == "---":
            break
        stripped = peek.lstrip()
        if peek.startswith((" ", "\t")) and stripped.startswith("- "):
            items.append(stripped[2:].strip().strip("\"'"))
            j += 1
            continue
        break
    return items, j


def _parse_frontmatter_body(lines: list[str]) -> tuple[dict[str, object], int]:
    """Parse the frontmatter key/value lines starting at ``lines[1]``
    (``lines[0]`` is the opening ``---`` fence, already checked by the
    caller). Returns ``(frontmatter, body_start_index)``.
    """
    fm: dict[str, object] = {}
    idx = 1
    while idx < len(lines):
        if lines[idx].strip() == "---":
            return fm, idx + 1
        line = lines[idx]
        if ":" not in line:
            idx += 1
            continue
        # Block-list detection: a key with no value followed by indented
        # ``  - item`` lines collects into a list.
        key_part, _, raw = line.partition(":")
        key = key_part.strip()
        raw_stripped = raw.strip()
        if raw_stripped == "":
            items, j = _collect_block_list(lines, idx + 1)
            if items:
                fm[key] = items
                idx = j
                continue
            fm[key] = ""  # Empty value, no list — keep as empty string.
            idx += 1
            continue
        if raw_stripped.startswith("[") and raw_stripped.endswith("]"):
            fm[key] = _strip_inline_list(raw_stripped)
        else:
            fm[key] = _clean_scalar_value(key, raw_stripped)
        idx += 1
    return fm, len(lines)


def parse_page(text: str) -> PageDocument:
    """Parse a page's frontmatter + body. Tolerant of missing frontmatter.

    Handles two YAML list forms:

      * Inline:  ``tags: [a, b, c]``
      * Block:   ``tags:\\n  - a\\n  - b``

    Block-style is required for ``curation_gaps`` and other multi-value
    metadata the file-doc skeletons emit. See ``_parse_frontmatter_body``
    for the key/value parsing loop and ``_collect_block_list`` for the
    block-list lookahead.
    """
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return PageDocument(body=text)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return PageDocument(body=text)
    fm, body_start = _parse_frontmatter_body(lines)
    body_lines = lines[body_start:]
    while body_lines and body_lines[0] == "":
        body_lines.pop(0)
    return PageDocument(frontmatter=fm, body="\n".join(body_lines))


def render_page(doc: PageDocument) -> str:
    """Render a PageDocument back to markdown text."""
    header = _format_frontmatter(doc.frontmatter)
    if header and doc.body:
        return header + doc.body + ("" if doc.body.endswith("\n") else "\n")
    if header:
        return header
    return doc.body + ("" if doc.body.endswith("\n") else "\n") if doc.body else ""
