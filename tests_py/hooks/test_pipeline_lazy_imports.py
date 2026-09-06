"""Stdlib-only regressions for W2-1a; no real store, MCP child or model.

Run independently of the database-owning pytest conftest:
python -m unittest tests_py.hooks.test_pipeline_lazy_imports
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import unquote, urlsplit

from mcp_server.handlers import ingest_helpers
from mcp_server.hooks import pipeline_impact_bump as hook
from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit
from scripts import measure_pipeline_hook as probe

_STORE_MODULE = "mcp_server.infrastructure.memory_store"


class ColdImportTests(unittest.TestCase):
    def run_cold(self, source: str) -> None:
        result = subprocess.run(
            [sys.executable, "-S", "-c", source],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "CORTEX_HEADLESS_AUTHORING_CHILD": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejected_events_do_not_import_store_or_lifecycle(self):
        self.run_cold("""
import io, json, runpy, sys
from unittest.mock import patch
blocked = ('mcp_server.__main__', 'mcp_server.hooks._store_lifecycle',
           'mcp_server.infrastructure.memory_store')
for raw in ('', '{', json.dumps({'tool_name': 'Read'}),
            json.dumps({'tool_name': 'Bash'}),
            json.dumps({'tool_name': 'Edit', 'tool_input': {}})):
    with patch('sys.stdin', io.StringIO(raw)):
        runpy.run_module('mcp_server.hooks.pipeline_impact_bump', run_name='__main__')
    imported = set(blocked).intersection(sys.modules)
    assert not imported, imported
""")

    def test_cooldown_does_not_import_lifecycle(self):
        self.run_cold("""
import sys
from unittest.mock import patch
from mcp_server.hooks import pipeline_impact_bump as hook
with patch.object(hook, '_check_cooldown', return_value=True):
    hook.process_event({'tool_name': 'Edit', 'tool_input': {'file_path': '/x.py'}})
assert 'mcp_server.hooks._store_lifecycle' not in sys.modules
assert 'mcp_server.infrastructure.memory_store' not in sys.modules
""")

    def test_graph_helpers_do_not_import_upstream(self):
        self.run_cold("""
import sys
from mcp_server.handlers import ingest_helpers
assert 'mcp_server.infrastructure.mcp_client_pool' not in sys.modules
assert 'mcp_server.infrastructure.upstream_governor' not in sys.modules
assert 'mcp_server.__main__' not in sys.modules
""")

    def test_teardown_without_store_does_not_import_it(self):
        self.run_cold("""
import sys
from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit
with close_shared_store_on_exit():
    pass
