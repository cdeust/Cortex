"""Craftsmanship rule 4 — module-scope numeric literals without a
``# source:`` comment.

Split out of ``craftsmanship_rules.py`` for the same reason
``craftsmanship_imports.py`` was (file-size self-application, see that
module's docstring).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Sibling-module import, same idiom as check_doc_claims.py: resolves
# identically whether this runs as a script or is loaded via
# importlib.util.spec_from_file_location from a test.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from craftsmanship_rules import Violation  # noqa: E402

SOURCE_COMMENT_MARKER = "# source:"

# source: task instruction (constants-without-source rule) — the literal
# exemption list: "0, 1, -1, 2, 100, 1000 et les puissances de deux
# usuelles"; "usuelles" bounded at 2**16 (65536), the largest power of two
# that appears as a plain magic number (buffer/timeout sizes) rather than a
# capacity a real source comment would explain anyway.
_POWERS_OF_TWO_USUELLES = frozenset(2**exp for exp in range(1, 17))
TRIVIAL_LITERALS = frozenset({0, 1, -1, 2, 100, 1000}) | _POWERS_OF_TWO_USUELLES


def _numeric_literal(node: ast.expr) -> int | float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _numeric_literal(node.operand)
        if inner is None:
            return None
        return -inner if isinstance(node.op, ast.USub) else inner
    return None


def _has_source_comment(lines: list[str], lineno: int) -> bool:
    """True if a ``# source:`` comment sits on, or immediately above, line
    ``lineno`` (1-indexed) — a contiguous run of comment lines, no blank
    line in between.
    """
    if 0 < lineno <= len(lines) and SOURCE_COMMENT_MARKER in lines[lineno - 1]:
        return True
    i = lineno - 2
    while i >= 0:
        stripped = lines[i].strip()
        if not stripped.startswith("#"):
            return False
        if SOURCE_COMMENT_MARKER in lines[i]:
            return True
        i -= 1
    return False


def _module_level_numeric_assignments(
    tree: ast.Module,
) -> list[tuple[str, ast.expr, int]]:
    """Return (name, value_node, lineno) for simple module-scope assignments."""
    found: list[tuple[str, ast.expr, int]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            found.append((node.targets[0].id, node.value, node.lineno))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            found.append((node.target.id, node.value, node.lineno))
    return found


def check_unsourced_constants(
    rel_path: str, tree: ast.Module, source: str
) -> list[Violation]:
    """Rule 4 — a non-trivial module-scope numeric literal with no nearby
    ``# source:`` comment. ``detail`` is the constant's name: stable across
    any edit that leaves the assignment (and its comment) untouched.
    """
    lines = source.splitlines()
    violations = []
    for name, value_node, lineno in _module_level_numeric_assignments(tree):
        value = _numeric_literal(value_node)
        if value is None or value in TRIVIAL_LITERALS:
            continue
        if not _has_source_comment(lines, lineno):
            violations.append(Violation(rel_path, "unsourced-constant", name))
    return violations
