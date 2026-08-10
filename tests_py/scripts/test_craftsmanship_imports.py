"""Tests for scripts/craftsmanship_imports.py — rule 3 (layer boundaries).

Pins the four checked layers' rules from ``docs/module-inventory.md`` §
Dependency Rules, plus the two AST edge cases the task calls out: a
conditional import under ``if TYPE_CHECKING:`` is exempt, and a relative
import (``from . import x``) never counts as a boundary crossing.
"""

from __future__ import annotations

import ast
import unittest

from tests_py.scripts._craftsmanship_support import craftsmanship_imports as imports_mod


def _find(source: str, file_layer: str):
    tree = ast.parse(source)
    return imports_mod.check_layer_violation("f.py", file_layer, tree)


class LayerViolationTests(unittest.TestCase):
    def test_shared_forbids_third_party_import(self) -> None:
        violations = _find("import numpy\n", "shared")
        self.assertEqual([v.detail for v in violations], ["numpy"])

    def test_shared_allows_stdlib(self) -> None:
        self.assertEqual(_find("import os\nimport re\n", "shared"), [])

    def test_shared_allows_sibling_shared_import(self) -> None:
        self.assertEqual(_find("import mcp_server.shared.text\n", "shared"), [])

    def test_core_forbids_pathlib(self) -> None:
        violations = _find("from pathlib import Path\n", "core")
        self.assertEqual([v.detail for v in violations], ["pathlib"])

    def test_core_forbids_os(self) -> None:
        violations = _find("import os\n", "core")
        self.assertEqual([v.detail for v in violations], ["os"])

    def test_core_forbids_infrastructure_import(self) -> None:
        violations = _find("from mcp_server.infrastructure.pg_store import X\n", "core")
        self.assertEqual(len(violations), 1)

    def test_core_allows_shared_import_and_general_stdlib(self) -> None:
        self.assertEqual(_find("import re\nimport typing\n", "core"), [])
        self.assertEqual(_find("from mcp_server.shared.text import f\n", "core"), [])

    def test_infrastructure_forbids_core_and_handlers(self) -> None:
        self.assertEqual(
            len(_find("from mcp_server.core.x import y\n", "infrastructure")), 1
        )
        self.assertEqual(
            len(_find("from mcp_server.handlers.x import y\n", "infrastructure")), 1
        )

    def test_infrastructure_allows_third_party(self) -> None:
        self.assertEqual(_find("import numpy\n", "infrastructure"), [])

    def test_server_forbids_core_and_infrastructure(self) -> None:
        self.assertEqual(len(_find("from mcp_server.core.x import y\n", "server")), 1)
        self.assertEqual(
            len(_find("from mcp_server.infrastructure.x import y\n", "server")), 1
        )

    def test_server_allows_handlers(self) -> None:
        self.assertEqual(_find("from mcp_server.handlers.x import y\n", "server"), [])

    def test_type_checking_import_is_exempt(self) -> None:
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from mcp_server.infrastructure.pg_store import X\n"
        )
        self.assertEqual(_find(source, "core"), [])

    def test_relative_import_is_exempt(self) -> None:
        self.assertEqual(_find("from . import sibling\n", "core"), [])

    def test_unrelated_layer_is_not_checked(self) -> None:
        # `handlers/` is intentionally outside this gate's four layers.
        self.assertEqual(_find("from mcp_server.core.x import y\n", "handlers"), [])


class LayerOfTests(unittest.TestCase):
    def test_layer_of_resolves_from_repo_relative_path(self) -> None:
        self.assertEqual(
            imports_mod.layer_of("mcp_server/core/wiki_classifier.py"), "core"
        )

    def test_layer_of_none_outside_mcp_server(self) -> None:
        self.assertIsNone(imports_mod.layer_of("scripts/check_craftsmanship.py"))


if __name__ == "__main__":
    unittest.main()
