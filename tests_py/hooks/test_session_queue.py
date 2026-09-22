"""Bundled stdlib queue durability without a Cortex database. source: ADR-1084"""

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins/hypermnesia-mcp-codex/scripts/session_queue.py"
)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv(
        "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
    )
    assert os.environ["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    spec = importlib.util.spec_from_file_location("session_queue", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intake_preserves_event_before_resolver_and_deduplicates(queue):
    root = queue.queue_root()
    event = {"session_id": "s1", "cwd": "/project"}
    key = queue.enqueue(root, event)
    queue.enqueue(root, event)
    assert len(list(root.glob("*.json"))) == 1
    assert json.loads((root / f"{key}.json").read_text())["event"] == event
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        queue.drain(root)
        queue.enqueue(root, event)
        queue.drain(root)
    assert run.call_count == 1
    assert queue.receipt(root / f"{key}.json").exists()
    assert not list(root.glob("*.json"))


def test_failure_retains_event_and_recovery_reports_it(queue, capsys):
    root = queue.queue_root()
    key = queue.enqueue(root, {"session_id": "retry"})
    with patch.object(queue.subprocess, "run", side_effect=FileNotFoundError("uvx")):
        queue.drain(root)
    assert (root / f"{key}.json").exists()
    assert "uvx" in (root / f"{key}.error").read_text()
    with (
        patch.object(sys, "argv", [str(SCRIPT), "recover"]),
        patch.object(queue, "spawn") as spawn,
    ):
        queue.main()
    spawn.assert_called_once_with(root)
    assert "pending" in capsys.readouterr().err


def test_spawn_is_detached_and_never_waits(queue):
    with patch.object(queue.subprocess, "Popen") as popen:
        queue.spawn(queue.queue_root())
    assert popen.call_args.kwargs["start_new_session"] is True
    popen.return_value.wait.assert_not_called()
    popen.return_value.communicate.assert_not_called()


def test_replay_uses_original_storage_environment(queue, monkeypatch):
    root = queue.queue_root()
    queue.enqueue(root, {"session_id": "backend"})
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable/new")
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        queue.drain(root)
    env = run.call_args.kwargs["env"]
    assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    assert env.get("DATABASE_URL") != "postgresql://unreachable/new"


def test_interrupted_worker_leaves_event_for_next_drain(queue, tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX signal/FIFO interruption probe")
    root = queue.queue_root()
    key = queue.enqueue(root, {"session_id": "interrupted"})
    fifo = tmp_path / "ready"
    os.mkfifo(fifo)
    uvx = tmp_path / "uvx"
    uvx.write_text(
        f"#!{sys.executable}\nimport os, signal\n"
        f"f=os.open({str(fifo)!r}, os.O_WRONLY)\n"
        "os.write(f,b'R')\nsignal.pause()\n"
    )
    uvx.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    worker = subprocess.Popen(
        [sys.executable, "-S", str(SCRIPT), "drain"], start_new_session=True
    )
    try:
        with fifo.open("rb", buffering=0) as ready:
            assert ready.read(1) == b"R"
        assert (root / f"{key}.json").exists()
    finally:
        os.killpg(worker.pid, signal.SIGKILL)
        worker.wait()
    uvx.write_text(f"#!{sys.executable}\n")
    subprocess.run([sys.executable, "-S", str(SCRIPT), "drain"], check=True)
    assert queue.receipt(root / f"{key}.json").exists()


def test_concurrent_drains_process_event_once(queue, tmp_path, monkeypatch):
    root = queue.queue_root()
    queue.enqueue(root, {"session_id": "concurrent"})
    count = tmp_path / "calls"
    uvx = tmp_path / "uvx"
    uvx.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\n"
        f"p=Path({str(count)!r})\n"
        "with p.open('a') as f: f.write('called\\n')\n"
    )
    uvx.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    workers = [
        subprocess.Popen([sys.executable, "-S", str(SCRIPT), "drain"]) for _ in range(2)
    ]
    assert [worker.wait() for worker in workers] == [0, 0]
    assert count.read_text().splitlines() == ["called"]


def test_nonzero_worker_keeps_event_unacknowledged(queue):
    root = queue.queue_root()
    key = queue.enqueue(root, {"session_id": "failed-worker"})
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 1
        queue.drain(root)
    assert (root / f"{key}.json").exists()
    assert not queue.receipt(root / f"{key}.json").exists()
    assert "exited 1" in (root / f"{key}.error").read_text()


def test_worker_requires_matching_plugin_version(queue):
    manifest = json.loads((SCRIPT.parents[1] / ".codex-plugin/plugin.json").read_text())
    assert queue.package_requirement() == (
        "hypermnesia-mcp[postgresql,sqlite]==" + manifest["version"]
    )


def test_saved_backend_is_frozen_for_replay(queue, monkeypatch):
    for key in (
        "CORTEX_MEMORY_STORE_BACKEND",
        "CORTEX_BACKEND",
        "DATABASE_URL",
        "CORTEX_MEMORY_DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    root = queue.queue_root()
    marker = root.parent / "backend.json"
    marker.write_text('{"backend":"sqlite"}')
    key = queue.enqueue(root, {"session_id": "saved-backend"})
    marker.write_text('{"backend":"postgresql"}')
    saved = json.loads((root / f"{key}.json").read_text())
    assert saved["environment"]["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"


def test_busy_job_does_not_block_another_session(queue):
    root = queue.queue_root()
    blocked = queue.enqueue(root, {"session_id": "busy"})
    available = queue.enqueue(root, {"session_id": "available"})
    with queue.job_lock(root / f"{blocked}.json") as acquired:
        assert acquired
        with patch.object(queue.subprocess, "run") as run:
            run.return_value.returncode = 0
            queue.drain(root)
        assert run.call_count == 1
    assert (root / f"{blocked}.json").exists()
    assert queue.receipt(root / f"{available}.json").exists()


@pytest.mark.parametrize("configured", ["~/state", "relative", "  relative  "])
def test_root_and_job_paths_preserve_intake_context(
    queue, tmp_path, monkeypatch, configured
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", configured)
    monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", "relative.db")
    root = queue.queue_root()
    expected = tmp_path / ("state" if configured.startswith("~") else "relative")
    assert root == expected / "methodology/session-end-queue"
    key = queue.enqueue(root, {"session_id": "relative-paths"})
    with patch.object(queue.subprocess, "Popen") as popen:
        queue.spawn(root)
    assert popen.call_args.kwargs["env"]["CORTEX_CLAUDE_DIR"] == str(expected)
    monkeypatch.chdir(root)
    with patch.object(queue.subprocess, "run") as run:
        run.return_value.returncode = 0
        queue.run_job(root / f"{key}.json")
    assert run.call_args.kwargs["cwd"] == str(tmp_path)
    assert (
        run.call_args.kwargs["env"]["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"]
        == "relative.db"
    )
    assert run.call_args.kwargs["env"]["CORTEX_CLAUDE_DIR"] == str(expected)


def test_first_use_syncs_each_new_directory_link(queue, tmp_path):
    observed = []
    with patch.object(queue, "sync_directory", side_effect=observed.append):
        queue.durable_directory(tmp_path / "a/b/c")
    assert observed == [tmp_path, tmp_path / "a", tmp_path / "a/b"]
