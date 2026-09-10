"""Canonical form for wiki page -> source-file path linkage.

source: ADR-0687
"""

from __future__ import annotations

from collections.abc import Mapping

_FILE_TAG_PREFIX = "file:"


def normalize_source_path(raw: str) -> str | None:
    """Canonicalize one raw path string. Returns None for blank input.

    Pre-condition:  ``raw`` is a str (possibly with backslashes, a leading
                    ``./``, or leading ``/`` — the forms this repo has
                    actually emitted or could plausibly copy-paste).
    Post-condition: return value is forward-slash separated with no
                    leading ``./`` or ``/``, or None if ``raw`` was blank.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.replace("\\", "/")
    # source: ADR-0687

    previous = None
    while text != previous:
        previous = text
        text = text.strip()
        while text.startswith("./"):
            text = text[2:]
        text = text.lstrip("/")
    return text or None


def extract_document_paths(
    frontmatter: Mapping[str, object], tags: list[str] | None = None
) -> list[str]:
    """Pull every documented-file path out of a page's frontmatter + tags.

    source: ADR-0687

    Post-condition: returned list is deduplicated (first occurrence wins,
                    insertion order preserved) and every entry is
                    canonical per ``normalize_source_path``.
    """
    raw_values: list[str] = []

    documents = frontmatter.get("documents")
    if isinstance(documents, list):
        raw_values.extend(str(v) for v in documents)
    elif isinstance(documents, str) and documents:
        raw_values.append(documents)

    source_file_path = frontmatter.get("source_file_path")
    if isinstance(source_file_path, str) and source_file_path:
        raw_values.append(source_file_path)

    file_field = frontmatter.get("file")
    if isinstance(file_field, str) and file_field:
        raw_values.append(file_field)

    for tag in tags or []:
        if isinstance(tag, str) and tag.startswith(_FILE_TAG_PREFIX):
            raw_values.append(tag[len(_FILE_TAG_PREFIX) :])

    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        canonical = normalize_source_path(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out
