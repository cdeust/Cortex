"""Craftsmanship rule 3 — layer-boundary imports.

Split out of ``craftsmanship_rules.py`` (issue: that file crossed the
300-line cap this very gate enforces — a gate that exempted itself would
not be credible, so it is split like anything else over the limit).
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

# source: docs/module-inventory.md § Dependency Rules — "core/ | shared/
# only | infrastructure, handlers, server, os/pathlib" — os/pathlib are
# banned even though they are stdlib, because core/ is "pure business
# logic, zero I/O" (module-inventory.md's own layer description).
_CORE_BANNED_STDLIB = frozenset({"os", "pathlib"})

# source: docs/module-inventory.md § Dependency Rules "Must NOT Import"
# column, restricted to the four layers this gate covers per the task
# instruction (shared/core/infrastructure/server).
FORBIDDEN_SECOND_COMPONENT = {
    "core": frozenset({"infrastructure", "handlers", "server"}),
    "infrastructure": frozenset({"core", "handlers", "server"}),
    "server": frozenset({"core", "infrastructure"}),
}

CHECKED_LAYERS = frozenset({"shared", "core", "infrastructure", "server"})


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


def _is_stdlib(top_level: str) -> bool:
    return top_level in sys.stdlib_module_names


def _import_violates_layer(file_layer: str, module: str) -> bool:
    """True if ``module`` (dotted, absolute) breaks ``file_layer``'s rule."""
    parts = module.split(".")
    top, second = parts[0], (parts[1] if len(parts) > 1 else None)
    if top == "mcp_server" and second == file_layer:
        return False  # sibling import inside the same layer
    if file_layer == "shared":
        return not _is_stdlib(top)
    if file_layer == "core" and top in _CORE_BANNED_STDLIB:
        return True
    forbidden = FORBIDDEN_SECOND_COMPONENT.get(file_layer)
    return bool(forbidden) and top == "mcp_server" and second in forbidden


def check_layer_violation(
    rel_path: str, file_layer: str | None, tree: ast.Module
) -> list[Violation]:
    """Rule 3 — an import that crosses a forbidden layer boundary.

    ``detail`` is the exact dotted module string as written, so two
    different imports never collide, and the same import surviving an
    otherwise-edited file still matches its baseline entry.
    """
    if file_layer not in CHECKED_LAYERS:
        return []
    collector = _ImportCollector()
    collector.visit(tree)
    return [
        Violation(rel_path, "layer-violation", module)
        for module in collector.modules
        if _import_violates_layer(file_layer, module)
    ]
