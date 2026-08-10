"""Tests for scripts/craftsmanship_layer_table.py — the § Dependency Rules
table parser (DRY fix: this is now the single source of truth, never a
second hardcoded copy in craftsmanship_imports.py).
"""

from __future__ import annotations

import unittest

from tests_py.scripts._craftsmanship_support import craftsmanship_layer_table as lt

_TABLE = """# Module Inventory

## Dependency Rules

| Layer | May Import | Must NOT Import |
|---|---|---|
| **shared/** | Python stdlib only | core, infrastructure, handlers, server |
| **core/** | shared/ only | infrastructure, handlers, server, os/pathlib |
| **infrastructure/** | shared/, Python stdlib | core, handlers, server |
| **validation/** | shared/, errors/ | core, infrastructure, handlers |
| **errors/** | nothing | everything |
| **handlers/** | core, infrastructure, shared, validation, errors | server |
| **server/** | handlers, errors | core, infrastructure (except via handlers) |
| **hooks/** | infrastructure, core, shared | server |

## Next section
not a table row
"""


class ParseLayerRulesTests(unittest.TestCase):
    def test_parses_all_eight_layers(self) -> None:
        rules = lt.parse_layer_rules(_TABLE)
        self.assertEqual(
            set(rules),
            {
                "shared",
                "core",
                "infrastructure",
                "validation",
                "errors",
                "handlers",
                "server",
                "hooks",
            },
        )

    def test_shared_is_pure_stdlib_only(self) -> None:
        rule = lt.parse_layer_rules(_TABLE)["shared"]
        self.assertTrue(rule.is_pure)
        self.assertTrue(rule.stdlib_allowed)
        self.assertEqual(rule.allowed_layers, frozenset())

    def test_core_allows_stdlib_except_os_pathlib(self) -> None:
        rule = lt.parse_layer_rules(_TABLE)["core"]
        self.assertTrue(rule.is_pure)
        self.assertTrue(rule.stdlib_allowed)
        self.assertEqual(rule.stdlib_denied, frozenset({"os", "pathlib"}))
        self.assertEqual(rule.allowed_layers, frozenset({"shared"}))

    def test_infrastructure_is_a_boundary_layer(self) -> None:
        rule = lt.parse_layer_rules(_TABLE)["infrastructure"]
        self.assertFalse(rule.is_pure)
        self.assertTrue(rule.stdlib_allowed)
        self.assertEqual(rule.allowed_layers, frozenset({"shared"}))

    def test_errors_allows_nothing(self) -> None:
        rule = lt.parse_layer_rules(_TABLE)["errors"]
        self.assertTrue(rule.is_pure)
        self.assertFalse(rule.stdlib_allowed)
        self.assertEqual(rule.allowed_layers, frozenset())

    def test_server_strips_parenthetical_note(self) -> None:
        # "core, infrastructure (except via handlers)" in Must NOT Import
        # must not leak "(except via handlers)" into a layer name — it is
        # not consulted by this parser (allowed_layers comes from May
        # Import only), but must not crash or corrupt stdlib_denied either.
        rule = lt.parse_layer_rules(_TABLE)["server"]
        self.assertEqual(rule.stdlib_denied, frozenset())
        self.assertEqual(rule.allowed_layers, frozenset({"handlers", "errors"}))

    def test_missing_header_raises(self) -> None:
        with self.assertRaises(ValueError):
            lt.parse_layer_rules("no table here")

    def test_header_with_no_rows_raises(self) -> None:
        broken = "| Layer | May Import | Must NOT Import |\n|---|---|---|\nnot a row\n"
        with self.assertRaises(ValueError):
            lt.parse_layer_rules(broken)

    def test_the_real_repository_table_parses(self) -> None:
        # Live integration check: the actual docs/module-inventory.md must
        # parse without error — a malformed table must fail LOUDLY (an
        # exception at import time), never silently under-enforce.
        rules = lt.load_layer_rules()
        self.assertIn("core", rules)
        self.assertIn("shared", rules)


if __name__ == "__main__":
    unittest.main()
