"""Tests for scripts/check_marketplace_pins.py — pin-staleness gate (#179).

Written unittest-style on purpose: the byte-identical AP copy runs them via
plain `python3 -m unittest` (no pytest there); Cortex's pytest collects
unittest classes natively.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.check_marketplace_pins.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.check_marketplace_pins",
    Path(__file__).resolve().parents[2] / "scripts" / "check_marketplace_pins.py",
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _git_repo_with_tags(root: str, tags: list[str]) -> Path:
    p = Path(root)
    subprocess.run(["git", "-C", root, "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", root, "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )
    for t in tags:
        subprocess.run(["git", "-C", root, "tag", t], check=True)
    return p


class TestParseSemver(unittest.TestCase):
    def test_v_prefix_and_bare(self):
        self.assertEqual(gate.parse_semver("v2.34.0"), (2, 34, 0))
        self.assertEqual(gate.parse_semver("2.7.1"), (2, 7, 1))

    def test_non_semver_none(self):
        self.assertIsNone(gate.parse_semver("nightly"))
        self.assertIsNone(gate.parse_semver("2.34"))

    def test_numeric_not_lexicographic(self):
        self.assertLess(gate.parse_semver("2.9.0"), gate.parse_semver("2.10.0"))


class TestPinBehindTag(unittest.TestCase):
    """The review's replay: both manifests agree AND both are stale (#67)."""

    def test_legacy_publication_identities_are_explicitly_frozen(self):
        self.assertEqual(
            gate.FROZEN_PINS,
            {
                "cortex": "deprecation shim, frozen at the 4.15.0 rename release",
                "cortex-viz": (
                    "deprecation shim, frozen at the 2.8.0 pre-rename release"
                ),
            },
        )

    def test_incident_replay_both_manifests_stale_tag_ahead(self):
        with TemporaryDirectory() as d:
            root = _git_repo_with_tags(d, ["v0.7.0", "v0.8.0", "v0.8.1", "v0.8.2"])
            plug = root / ".claude-plugin"
            plug.mkdir()
            (plug / "plugin.json").write_text(json.dumps({"version": "0.8.0"}))
            failures = gate.check_self_pin("ap", "./", "0.8.0", root)
            joined = "\n".join(failures)
            self.assertIn("PIN_BEHIND_TAG", joined)  # detection ORIGINATES here
            self.assertNotIn("SELF_PIN_MISMATCH", joined)  # manifests agree
            self.assertIn("2 release(s)", joined)  # v0.8.1 + v0.8.2 counted

    def test_current_pin_green(self):
        with TemporaryDirectory() as d:
            root = _git_repo_with_tags(d, ["v0.8.2"])
            plug = root / ".claude-plugin"
            plug.mkdir()
            (plug / "plugin.json").write_text(json.dumps({"version": "0.8.2"}))
            self.assertEqual(gate.check_self_pin("ap", "./", "0.8.2", root), [])

    def test_untagged_repo_no_crash_no_flag(self):
        with TemporaryDirectory() as d:
            root = _git_repo_with_tags(d, [])
            self.assertEqual(gate.check_self_pin("p", "./", "1.0.0", root), [])

    def test_frozen_pin_skips_tag_check_keeps_coherence(self):
        with TemporaryDirectory() as d:
            root = _git_repo_with_tags(d, ["v4.16.0"])
            shim = root / "shim" / ".claude-plugin"
            shim.mkdir(parents=True)
            (shim / "plugin.json").write_text(json.dumps({"version": "4.15.0"}))
            gate.FROZEN_PINS["frozen-test"] = "test"
            try:
                self.assertEqual(
                    gate.check_self_pin("frozen-test", "shim", "4.15.0", root), []
                )
                (shim / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
                failures = gate.check_self_pin("frozen-test", "shim", "4.15.0", root)
                self.assertIn("SELF_PIN_MISMATCH", "\n".join(failures))
            finally:
                gate.FROZEN_PINS.pop("frozen-test")


class TestGithubPin(unittest.TestCase):
    def test_stale_flagged_with_count(self):
        failure, notice = gate.check_github_pin(
            "p", "o/r", "2.29.0", fetch=lambda r: "v2.34.0", count=lambda *a: 6
        )
        self.assertIn("PIN_BEHIND_RELEASE", failure)
        self.assertIn("6 release(s)", failure)
        self.assertIsNone(notice)

    def test_stale_flagged_count_degraded(self):
        failure, _ = gate.check_github_pin(
            "p", "o/r", "2.29.0", fetch=lambda r: "v2.34.0", count=lambda *a: None
        )
        self.assertIn("PIN_BEHIND_RELEASE", failure)
        self.assertNotIn("None", failure)

    def test_current_and_ahead_pass(self):
        self.assertEqual(
            gate.check_github_pin("p", "o/r", "2.34.0", fetch=lambda r: "v2.34.0"),
            (None, None),
        )
        self.assertEqual(
            gate.check_github_pin("p", "o/r", "2.35.0", fetch=lambda r: "v2.34.0"),
            (None, None),
        )

    def test_network_failure_degrades_to_notice(self):
        def down(_repo):
            raise urllib.error.URLError("offline")

        failure, notice = gate.check_github_pin("p", "o/r", "2.29.0", fetch=down)
        self.assertIsNone(failure)  # fail-open: no red run from an outage
        self.assertIn("network degraded", notice)

    def test_no_releases_repo_is_notice_not_keyerror(self):
        failure, notice = gate.check_github_pin(
            "p", "o/r", "1.0.0", fetch=lambda r: None
        )
        self.assertIsNone(failure)
        self.assertIn("no published releases", notice)

    def test_unparseable_tag_reported(self):
        failure, _ = gate.check_github_pin(
            "p", "o/r", "1.0.0", fetch=lambda r: "nightly"
        )
        self.assertIn("UNPARSEABLE", failure)


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

        automatised-pipeline carried manifest.json 0.8.0 while server.json and
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
