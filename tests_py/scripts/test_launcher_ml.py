"""scripts/launcher_ml.py: semantic search installs in one background job.

The SessionStart launch never installs the ML set itself (a cancelled hook
would kill it, and the host discards the output of a hook past its timeout):
it starts at most one detached job and reports where semantic search stands.

source: ADR-1104
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ml_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_ml", REPO_ROOT / "scripts" / "launcher_ml.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv(module.ZERO_DOWNLOAD_ENV, raising=False)
    return module


@pytest.fixture
def deps_dir(tmp_path: Path) -> str:
    (tmp_path / "deps").mkdir()
    return str(tmp_path / "deps")


@pytest.fixture
def spawned(ml_mod, monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        ml_mod.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw))
    )
    return calls


def _status(ml_mod, deps_dir: str, outcome: dict) -> None:
    ml_mod.status_file(deps_dir).write_text(json.dumps(outcome))


def test_state_is_installing_until_the_job_records_an_outcome(ml_mod, deps_dir):
    assert ml_mod.state(deps_dir) == ("installing", "")


def test_state_names_the_failure_and_the_log(ml_mod, deps_dir):
    _status(ml_mod, deps_dir, {"status": "failed", "error": "NoWheel: torch"})
    state, detail = ml_mod.state(deps_dir)
    assert state == "failed"
    assert "NoWheel: torch" in detail and "semantic-install.log" in detail


def test_ready_needs_the_job_and_the_stamp(ml_mod, deps_dir, monkeypatch):
    _status(ml_mod, deps_dir, {"status": "ready", "model_files": ml_mod.MODEL_FILES})
    monkeypatch.setattr(ml_mod.launcher_deps, "set_ready", lambda d, k: False)
    assert ml_mod.state(deps_dir)[0] == "installing"  # uv.lock moved on
    monkeypatch.setattr(ml_mod.launcher_deps, "set_ready", lambda d, k: k == "ml")
    assert ml_mod.state(deps_dir) == ("ready", "")


def test_start_spawns_one_detached_warmup_job(ml_mod, deps_dir, spawned):
    assert ml_mod.start(deps_dir, "/plugin/scripts/launcher.py")[0] == "installing"
    ((argv, kwargs),) = spawned
    assert argv == [sys.executable, "/plugin/scripts/launcher.py", ml_mod.WARMUP_MODULE]
    assert kwargs["env"][ml_mod.STATUS_ENV] == str(ml_mod.status_file(deps_dir))
    assert kwargs["stdin"] is ml_mod.subprocess.DEVNULL


def test_start_does_nothing_while_the_job_runs(ml_mod, deps_dir, spawned):
    with ml_mod.launcher_lock.held_if_free(ml_mod.job_lock(deps_dir)) as mine:
        assert mine
        assert ml_mod.start(deps_dir, "launcher.py")[0] == "installing"
    assert spawned == []


def test_start_respects_the_zero_download_opt_out(
    ml_mod, deps_dir, spawned, monkeypatch
):
    monkeypatch.setenv(ml_mod.ZERO_DOWNLOAD_ENV, "1")
    state, detail = ml_mod.start(deps_dir, "launcher.py")
    assert (state, spawned) == ("off", [])
    assert ml_mod.ZERO_DOWNLOAD_ENV in detail


def test_run_job_marks_the_attempt_then_installs_then_warms_up(
    ml_mod, deps_dir, monkeypatch
):
    monkeypatch.setenv(ml_mod.STATUS_ENV, "restored by monkeypatch after the test")
    monkeypatch.setattr(ml_mod.launcher_deps, "set_ready", lambda d, k: True)
    order: list = []
    ml_mod.run_job(
        deps_dir, lambda: order.append("install"), lambda: order.append("run")
    )
    assert order == ["install", "run"]
    assert (
        json.loads(ml_mod.status_file(deps_dir).read_text())["status"] == "installing"
    )


def test_a_second_job_returns_without_installing(ml_mod, deps_dir):
    order: list = []
    with ml_mod.launcher_lock.held_if_free(ml_mod.job_lock(deps_dir)):
        ml_mod.run_job(deps_dir, lambda: order.append("install"), lambda: None)
    assert order == []


def test_the_status_variable_matches_the_warmup_module(ml_mod):
    from mcp_server.infrastructure import embedding_warmup

    assert embedding_warmup.STATUS_ENV == ml_mod.STATUS_ENV
    assert embedding_warmup.MODEL_FILES == ml_mod.MODEL_FILES


def test_a_ready_record_without_the_onnx_encoder_reruns_the_job(
    ml_mod, deps_dir, spawned, monkeypatch
):
    # Issue #706: a pre-upgrade record lacks the hook's query-encoder files.
    _status(ml_mod, deps_dir, {"status": "ready", "model": "all-MiniLM-L6-v2"})
    monkeypatch.setattr(ml_mod.launcher_deps, "set_ready", lambda d, k: True)
    assert ml_mod.state(deps_dir) == ("installing", "")
    ml_mod.start(deps_dir, "/plugin/scripts/launcher.py")
    assert len(spawned) == 1


def test_a_failed_ml_install_is_recorded_as_such_and_skips_the_warm_up(
    ml_mod, deps_dir, monkeypatch
):
    monkeypatch.setenv(ml_mod.STATUS_ENV, "restored by monkeypatch after the test")
    monkeypatch.setattr(ml_mod.launcher_deps, "set_ready", lambda d, k: False)
    ml_mod.run_job(deps_dir, lambda: None, lambda: pytest.fail("warmed up"))
    state, detail = ml_mod.state(deps_dir)
    assert state == "failed"
    assert "the locked ML set did not install" in detail
