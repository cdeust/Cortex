"""Tests for scripts/marketplace_pins_registry.py — the public MCP registry
cross-check (REGISTRY_VERSION_STALE). Split out as its own test file
(same rationale as test_check_marketplace_pins_sha_manifest.py: keeps each
test file under the 300-line §4.1 cap); same `gate` module instance via
_marketplace_pins_test_loader.py.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

from tests_py.scripts._marketplace_pins_test_loader import gate


class TestRegistryVersion(unittest.TestCase):
    def test_current_passes(self):
        entries = [("io.github.cdeust/hypermnesia-mcp", "4.17.2", True)]
        self.assertEqual(
            gate.check_registry_version(
                "io.github.cdeust/hypermnesia-mcp",
                "4.17.2",
                list_versions=lambda s: entries,
                pending={},
            ),
            (None, None),
        )

    def test_incident_replay_registry_behind_repo_is_flagged(self):
        """The exact incident: registry serves 4.17.1, repo (tag/server.json/
        PyPI) is already 4.17.2 — measured 2026-08-10, no CI gate caught it
        because nothing read this surface before this check existed.
        """
        entries = [("io.github.cdeust/hypermnesia-mcp", "4.17.1", True)]
        failure, notice = gate.check_registry_version(
            "io.github.cdeust/hypermnesia-mcp",
            "4.17.2",
            list_versions=lambda s: entries,
            pending={},
        )
        self.assertIn("REGISTRY_VERSION_STALE", failure)
        self.assertIn("4.17.1", failure)
        self.assertIn("4.17.2", failure)
        self.assertIsNone(notice)

    def test_registry_ahead_of_repo_is_also_flagged(self):
        """Equality, not "behind": a registry entry ahead of the repo is a
        republish of a version this repo never tagged — just as false.
        """
        entries = [("io.github.cdeust/hypermnesia-mcp", "5.0.0", True)]
        failure, _ = gate.check_registry_version(
            "io.github.cdeust/hypermnesia-mcp",
            "4.17.2",
            list_versions=lambda s: entries,
            pending={},
        )
        self.assertIn("REGISTRY_VERSION_STALE", failure)

    def test_pending_degrades_to_named_notice(self):
        entries = [("io.github.cdeust/hypermnesia-mcp", "4.17.1", True)]
        failure, notice = gate.check_registry_version(
            "io.github.cdeust/hypermnesia-mcp",
            "4.17.2",
            list_versions=lambda s: entries,
            pending={"io.github.cdeust/hypermnesia-mcp": "release.yml (tracked)"},
        )
        self.assertIsNone(failure)
        self.assertIn("PENDING", notice)
        self.assertIn("release.yml", notice)

    def test_no_is_latest_entry_is_notice_not_crash(self):
        entries = [("io.github.cdeust/hypermnesia-mcp", "4.17.1", False)]
        failure, notice = gate.check_registry_version(
            "io.github.cdeust/hypermnesia-mcp",
            "4.17.2",
            list_versions=lambda s: entries,
            pending={},
        )
        self.assertIsNone(failure)
        self.assertIn("no 'latest' entry", notice)

    def test_not_found_is_notice_not_crash(self):
        failure, notice = gate.check_registry_version(
            "io.github.cdeust/nonexistent",
            "1.0.0",
            list_versions=lambda s: None,
            pending={},
        )
        self.assertIsNone(failure)
        self.assertIn("not found", notice)

    def test_network_failure_degrades_to_notice(self):
        def down(_search):
            raise urllib.error.URLError("offline")

        failure, notice = gate.check_registry_version(
            "io.github.cdeust/hypermnesia-mcp", "4.17.2", list_versions=down
        )
        self.assertIsNone(failure)
        self.assertIn("network degraded", notice)


class TestRegistrySurface(unittest.TestCase):
    def test_absent_server_json_is_not_a_failure(self):
        with TemporaryDirectory() as d:
            self.assertEqual(gate.check_registry_surface(Path(d), "1.0.0"), ([], []))

    def test_missing_name_field_skips_version_check_not_schema_check(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(
                json.dumps({"version": "1.0.0", "description": "A valid description."})
            )
            self.assertEqual(gate.check_registry_surface(root, "1.0.0"), ([], []))


class TestServerJsonSchema(unittest.TestCase):
    """SERVER_JSON_DESCRIPTION_TOO_LONG/TOO_SHORT — offline, schema-derived
    (maxLength=100, minLength=1, both read live from
    https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
    2026-08-10). Distinct defect class from REGISTRY_VERSION_STALE: a
    server.json can have the exactly-correct version and still be
    unpublishable (422) because of an unrelated schema field.
    """

    def test_absent_server_json_is_not_a_failure(self):
        with TemporaryDirectory() as d:
            self.assertEqual(gate.check_server_json_schema(Path(d)), [])

    def test_compliant_description_passes(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"description": "x" * 100}))
            self.assertEqual(gate.check_server_json_schema(root), [])

    def test_incident_replay_144_char_description_never_publishable(self):
        """The neighboring incident this check exists to close: a 422 at
        publish time (ai-architect-mcp-codebase v0.9.1, 144-char
        description) that could never be recovered from once tagged — the
        fix landed on `main` only, not in the tagged tree. This test
        proves the check fires BEFORE a tag would ever be cut.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            description = "x" * 144
            (root / "server.json").write_text(json.dumps({"description": description}))
            failures = gate.check_server_json_schema(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("SERVER_JSON_DESCRIPTION_TOO_LONG", failures[0])
            self.assertIn("144", failures[0])
            self.assertIn("100", failures[0])

    def test_off_by_one_boundary(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"description": "x" * 101}))
            failures = gate.check_server_json_schema(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("TOO_LONG", failures[0])

    def test_empty_description_fails(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"description": ""}))
            failures = gate.check_server_json_schema(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("SERVER_JSON_DESCRIPTION_TOO_SHORT", failures[0])

    def test_missing_description_key_fails(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"name": "x"}))
            failures = gate.check_server_json_schema(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("SERVER_JSON_DESCRIPTION_TOO_SHORT", failures[0])

    def test_real_current_server_json_is_compliant(self):
        """Not a fixture — the actual committed server.json this PR ships.
        Direct verification requested by review: fetched-at-tag v4.17.2 was
        ALREADY compliant (95 chars, pre-dating this PR); this asserts the
        working-tree copy this PR carries (98 chars) also is, which is what
        the NEXT tag will publish.
        """
        repo_root = Path(__file__).resolve().parents[2]
        failures = gate.check_server_json_schema(repo_root)
        self.assertEqual(failures, [], "server.json must stay registry-publishable")


if __name__ == "__main__":
    unittest.main()
