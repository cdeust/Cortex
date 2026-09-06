"""Filesystem safety tests operate only on newly created temporary trees."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests_py.scripts._cleanup_fixture import HAS_SAFE_FS, CleanupFixture

import launcher_cleanup
from launcher_cleanup_registry import CleanupScope


@unittest.skipUnless(HAS_SAFE_FS, "platform lacks no-follow descriptor operations")
class TestCleanupFilesystem(CleanupFixture):
    def assert_refused(self) -> None:
        with self.assertLogs("launcher_cleanup", level="WARNING"):
            report = launcher_cleanup.sweep(self.scope, ["orphan@market"], apply=True)
        self.assertTrue(report.refused)
        self.assertFalse(report.removed)

    def test_root_parents_identity_deps_and_registry_symlinks_refuse(self) -> None:
        paths = (
            self.root,
            self.root / "plugins",
            self.scope.data_root,
            self.scope.current_deps.parent,
            self.scope.data_root / "orphan-market",
            self.scope.data_root / "orphan-market/deps",
            self.registry,
            self.root / "settings.json",
        )
        for index, path in enumerate(paths):
            with self.subTest(path=path):
                target = self.workspace / f"link-target-{index}"
                path.rename(target)
                path.symlink_to(target, target_is_directory=target.is_dir())
                self.assert_refused()
                self.assertTrue(target.exists())
                path.unlink()
                target.rename(path)
        self.assertTrue(
            (self.scope.data_root / "orphan-market/deps/fixture.txt").is_file()
        )

    def test_descendant_symlink_refuses_and_leaves_target_untouched(self) -> None:
        target = self.workspace / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        link = self.scope.data_root / "orphan-market/deps/linked.txt"
        link.symlink_to(target)
        self.assert_refused()
        self.assertEqual(target.read_text(), "outside")
        self.assertTrue(link.is_symlink())

    def test_non_directory_deps_refuses_without_deleting_the_file(self) -> None:
        path = self.scope.data_root / "orphan-market/deps"
        path.rename(path.parent / "saved")
        path.write_text("user file", encoding="utf-8")
        self.assert_refused()
        self.assertEqual(path.read_text(), "user file")

    def test_current_path_outside_exact_layout_refuses(self) -> None:
        self.scope = CleanupScope(self.root, self.workspace / "other/deps")
        self.assert_refused()

    def test_python_310_rmtree_signature_refuses_without_call(self) -> None:
        calls = []

        def old_rmtree(path, ignore_errors=False, onerror=None):
            calls.append(path)

        old_rmtree.avoids_symlink_attacks = True
        with patch("launcher_cleanup_fs.shutil.rmtree", old_rmtree):
            with self.assertLogs("launcher_cleanup", level="WARNING"):
                report = launcher_cleanup.sweep(
                    self.scope, ["orphan@market"], apply=True
                )
        self.assertIn("Python 3.11", report.refused[0])
        self.assertFalse(calls)
        self.assertTrue((self.scope.data_root / "orphan-market/deps").is_dir())

    def test_unsafe_rmtree_refuses_without_call(self) -> None:
        calls = []

        def unsafe_rmtree(path, *, dir_fd=None):
            calls.append(path)

        unsafe_rmtree.avoids_symlink_attacks = False
        with patch("launcher_cleanup_fs.shutil.rmtree", unsafe_rmtree):
            with self.assertLogs("launcher_cleanup", level="WARNING"):
                report = launcher_cleanup.sweep(
                    self.scope, ["orphan@market"], apply=True
                )
        self.assertIn("symlink-resistant", report.refused[0])
        self.assertFalse(calls)

    def test_unsupported_platform_refuses_explicitly(self) -> None:
        with patch("launcher_cleanup_fs.os.supports_dir_fd", set()):
            with self.assertLogs("launcher_cleanup", level="WARNING"):
                report = launcher_cleanup.sweep(self.scope, [])
        self.assertIn("descriptor-relative", report.refused[0])

    def test_removal_error_is_reported_without_success_claim(self) -> None:
        with patch("launcher_cleanup.require_removal_support"):
            with patch(
                "launcher_cleanup.remove_deps", side_effect=PermissionError("denied")
            ):
                self.assert_refused()


if __name__ == "__main__":
    unittest.main()
