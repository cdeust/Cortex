"""Tests for scripts/craftsmanship_imports.py — rule 3 (layer boundaries),
a TRUE whitelist over all eight documented layers.

Pins the exact review-round counter-examples that broke the prior
blacklist implementation (`import numpy`, `import requests`, `import
scripts.legacy_bridge` inside `core/`, all previously silent), plus the
boundary-layer symmetry (third-party IS permitted in infrastructure/,
since that is Clean Architecture's adapter layer) and the two AST edge
cases: a conditional import under ``if TYPE_CHECKING:`` is exempt, and a
relative import (``from . import x``) never counts as a boundary crossing.
"""

from __future__ import annotations

import ast
import unittest

from tests_py.scripts._craftsmanship_support import craftsmanship_imports as imports_mod


def _find(source: str, file_layer: str):
    tree = ast.parse(source)
    return imports_mod.check_layer_violation("f.py", file_layer, tree)


class ReviewCounterExampleTests(unittest.TestCase):
    """The exact three imports review confirmed passed silently in core/."""

    def test_numpy_in_core_is_now_caught(self) -> None:
        violations = _find("import numpy\n", "core")
        self.assertEqual([v.detail for v in violations], ["numpy"])

    def test_requests_in_core_is_now_caught(self) -> None:
        violations = _find("import requests\n", "core")
        self.assertEqual([v.detail for v in violations], ["requests"])

    def test_stray_project_package_in_core_is_now_caught(self) -> None:
        violations = _find("import scripts.legacy_bridge\n", "core")
        self.assertEqual([v.detail for v in violations], ["scripts.legacy_bridge"])


class PureLayerTests(unittest.TestCase):
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

    def test_core_forbids_validation_and_errors_too(self) -> None:
        # Not in core/'s whitelist ({"shared"}) even though neither was in
        # the old hardcoded blacklist — the true-whitelist fix's whole point.
        self.assertEqual(
            len(_find("from mcp_server.validation.schemas import X\n", "core")), 1
        )
        self.assertEqual(
            len(_find("from mcp_server.errors import ValidationError\n", "core")), 1
        )

    def test_core_allows_shared_import_and_general_stdlib(self) -> None:
        self.assertEqual(_find("import re\nimport typing\n", "core"), [])
        self.assertEqual(_find("from mcp_server.shared.text import f\n", "core"), [])

    def test_errors_forbids_everything_but_stdlib_ambient(self) -> None:
        self.assertEqual(len(_find("import re\n", "errors")), 1)
        self.assertEqual(
            len(_find("from mcp_server.shared.text import f\n", "errors")), 1
        )
        self.assertEqual(len(_find("import numpy\n", "errors")), 1)


class BoundaryLayerTests(unittest.TestCase):
    """Infrastructure/validation/handlers/server/hooks: adapter layers —
    third-party is the point, not a violation; mcp_server.* cross-refs are
    still a true whitelist.
    """

    def test_infrastructure_allows_third_party(self) -> None:
        self.assertEqual(_find("import numpy\n", "infrastructure"), [])
        self.assertEqual(_find("import psycopg2\n", "infrastructure"), [])

    def test_infrastructure_forbids_core_and_handlers(self) -> None:
        self.assertEqual(
            len(_find("from mcp_server.core.x import y\n", "infrastructure")), 1
        )
        self.assertEqual(
            len(_find("from mcp_server.handlers.x import y\n", "infrastructure")), 1
        )

    def test_validation_allows_shared_and_errors_only(self) -> None:
        self.assertEqual(
            _find("from mcp_server.shared.text import f\n", "validation"), []
        )
        self.assertEqual(
            _find("from mcp_server.errors import ValidationError\n", "validation"), []
        )
        self.assertEqual(
            len(_find("from mcp_server.core.x import y\n", "validation")), 1
        )

    def test_handlers_allows_five_named_layers(self) -> None:
        for layer in ("core", "infrastructure", "shared", "validation", "errors"):
            self.assertEqual(
                _find(f"from mcp_server.{layer}.x import y\n", "handlers"), []
            )
        self.assertEqual(
            len(_find("from mcp_server.server.x import y\n", "handlers")), 1
        )

    def test_server_forbids_core_and_infrastructure(self) -> None:
        self.assertEqual(len(_find("from mcp_server.core.x import y\n", "server")), 1)
        self.assertEqual(
            len(_find("from mcp_server.infrastructure.x import y\n", "server")), 1
        )

    def test_server_allows_handlers(self) -> None:
        self.assertEqual(_find("from mcp_server.handlers.x import y\n", "server"), [])

    def test_hooks_allows_infrastructure_core_shared(self) -> None:
        for layer in ("infrastructure", "core", "shared"):
            self.assertEqual(
                _find(f"from mcp_server.{layer}.x import y\n", "hooks"), []
            )
        self.assertEqual(len(_find("from mcp_server.server.x import y\n", "hooks")), 1)


class AstEdgeCaseTests(unittest.TestCase):
    def test_type_checking_import_is_exempt(self) -> None:
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from mcp_server.infrastructure.pg_store import X\n"
        )
        self.assertEqual(_find(source, "core"), [])

    def test_relative_import_is_exempt(self) -> None:
        self.assertEqual(_find("from . import sibling\n", "core"), [])


class LayerOfTests(unittest.TestCase):
    def test_layer_of_resolves_from_repo_relative_path(self) -> None:
        self.assertEqual(
            imports_mod.layer_of("mcp_server/core/wiki_classifier.py"), "core"
        )

    def test_layer_of_none_outside_mcp_server(self) -> None:
        self.assertIsNone(imports_mod.layer_of("scripts/check_craftsmanship.py"))

    def test_checked_layers_covers_all_eight(self) -> None:
        self.assertEqual(
            imports_mod.CHECKED_LAYERS,
            frozenset(
                {
                    "shared",
                    "core",
                    "infrastructure",
                    "validation",
                    "errors",
                    "handlers",
                    "server",
                    "hooks",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
