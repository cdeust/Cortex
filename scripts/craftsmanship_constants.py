"""Craftsmanship rule 4 — module-scope numeric literals without a
``# source:`` comment.

Split out of ``craftsmanship_rules.py`` for the same reason
``craftsmanship_imports.py`` was (file-size self-application, see that
module's docstring).

**Known, documented detection gaps** (flagged in review; each is pinned by
a test in ``tests_py/scripts/test_craftsmanship_constants.py`` asserting
the CURRENT non-detecting behavior, so silently "fixing" one is a reviewed
diff, not an accidental drift):

1. **Computed expressions** — ``TIMEOUT = 60 * 60`` is an ``ast.BinOp``,
   not the bare ``ast.Constant``/negated-constant this rule's
   ``_numeric_literal`` matches, so it is never flagged.
2. **Class-scope constants** — ``_module_level_numeric_assignments`` only
   walks ``tree.body`` (the module's own top-level statements); a class
   attribute (``class C: TIMEOUT = 3600``) sits one level deeper and is
   never visited.
3. **Default-argument values** — ``def f(timeout: int = 3600):`` is a
   value inside a ``FunctionDef.args.defaults`` list, a different AST
   surface this rule never inspects.

None of these are exotic — they are exactly the forms most likely to
carry an accidental magic number. Extending detection to them is future
work, not silently promised by this module's name.
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

# NOT a "# source:"-backed constant (flagged in review: citing "task
# instruction" as a §8 source is not one — §8 wants a paper, a committed
# benchmark, or a dated measurement, none of which apply to an exemption
# list). This is a documented implementer DECISION, not a measurement:
# the exact values a human reviewer accepts without asking "where does
# that number come from" — 0/1/-1/2/100/1000 are load-bearing in every
# language's arithmetic idiom (empty/singleton/negation/pair/percent/
# per-mille), and a power of two up to 2**16 (65536) is legible on sight
# as a bit-width or buffer size, not a business threshold that needs
# citing. Pinned by
# tests_py/scripts/test_craftsmanship_constants.py so a change to this
# list is a reviewed diff, not silent drift.
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
