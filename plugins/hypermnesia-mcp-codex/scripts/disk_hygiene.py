#!/usr/bin/env python3
"""Explicit session-owned cleanup, shared by Claude Code and Codex."""

# Source: ADR-1092; local disk-hygiene CLI port.
import argparse
import json
import os
from pathlib import Path
import re
import sys

from cleanup_registry import Protected, registry
from cleanup_operations import (
    register_worktree,
    owned,
    validate_pr,
    create_temp,
    preserve,
    dispose,
)
from cleanup_hooks import hook_result
import cleanup_intake
import host_cleanup
import transcript_policy


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        default=str(
            Path(os.environ.get("CORTEX_CLAUDE_DIR", "~/.claude")).expanduser()
            / "methodology/worktree-cleanup.json"
        ),
    )
    parser.add_argument("--host", required=True, choices=["claude", "codex"])
    parser.add_argument("--session")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register-worktree")
    reg.add_argument("--path", required=True)
    reg.add_argument("--repo", required=True)
    reg.add_argument("--pr")
    link = sub.add_parser("link-pr")
    link.add_argument("--path", required=True)
    link.add_argument("--pr", required=True)
    temp = sub.add_parser("create-temp")
    temp.add_argument("--parent", required=True)
    evidence = sub.add_parser("evidence-preserved")
    evidence.add_argument("--path", required=True)
    evidence.add_argument("--evidence", required=True)
    clean = sub.add_parser("dispose")
    clean.add_argument("--path")
    clean.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    hook = sub.add_parser("hook")
    hook.add_argument(
        "event", choices=["PostToolUse", "SessionStart", "SessionEnd", "Stop"]
    )
    args = parser.parse_args()
    for key in ("path", "repo", "parent", "evidence"):
        value = getattr(args, key, None)
        if value:
            setattr(args, key, str(Path(value).expanduser().absolute()))
    return args


def execute(state, owner, args, payload):
    if args.command == "register-worktree":
        register_worktree(state, owner, args.path, {"repo": args.repo, "pr": args.pr})
        return {"registered": args.path}
    if args.command == "link-pr":
        record = owned(state, owner, args.path)
        if record["kind"] != "worktree":
            raise Protected("only worktrees can be linked to PRs")
        validate_pr(args.pr)
        record["pr"] = args.pr
        return {"linked": args.path, "pr": args.pr}
    if args.command == "create-temp":
        return create_temp(state, owner, args.parent)
    if args.command == "evidence-preserved":
        preserve(state, owner, args.path, args.evidence)
        return {"evidence_preserved": args.path}
    if args.command == "dispose":
        return dispose(state, owner, args.path, {"dry_run": args.dry_run})
    if args.command == "hook":
        return hook_result(state, owner, args, payload)
    return {p: r for p, r in state.items() if p != "_ended" and r["owner"] == owner}


def main():
    args = parse_args()
    transcript_policy.delete_enabled()  # Validate consent before any cleanup.
    payload = json.load(sys.stdin) if args.command == "hook" else {}
    if not isinstance(payload, dict):
        raise Protected("hook payload must be an object")
    args.session = (
        args.session
        or payload.get("session_id")
        or (os.environ.get("CODEX_THREAD_ID") if args.host == "codex" else None)
    )
    if not isinstance(args.session, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", args.session
    ):
        raise Protected(
            "explicit session identity is required; no ownership inferred from cwd"
        )
    result = run_command(args, payload)
    print(json.dumps(result))


def run_command(args, payload):
    owner = args.host + ":" + args.session
    is_hook = args.command == "hook"
    if is_hook and args.event == "SessionEnd":
        cleanup_intake.record_end(args, payload)
        result = {"ended": owner}
        if args.host == "claude":
            result = host_cleanup.after_hook(args, payload, result)
        return result
    events = []
    if is_hook and args.event == "SessionStart":
        events = cleanup_intake.read_pending(args.state, "worktree")
    with registry(args.state) as state:
        if events:
            cleanup_intake.merge_worktrees(state, events)
        result = execute(state, owner, args, payload)
    cleanup_intake.acknowledge(events)
    if is_hook:
        result = host_cleanup.after_hook(args, payload, result)
    return result


if __name__ == "__main__":
    try:
        main()
    except (Protected, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"protected": str(error)}))
        sys.exit(1)
