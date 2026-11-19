"""Durable intake before uvx startup; Python standard library only.

source: ADR-1084
"""

from __future__ import annotations

import errno
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl
from contextlib import contextmanager


def queue_root():
    configured = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".claude"
    path = root.resolve() / "methodology" / "session-end-queue"
    durable_directory(path)
    return path


def sync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def durable_directory(path):
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True, mode=0o700)
        sync_directory(directory.parent)


def environment():
    keys = {"DATABASE_URL", "CLAUDE_PROJECT_ROOT"}
    env = {k: v for k, v in os.environ.items() if k.startswith("CORTEX_") or k in keys}
    env["CORTEX_CLAUDE_DIR"] = str(queue_root().parent.parent)
    # source: ADR-0505 (freeze the existing backend precedence for replay).
    configured = (
        env.get("CORTEX_MEMORY_STORE_BACKEND", "").strip()
        or env.get("CORTEX_BACKEND", "").strip().lower()
        in {"sqlite", "postgres", "postgresql"}
        or env.get("DATABASE_URL", "").strip()
        or env.get("CORTEX_MEMORY_DATABASE_URL", "").strip()
    )
    if not configured:
        marker = queue_root().parent / "backend.json"
        backend = "auto"
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))["backend"]
            if saved not in {"sqlite", "postgresql"}:
                raise ValueError("invalid saved Cortex backend")
            backend = saved
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(
                f"[cortex SessionEnd] backend marker unreadable: {exc}", file=sys.stderr
            )
        env["CORTEX_MEMORY_STORE_BACKEND"] = backend
    return env


def receipt(path):
    """One receipt per ``job_key``, also for ``<key>-<ns>``. source: ADR-1145"""
    completed = path.parent / "completed"
    durable_directory(completed)
    return completed / f"{path.stem.split('-')[0]}.json"


def job_key(event):
    """One job per session and rollout file, so a continued session's second
    file is not dropped as a replay of the first (#716). The same value as
    ``mcp_server.shared.injection_markers.session_end_event_id``.

    source: ADR-1141
    """
    path = event.get("transcript_path")
    stem = Path(path).stem if isinstance(path, str) and path else ""
    text = f"{event['session_id']}\0{stem}" if stem else event["session_id"]
    return hashlib.sha256(text.encode()).hexdigest()


def enqueue(root, event):
    if not isinstance(event, dict) or not isinstance(event.get("session_id"), str):
        raise ValueError("SessionEnd requires a nonempty session_id")
    if not event["session_id"].strip():
        raise ValueError("SessionEnd requires a nonempty session_id")
    key = job_key(event)
    target, rollout = root / f"{key}.json", event.get("transcript_path")
    if not isinstance(rollout, str) and receipt(target).exists():
        return key
    fd, tmp = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {"event": event, "environment": environment(), "cwd": str(Path.cwd())},
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            if not isinstance(rollout, str):
                return key
            # The pending job may already be reading older bytes (ADR-1145).
            target = root / f"{key}-{time.time_ns()}.json"
            os.link(tmp, target)
        sync_directory(root)
    finally:
        os.unlink(tmp)
    return target.stem


# CPython ignores start_new_session on Windows; there the drain's flags are
# decided from the measured job by windows_job.py, the stdlib copy of
# mcp_server.shared.detached_spawn (this script ships without mcp_server).
# source: ADR-1102 (the Codex drain follows the shared decision).
_WINDOWS = os.name == "nt"


def _windows_job():
    return _sibling("windows_job")


@functools.lru_cache(maxsize=None)
def _sibling(name):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"cortex_codex_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detach_options():
    if _WINDOWS:
        return {"creationflags": _windows_job().measured_creationflags()}
    return {"start_new_session": True}


def spawn(root):
    fd = os.open(root / "worker.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "drain"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            **detach_options(),
            cwd=root,
            env={**os.environ, "CORTEX_CLAUDE_DIR": str(root.parent.parent)},
        )


@contextmanager
def job_lock(path):
    locks = path.parent / "locks"
    durable_directory(locks)
    fd = os.open(locks / receipt(path).stem, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if os.name == "nt":
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EAGAIN, errno.EACCES}:
                raise
            yield False
            return
        yield True
    finally:
        os.close(fd)


def run_job(path):
    job = json.loads(path.read_text(encoding="utf-8"))
    rollout = _sibling("rollout_version")
    current = rollout.version(job["event"])  # hashed here, never at intake
    if rollout.is_replay(receipt(path), current):
        path.unlink()
        return
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CORTEX_")
        and k not in {"DATABASE_URL", "CLAUDE_PROJECT_ROOT"}
    }
    env.update(job["environment"])
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("runtime.py")),
            "session_lifecycle",
        ],
        input=json.dumps(job["event"]),
        text=True,
        encoding="utf-8",  # the hook reads its stdin as strict UTF-8 (#664)
        env=env,
        cwd=job["cwd"],
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"lifecycle exited {result.returncode}")
    rollout.record(receipt(path), job, current)
    sync_directory(receipt(path).parent)
    path.unlink()
    path.with_suffix(".error").unlink(missing_ok=True)
    sync_directory(path.parent)


def drain(root):
    for path in sorted(root.glob("*.json")):
        with job_lock(path) as acquired:
            if not acquired or not path.exists():
                continue
            try:
                run_job(path)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                message = f"[cortex SessionEnd] {path.name}: {exc}"
                print(message, file=sys.stderr, flush=True)
                fd = os.open(
                    path.with_suffix(".error"),
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(message)


def read_event():
    """The SessionEnd event from stdin, decoded as UTF-8.

    The host writes UTF-8; text-mode stdin would decode with the locale code
    page (cp1252 on Windows), issue #664. Invalid UTF-8 is reported on stderr
    and exits 1 (this hook blocks nothing), never replaced.
    """
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except UnicodeDecodeError as exc:
        print(
            f"[cortex SessionEnd] event on stdin is not valid UTF-8: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    if os.environ.get("CORTEX_HEADLESS_AUTHORING_CHILD") == "1":
        return
    root = queue_root()
    mode = sys.argv[1]
    if mode == "drain":
        drain(root)
        return
    if mode == "intake":
        enqueue(root, read_event())
    elif mode != "recover":
        raise ValueError(f"unknown queue mode: {mode}")
    pending = list(root.glob("*.json"))
    if pending:
        print(
            f"[cortex SessionEnd] {len(pending)} pending; "
            f"worker log: {root / 'worker.log'}",
            file=sys.stderr,
        )
        for error in root.glob("*.error"):
            print(error.read_text(encoding="utf-8"), file=sys.stderr)
        spawn(root)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"[cortex SessionEnd] durable queue failed: {exc}", file=sys.stderr)
        sys.exit(1)
