"""Durable intake before uvx startup; Python standard library only.

source: ADR-1084
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

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
            saved = json.loads(marker.read_text())["backend"]
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
    completed = path.parent / "completed"
    durable_directory(completed)
    return completed / path.name


def enqueue(root, event):
    if not isinstance(event, dict) or not isinstance(event.get("session_id"), str):
        raise ValueError("SessionEnd requires a nonempty session_id")
    if not event["session_id"].strip():
        raise ValueError("SessionEnd requires a nonempty session_id")
    key = hashlib.sha256(event["session_id"].encode()).hexdigest()
    target = root / f"{key}.json"
    if receipt(target).exists():
        return key
    fd, tmp = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {"event": event, "environment": environment(), "cwd": str(Path.cwd())},
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            pass
        sync_directory(root)
    finally:
        os.unlink(tmp)
    return key


def spawn(root):
    fd = os.open(root / "worker.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "drain"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
            cwd=root,
            env={**os.environ, "CORTEX_CLAUDE_DIR": str(root.parent.parent)},
        )


@contextmanager
def job_lock(path):
    locks = path.parent / "locks"
    durable_directory(locks)
    fd = os.open(locks / path.stem, os.O_RDWR | os.O_CREAT, 0o600)
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


def package_requirement():
    manifest = Path(__file__).resolve().parents[1] / ".codex-plugin/plugin.json"
    version = json.loads(manifest.read_text())["version"]
    return f"hypermnesia-mcp[postgresql,sqlite]=={version}"


def run_job(path):
    if receipt(path).exists():
        path.unlink()
        return
    job = json.loads(path.read_text())
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CORTEX_")
        and k not in {"DATABASE_URL", "CLAUDE_PROJECT_ROOT"}
    }
    env.update(job["environment"])
    result = subprocess.run(
        [
            "uvx",
            "--from",
            package_requirement(),
            "hypermnesia-mcp-hook",
            "session_lifecycle",
        ],
        input=json.dumps(job["event"]),
        text=True,
        env=env,
        cwd=job["cwd"],
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"lifecycle exited {result.returncode}")
    os.replace(path, receipt(path))
    sync_directory(receipt(path).parent)
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
                with os.fdopen(fd, "w") as stream:
                    stream.write(message)


def main():
    if os.environ.get("CORTEX_HEADLESS_AUTHORING_CHILD") == "1":
        return
    root = queue_root()
    mode = sys.argv[1]
    if mode == "drain":
        drain(root)
        return
    if mode == "intake":
        enqueue(root, json.load(sys.stdin))
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
            print(error.read_text(), file=sys.stderr)
        spawn(root)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"[cortex SessionEnd] durable queue failed: {exc}", file=sys.stderr)
        sys.exit(1)
