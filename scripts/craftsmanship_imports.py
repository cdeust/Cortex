"""Craftsmanship rule 3 — layer-boundary imports, a TRUE whitelist.

Rewritten after review found the prior version was a blacklist wearing a
whitelist's name: it denied a short hardcoded list of specific imports
(``os``, ``pathlib``, a few ``mcp_server.<layer>`` prefixes) and silently
ALLOWED everything else — so `import numpy`, `import requests`, and
`import scripts.legacy_bridge` inside `core/` all passed uncaught. The
fix is structural, not a bigger blacklist: every import is now checked
against what a layer is explicitly PERMITTED to reference (derived from
``craftsmanship_layer_table.py``, itself parsed from
``docs/module-inventory.md`` § Dependency Rules — never a second
hardcoded copy of that table); anything not on the permitted list is a
violation, covering all eight documented layers, not four.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from craftsmanship_layer_table import LayerRule, is_stdlib, load_layer_rules  # noqa: E402
from craftsmanship_rules import Violation  # noqa: E402

CHECKED_LAYERS = frozenset(load_layer_rules())


def layer_of(rel_posix_path: str) -> str | None:
    """Return the ``mcp_server/<layer>/`` this file lives under, or None."""
    parts = rel_posix_path.split("/")
    if "mcp_server" not in parts:
        return None
    idx = parts.index("mcp_server")
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class _ImportCollector(ast.NodeVisitor):
    """Collects absolute, runtime-reachable dotted import module names.

    Relative imports (``from . import x``, ``level > 0``) are skipped: they
    resolve within the same package and cannot cross a layer boundary that
    an absolute ``mcp_server.<layer>`` import would. Imports inside
    ``if TYPE_CHECKING:`` are skipped too — a type-only forward reference
    used for annotations, not a runtime dependency the layer rule polices.
    """

    def __init__(self) -> None:
        self.modules: list[str] = []

    def visit_If(self, node: ast.If) -> None:  # noqa: N802 (ast.NodeVisitor API)
        if _is_type_checking_test(node.test):
            for stmt in node.orelse:
                self.visit(stmt)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.modules.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.level and node.level > 0:
            return
        if node.module:
            self.modules.append(node.module)


def _import_violates_layer(rule: LayerRule, module: str) -> bool:
    """True if ``module`` (dotted, absolute) breaks ``rule``'s whitelist.

    Every branch is a permission CHECK, not a denial check: an import that
    matches none of them falls through to the final ``return True`` — the
    fix for the review finding that a permitted set with an implicit
    "everything else is fine" default is not a whitelist.
    """
    parts = module.split(".")
    top, second = parts[0], (parts[1] if len(parts) > 1 else None)
    if top == "mcp_server" and second == rule.name:
        return False  # sibling import inside the same layer
    if top == "mcp_server":
        return second not in rule.allowed_layers
    if is_stdlib(top):
        if top in rule.stdlib_denied:
            return True
        return not rule.stdlib_allowed
    # Third-party (neither `mcp_server.*` nor stdlib): permitted only for a
    # "boundary" layer (infrastructure/validation/handlers/server/hooks) —
    # Clean Architecture's adapter layers, where frameworks belong. A
    # "pure" layer (shared/, core/, errors/) forbids it outright.
    return rule.is_pure


def check_layer_violation(
    rel_path: str, file_layer: str | None, tree: ast.Module
) -> list[Violation]:
    """Rule 3 — an import that crosses a forbidden layer boundary.

    ``detail`` is the exact dotted module string as written, so two
    different imports never collide, and the same import surviving an
    otherwise-edited file still matches its baseline entry.
    """
    rule = load_layer_rules().get(file_layer) if file_layer else None
    if rule is None:
        return []
    collector = _ImportCollector()
    collector.visit(tree)
    return [
        Violation(rel_path, "layer-violation", module)
        for module in collector.modules
        if _import_violates_layer(rule, module)
    ]
