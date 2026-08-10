"""Tests for scripts/marketplace_pins_registry.py — the public MCP registry
cross-check (REGISTRY_VERSION_STALE). Split out as its own test file
(same rationale as test_check_marketplace_pins_sha_manifest.py: keeps each
test file under the 300-line §4.1 cap); same `gate` module instance via
_marketplace_pins_test_loader.py.
"""

from __future__ import annotations

import unittest
import urllib.error

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
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as d:
            self.assertEqual(gate.check_registry_surface(Path(d), "1.0.0"), ([], []))

    def test_missing_name_field_is_not_a_failure(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"version": "1.0.0"}))
            self.assertEqual(gate.check_registry_surface(root, "1.0.0"), ([], []))


if __name__ == "__main__":
    unittest.main()
