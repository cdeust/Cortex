"""Lock-independent durable end events for the two cleanup consumers.

source: ADR-1092 . Unique event files cannot overwrite another hook's end marker.
"""

import json
import os
from pathlib import Path
import uuid

from cleanup_registry import Protected, save


def directory(state, consumer):
    if consumer not in ("worktree", "host"):
        raise Protected("unknown end-event consumer")
    state = Path(state).expanduser().absolute()
    return state.with_name(state.name + ".ended") / consumer


def roots():
    return {
        "codex_home": str(
            Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser().resolve()
        ),
        "claude_home": str(
            Path(os.environ.get("CORTEX_CLAUDE_DIR") or "~/.claude")
            .expanduser()
            .resolve()
        ),
        "claude_tmp": str(
            Path(os.environ.get("CLAUDE_CODE_TMPDIR") or "/tmp").expanduser().resolve()
        ),
    }


def record_end(args, payload):
    event = {
        "host": args.host,
        "session": args.session,
        "roots": roots(),
        "cwd": payload.get("cwd"),
        "payload": payload,
    }
    event_id = uuid.uuid4().hex + ".json"
    for consumer in ("worktree", "host"):
        folder = directory(args.state, consumer)
        folder.mkdir(parents=True, exist_ok=True)
        save(folder / event_id, event)
        if os.name != "nt":
            descriptor = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return event


def read_pending(state, consumer):
    events = []
    for path in sorted(directory(state, consumer).glob("*.json")):
        if path.is_symlink():
            raise Protected("symlink end intake")
        event = json.loads(path.read_text())
        if (
            not isinstance(event, dict)
            or event.get("host") not in ("claude", "codex")
            or not isinstance(event.get("session"), str)
            or not event["session"]
            or not isinstance(event.get("roots"), dict)
        ):
            raise Protected("invalid end intake")
        events.append((path, event))
    return events


def acknowledge(events):
    # Each filename is a unique immutable event, never an owner slot reused by resume.
    for path, _event in events:
        path.unlink(missing_ok=True)


def merge_worktrees(state, events):
    ended = state.setdefault("_ended", {})
    for _path, event in events:
        ended[event["host"] + ":" + event["session"]] = True
