"""Real launcher process boundaries for capture exclusion and stdin replay."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CHILD = r"""
import importlib.abc
import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'scripts'))
import launcher
attempted = []
bootstrap = []
dispatched = []
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith('mcp_server.infrastructure'):
            attempted.append(fullname)
            if os.environ['EXPECT_EXCLUDED'] == '1':
                raise AssertionError('unexpected infrastructure: ' + fullname)
sys.meta_path.insert(0, Guard())
launcher.launcher_deps.ensure_deps = lambda path: bootstrap.append('base')
launcher.launcher_deps.ensure_all_deps = lambda path: bootstrap.append('all')
def dispatch(module, **kwargs):
    replay = isinstance(getattr(sys.stdin, 'buffer', None), io.BytesIO)
    fd_child = None
    if replay:
        fd_child = subprocess.check_output(
            [sys.executable, '-S', '-c', 'import sys; print(repr(sys.stdin.read()))'],
            text=True,
        ).strip()
    dispatched.append({'module': module, 'raw': sys.stdin.read(),
                       'replay': replay, 'fd_child': fd_child})
runpy.run_module = dispatch
sys.argv = ['launcher.py', os.environ['TARGET_MODULE']]
if os.environ.get('INSTALL_DEPS') == '1':
    sys.argv.append('--install-deps')
try:
    launcher.main()
except SystemExit as error:
    assert error.code == 0, error.code
print(json.dumps({'attempted': attempted, 'bootstrap': bootstrap,
                  'dispatched': dispatched}))
"""


class LauncherCaptureModes(unittest.TestCase):
    def setUp(self):
        tree = tempfile.TemporaryDirectory(prefix="cortex-launcher-capture-")
        self.addCleanup(tree.cleanup)
        self.root = Path(tree.name)

    def run_child(self, mode, raw, options=None):
        options = options or {}
        env = {
            key: os.environ[key]
            for key in ("PATH", "SystemRoot", "WINDIR")
            if key in os.environ
        }
        env.update(
            PYTHONIOENCODING="utf-8",
            CORTEX_CLAUDE_DIR=str(self.root),
            CLAUDE_PLUGIN_DATA=str(self.root / "plugin-data"),
            CLAUDE_PLUGIN_ROOT=str(_ROOT),
            CORTEX_MEMORY_STORE_BACKEND="sqlite",
            CORTEX_CAPTURE_MODE=mode,
            TARGET_MODULE="mcp_server.hooks.post_tool_capture",
            EXPECT_EXCLUDED="0",
        )
        env.update(options)
        done = subprocess.run(
            [sys.executable, "-S", "-c", _CHILD],
            cwd=_ROOT,
            input=raw,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=10,  # source: existing capture hook timeout in plugin.json.
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout), done.stderr

    def test_excluded_launcher_never_imports_infrastructure_or_bootstraps(self):
        for mode in ("writes-only", "off", "", "Full"):
            with self.subTest(mode=mode):
                result, stderr = self.run_child(
                    mode, '{"tool_name":"Read"}', {"EXPECT_EXCLUDED": "1"}
                )
                self.assertEqual(
                    result, {"attempted": [], "bootstrap": [], "dispatched": []}
                )
                self.assertIn("CORTEX_CAPTURE_MODE", stderr)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_admitted_payload_preserves_decoded_text_and_consumes_pipe(self):
        raw = ' \n{"tool_name":"Bash", "tool_response":"été 漢字 🧠"}\n '
        result, _ = self.run_child("writes-only", raw)
        self.assertIn("mcp_server.infrastructure.backend_marker", result["attempted"])
        self.assertEqual(result["bootstrap"], ["base"])
        dispatched = result["dispatched"][0]
        self.assertEqual(dispatched["raw"], raw)
        self.assertTrue(dispatched["replay"])
        self.assertEqual(dispatched["fd_child"], "''")

    def test_invalid_payload_is_forwarded_to_existing_hook_validation(self):
        for raw in ("{invalid", "[]", '{"tool_name":17}', "\n"):
            with self.subTest(raw=raw):
                result, _ = self.run_child("writes-only", raw)
                self.assertEqual(result["dispatched"][0]["raw"], raw)
                self.assertEqual(result["bootstrap"], ["base"])

    def test_other_entries_and_explicit_install_preserve_original_stdin(self):
        cases = (
            ("full", {}, "base"),
            ("off", {"TARGET_MODULE": "mcp_server"}, "base"),
            ("off", {"INSTALL_DEPS": "1"}, "all"),
        )
        raw = '{"tool_name":"Read"}'
        for mode, options, bootstrap in cases:
            with self.subTest(mode=mode, options=options):
                result, _ = self.run_child(mode, raw, options)
                self.assertEqual(result["bootstrap"], [bootstrap])
                self.assertFalse(result["dispatched"][0]["replay"])
                self.assertEqual(result["dispatched"][0]["raw"], raw)

    def test_headless_exit_precedes_bootstrap_and_dispatch(self):
        result, _ = self.run_child(
            "writes-only",
            '{"tool_name":"Bash"}',
            {"CORTEX_HEADLESS_AUTHORING_CHILD": "1", "EXPECT_EXCLUDED": "1"},
        )
        self.assertEqual(result, {"attempted": [], "bootstrap": [], "dispatched": []})


if __name__ == "__main__":
    unittest.main()
