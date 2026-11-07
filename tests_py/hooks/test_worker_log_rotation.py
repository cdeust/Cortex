"""Verify each worker spawn hands its output to the redaction relay.

Before ADR-1110 the hook rotated the log and handed the child the open file;
now no hook opens the log: the child's stdout+stderr are the relay's stdin
pipe and the relay appends (and rotates) under the gate. Relay rotation and
redaction are pinned in tests_py/infrastructure/test_log_relay.py."""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from mcp_server.shared import detached_spawn


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
        self.consolidate = importlib.import_module(
            "mcp_server.hooks.session_start_consolidate"
        )
        self.background = importlib.import_module(
            "mcp_server.hooks.session_start_background"
        )
        self.commit = importlib.import_module("mcp_server.hooks.post_commit_reindex")

    def assert_spawn_routes_through_relay(self, filename: str, spawn) -> None:
        path = self.root / "isolated-claude/methodology" / filename
        calls = []

        def popen(command, **options):
            calls.append((command, options))
            return SimpleNamespace(pid=42, stdin=io.BytesIO())

        with patch("subprocess.Popen", side_effect=popen):
            spawn()
        self.assertEqual(len(calls), 2)
        (relay_cmd, relay_opts), (child_cmd, child_opts) = calls
        self.assertEqual(
            relay_cmd[-2:], ["mcp_server.infrastructure.log_relay", str(path)]
        )
        self.assertEqual(relay_opts["stdin"], subprocess.PIPE)
        self.assertIsInstance(child_opts["stdout"], io.BytesIO)  # the relay's stdin
        self.assertTrue(child_opts["stdout"].closed)  # parent kept no copy
        self.assertEqual(child_opts["stderr"], subprocess.STDOUT)
        self.assertFalse(path.exists())  # the hook itself opened nothing

    def test_consolidate_spawn_routes_output_through_the_redaction_relay(self) -> None:
        self.assert_spawn_routes_through_relay(
            "consolidate.log",
            lambda: self.consolidate._spawn_consolidate_cycle(detached_spawn.options()),
        )

    def test_post_commit_spawn_routes_output_through_the_redaction_relay(self) -> None:
        self.assert_spawn_routes_through_relay(
            "pipeline_reanalyze.log", lambda: self.commit._spawn_reanalyze("fixture")
        )

    def test_session_reanalyze_routes_output_through_the_redaction_relay(self) -> None:
        discovery = ModuleType("mcp_server.infrastructure.pipeline_discovery")
        discovery.discover_pipeline_command = lambda project_root: ["fixture"]
        ttl = ModuleType("mcp_server.infrastructure.pipeline_graph_ttl")
        ttl.graph_is_stale = lambda path: True
        ttl.claim_reanalysis_slot = lambda project_root: True
        with patch.dict(
            sys.modules, {discovery.__name__: discovery, ttl.__name__: ttl}
        ):
            self.assert_spawn_routes_through_relay(
                "pipeline_reanalyze.log",
                lambda: self.background._maybe_background_reanalyze(
                    "fixture", lambda project_root: "fixture"
                ),
            )


if __name__ == "__main__":
    unittest.main()
