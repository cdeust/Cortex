"""The first SessionStart in a cold profile ends inside its hook timeout.

Issue #705 measured 85.6 s for the first SessionStart against the 30 s
``timeout`` of the manifest, because the hook installed about 1.1 GB of
dependencies. ADR-1108 moved every install out of the hooks. This test runs
the manifest's own SessionStart command, as the host runs it, against an empty
plugin data directory and times it against that same ``timeout``: a hook that
installs again, or blocks on anything, fails here on every CI run.

The background install the hook starts is the one thing the test keeps from
running: it holds the job lock, so the hook takes the "an install is already
running" branch. That branch differs from the first-ever launch only by the
``Popen`` of the detached job, which does not wait for the job.

source: issue #705 ("A CI check on a clean runner that times the first
SessionStart against the hook timeout"), ADR-1108
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
# The hook input the host writes on stdin; the not-ready branch never reads it.
# source: Claude Code hooks reference, SessionStart input (source "startup")
HOOK_INPUT = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})


@pytest.fixture
def scripts_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))


def _session_start_hook() -> dict:
    """The one SessionStart command hook of the manifest, with its timeout."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    groups = manifest["hooks"]["SessionStart"]
    hooks = [hook for group in groups for hook in group["hooks"]]
    assert len(hooks) == 1, hooks
    assert hooks[0]["type"] == "command"
    return hooks[0]


def _cold_deps_dir(data: Path) -> str:
    """The set directory the launcher resolves for this tree in ``data``."""
    import launcher_deps  # noqa: PLC0415 — on sys.path only through scripts_on_path
    import launcher_layout  # noqa: PLC0415

    key = launcher_deps.lock_key() or launcher_layout.NO_LOCK
    return launcher_layout.deps_dir(data, key)


def _host_env(data: Path, home: Path) -> dict[str, str]:
    """The variables the host sets for a plugin hook, in a throwaway HOME."""
    env = dict(os.environ)
    env.update(
        {
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
            "CLAUDE_PLUGIN_DATA": str(data),
            "HOME": str(home),
            "USERPROFILE": str(home),
        }
    )
    return env


def _run_cold(tmp_path: Path) -> tuple[subprocess.CompletedProcess, float, dict]:
    """Run the SessionStart hook on an empty data dir; (result, seconds, hook)."""
    import launcher_base_job  # noqa: PLC0415
    import launcher_lock  # noqa: PLC0415

    hook = _session_start_hook()
    data, home = tmp_path / "plugin-data", tmp_path / "home"
    data.mkdir()
    home.mkdir()
    deps = _cold_deps_dir(data)
    with launcher_lock.held(launcher_base_job.job_lock(deps), wait_seconds=1):
        started = time.monotonic()
        result = subprocess.run(
            hook["command"],
            shell=True,
            env=_host_env(data, home),
            input=HOOK_INPUT,
            capture_output=True,
            text=True,
            timeout=hook["timeout"] * 2,
        )
        elapsed = time.monotonic() - started
    return result, elapsed, {"hook": hook, "deps": deps, "data": data}


def test_first_session_start_ends_inside_the_manifest_timeout(
    scripts_on_path, tmp_path
):
    result, elapsed, run = _run_cold(tmp_path)
    timeout = run["hook"]["timeout"]
    assert result.returncode == 0, result.stderr
    assert elapsed < timeout, (
        f"the first SessionStart took {elapsed:.1f} s against its "
        f"{timeout} s timeout; stderr: {result.stderr}"
    )


def test_first_session_start_installs_nothing_and_says_so(scripts_on_path, tmp_path):
    import launcher_notice  # noqa: PLC0415

    result, _, run = _run_cold(tmp_path)
    out = json.loads(result.stdout)
    assert out["systemMessage"] == f"{launcher_notice.INSTALLING}."
    context = out["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    assert context["additionalContext"] == f"{launcher_notice.INSTALLING}."
    assert "installed nothing" in result.stderr
    assert not Path(run["deps"]).exists(), sorted(
        str(p.relative_to(run["data"])) for p in run["data"].rglob("*")
    )
