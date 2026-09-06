"""Verify each worker spawn rotates its log before handing off the fd."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from mcp_server.shared import log_rotation


class TestWorkerLogRotation(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-worker-rotation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plugin = self.root / "plugin"
        (self.plugin / "scripts").mkdir(parents=True)
        (self.plugin / "scripts/launcher.py").write_text("# fixture", encoding="utf-8")
        environment = patch.dict(
            os.environ,
            {
                "CLAUDE_PLUGIN_ROOT": str(self.plugin),
                "CORTEX_CLAUDE_DIR": str(self.root / "isolated-claude"),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        home = patch.object(Path, "home", return_value=self.root)
        home.start()
        self.addCleanup(home.stop)
        self.session = importlib.import_module("mcp_server.hooks.session_start")
        self.commit = importlib.import_module("mcp_server.hooks.post_commit_reindex")

    def assert_spawn_rotates(self, filename: str, spawn) -> None:
        path = self.root / "isolated-claude/methodology" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old\n", encoding="utf-8")
        captured = []

        def popen(command, **options):
            self.assertEqual(path.with_name(filename + ".1").read_text(), "old\n")
            self.assertFalse(options["stdout"].closed)
            options["stdout"].write("new\n")
            captured.append(options["stdout"])
            return SimpleNamespace(pid=42)

        with patch.object(log_rotation, "MAX_LOG_BYTES", len("old\n")):
            with patch("subprocess.Popen", side_effect=popen):
                spawn()
        self.assertEqual(path.read_text(), "new\n")
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].closed)

    def test_consolidate_spawn_rotates_and_closes_parent_descriptor(self) -> None:
        self.assert_spawn_rotates(
            "consolidate.log", self.session._spawn_consolidate_cycle
        )

    def test_post_commit_spawn_rotates_and_closes_parent_descriptor(self) -> None:
        self.assert_spawn_rotates(
            "pipeline_reanalyze.log", lambda: self.commit._spawn_reanalyze("fixture")
        )

    def test_session_reanalyze_rotates_and_closes_parent_descriptor(self) -> None:
        discovery = ModuleType("mcp_server.infrastructure.pipeline_discovery")
        discovery.discover_pipeline_command = lambda: ["fixture"]
        ttl = ModuleType("mcp_server.infrastructure.pipeline_graph_ttl")
        ttl.graph_is_stale = lambda path: True
        with patch.dict(
            sys.modules, {discovery.__name__: discovery, ttl.__name__: ttl}
        ):
            with patch.object(
                self.session, "_lookup_cached_graph_path", return_value="fixture"
            ):
                self.assert_spawn_rotates(
                    "pipeline_reanalyze.log", self.session._maybe_background_reanalyze
                )


if __name__ == "__main__":
    unittest.main()
