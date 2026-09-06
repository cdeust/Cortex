"""Registry failures must not convert incomplete knowledge into uninstallation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests_py.scripts._cleanup_fixture import HAS_SAFE_FS, CleanupFixture

import launcher_cleanup


@unittest.skipUnless(HAS_SAFE_FS, "platform lacks no-follow descriptor operations")
class TestCleanupRegistry(CleanupFixture):
    def assert_refused(self, expected: str = "") -> None:
        before = self.all_deps()
        with self.assertLogs("launcher_cleanup", level="WARNING"):
            report = launcher_cleanup.sweep(self.scope, ["orphan@market"], apply=True)
        self.assertTrue(report.refused)
        self.assertIn(expected, report.refused[0])
        self.assertFalse(report.removed)
        self.assertEqual(before, self.all_deps())

    def add_project(self) -> None:
        self.project = self.workspace / "project"
        self.installs["project@market"] = [
            {
                **self.install_record("project"),
                "projectPath": str(self.project),
            }
        ]
        self.write(self.registry, {"plugins": self.installs})
        self.write(
            self.project / ".claude/settings.json",
            {"enabledPlugins": {"orphan@market": False}},
        )
        self.write(
            self.project / ".claude/settings.local.json",
            {"enabledPlugins": {"local@market": True}},
        )
        self.make_deps("local@market")

    def test_project_and_local_settings_protect_all_references(self) -> None:
        self.add_project()
        report = launcher_cleanup.sweep(self.scope, [])
        self.assertFalse(report.refused)
        self.assertIn(
            str(self.scope.data_root / "orphan-market/deps"), report.protected
        )
        self.assertIn(str(self.scope.data_root / "local-market/deps"), report.protected)

    def test_missing_registry_or_global_settings_refuses(self) -> None:
        for path in (self.registry, self.root / "settings.json"):
            contents = path.read_bytes()
            path.unlink()
            self.assert_refused("No such file")
            path.write_bytes(contents)

    def test_invalid_json_unicode_duplicate_keys_and_nonobject_refuse(self) -> None:
        for contents in (b"{", b"\xff", b"[]", b'{"plugins":{},"plugins":{}}'):
            with self.subTest(contents=contents):
                self.registry.write_bytes(contents)
                self.assert_refused()

    def test_incomplete_registry_entries_refuse(self) -> None:
        invalid = (
            {},
            {"plugins": []},
            {"plugins": {"orphan@market": []}},
            {"plugins": {"orphan@market": [None]}},
            {
                "plugins": {
                    "orphan@market": [{"installPath": "relative", "scope": "user"}]
                }
            },
        )
        for value in invalid:
            with self.subTest(value=value):
                self.write(self.registry, value)
                self.assert_refused()

    def test_unknown_missing_and_invalid_scope_refuse(self) -> None:
        for scope in (None, "managed", "unknown", {}, []):
            with self.subTest(scope=scope):
                record = {**self.install_record(), "scope": scope}
                self.write(self.registry, {"plugins": {"installed@market": [record]}})
                self.assert_refused("scope")

    def test_incomplete_settings_refuse(self) -> None:
        for value in ({}, {"enabledPlugins": []}, {"enabledPlugins": {"a@b": "false"}}):
            with self.subTest(value=value):
                self.write(self.root / "settings.json", value)
                self.assert_refused("enabledPlugins")

    def test_project_without_project_path_refuses(self) -> None:
        self.write(
            self.registry,
            {"plugins": {"project@market": [self.install_record("project")]}},
        )
        self.assert_refused("projectPath")

    def test_missing_project_or_local_settings_refuses(self) -> None:
        self.add_project()
        for name in ("settings.json", "settings.local.json"):
            path = self.project / ".claude" / name
            contents = path.read_bytes()
            path.unlink()
            self.assert_refused("No such file")
            path.write_bytes(contents)

    def test_unreadable_registry_refuses_with_diagnostic(self) -> None:
        with patch(
            "launcher_cleanup_registry.read_object",
            side_effect=PermissionError("denied"),
        ):
            self.assert_refused("denied")


if __name__ == "__main__":
    unittest.main()
