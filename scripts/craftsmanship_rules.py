"""Craftsmanship detectors: file size, method size, layer imports, magic
numbers — the four rules ``CLAUDE.md`` § Code Style states but nothing
checks (issue: no automated pre-commit hook exists, admitted in that
section before this gate).

Every detector returns a set of stable ``Violation`` identifiers — stable
meaning the identifier text does not change just because a line count
shifted elsewhere in the file (see each function's docstring). Stability is
what lets ``check_craftsmanship.py`` diff today's violations against a
baseline without every violation appearing "new" on every commit.

This module owns rules 1-2 (file size, method size) plus the ``Violation``
type and the ``scan_source`` aggregator; rules 3-4 (layer imports, magic
numbers) live in ``craftsmanship_imports.py`` / ``craftsmanship_constants.py``
— split out because keeping all four here crossed the very 300-line cap
this gate enforces (a gate that exempted itself would not be credible).

No I/O in this module — the caller reads the file; this module is pure AST
analysis, same discipline as ``core/`` (this file lives in ``scripts/``
where that boundary is a convention, not an enforced layer rule).
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# source: CLAUDE.md § Code Style — "300 lines max per file" — a local
# tightening of coding-standards.md §4.1 (500).
FILE_LINE_LIMIT = 300
# source: CLAUDE.md § Code Style — "40 lines max per method" — a local
# tightening of coding-standards.md §4.2 (50).
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

    No fixed line count (a prior version hardcoded "scan the first 5
    lines", an arbitrary constant flagged in review): a header is
    naturally delimited by the first line that is neither blank nor a
    comment, so this handles a one-line marker or a multi-line license
    block identically, with nothing to source or justify.
    """
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

    ``node.lineno`` is the ``def`` line itself (decorators carry their own
    ``lineno`` in the AST since Python 3.8), so a decorated function is
    measured by its own body, not inflated by its decorator lines.
    """
    violations = []
    for qualified, node in _qualified_function_defs(tree):
        if node.end_lineno is None:
            continue
        span = node.end_lineno - node.lineno
        if span > METHOD_LINE_LIMIT:
            violations.append(Violation(rel_path, "method-size", qualified))
    return violations


# Sibling modules, imported at module level (not function-local — ruff
# PLC0415) as bare ``import X`` rather than ``from X import Y``: each
# sibling's own top does ``from craftsmanship_rules import Violation``,
# which only needs ``Violation`` to already exist in THIS module's
# namespace — true from this point on, since it is defined above. A bare
# ``import X`` here binds the module object without touching any of its
# attributes yet, so it is safe regardless of which of the three modules
# Python loads first; only ``scan_source`` below, called later, actually
# dereferences into them.
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
