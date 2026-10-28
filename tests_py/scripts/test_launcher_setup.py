"""scripts/launcher_setup.py: Setup installs both sets and stamps them, or fails.

The seams are the locked-set install and the model download; the stamps, the
outcome file and the log are the real ones.

source: ADR-1108
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def setup_env(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import launcher_deps
    import launcher_layout
    import launcher_pg_provision
    import launcher_setup

    key = launcher_deps.lock_key()
    deps = launcher_layout.deps_dir(tmp_path / "data", key)
    installed: list = []
    removed: list = []

    def fake_install(deps_dir, set_args):
        installed.append(tuple(set_args))
        return True

    monkeypatch.setattr(launcher_deps, "_locked_set_digest", lambda *_a: "s" * 64)
    monkeypatch.setattr(launcher_deps, "_install_locked_set", fake_install)
    monkeypatch.setattr(launcher_deps, "_importable", lambda *_a: True)
    monkeypatch.setattr(
        launcher_setup.launcher_gc,
        "collect",
        lambda root, data: removed.append((root, data)) or [],
    )
    # The managed PostgreSQL step has its own tests (test_launcher_pg_*).
    monkeypatch.setattr(
        launcher_setup,
        "managed_pg_step",
        lambda deps, say: launcher_pg_provision.StepOutcome(),
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    monkeypatch.delenv("CORTEX_RUNNING_ROOT", raising=False)
    monkeypatch.delenv(launcher_setup.launcher_ml.ZERO_DOWNLOAD_ENV, raising=False)
    return launcher_setup, launcher_deps, deps, installed, removed


def _warm(monkeypatch, setup, cause=""):
    calls: list = []
    monkeypatch.setattr(
        setup, "_warm_model", lambda deps, launcher, log: calls.append(deps) or cause
    )
    return calls


def test_setup_installs_both_sets_stamps_them_and_downloads_the_model(
    setup_env, monkeypatch, capsys
):
    setup, deps_mod, deps, installed, removed = setup_env
    warmed = _warm(monkeypatch, setup)
    assert setup.run(deps, "launcher.py") == 0
    assert installed == [tuple(deps_mod._sets.BASE), tuple(deps_mod._sets.ML)]
    assert deps_mod.set_ready(deps, "base") and deps_mod.set_ready(deps, "ml")
    stamp = json.loads(Path(deps_mod._stamp_path(deps, "ml")).read_text())
    assert stamp["lock"] == deps_mod.lock_key()
    assert warmed == [deps]
    assert setup.outcome(deps) == {"status": "ready", "error": ""}
    assert removed == [(str(REPO_ROOT), str(Path(deps).parent.parent))]
    assert "[cortex-setup] ready in" in capsys.readouterr().out
    assert "[cortex-setup] ready in" in setup.log_path(deps).read_text()


def test_a_second_setup_installs_nothing(setup_env, monkeypatch):
    setup, _, deps, installed, _ = setup_env
    _warm(monkeypatch, setup)
    setup.run(deps, "launcher.py")
    installed.clear()
    assert setup.run(deps, "launcher.py") == 0
    assert installed == []


def test_a_base_set_that_does_not_install_fails_loudly(setup_env, monkeypatch, capsys):
    setup, deps_mod, deps, _, removed = setup_env
    monkeypatch.setattr(deps_mod, "_install_locked_set", lambda *_a: False)
    warmed = _warm(monkeypatch, setup)
    assert setup.run(deps, "launcher.py") == 1
    assert setup.outcome(deps)["status"] == "failed"
    assert "base dependency set did not install" in setup.outcome(deps)["error"]
    assert "FAILED" in capsys.readouterr().out
    assert warmed == [] and removed == []


def test_a_model_that_does_not_download_fails_with_its_cause(setup_env, monkeypatch):
    setup, _, deps, _, removed = setup_env
    _warm(monkeypatch, setup, cause="URLError: offline")
    assert setup.run(deps, "launcher.py") == 1
    assert "URLError: offline" in setup.outcome(deps)["error"]
    assert removed == []


def test_the_operators_opt_out_skips_the_semantic_set_and_the_model(
    setup_env, monkeypatch
):
    setup, deps_mod, deps, installed, _ = setup_env
    monkeypatch.setenv(setup.launcher_ml.ZERO_DOWNLOAD_ENV, "1")
    warmed = _warm(monkeypatch, setup)
    assert setup.run(deps, "launcher.py") == 0
    assert installed == [tuple(deps_mod._sets.BASE)]
    assert warmed == []


def test_the_pre_install_collects_for_the_running_version(setup_env, monkeypatch):
    setup, _, deps, _, removed = setup_env
    _warm(monkeypatch, setup)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/the/clone")
    monkeypatch.setenv("CORTEX_RUNNING_ROOT", "/the/running/copy")
    setup.run(deps, "launcher.py")
    assert removed[0][0] == "/the/running/copy"


def test_a_successful_setup_clears_the_base_job_failure(setup_env, monkeypatch):
    setup, _, deps, _, _ = setup_env
    _warm(monkeypatch, setup)
    stamp = Path(f"{deps}.base-job.failed")
    stamp.parent.mkdir(parents=True)
    stamp.write_text("{}")
    setup.run(deps, "launcher.py")
    assert not stamp.exists()


def _plugin_copy(root: Path) -> None:
    """The files a launch needs, copied so a wrongly placed install lands in tmp."""
    import shutil

    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO_ROOT / "scripts", root / "scripts", ignore=ignore)
    for part in ("hooks", "shared"):
        shutil.copytree(
            REPO_ROOT / "mcp_server" / part, root / "mcp_server" / part, ignore=ignore
        )
    shutil.copy(
        REPO_ROOT / "mcp_server" / "__init__.py", root / "mcp_server" / "__init__.py"
    )
    shutil.copy(REPO_ROOT / "uv.lock", root / "uv.lock")


def test_setup_typed_by_hand_without_the_host_data_directory_installs_nothing(
    tmp_path,
):
    """Without CLAUDE_PLUGIN_DATA the launcher would install into the plugin tree
    (<root>/sets/<key>), where no hook looks; --setup refuses instead."""
    import os
    import subprocess
    import sys

    root = tmp_path / "plugin"
    _plugin_copy(root)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT")
    }
    # A launcher that did not refuse would download a gigabyte: no network.
    env["HTTPS_PROXY"] = env["HTTP_PROXY"] = "http://127.0.0.1:9"
    done = subprocess.run(
        [sys.executable, str(root / "scripts" / "launcher.py"), "--setup"],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 1
    assert "CLAUDE_PLUGIN_DATA is not set" in done.stderr
    assert "claude --init-only" in done.stderr
    assert not (root / "sets").exists()


def test_a_setup_waits_for_a_concurrent_setup_however_long_it_holds_the_lock(
    setup_env, monkeypatch
):
    """The kernel releases the lock when its holder exits, so the holder is
    alive and installing for as long as the lock is held: no wall-clock bound
    turns that into a recorded failure. The clock is a seam here, not waited on."""
    import itertools
    from types import SimpleNamespace

    setup, _, deps, _, _ = setup_env
    _warm(monkeypatch, setup)
    lock = setup.launcher_lock
    busy = [False, False, False]  # the other Setup holds it for three polls
    real_try = lock._try
    monkeypatch.setattr(lock, "_try", lambda fd: busy.pop() if busy else real_try(fd))
    clock = itertools.count(0, 10**6)  # each poll a million seconds later
    monkeypatch.setattr(
        lock,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _s: None),
    )
    assert setup.run(deps, "launcher.py") == 0
    assert busy == []
    assert setup.outcome(deps)["status"] == "ready"


def test_a_collection_that_raises_after_ready_is_logged_and_recorded(
    setup_env, monkeypatch
):
    """The set is ready; the GC's OSError reaches setup.log and the outcome file.

    Before: the exception escaped after the streams were restored, so setup.log
    ended "ready" and nothing recorded the failure.
    """
    setup, _, deps, _, _ = setup_env
    _warm(monkeypatch, setup)

    def unlistable(root, data):
        raise PermissionError(13, "Permission denied", f"{data}/sets")

    monkeypatch.setattr(setup.launcher_gc, "collect", unlistable)
    assert setup.run(deps, "launcher.py") == 0
    sets = f"{setup.launcher_layout.data_dir(deps)}/sets"
    result = setup.outcome(deps)
    assert result["status"] == "ready"
    assert "Permission denied" in result["gc_error"]
    assert sets in result["gc_error"]  # which path failed, not only the errno
    log = setup.log_path(deps).read_text(encoding="utf-8")
    assert "could not collect the sets of earlier versions" in log
    assert sets in log


def test_any_other_exception_leaves_its_traceback_in_the_log(setup_env, monkeypatch):
    setup, _, deps, _, _ = setup_env
    _warm(monkeypatch, setup)

    def broken(root, data):
        raise RuntimeError("collector bug")

    monkeypatch.setattr(setup.launcher_gc, "collect", broken)
    with pytest.raises(RuntimeError):
        setup.run(deps, "launcher.py")
    log = setup.log_path(deps).read_text(encoding="utf-8")
    assert "Traceback" in log and "collector bug" in log
