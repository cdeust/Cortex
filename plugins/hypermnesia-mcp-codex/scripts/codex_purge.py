"""Codex session artifacts, with durable Cortex reader completion protection.

source: ADR-1092 (native Codex source hook trial 2026-09-26).
No shared databases or generated images are disposable.
Only explicitly ended session IDs enter the retry ledger.
"""

import hashlib
import json
import os

import transcript_policy
from pathlib import Path

import session_purge


ARTIFACTS = (
    "shell_snapshots/{sid}.*.sh",
    "shell_snapshots/{sid}.sh",
    "tui-thread-reference-capabilities/{sid}",
)
TRANSCRIPTS = (
    "sessions/*/*/*/rollout-*-{sid}.jsonl",
    "archived_sessions/rollout-*-{sid}.jsonl",
)


def roots():
    home = (
        Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        .expanduser()
        .absolute()
    )
    cortex = (
        Path(os.environ.get("CORTEX_CLAUDE_DIR") or Path.home() / ".claude")
        .expanduser()
        .absolute()
    )
    return home, cortex / "methodology/session-end-queue/completed"


def completed(queue, session, transcript):
    """The installed Cortex queue moves the original event after reader success."""
    key = hashlib.sha256(session.encode()).hexdigest()
    try:
        receipt = queue / (key + ".json")
        event = json.loads(receipt.read_text())["event"]
        return (
            event["session_id"] == session
            and Path(event["transcript_path"]).absolute() == transcript.absolute()
            and receipt.stat().st_mtime_ns >= transcript.stat().st_mtime_ns
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def purge(locations, session, guard, ended=True):
    home, queue = locations
    sid = session_purge.checked(session)
    results = []
    lock = home / "thread-writer-locks" / (sid + ".lock")
    try:
        check_writer(lock, guard)
    except RuntimeError as exc:
        return [{"path": str(lock), "protected": str(exc)}]
    patterns = ARTIFACTS + (TRANSCRIPTS if transcript_policy.delete_enabled() else ())
    for pattern in patterns:
        for path in home.glob(pattern.format(sid=sid)):
            # Never follow a symlinked ancestor out of the session namespace.
            if path.parent.resolve() != path.parent.absolute():
                results.append({"path": str(path), "protected": "symlink parent"})
                continue
            if pattern in TRANSCRIPTS and (
                not ended or not completed(queue, sid, path)
            ):
                results.append(
                    {
                        "path": str(path),
                        "protected": "Cortex completion receipt pending",
                    }
                )
                continue
            try:
                results.extend(session_purge.remove_tree(path, guard))
            except OSError as exc:
                results.append({"path": str(path), "protected": str(exc)})
    return results


def settle(args, registry, guard):
    """Retry ended sessions on each event; resume cancels that session's entry."""
    session_purge.checked(args.session)
    home, queue = roots()
    ledger = Path(args.state).with_name("codex-ended-sessions.json")
    results = []
    with registry(ledger) as pending:
        scope = {"home": str(home), "queue": str(queue)}
        matching = args.session not in pending or pending[args.session] == scope
        if args.event == "SessionStart" and matching:
            pending.pop(args.session, None)
        if args.event == "SessionEnd":
            if not matching:
                return [{"session": args.session, "protected": "different Codex roots"}]
            pending[args.session] = scope
            return []  # Native Codex SessionEnd is limited to three seconds; ADR-1092.
        for sid, record in list(pending.items()):
            if sid == args.session and args.event != "SessionEnd":
                continue
            if record != {"home": str(home), "queue": str(queue)}:
                continue  # Another configured home owns this entry.
            done = purge((home, queue), sid, guard)
            results.extend(done)
            if not any("protected" in r for r in done):
                del pending[sid]
    return results


def check_writer(lock, guard):
    if lock.exists():
        guard(str(lock))
