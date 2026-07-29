"""Canonical form for wiki page -> source-file path linkage (ADR-0051 STEP 2).

Wiki pages record the source file(s) they document in one of three legacy
frontmatter forms (``source_file_path:``, ``file:``, or a ``file:<path>``
tag), all three of which already carry the value produced by
``wiki_coverage.list_source_files`` / ``wiki_file_doc_skeleton``: a path
*relative to the project source root*, forward-slash separated
(``mcp_server.shared.platform.to_posix``). This module is the single place
that normalizes any of those raw strings into that one canonical form
before it reaches ``wiki.page_sources.source_path`` — reusing the existing
convention rather than inventing a new one (see
``mcp_server/core/wiki_coverage.py::list_source_files`` and
``mcp_server/core/wiki_drift.py::audit_wiki_drift``, both of which already
produce/consume this exact shape).

Canonical form: POSIX-separated, no leading ``./``, no leading ``/``,
project-source-root-relative. Pure string processing — no filesystem
access, no project-source-root resolution — hence shared/ (stdlib only).

Pre-condition:  raw frontmatter values are strings (scalar) or lists of
                strings, as parsed by ``mcp_server.core.wiki_pages.parse_page``.
Post-condition: every path returned by ``extract_document_paths`` is
                non-empty, forward-slash separated, and has no leading
                ``./`` or ``/``. Duplicates are removed, order preserved.
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
    # Strip surrounding whitespace, "./" and "/" prefixes to a fixed point,
    # alternating — every one of the three inside the loop.
    #
    # This used to strip "./" in a loop and THEN lstrip("/") exactly once,
    # which is not a canonicalisation: removing the leading slashes can
    # expose a "./" the loop has already walked past. ".//./x" came out as
    # "./x" and "/./z" as "./z" — both still carrying the prefix this
    # function exists to remove, in violation of the post-condition above.
    #
    # Making the two PREFIX strips a fixed point left whitespace outside it,
    # which is the same defect one layer up: strip() ran once, before the
    # loop, so removing a leading "/" re-exposed whitespace nothing stripped
    # again. "/\n?" came out as "\n?", which normalises further to "?" — a
    # result that is not its own normal form. Fuzzing found 300 such inputs
    # over a 7-character alphabet at length <= 4.
    #
    # The cost was silent: extract_document_paths promises every entry is
    # canonical and dedupes on that basis, so one document reachable by two
    # spellings counted as two documents, and any caller comparing
    # normalised paths for equality saw a mismatch. Found by fuzzing this
    # post-condition (fuzz/fuzz_source_path.py); regression pinned in
    # tests_py/shared/test_wiki_source_paths.py.
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

    Reads, in this precedence order, every legacy form this repo has
    written (back-compat — all are read, none is preferred over the
    others as a *source*; results are deduped, not chosen-between):

      * ``documents:`` — the new field (list or scalar).
      * ``source_file_path:`` — file-doc skeleton pages (scalar).
      * ``file:`` — ``build_file_doc`` pages (scalar).
      * ``file:<path>`` tags — legacy tag-encoded form.

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
