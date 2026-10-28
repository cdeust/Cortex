"""ADR1114 D3: repeated Setup must retain the same SQLite fallback provenance.

Source: native Windows PR792 run40030412977; Setup succeeds, but the next
--init-only reruns Setup after SQLite exists and its fallback line disappears.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
_RUN = r"""
import contextlib, io, json, os, sqlite3, sys
from pathlib import Path
root, work, phase = map(Path, sys.argv[1:])
sys.path[:0] = [str(root / "scripts"), str(root)]
os.environ["CORTEX_CLAUDE_DIR"] = str(work / "claude")
os.environ["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] = "1"
import launcher_setup as setup
import launcher_backend
import launcher_pg_provision as provision
from mcp_server.infrastructure import backend_marker

deps = str(work / "data" / "sets" / "fixture")
Path(deps).mkdir(parents=True, exist_ok=True)
setup.launcher_deps.ensure_deps = lambda *_: None
setup.launcher_deps.set_ready = lambda *_: True
setup._collect = lambda *_: None
calls = []
def unsupported(*args):
    calls.append(True)
    raise provision.launcher_pg_assets.UnsupportedError("native Windows fixture")
provision.provision = unsupported
phase = str(phase)
if phase == "configured":
    os.environ["DATABASE_URL"] = "postgresql://configured.invalid/store"
elif phase == "changed_path":
    os.environ["CORTEX_MEMORY_DB_PATH"] = str(work / "other.db")
elif phase == "explicit_sqlite":
    os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
elif phase == "plugin_option":
    os.environ["CLAUDE_PLUGIN_OPTION_DATABASE_URL"] = "postgresql://configured.invalid/store"
elif phase == "postgres_marker":
    backend_marker.write_backend_marker("postgresql", "operator")
elif phase == "operator_marker":
    backend_marker.write_backend_marker("sqlite", "operator")
elif phase == "legacy_outcome":
    outcome = setup.outcome(deps)
    outcome.pop("sqlite_fallback_paths", None)
    setup.status_file(deps).write_text(json.dumps(outcome))
shown = io.StringIO()
with contextlib.redirect_stdout(shown):
    code = setup.run(deps, "launcher.py")
    outcome = setup.outcome(deps)
    if phase in ("first", "repeat"):
        launcher_backend.apply()
        path = backend_marker.BACKEND_MARKER_PATH.parent / "memory.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS memories (content TEXT)")
        import launcher
        launcher.launcher_base_job.require_ready = lambda *_: None
        launcher.launcher_ml.start = lambda *_: ("ready", "")
        launcher._ensure_runtime("mcp_server.hooks.session_start", False, deps)
        from mcp_server.hooks.session_start_status import sqlite_ready
        message = sqlite_ready("SQLite memory at " + str(path), 0)
    else:
        message = ""
print(json.dumps({"code": code, "outcome": outcome, "message": message,
                  "output": shown.getvalue(), "provision_calls": len(calls)}))
"""


def _setup(work: Path, phase: str) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CORTEX_", "CLAUDE_PLUGIN_", "PG"))
        and key not in ("DATABASE_URL", "PYTHONPATH")
    }
    done = subprocess.run(
        [sys.executable, "-I", "-c", _RUN, str(ROOT), str(work), phase],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_fresh_process_repeated_setup_keeps_fallback_for_existing_sqlite(tmp_path):
    first = _setup(tmp_path, "first")
    second = _setup(tmp_path, "repeat")
    assert first["code"] == second["code"] == 0
    assert first["provision_calls"] == 1 and second["provision_calls"] == 0
    cause = first["outcome"]["sqlite_fallback"]
    assert second["outcome"]["sqlite_fallback"] == cause
    assert f"SQLite fallback: {cause}" in second["message"]
    assert f"SQLite fallback: {cause}" in second["output"]


def test_reconfiguration_does_not_reuse_previous_store_fallback(tmp_path):
    for phase in (
        "configured",
        "changed_path",
        "postgres_marker",
        "explicit_sqlite",
        "plugin_option",
        "operator_marker",
        "legacy_outcome",
    ):
        work = tmp_path / phase
        _setup(work, "first")
        result = _setup(work, phase)
        assert result["code"] == 0
        assert "sqlite_fallback" not in result["outcome"]
