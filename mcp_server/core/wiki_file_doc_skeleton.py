"""Generate file-doc skeletons that EXPOSE their curation gaps.

User direction 2026-05-18: a file-doc page is not "remove it because
it's thin" — it's "show what's missing so the curation queue is
visible at the document." This module produces skeletons that
declare every canonical section as a heading + an explicit
``_(missing — needs: <description>)_`` marker the LLM (or human author)
sees and fills in.

The skeletons are NOT stubs in the placeholder sense — the stub
detector targets ``_(to be filled)_`` / ``_To be written._``. These
skeletons use ``_(missing — needs:`` so they're distinguishable; the
purge defaults will leave them alone.

Pure logic — produces a string. Callers write to disk.
"""

from __future__ import annotations

import pathlib
import re
from typing import Iterable

from mcp_server.core.wiki_curation_gaps import FILE_DOC_SECTIONS


# Tags safe to add — these do NOT trigger the classifier's audit-tag
# rejection. ``codebase-skeleton`` is a distinct provenance marker
# from the legacy ``codebase`` tag so the new skeletons are
# admitted while old auto-gen pages remain rejected.
_DEFAULT_TAGS: tuple[str, ...] = (
    "file-doc",
    "codebase-skeleton",
    "needs-curation",
)


def _detect_language(path: str) -> str:
    ext = pathlib.Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".java": "java",
        ".kt": "kotlin",
        ".swift": "swift",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".sql": "sql",
    }.get(ext, "text")


_PY_IMPORT_RE = re.compile(r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
_TS_IMPORT_RE = re.compile(r"^import\s+.*from\s+['\"]([^'\"]+)['\"]")


def _extract_imports(language: str, source: str) -> list[str]:
    imports: list[str] = []
    for ln in source.splitlines()[:200]:  # cap at first 200 lines
        s = ln.strip()
        if language == "python":
            m = _PY_IMPORT_RE.match(s)
            if m:
                imports.append(m.group(1) or m.group(2))
        elif language in ("typescript", "javascript"):
            m = _TS_IMPORT_RE.match(s)
            if m:
                imports.append(m.group(1))
    # Dedupe preserving order, cap at 20.
    seen: dict[str, None] = {}
    for i in imports:
        seen.setdefault(i, None)
    return list(seen)[:20]


_PY_DEF_RE = re.compile(r"^(?:async\s+def|def|class)\s+([A-Za-z_]\w*)")
_TS_EXPORT_RE = re.compile(
    r"^export\s+(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_]\w*)"
)


def _extract_symbols(language: str, source: str) -> list[str]:
    syms: list[str] = []
    for ln in source.splitlines():
        s = ln.lstrip()  # keep top-level only (lstrip then check indent)
        if ln != s:
            continue  # indented — skip nested defs
        if language == "python":
            m = _PY_DEF_RE.match(s)
            if m:
                syms.append(m.group(1))
        elif language in ("typescript", "javascript"):
            m = _TS_EXPORT_RE.match(s)
            if m:
                syms.append(m.group(1))
    # Dedupe + cap.
    seen: dict[str, None] = {}
    for s in syms:
        seen.setdefault(s, None)
    return [s for s in seen if not s.startswith("_")][:25]


def _frontmatter(
    rel_source_path: str,
    domain: str,
    language: str,
    line_count: int,
    gap_names: Iterable[str],
    *,
    today: str,
    extra_tags: tuple[str, ...] = (),
) -> str:
    tags = (
        list(_DEFAULT_TAGS)
        + [
            f"lang:{language}",
            f"file:{rel_source_path}",
            f"domain:{domain}",
        ]
        + list(extra_tags)
    )
    tag_block = "\n".join(f"  - {t}" for t in tags)
    gap_block = "\n".join(f"  - {g}" for g in gap_names)
    return (
        "---\n"
        f"title: File: {rel_source_path}\n"
        "kind: reference\n"
        f"domain: {domain}\n"
        f"source_file_path: {rel_source_path}\n"
        f"language: {language}\n"
        f"line_count: {line_count}\n"
        "lifecycle: needs-curation\n"
        "provenance: skeleton\n"
        "authored_by: file-doc-skeleton-v2\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"last_reviewed: {today}\n"
        f"curation_gaps:\n{gap_block}\n"
        f"tags:\n{tag_block}\n"
        "---\n\n"
    )


def _missing_marker(description: str) -> str:
    """Marker the LLM and human reader both recognise as 'fill me in'.

    Deliberately distinct from the stub markers (`_(to be filled)_` /
    `_To be written._`) so the stub detector / purge doesn't sweep
    these skeletons. The wiki view renders pages with these markers
    with a "curation needed" banner — see ``wiki_curation_gaps``.
    """
    return f"_(missing — needs: {description})_"


def build_file_doc(
    rel_source_path: str,
    source_text: str,
    domain: str,
    *,
    today: str,
) -> str:
    """Build a file-doc page body for the given source file.

    The body contains EVERY canonical section as a heading. Sections
    the skeleton can populate automatically (file path, language,
    imports, public symbols) are filled in. Sections that need a
    human or LLM explanation are emitted with a clear
    ``_(missing — needs: …)_`` marker that lists what should go there.
    """
    language = _detect_language(rel_source_path)
    line_count = source_text.count("\n") + 1
    imports = _extract_imports(language, source_text)
    symbols = _extract_symbols(language, source_text)

    # Sections we can pre-populate skip the "missing" marker.
    auto_populated: dict[str, str] = {}

    # Dependencies — we can list the raw imports; the curation gap
    # is the "why each import is here" annotation, so we leave the
    # heading as "needs curation" if there are imports we can't annotate.
    if imports:
        deps = "\n".join(f"* `{i}`" for i in imports)
        auto_populated["dependencies"] = (
            f"_The following imports are declared at the top of "
            f"`{rel_source_path}`. The curation step is to explain "
            "what each one is for and why this file depends on it._\n\n" + deps
        )

    if symbols:
        api_lines = "\n".join(
            f"* `{s}` — _(missing — needs: one-line semantic)_" for s in symbols
        )
        auto_populated["public-api"] = (
            "_The exported / top-level symbols below were extracted "
            "automatically. The curation step is to write what each "
            "one does._\n\n" + api_lines
        )

    gaps: list[str] = []
    body_parts: list[str] = []
    body_parts.append(f"# File: `{rel_source_path}`\n")
    body_parts.append(
        f"_Project_: **{domain}**  |  _Language_: **{language}**  |  "
        f"_Line count_: **{line_count}**\n"
    )
    body_parts.append(
        "_This file-doc was generated as a curation skeleton. Sections "
        "marked **needs curation** are explicit gaps the autonomous "
        "re-author loop (or a human author) will fill in. Nothing is "
        "hidden — every missing piece of the explanation is named below._\n"
    )

    for section in FILE_DOC_SECTIONS:
        body_parts.append("\n" + section.heading + "\n")
        if section.name in auto_populated:
            body_parts.append(auto_populated[section.name])
        else:
            body_parts.append(_missing_marker(section.description))
            gaps.append(section.name)

    body_parts.append("\n## See also\n")
    body_parts.append(
        _missing_marker(
            "cross-links to the project's architecture / services / api "
            "anchor pages and any sibling files in the same module"
        )
    )
    if "see-also" not in {s.name for s in FILE_DOC_SECTIONS}:
        gaps.append("see-also")

    fm = _frontmatter(
        rel_source_path,
        domain,
        language,
        line_count,
        gaps,
        today=today,
    )
    return fm + "\n".join(body_parts) + "\n"
