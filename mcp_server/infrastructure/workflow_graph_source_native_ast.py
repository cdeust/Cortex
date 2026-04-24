"""Native AST source for the workflow graph — Cortex's in-house tree-sitter
pipeline, used when automatised-pipeline (AP) is disabled or has not yet
indexed a project.

Mirrors the public API of ``workflow_graph_source_ast`` (AP bridge) so the
handler treats them uniformly. Emits the same dict shapes the builder
already expects (see `ingest_symbol` / `ingest_ast_edge` in
`core/workflow_graph_builder_relational.py`).

Output shapes:

    symbols → [{
        file_path, qualified_name, symbol_type, signature, language, line,
    }]

    edges → [{
        kind: "calls" | "imports" | "member_of",
        src_file, src_name,          # src_name empty for file-level IMPORTS
        dst_file, dst_name,
        confidence: 1.0,             # AST facts — Gap 6 provenance default
        reason: "native-ast",
    }]

Why this module exists (user-visible motivation): v3.14's L6 symbol ring
is wired end-to-end but only populated when AP is present. On a fresh
project with AP disabled, the graph renders Claude's file entry-points
faithfully but has no INTERNAL depth — no functions, classes, methods
are visible. This source closes that gap using only Python tree-sitter
that Cortex already ships.

Source: docs/program/v3.14-gap-analysis-v2-corrected.md §5 move 1 +
docs/program/gitnexus-competitive-analysis.md M4; ADR-0046 Phase 1 (the
"6th ring" of symbols inside files) now works without AP.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from mcp_server.core.ast_parser import is_available as ast_available
from mcp_server.core.ast_parser import parse_file_ast
from mcp_server.core.codebase_graph import resolve_all_imports
from mcp_server.core.codebase_parser import FileAnalysis, detect_language, parse_file

logger = logging.getLogger(__name__)

# Per-file parse cap — same limit AP uses (1 MB) for bounded parse work.
_MAX_PARSE_BYTES = 1_048_576

# How many files to parse per call. A typical session touches fewer than
# this many files; the cap protects against runaway when the caller
# passes an unbounded list.
_MAX_FILES_PER_CALL = 2_000


class WorkflowGraphNativeASTSource:
    """In-process AST source — tree-sitter when installed, regex fallback
    otherwise. Enabled whenever the caller provides at least one readable
    file path with a detectable language.
    """

    def enabled(self) -> bool:
        # Always enabled — regex fallback handles the languages where
        # tree-sitter isn't installed. The loaders simply return [] when
        # no file paths are provided.
        return True

    def ast_available(self) -> bool:
        """Tree-sitter proper is installed (deeper extraction)."""
        return ast_available()

    def load_symbols(
        self, file_paths: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Return one symbol row per function/class/method definition
        found in each readable file. Skips unreadable files silently.
        """
        analyses = self._parse_all(file_paths)
        symbols: list[dict[str, Any]] = []
        for a in analyses:
            for sym in a.definitions:
                symbols.append(
                    {
                        "file_path": a.path,
                        "qualified_name": sym.name,
                        "symbol_type": sym.kind,
                        "signature": sym.signature,
                        "language": a.language,
                        "line": None,  # regex/AST extractors don't carry line numbers (yet)
                        "domain": "",
                    }
                )
        return symbols

    def load_ast_edges(
        self, file_paths: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Return IMPORTS, MEMBER_OF edges for the given files.

        CALLS edges require per-function call-site attribution which the
        in-house extractors don't expose yet (only file-level lists via
        `extract_calls_generic`). Until that lands, callers get empty
        CALLS from this source — AP fills the gap when enabled, and the
        L6 ring is still populated via DEFINED_IN (auto-emitted by
        `ingest_symbol`) + MEMBER_OF + IMPORTS.
        """
        analyses = self._parse_all(file_paths)
        if not analyses:
            return []
        edges: list[dict[str, Any]] = []
        edges.extend(self._member_of_edges(analyses))
        edges.extend(self._import_edges(analyses))
        return edges

    # ── internals ────────────────────────────────────────────────────

    def _parse_all(self, file_paths: Iterable[str]) -> list[FileAnalysis]:
        """Read + parse each file; skip unreadable / too-large / non-source."""
        analyses: list[FileAnalysis] = []
        n = 0
        for raw_path in file_paths:
            n += 1
            if n > _MAX_FILES_PER_CALL:
                break
            if not raw_path:
                continue
            # Skip files with no language we can parse — saves the
            # fs.stat + open call on every .md / .txt Claude touched.
            if not detect_language(raw_path):
                continue
            try:
                p = Path(raw_path)
                if not p.is_file():
                    continue
                if p.stat().st_size > _MAX_PARSE_BYTES:
                    continue
                content = p.read_bytes()
            except (OSError, PermissionError):
                continue
            analyses.append(self._parse_one(raw_path, content))
        return analyses

    def _parse_one(self, path: str, content: bytes) -> FileAnalysis:
        """Prefer tree-sitter; fall back to regex. `parse_file_ast`
        already does the fallback internally when AST_SUPPORTED doesn't
        cover the language or tree-sitter isn't installed."""
        try:
            return parse_file_ast(path, content)
        except Exception as exc:
            logger.debug("parse_file_ast failed for %s: %s", path, exc)
            try:
                return parse_file(path, content.decode(errors="replace"))
            except Exception as exc2:
                logger.debug("regex parse_file failed for %s: %s", path, exc2)
                # Empty analysis — caller treats missing data as normal.
                return FileAnalysis(
                    path=path,
                    language=detect_language(path) or "unknown",
                    content_hash="",
                )

    def _member_of_edges(
        self, analyses: list[FileAnalysis]
    ) -> list[dict[str, Any]]:
        """method → class MEMBER_OF. The parser emits method names as
        ``ClassName.method``; we split on ``.`` and attach the method
        symbol to the class symbol in the same file."""
        out: list[dict[str, Any]] = []
        for a in analyses:
            # class names defined in THIS file (MEMBER_OF is intra-file).
            classes_in_file = {
                d.name for d in a.definitions if d.kind == "class"
            }
            for sym in a.definitions:
                if sym.kind != "method":
                    continue
                if "." not in sym.name:
                    continue
                parent = sym.name.rsplit(".", 1)[0]
                if parent not in classes_in_file:
                    continue
                out.append(
                    {
                        "kind": "member_of",
                        "src_file": a.path,
                        "src_name": sym.name,
                        "dst_file": a.path,
                        "dst_name": parent,
                        "confidence": 1.0,
                        "reason": "native-ast:member-of",
                    }
                )
        return out

    def _import_edges(
        self, analyses: list[FileAnalysis]
    ) -> list[dict[str, Any]]:
        """File → imported-symbol IMPORTS. Resolves each import's target
        file via ``resolve_all_imports``; then, for every imported name
        that corresponds to a SYMBOL defined in the target file, emit
        one edge.

        ``codebase_graph.resolve_all_imports`` builds candidate paths
        like ``lib.py`` or ``lib/__init__.py`` — it's only useful when
        FileAnalysis.path is relative to the project root. Absolute
        paths from session tool-events would never match. We normalise
        every analysis to a relative-to-common-prefix path before
        resolving, then map results back to absolutes for the emitted
        edges (ingest_ast_edge keys nodes by absolute path).
        """
        if not analyses:
            return []
        abs_paths = [a.path for a in analyses]
        rel_paths = _relativize(abs_paths)
        rel_to_abs = dict(zip(rel_paths, abs_paths))
        # Build a shallow copy with relative paths so
        # `resolve_all_imports` can find candidates. Original analyses
        # stay untouched.
        rel_analyses = [
            FileAnalysis(
                path=rel_paths[i],
                language=a.language,
                content_hash=a.content_hash,
                imports=a.imports,
                definitions=a.definitions,
            )
            for i, a in enumerate(analyses)
        ]
        file_to_file_rel = set(resolve_all_imports(rel_analyses))

        # Map target-file path (ABSOLUTE) → set of top-level symbol names.
        symbols_in_file: dict[str, set[str]] = {}
        for a in analyses:
            names: set[str] = {
                sym.name for sym in a.definitions if "." not in sym.name
            }
            symbols_in_file[a.path] = names

        out: list[dict[str, Any]] = []
        for i, a in enumerate(analyses):
            rel_src = rel_paths[i]
            for imp in a.imports:
                if not imp.names:
                    continue  # e.g. `import foo` with no named members
                target_rel = next(
                    (tgt for (src, tgt) in file_to_file_rel if src == rel_src),
                    None,
                )
                if target_rel is None:
                    continue
                target_abs = rel_to_abs.get(target_rel)
                if target_abs is None:
                    continue
                tgt_names = symbols_in_file.get(target_abs, set())
                for name in imp.names:
                    if name not in tgt_names:
                        continue
                    out.append(
                        {
                            "kind": "imports",
                            "src_file": a.path,
                            "src_name": "",
                            "dst_file": target_abs,
                            "dst_name": name,
                            "confidence": 1.0,
                            "reason": "native-ast:import",
                        }
                    )
        return out


def _relativize(abs_paths: list[str]) -> list[str]:
    """Return each path relative to their longest common parent. Strips
    the leading slash + shared directory so ``codebase_graph``'s candidate
    logic (which assumes repo-root-relative paths) can find targets."""
    if not abs_paths:
        return []
    # os.path.commonpath handles the edge cases (trailing slashes,
    # mixed separators on Windows) we'd re-invent otherwise.
    import os.path

    try:
        root = os.path.commonpath(abs_paths)
    except ValueError:
        # Paths on different drives (Windows) — bail out to absolute.
        return list(abs_paths)
    if not root or root == "/":
        return list(abs_paths)
    return [os.path.relpath(p, root) for p in abs_paths]


__all__ = ["WorkflowGraphNativeASTSource"]
