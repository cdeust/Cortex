"""Durable ownership ledger; fail closed on invalid data or unavailable locks."""

# Source: ADR-1092 — disk-hygiene atomic ledger protocol.
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class ProtectedError(RuntimeError):
    pass


Protected = ProtectedError


def validate(state):
    if not isinstance(state, dict):
        raise Protected("registry must be an object")
    for path, record in state.items():
        if not isinstance(record, dict):
            raise Protected("registry records must be objects")
        if path == "_ended":
            if not all(isinstance(k, str) and v is True for k, v in record.items()):
                raise Protected("invalid ended owners")
            continue
        if not Path(path).is_absolute() or record.get("kind") not in (
            "temp",
            "worktree",
        ):
            raise Protected("invalid registered path or kind")
        if not isinstance(record.get("owner"), str) or not isinstance(
            record.get("identity"), list
        ):
            raise Protected("invalid registered owner or identity")
        if record["kind"] == "worktree" and not all(
            isinstance(record.get(k), str) for k in ("repo", "branch")
        ):
            raise Protected("invalid worktree record")


@contextmanager
def lock_file(handle):
    if os.name == "nt":
        handle.seek(0)
        if not handle.read(1):
            handle.write("0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(path, state):
    fd, pending = tempfile.mkstemp(prefix=".hygiene-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


@contextmanager
def registry(path, validator=validate):
    path = Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+") as handle, lock_file(handle):
        state = json.loads(path.read_text()) if path.exists() else {}
        validator(state)
        yield state
        validator(state)
        save(path, state)
