"""Shared host lifecycle adapter for the disk-hygiene cleanup protocol."""

# Source: ADR-1092 — explicit owner markers, no inferred ownership or host file sweep.
import json
from pathlib import Path
import re
import shlex

from cleanup_operations import Protected, dispose, trees


def scope(cwd):
    listing = trees(cwd)
    if not listing:
        raise Protected("cannot identify main checkout")
    return str(Path(listing[0]["worktree"]).resolve())


def recover(state, owner, cwd):
    ended = state.setdefault("_ended", {})
    ended.pop(owner, None)  # Resuming an owner cancels its end marker.
    eligible = [
        (p, r) for p, r in state.items() if p != "_ended" and r.get("owner") in ended
    ]
    if not eligible:
        return []
    try:
        repo = scope(cwd)
    except Protected as exc:
        return [{"path": p, "protected": str(exc)} for p, _ in eligible]
    result = []
    for path, record in list(state.items()):
        if path == "_ended" or record.get("owner") not in ended:
            continue
        if record.get("repo") == repo:
            result += dispose(state, record["owner"], path)
    for previous in list(ended):
        if not any(
            r.get("owner") == previous for p, r in state.items() if p != "_ended"
        ):
            del ended[previous]
    return result


def pushed(payload):
    text = json.dumps(payload.get("tool_input", {}))
    return bool(
        re.search(r"\bgit(?:\s+-C\s+\S+)?\s+push\b", text)
        or "gh pr create" in text
        or "create_pull_request" in payload.get("tool_name", "")
    )


def hook_result(state, owner, args, payload):
    if args.event == "SessionEnd":
        state.setdefault("_ended", {})[owner] = True
        return {"ended": owner}
    if args.event == "SessionStart":
        result = recover(state, owner, payload.get("cwd") or str(Path.cwd()))
        return startup_context(args, result)
    if args.event == "Stop" or (args.event == "PostToolUse" and pushed(payload)):
        result = dispose(state, owner)
        blocked = [r for r in result if "protected" in r]
        if args.event == "Stop" and not payload.get("stop_hook_active") and blocked:
            return {
                "decision": "block",
                "reason": "Owned cleanup remains: " + json.dumps(blocked),
            }
        return result
    return []


def startup_context(args, result):
    entry = str(Path(__file__).with_name("disk_hygiene.py"))
    command = shlex.join(
        [
            "python3",
            entry,
            "--host",
            args.host,
            "--session",
            args.session,
            "register-worktree",
            "--repo",
            "MAIN_CHECKOUT",
            "--path",
            "NEW_WORKTREE",
        ]
    )
    context = (
        "Register each new worktree: "
        + command
        + ". Link its PR and preserve evidence before dispose. "
        + "Transcripts are retained by default. Cleanup: "
        + json.dumps(result)
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
