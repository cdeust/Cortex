"""Tests for scripts/check_marketplace_pins.py — pin-staleness gate (#179).

Written unittest-style on purpose: the byte-identical AP copy runs them via
plain `python3 -m unittest` (no pytest there); Cortex's pytest collects
unittest classes natively.

Split into three files (issue: this file crossed the 300-line §4.1 cap once
PIN_VERSION_UNPUBLISHED coverage was added) — sha/reachability and root-
manifest-split coverage moved to
test_check_marketplace_pins_sha_manifest.py, same `gate` module instance via
_marketplace_pins_test_loader.py.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from tempfile import TemporaryDirectory

from tests_py.scripts._marketplace_pins_legacy_replay import (
    LegacyGithubFetchers,
    pre_fix_check_github_pin,
    pre_fix_check_self_pin,
)
from tests_py.scripts._marketplace_pins_test_loader import gate, git_repo_with_tags


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
            root = git_repo_with_tags(d, ["v0.7.0", "v0.8.0", "v0.8.1", "v0.8.2"])
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
            root = git_repo_with_tags(d, ["v0.8.2"])
            plug = root / ".claude-plugin"
            plug.mkdir()
            (plug / "plugin.json").write_text(json.dumps({"version": "0.8.2"}))
            self.assertEqual(gate.check_self_pin("ap", "./", "0.8.2", root), [])

    def test_untagged_repo_no_crash_no_flag(self):
        with TemporaryDirectory() as d:
            root = git_repo_with_tags(d, [])
            self.assertEqual(gate.check_self_pin("p", "./", "1.0.0", root), [])

    def test_pin_ahead_of_every_tag_is_unpublished_not_silently_current(self):
        """The generic form of the cortex-viz 3.0.0 incident, on a self-pin —
        replayed through BOTH the frozen pre-fix `check_self_pin` and the
        current one on identical inputs, not just asserted in prose.
        """
        with TemporaryDirectory() as d:
            root = git_repo_with_tags(d, ["v2.8.0", "v2.7.1", "v2.7.0"])

            # BEFORE: a pin newer than the latest tag read as "current" (the
            # old check only ever asked "is pin < latest?"; it never asked
            # "does a tag matching pin exist at all?").
            pre_fix_failures = pre_fix_check_self_pin("p", "./", "3.0.0", root)
            self.assertEqual(
                pre_fix_failures, [], "the historical defect: silently current"
            )

            # AFTER: this is the exact defect PIN_VERSION_UNPUBLISHED closes.
            failures = gate.check_self_pin("p", "./", "3.0.0", root)
            joined = "\n".join(failures)
            self.assertIn("PIN_VERSION_UNPUBLISHED", joined)
            self.assertIn("no matching tag", joined)
            self.assertIn("2.8.0", joined)  # latest real tag, named for the reader
            self.assertNotIn("PIN_BEHIND_TAG", joined)  # not a staleness case

    def test_frozen_pin_skips_tag_check_keeps_coherence(self):
        with TemporaryDirectory() as d:
            root = git_repo_with_tags(d, ["v4.16.0"])
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
        tags = [
            "v2.28.0",
            "v2.29.0",
            "v2.30.0",
            "v2.31.0",
            "v2.32.0",
            "v2.33.0",
            "v2.34.0",
        ]
        failure, notice = gate.check_github_pin(
            "p", "o/r", "2.28.0", list_tags=lambda r: tags
        )
        self.assertIn("PIN_BEHIND_RELEASE", failure)
        self.assertIn("6 release(s)", failure)  # v2.29.0..v2.34.0
        self.assertIsNone(notice)

    def test_current_pin_passes(self):
        tags = ["v2.29.0", "v2.34.0"]
        self.assertEqual(
            gate.check_github_pin("p", "o/r", "2.34.0", list_tags=lambda r: tags),
            (None, None),
        )

    def test_incident_replay_pin_ahead_of_every_release_is_unpublished(self):
        """The exact cortex-viz incident, replayed through BOTH the frozen
        pre-fix logic and the current one on the identical historical
        inputs — not just asserted in prose. Pin "3.0.0", repo's real tags
        top out at v2.8.0.
        """
        tags = ["v2.8.0", "v2.7.1", "v2.7.0", "v2.6.3"]

        # BEFORE: `3.0.0 < 2.8.0` is false, so the pre-fix check (which only
        # ever asked "is pin behind latest?") read this as current — silent
        # pass, six days of a dangling pin, zero red runs.
        pre_fix_result = pre_fix_check_github_pin(
            "hypermnesia-mcp-viz",
            "cdeust/cortex-viz",
            "3.0.0",
            LegacyGithubFetchers(fetch=lambda r: "v2.8.0", count=lambda *a: 0),
        )
        self.assertEqual(
            pre_fix_result,
            (None, None),
            "the historical defect: silently current, not a red run",
        )

        # AFTER: the same inputs (repo's tags list rather than a single
        # "latest" fetch — the new signature) through the current check.
        failure, notice = gate.check_github_pin(
            "hypermnesia-mcp-viz",
            "cdeust/cortex-viz",
            "3.0.0",
            list_tags=lambda r: tags,
            pending={},  # no pending exemption active for this assertion
        )
        self.assertIsNotNone(failure, "must not silently pass — this is the incident")
        self.assertIn("PIN_VERSION_UNPUBLISHED", failure)
        self.assertIn("no matching", failure)
        self.assertIn("v2.8.0", failure)  # names the real latest, for the reader
        self.assertIsNone(notice)

    def test_pending_pin_degrades_unpublished_to_named_notice(self):
        """A pin correctly flagged unpublished, but the release is genuinely
        in flight (tracked by an open upstream PR) — not silence: a NOTICE
        that names the tracking reference, still printed every run.
        """
        tags = ["v2.8.0"]
        failure, notice = gate.check_github_pin(
            "hypermnesia-mcp-viz",
            "cdeust/cortex-viz",
            "3.1.0",
            list_tags=lambda r: tags,
            pending={"hypermnesia-mcp-viz": "cdeust/cortex-viz#130"},
        )
        self.assertIsNone(failure)
        self.assertIn("PENDING", notice)
        self.assertIn("cortex-viz#130", notice)

    def test_network_failure_degrades_to_notice(self):
        def down(_repo):
            raise urllib.error.URLError("offline")

        failure, notice = gate.check_github_pin("p", "o/r", "2.29.0", list_tags=down)
        self.assertIsNone(failure)  # fail-open: no red run from an outage
        self.assertIn("network degraded", notice)

    def test_no_releases_repo_is_notice_not_keyerror(self):
        failure, notice = gate.check_github_pin(
            "p", "o/r", "1.0.0", list_tags=lambda r: None
        )
        self.assertIsNone(failure)
        self.assertIn("no published releases", notice)

    def test_unpublishable_pin_reported(self):
        failure, _ = gate.check_github_pin(
            "p", "o/r", "not-a-version", list_tags=lambda r: ["v1.0.0"]
        )
        self.assertIn("UNPARSEABLE", failure)

    def test_repo_with_only_unparseable_tags_reported(self):
        failure, _ = gate.check_github_pin(
            "p", "o/r", "1.0.0", list_tags=lambda r: ["nightly"]
        )
        self.assertIn("UNPARSEABLE", failure)


if __name__ == "__main__":
    unittest.main()
