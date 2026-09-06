"""Bounded stdlib tests: conservative classification and owner-only removal."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests_py.scripts._cleanup_fixture import (
    HAS_SAFE_FS,
    HAS_SAFE_REMOVE,
    CleanupFixture,
)

import launcher_cleanup
from launcher_cleanup_fs import CleanupRefusedError
from launcher_cleanup_registry import identity


@unittest.skipUnless(HAS_SAFE_FS, "platform lacks no-follow descriptor operations")
class TestCleanupAudit(CleanupFixture):
    def test_audit_preserves_installed_enabled_disabled_and_current(self) -> None:
        before = self.all_deps()
        report = launcher_cleanup.sweep(self.scope, [])
        self.assertFalse(report.refused)
        self.assertEqual(before, self.all_deps())
        self.assertEqual(len(report.protected), 4)
        self.assertEqual(len(report.indeterminate), 3)
        self.assertFalse(report.candidates)
        self.assertFalse(report.removed)

    def test_explicit_identity_dry_run_lists_candidate_without_deletion(self) -> None:
        before = self.all_deps()
        report = launcher_cleanup.sweep(self.scope, ["orphan@market"])
        self.assertEqual(
            report.candidates, [str(self.scope.data_root / "orphan-market/deps")]
        )
        self.assertEqual(before, self.all_deps())
        self.assertFalse(report.refused)
        self.assertFalse(report.removed)

    @unittest.skipUnless(HAS_SAFE_REMOVE, "safe removal needs Python 3.11+")
    def test_apply_removes_only_selected_deps_and_retains_user_data(self) -> None:
        before = self.all_deps()
        orphan = self.scope.data_root / "orphan-market/deps"
        report = launcher_cleanup.sweep(self.scope, ["orphan@market"], apply=True)
        self.assertFalse(report.refused)
        self.assertEqual(report.removed, [str(orphan)])
        self.assertEqual(self.all_deps(), [path for path in before if path != orphan])
        self.assertEqual((orphan.parent / "keep.json").read_text(), "user data")

    def test_apply_without_explicit_identity_refuses(self) -> None:
        before = self.all_deps()
        with self.assertLogs("launcher_cleanup", level="WARNING") as logs:
            report = launcher_cleanup.sweep(self.scope, [], apply=True)
        self.assertIn("owner-verified --plugin-id", report.refused[0])
        self.assertIn("refused", logs.output[0])
        self.assertEqual(before, self.all_deps())

    def test_protected_and_unregistered_selections_refuse(self) -> None:
        before = self.all_deps()
        for plugin in (
            "current@market",
            "installed@market",
            "enabled@market",
            "disabled@market",
            "scratch@inline",
            "cloud@synced",
            "absent@market",
        ):
            with self.subTest(plugin=plugin), self.assertLogs("launcher_cleanup"):
                report = launcher_cleanup.sweep(self.scope, [plugin], apply=True)
                self.assertTrue(report.refused)
                self.assertFalse(report.removed)
        self.assertEqual(before, self.all_deps())

    @unittest.skipUnless(HAS_SAFE_REMOVE, "safe removal needs Python 3.11+")
    def test_registry_changed_after_audit_prevents_removal(self) -> None:
        original = launcher_cleanup.protections
        calls = []

        def changed(scope):
            calls.append(scope)
            if len(calls) > 1:
                self.write(
                    self.root / "settings.json",
                    {"enabledPlugins": {"orphan@market": False}},
                )
            return original(scope)

        with patch.object(launcher_cleanup, "protections", side_effect=changed):
            with self.assertLogs("launcher_cleanup"):
                report = launcher_cleanup.sweep(
                    self.scope, ["orphan@market"], apply=True
                )
        self.assertIn("became protected", report.refused[0])
        self.assertTrue((self.scope.data_root / "orphan-market/deps").is_dir())

    def test_non_deps_sibling_directory_is_not_removed(self) -> None:
        extra = self.scope.data_root / "no-deps-market"
        extra.mkdir()
        (extra / "personal.txt").write_text("keep", encoding="utf-8")
        (self.scope.data_root / "personal.txt").write_text(
            "root file", encoding="utf-8"
        )
        report = launcher_cleanup.sweep(self.scope, [])
        self.assertFalse(report.refused)
        self.assertEqual((extra / "personal.txt").read_text(), "keep")
        self.assertEqual(
            (self.scope.data_root / "personal.txt").read_text(), "root file"
        )


class TestIdentityMapping(unittest.TestCase):
    def test_official_documentation_examples_and_punctuation(self) -> None:
        self.assertEqual(
            identity("formatter@my-marketplace"), "formatter-my-marketplace"
        )
        self.assertEqual(
            identity("my.plugin@my_marketplace"), "my-plugin-my_marketplace"
        )

    def test_unsupported_identifier_refuses(self) -> None:
        for value in ("missing-market", "@market", "plugin@", "a@b@c", "a b@market"):
            with self.subTest(value=value), self.assertRaises(CleanupRefusedError):
                identity(value)


if __name__ == "__main__":
    unittest.main()
