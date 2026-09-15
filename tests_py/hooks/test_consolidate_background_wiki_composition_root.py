"""Regression cover for the 2026-09-16 review finding: mcp_server/hooks/
consolidate_background.py (spawned by SessionStart) runs
handlers.consolidate with wiki=True, which reaches core/wiki_coverage.py
and core/wiki_coverage_dashboard.py -- both behind the composition-root
seams this issue (#560) introduced. Those seams are wired only in
mcp_server/__main__.py and the test session
(tests_py/_composition_root_wiring.py, loaded by conftest.py), and they
raise RuntimeError when unwired. conftest.py always wires everything, so
the ordinary test suite cannot see a hook process that never imports it.

This test runs the hook as a REAL subprocess with its own isolated
environment (SQLite backend, throwaway $CORTEX_CLAUDE_DIR). The
subprocess never imports tests_py.conftest and starts with an empty
sys.modules, so it cannot inherit the parent pytest process's
already-wired seams.
"""

from __future__ import annotations

import os
import subprocess
import sys

from pathlib import Path


def _isolated_env(sandbox: Path) -> dict[str, str]:
    """Same shape as scripts/measure_pipeline_hook.py's sandbox env."""
    db_path = str(sandbox / "memory.db")
    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "SYSTEMROOT", "WINDIR")
        if key in os.environ
    }
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "CORTEX_CLAUDE_DIR": str(sandbox / "claude"),
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
            "CORTEX_MEMORY_DB_PATH": db_path,
            "CORTEX_MEMORY_SQLITE_FALLBACK_PATH": db_path,
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", ""),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE", ""),
        }
    )
    return env


def test_consolidate_background_with_wiki_completes_on_a_throwaway_store(
    tmp_path,
):
    """The exact production path: `python -m mcp_server.hooks.
    consolidate_background` on a fresh SQLite store, wiki=True (the
    hook's own hard-coded default, consolidate_background._build_args).

    Before the composition-root fix, core/wiki_coverage_dashboard.py's
    seam raised inside write_dashboards(); handlers/consolidation/
    wiki_maintenance.py catches that per-sub-task (so one broken wiki
    sub-task cannot kill the whole cycle) and records it as
    stats["wiki"]["dashboards"]["status"] = "error: ...", nested deep
    enough that handlers/consolidate.py's own overall-status check never
    sees it -- the process would still exit 0 with "status=ok" printed,
    silently masking the regression. Verified this by disabling the
    wiring locally and re-running: the process still exited 0, which is
    exactly why the assertion below checks the wiki summary line's
    ``dashboards=`` field (``written=N`` on success, ``error: ...`` when a
    seam is unwired), not just the exit code.
    """
    env = _isolated_env(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.consolidate_background"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, (
        f"consolidate_background exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "[bg-consolidate] finished status=ok" in result.stderr, result.stderr
    assert "dashboards=written=" in result.stderr, (
        "wiki dashboard generation failed -- almost certainly an unwired "
        f"composition-root seam\n--- stderr ---\n{result.stderr}"
    )
