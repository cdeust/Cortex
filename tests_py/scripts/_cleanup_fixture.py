"""Synthetic-only Claude trees for launcher cleanup tests (stdlib runner)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from launcher_cleanup_registry import CleanupScope, identity  # noqa: E402

HAS_SAFE_FS = hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
HAS_SAFE_REMOVE = (
    HAS_SAFE_FS
    and sys.version_info >= (3, 11)
    and getattr(shutil.rmtree, "avoids_symlink_attacks", False)
)


class CleanupFixture(unittest.TestCase):
    """No home-directory access, database connection or dependency bootstrap."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-cleanup-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name).resolve()
        self.root = self.workspace / "claude"
        self.scope = CleanupScope(
            self.root, self.root / "plugins/data/current-market/deps"
        )
        self.registry = self.root / "plugins/installed_plugins.json"
        self.installs = {"installed@market": [self.install_record()]}
        self.write(self.registry, {"plugins": self.installs})
        self.write(
            self.root / "settings.json",
            {
                "enabledPlugins": {
                    "enabled@market": True,
                    "disabled@market": False,
                }
            },
        )
        for plugin in (
            "current@market",
            "installed@market",
            "enabled@market",
            "disabled@market",
            "orphan@market",
            "scratch@inline",
            "cloud@synced",
        ):
            self.make_deps(plugin)

    def write(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def install_record(self, scope: str = "user") -> dict[str, str]:
        return {"scope": scope, "installPath": str(self.workspace / "install")}

    def make_deps(self, plugin: str) -> Path:
        path = self.scope.data_root / identity(plugin) / "deps"
        path.mkdir(parents=True, exist_ok=True)
        (path / "fixture.txt").write_text("fixture bytes", encoding="utf-8")
        (path.parent / "keep.json").write_text("user data", encoding="utf-8")
        return path

    def all_deps(self) -> list[Path]:
        return sorted(self.scope.data_root.glob("*/deps"))
