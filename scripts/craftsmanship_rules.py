"""Craftsmanship detectors: file size, method size, layer imports, magic
numbers — the four rules ``docs/agent-guidance.md`` § Code Style states but nothing
checks (issue: no automated pre-commit hook exists, admitted in that
section before this gate).

No I/O in this module — the caller reads the file; this module is pure AST
analysis, same discipline as ``core/`` (this file lives in ``scripts/``
where that boundary is a convention, not an enforced layer rule).

source: ADR-0726"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# source: ADR-0726
FILE_LINE_LIMIT = 300
# source: ADR-0726
METHOD_LINE_LIMIT = 40

AUTO_GENERATED_MARKER = "auto-generated"


@dataclass(frozen=True)
class Violation:
    """A single, stably-identified rule violation.

    ``detail`` deliberately excludes anything that drifts without the
    violation itself changing (a line count, a byte offset) — see each
    detector for what makes its ``detail`` stable.
    """

    file: str
    kind: str
    detail: str


def _leading_header_block(lines: list[str]) -> str:
    """The file's leading run of comment/blank lines, joined.

    source: ADR-0726"""
    header_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            header_lines.append(line)
            continue
        break
    return "\n".join(header_lines)


def check_file_size(rel_path: str, source: str) -> list[Violation]:
    """Rule 1 — file exceeds FILE_LINE_LIMIT lines. Exempt: auto-generated."""
    lines = source.splitlines()
    if AUTO_GENERATED_MARKER in _leading_header_block(lines).lower():
        return []
    if len(lines) <= FILE_LINE_LIMIT:
        return []
    # No line count in `detail`: the violation's identity is "this file is
    # over the cap", not "this file is exactly N lines over the cap".
    return [Violation(rel_path, "file-size", "exceeds 300-line cap")]


def _qualified_function_defs(
    tree: ast.AST,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Walk the tree, yielding (dotted qualified name, def node) pairs."""
    results: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    _walk_defs(tree, [], results)
    return results


def _walk_defs(
    node: ast.AST,
    stack: list[str],
    results: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]],
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = ".".join([*stack, child.name])
            results.append((qualified, child))
            _walk_defs(child, [*stack, child.name], results)
        elif isinstance(child, ast.ClassDef):
            _walk_defs(child, [*stack, child.name], results)
        else:
            _walk_defs(child, stack, results)


def check_method_size(rel_path: str, tree: ast.Module) -> list[Violation]:
    """Rule 2 — a function/method body spans more than METHOD_LINE_LIMIT
        lines, measured by AST (``end_lineno - lineno``) per the task
        instruction, never by regex.

    source: ADR-0726"""
    violations = []
    for qualified, node in _qualified_function_defs(tree):
        if node.end_lineno is None:
            continue
        span = node.end_lineno - node.lineno
        if span > METHOD_LINE_LIMIT:
            violations.append(Violation(rel_path, "method-size", qualified))
    return violations


# source: ADR-0726
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
import craftsmanship_constants  # noqa: E402
import craftsmanship_imports  # noqa: E402


def scan_source(rel_path: str, source: str) -> list[Violation]:
    """Run all four detectors over one file's source text.

    Returns an empty list (never raises) for a file that fails to parse —
    the caller is expected to have already selected ``.py`` files; a syntax
    error here means the file is broken independent of this gate, and this
    gate's job is craftsmanship, not "does it parse".
    """
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    layer = craftsmanship_imports.layer_of(rel_path)
    return [
        *check_file_size(rel_path, source),
        *check_method_size(rel_path, tree),
        *craftsmanship_imports.check_layer_violation(rel_path, layer, tree),
        *craftsmanship_constants.check_unsourced_constants(rel_path, tree, source),
    ]
