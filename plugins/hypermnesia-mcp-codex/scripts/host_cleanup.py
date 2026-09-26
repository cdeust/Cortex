"""Wire the existing host-file purgers into the shared hook. source: ADR-1092"""

from pathlib import Path
from functools import partial

import codex_purge
import cleanup_intake
import session_purge
from cleanup_hooks import pushed
from cleanup_operations import git, no_open_files
from cleanup_registry import Protected, registry


def validate_pending(state):
    """Pending host records may only contain UUID keys and object values."""
    if not isinstance(state, dict):
        raise Protected("host cleanup ledger must be an object")
    for sid, record in state.items():
        session_purge.checked(sid)
        if not isinstance(record, dict):
            raise Protected("host cleanup records must be objects")


host_registry = partial(registry, validator=validate_pending)


def import_ended(args):
    """Transfer immutable end intake only after the host ledger is committed."""
    events = [
        item
        for item in cleanup_intake.read_pending(args.state, "host")
        if item[1]["host"] == args.host and item[1]["roots"] == cleanup_intake.roots()
    ]
    if not events:
        return
    name = (
        "codex-ended-sessions.json" if args.host == "codex" else "ended-sessions.json"
    )
    acknowledged = []
    with host_registry(Path(args.state).with_name(name)) as pending:
        for item in events:
            if import_one(args, item[1], pending):
                acknowledged.append(item)
    cleanup_intake.acknowledge(acknowledged)


def import_one(args, event, pending):
    sid = session_purge.checked(event["session"])
    if args.host == "codex":
        home, queue = codex_purge.roots()
        record = {"home": str(home), "queue": str(queue)}
        matching = sid not in pending or pending[sid] == record
    else:
        scope = session_purge.pending_scope(
            session_purge.claude_home(), session_purge.temp_root()
        )
        record = {
            "host": None,
            "tasks": session_purge.owns_tasks(Path(scope["root"]), sid),
            "scope": scope,
        }
        matching = sid not in pending or pending[sid].get("scope") == scope
    if not matching:
        return (
            False  # Keep intake and the prior scoped record; never overwrite ownership.
        )
    if args.event == "SessionStart" and sid == args.session:
        pending.pop(sid, None)
    else:
        pending.setdefault(sid, record)
    return True


def push_landed(payload, result):
    """Original push guard: removed verified tree or HEAD reached its upstream."""
    if isinstance(result, list) and any(
        r.get("status", "").startswith("removed worktree") for r in result
    ):
        return True
    try:
        git(payload.get("cwd") or ".", "merge-base", "--is-ancestor", "HEAD", "@{u}")
    except Protected:
        return False
    return True


def settle_claude(args):
    home, root = session_purge.claude_home(), session_purge.temp_root()
    ended = Path(args.state).with_name("ended-sessions.json")
    with host_registry(ended) as pending:
        result = session_purge.retry_ended(
            pending,
            (home, root),
            args.session,
            {"guard": no_open_files, "cancel_current": args.event == "SessionStart"},
        )
    if args.event == "SessionEnd":
        noted = {}
        result += session_purge.end_session(
            noted,
            (home, root),
            args.session,
            {"guard": no_open_files, "host": session_purge.host_pid()},
        )
        with host_registry(ended) as pending:
            result += save_end_result(
                pending, noted, args.session, session_purge.pending_scope(home, root)
            )
    return result


def save_end_result(pending, noted, session, scope):
    result = []
    current = pending.get(session, {})
    if session not in noted and current.get("scope") == scope:
        pending.pop(session, None)
    for sid, record in noted.items():
        if sid not in pending or pending[sid].get("scope") == record["scope"]:
            pending[sid] = record
        else:
            result.append({"session": sid, "protected": "different Claude roots"})
    return result


def after_hook(args, payload, result):
    session_purge.checked(args.session)
    import_ended(args)
    purged = []
    if args.event == "PostToolUse" and pushed(payload) and push_landed(payload, result):
        if args.host == "claude":
            purged += session_purge.purge_now(
                (session_purge.claude_home(), session_purge.temp_root()),
                args.session,
                no_open_files,
            )
        else:
            purged += codex_purge.purge(
                codex_purge.roots(), args.session, no_open_files, ended=False
            )
    if args.host == "codex":
        purged += codex_purge.settle(args, host_registry, no_open_files)
    elif args.event in ("SessionStart", "SessionEnd"):
        purged += settle_claude(args)
    return dict(result, purged=purged) if isinstance(result, dict) else result + purged
