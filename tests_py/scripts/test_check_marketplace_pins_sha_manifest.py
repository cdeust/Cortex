"""Tests for scripts/check_marketplace_pins.py — sha reachability + root
manifest split checks. Split out of test_check_marketplace_pins.py (issue:
that file crossed the 300-line §4.1 cap once PIN_VERSION_UNPUBLISHED
coverage was added); same `gate` module instance via
_marketplace_pins_test_loader.py.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

from tests_py.scripts._marketplace_pins_test_loader import gate


class TestPinShaReachability(unittest.TestCase):
    """PIN_SHA_UNREACHABLE — a pinned commit must live on the default branch."""

    @staticmethod
    def _probe(status):
        return dict(branch=lambda r: "main", compare=lambda r, b, h: status)

    def test_identical_and_behind_pass(self):
        for status in ("identical", "behind"):
            with self.subTest(status=status):
                self.assertEqual(
                    gate.check_pin_sha("p", "o/r", "a" * 40, **self._probe(status)),
                    (None, None),
                )

    def test_ahead_is_the_cortex_351_incident(self):
        # Regression: Cortex #351 pinned cortex-viz at an unmerged PR head
        # twice (ee0d41db, then 7e297ebc), both `ahead` of main.
        failure, notice = gate.check_pin_sha(
            "hypermnesia-mcp-viz",
            "cdeust/cortex-viz",
            "7e297ebc31af3f4be0a5d06974c7f11a72070b99",
            **self._probe("ahead"),
        )
        self.assertIn("PIN_SHA_UNREACHABLE", failure)
        self.assertIn("7e297ebc31af", failure)
        self.assertIn("main", failure)
        self.assertIsNone(notice)

    def test_diverged_flagged(self):
        failure, _ = gate.check_pin_sha("p", "o/r", "b" * 40, **self._probe("diverged"))
        self.assertIn("PIN_SHA_UNREACHABLE", failure)

    def test_absent_commit_flagged_not_crashed(self):
        failure, notice = gate.check_pin_sha("p", "o/r", "c" * 40, **self._probe(None))
        self.assertIn("PIN_SHA_UNREACHABLE", failure)
        self.assertIn("absent", failure)
        self.assertIsNone(notice)

    def test_unknown_repo_degrades_to_notice(self):
        failure, notice = gate.check_pin_sha(
            "p", "o/r", "d" * 40, branch=lambda r: None, compare=lambda *a: "ahead"
        )
        self.assertIsNone(failure)  # fail-open, same contract as the version path
        self.assertIn("does not resolve", notice)

    def test_network_failure_degrades_to_notice(self):
        def down(_repo):
            raise urllib.error.URLError("offline")

        failure, notice = gate.check_pin_sha("p", "o/r", "e" * 40, branch=down)
        self.assertIsNone(failure)
        self.assertIn("network degraded", notice)

    def test_compare_outage_degrades_to_notice(self):
        def down(*_a):
            raise TimeoutError("slow")

        failure, notice = gate.check_pin_sha(
            "p", "o/r", "f" * 40, branch=lambda r: "main", compare=down
        )
        self.assertIsNone(failure)
        self.assertIn("network degraded", notice)


class TestRootManifestSplit(unittest.TestCase):
    def test_three_way_split_third_leg_flagged(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"version": "0.8.2"}))
            issues = gate.check_root_manifests(root, "0.8.0")
            self.assertTrue(any("SERVER_JSON_SPLIT" in i for i in issues))

    def test_ap_172_incident_replay_manifest_json_two_releases_stale(self):
        """The exact tree that exited 0 before this check existed.

        ai-architect-mcp-codebase carried manifest.json 0.8.0 while server.json and
        every marketplace pin read 0.8.2. The gate passed, and the wrong
        version shipped inside every .mcpb bundle for two releases.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"version": "0.8.2"}))
            (root / "manifest.json").write_text(json.dumps({"version": "0.8.0"}))
            issues = gate.check_root_manifests(root, "0.8.2")
            self.assertEqual(len(issues), 1, issues)
            self.assertIn("MANIFEST_JSON_SPLIT", issues[0])
            self.assertIn("0.8.0", issues[0])

    def test_both_stale_are_reported_separately(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "server.json").write_text(json.dumps({"version": "0.8.1"}))
            (root / "manifest.json").write_text(json.dumps({"version": "0.8.0"}))
            issues = gate.check_root_manifests(root, "0.8.2")
            self.assertEqual(len(issues), 2, issues)

    def test_aligned_passes_and_absent_passes(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            # Absent: the canonical repo has neither file — not a failure.
            self.assertEqual(gate.check_root_manifests(root, "0.8.2"), [])
            (root / "server.json").write_text(json.dumps({"version": "0.8.2"}))
            (root / "manifest.json").write_text(json.dumps({"version": "0.8.2"}))
            self.assertEqual(gate.check_root_manifests(root, "0.8.2"), [])

    def test_missing_version_key_is_not_a_failure(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "manifest.json").write_text(json.dumps({"name": "x"}))
            self.assertEqual(gate.check_root_manifests(root, "0.8.2"), [])


if __name__ == "__main__":
    unittest.main()