assert 'mcp_server.infrastructure.memory_store' not in sys.modules
""")


class StoreTeardownTests(unittest.TestCase):
    def setUp(self):
        self.store_module = ModuleType(_STORE_MODULE)
        self.reset = Mock()
        self.store_module.reset_shared_store = self.reset
        self.modules = patch.dict(sys.modules, {_STORE_MODULE: self.store_module})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_success_closes_a_store_loaded_inside_the_block(self):
        sys.modules.pop(_STORE_MODULE)
        with close_shared_store_on_exit():
            sys.modules[_STORE_MODULE] = self.store_module
        self.reset.assert_called_once_with()

    def _assert_exception_closure(self):
        for error in (ValueError("original"), SystemExit(7)):
            self.reset.reset_mock()
            with self.assertRaises(type(error)) as caught:
                with close_shared_store_on_exit():
                    raise error
            self.assertIs(caught.exception, error)
            self.reset.assert_called_once_with()

    def test_exception_and_system_exit_close_store(self):
        self._assert_exception_closure()

    def test_teardown_failure_preserves_every_outcome(self):
        self.reset.side_effect = RuntimeError("close failed")
        with close_shared_store_on_exit():
            pass
        self._assert_exception_closure()


class PipelineGraphTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.graph = self.root / "custom-output" / "graph"
        self.graph.parent.mkdir()
        self.graph.write_text("materialised graph")
        self.store = Mock()
        self.store.get_memories_by_tag.return_value = [
            {
                "tags": [ingest_helpers.code_graph_tag(str(self.project))],
                "content": f"graph_path={self.graph}",
            }
        ]
        self.factory = ModuleType(_STORE_MODULE)
        self.factory.get_shared_store = Mock(return_value=self.store)
        self.factory.reset_shared_store = Mock()
        self.upstream = AsyncMock(return_value={"impacted_symbols": ["module::symbol"]})
        self.bump = Mock(return_value=0)
        self.event = {"tool_name": "Edit", "tool_input": {"file_path": "/changed.py"}}
        patches = (
            patch.dict(sys.modules, {_STORE_MODULE: self.factory}),
            patch.dict(os.environ, {"CLAUDE_PROJECT_ROOT": str(self.project)}),
            patch.object(hook, "_COOLDOWN_FILE", self.root / "cooldown.json"),
            patch.object(ingest_helpers, "call_upstream", self.upstream),
            patch.object(hook, "_bump_heat_for_symbols", self.bump),
        )
        for replacement in patches:
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_custom_output_dir_is_found_and_store_closed(self):
        hook.process_event(self.event)
        self.upstream.assert_awaited_once_with(
            "codebase",
            "detect_changes",
            {
                "graph_path": str(self.graph),
                "diff_text": "diff --git a//changed.py b//changed.py\n",
            },
        )
        self.bump.assert_called_once_with(["module::symbol"])
        self.factory.reset_shared_store.assert_called_once_with()

    def test_absent_graph_skips_upstream_and_closes_store(self):
        self.store.get_memories_by_tag.return_value = []
        hook.process_event(self.event)
        self.upstream.assert_not_awaited()
        self.bump.assert_not_called()
        self.factory.reset_shared_store.assert_called_once_with()

    def test_missing_graph_artifact_skips_upstream(self):
        self.graph.unlink()
        hook.process_event(self.event)
        self.upstream.assert_not_awaited()
        self.factory.reset_shared_store.assert_called_once_with()

    def test_empty_graph_artifact_skips_upstream(self):
        self.graph.write_text("")
        hook.process_event(self.event)
        self.upstream.assert_not_awaited()
        self.factory.reset_shared_store.assert_called_once_with()

    def test_upstream_failure_closes_store(self):
        self.upstream.side_effect = RuntimeError("upstream failed")
        with patch.object(hook, "_log") as log:
            hook.process_event(self.event)
        self.assertIn("upstream failed", log.call_args.args[0])
        self.factory.reset_shared_store.assert_called_once_with()

    def test_system_exit_during_lookup_closes_store(self):
        self.store.get_memories_by_tag.side_effect = SystemExit(7)
        with self.assertRaises(SystemExit) as caught:
            hook.process_event(self.event)
        self.assertEqual(caught.exception.code, 7)
        self.factory.reset_shared_store.assert_called_once_with()


class UpstreamImportTests(unittest.TestCase):
    def test_deferred_import_preserves_client_and_governor_calls(self):
        client = Mock(max_concurrent_calls=3)
        client.call = AsyncMock(return_value='{"ok": true}')
        pool = ModuleType("mcp_server.infrastructure.mcp_client_pool")
        pool.get_client = AsyncMock(return_value=client)
        governor = ModuleType("mcp_server.infrastructure.upstream_governor")
        governor.govern = Mock(return_value=AsyncMock())
        with patch.dict(
            sys.modules, {pool.__name__: pool, governor.__name__: governor}
        ):
            result = asyncio.run(ingest_helpers.call_upstream("codebase", "probe", {}))
        self.assertEqual(result, {"ok": True})
        pool.get_client.assert_awaited_once_with("codebase")
        governor.govern.assert_called_once_with("codebase", 3)
        client.call.assert_awaited_once_with("probe", {})


class MeasurementProtocolTests(unittest.TestCase):
    def test_environment_overrides_live_roots_and_headless_flag(self):
        hostile = {
            "DATABASE_URL": "postgresql://production",
            "CORTEX_MEMORY_DATABASE_URL": "postgresql://production",
            "CORTEX_MEMORY_DB_PATH": "/production/memory.db",
            "CORTEX_HEADLESS_AUTHORING_CHILD": "1",
            "PGHOSTADDR": "127.0.0.1",
            "PGSERVICE": "production",
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, hostile),
        ):
            root = Path(temporary)
            env = probe._environment(root / "repo", root)
        self.assertEqual(env["DATABASE_URL"], env["CORTEX_MEMORY_DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["CORTEX_TEST_DATABASE_URL"])
        self.assertEqual(
            unquote(urlsplit(env["DATABASE_URL"]).netloc),
            str(root.resolve() / "no-postgres"),
        )
        self.assertEqual(env["CORTEX_MEMORY_STORE_BACKEND"], "sqlite")
        self.assertEqual(env["CORTEX_MEMORY_DB_PATH"], str(root / "memory.db"))
        self.assertEqual(
            env["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"], str(root / "memory.db")
        )
        self.assertEqual(env["CORTEX_CLAUDE_DIR"], str(root / "claude"))
        self.assertNotIn("CORTEX_HEADLESS_AUTHORING_CHILD", env)
        self.assertFalse({"PGHOSTADDR", "PGSERVICE"}.intersection(env))

    def test_four_samples_discard_first_and_profile_separately(self):
        args = SimpleNamespace(python="/prepared/python", output=Path("/isolated"))
        with patch.object(
            probe, "_run_sample", side_effect=lambda *args: {"stderr": "trace"}
        ) as run:
            case = probe._measure_case("Read", args, {})
        self.assertEqual(
            [row["discarded"] for row in case["samples"]], [True, False, False, False]
        )
        self.assertEqual(len(run.call_args_list), 5)
        self.assertNotIn("-X", run.call_args_list[0].args[0])
        self.assertIn("importtime", run.call_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()
