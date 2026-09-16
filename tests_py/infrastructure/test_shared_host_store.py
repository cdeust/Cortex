"""Independent host processes observe the same committed SQLite memories.

source: docs/shared-host-memory.md. This tests persistence, not semantic recall
or automatic host capture; project ADR isolation is tested through real MCP.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[2]


# Test liveness/cleanup budgets, not memory-store performance requirements.
# source: docs/shared-host-memory.md — test liveness budget policy.
PROTOCOL_TIMEOUT = 30
# source: docs/shared-host-memory.md — test liveness budget policy.
CLEANUP_TIMEOUT = 5


def _readline(process):
    deadline = time.monotonic() + PROTOCOL_TIMEOUT
    line = bytearray()
    while not line.endswith(b"\n"):
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([process.stdout], [], [], max(0, remaining))
        assert ready and remaining > 0, "shared-store worker response timed out"
        chunk = os.read(process.stdout.fileno(), 1)
        assert chunk, "shared-store worker exited without acknowledgement"
        line.extend(chunk)
    return json.loads(line)


def _exchange(process, payload):
    data = (json.dumps(payload) + "\n").encode()
    deadline = time.monotonic() + PROTOCOL_TIMEOUT
    while data:
        remaining = deadline - time.monotonic()
        _, ready, _ = select.select([], [process.stdin], [], max(0, remaining))
        assert ready and remaining > 0, "shared-store worker request timed out"
        data = data[os.write(process.stdin.fileno(), data) :]
    return _readline(process)


def _stop(process):
    process.stdin.close()
    try:
        process.wait(timeout=CLEANUP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=CLEANUP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=CLEANUP_TIMEOUT)
    finally:
        process.stdout.close()


def _environment(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CORTEX_")}
    env.pop("DATABASE_URL", None)
    database = str(root / "memory.db")
    env.update(
        CORTEX_CLAUDE_DIR=str(root),
        CORTEX_MEMORY_STORE_BACKEND="sqlite",
        CORTEX_MEMORY_DB_PATH=database,
        CORTEX_MEMORY_SQLITE_FALLBACK_PATH=database,
    )
    return env


@contextmanager
def _worker(root):
    with tempfile.TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests_py.fixtures.shared_host_store_worker"],
            cwd=REPO,
            env=_environment(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            bufsize=0,
        )
        try:
            yield process, _readline(process)
        finally:
            failed = sys.exc_info()[0] is not None
            _stop(process)
            if not failed:
                errors.seek(0)
                assert process.returncode == 0, errors.read()


def _concurrent_writes(claude, codex):
    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [
            pool.submit(
                _exchange,
                process,
                {
                    "operation": "write",
                    "content": f"ADR-0056 outcome from {host}",
                    "source": host,
                },
            )
            for process, host in [
                (claude, "claude-test"),
                (codex, "codex-test"),
            ]
        ]
        return [future.result(timeout=PROTOCOL_TIMEOUT) for future in writes]


def test_cross_process_handoff_and_concurrent_acknowledged_writes(tmp_path):
    with _worker(tmp_path) as (claude, first):
        with _worker(tmp_path) as (codex, second):
            assert first["pid"] != second["pid"]
            assert first["backend"] == second["backend"] == "SqliteMemoryStore"
            original = _exchange(
                claude,
                {
                    "operation": "write",
                    "content": "ADR-0056: adopt shared memory",
                    "source": "claude-test",
                },
            )
            seen = _exchange(codex, {"operation": "read", "id": original})
            assert seen["content"] == "ADR-0056: adopt shared memory"
            assert seen["source"] == "claude-test"
            identifiers = _concurrent_writes(claude, codex)
            assert len({original, *identifiers}) == 3
            for identifier, host in zip(
                identifiers, ["claude-test", "codex-test"], strict=True
            ):
                for process in (claude, codex):
                    record = _exchange(process, {"operation": "read", "id": identifier})
                    assert record["content"] == f"ADR-0056 outcome from {host}"
                    assert record["source"] == host
    with _worker(tmp_path) as (reopened, _):
        assert _exchange(reopened, {"operation": "read", "id": original}) == seen
