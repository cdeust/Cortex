"""Deterministic PreToolUse boundary for untrusted native review sessions.

Sources: anthropics/claude-code plugins/code-review/commands/code-review.md
frontmatter grants gh reads/writes; https://code.claude.com/docs/en/skills
says allowed-tools adds grants. https://code.claude.com/docs/en/hooks specifies
PreToolUse deny precedence. The trusted settings command maps every error to
exit2, which blocks a tool even if Python cannot load this guard.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import sys
from pathlib import Path

# Native review inputs, subagent results and internal task bookkeeping only.
INPUT_AND_TASK_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "LS",
        "TodoWrite",
        "TaskOutput",
        "TaskGet",
        "TaskList",
        "TaskCreate",
        "TaskUpdate",
        "TaskStop",
    }
)


def allowed(payload, environ):
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return False
    command = environ.get("CORTEX_REVIEW_PUBLISH_COMMAND")
    verdict = environ.get("CORTEX_REVIEW_FILE")
    skill = environ.get("CORTEX_REVIEW_SKILL")
    receipt_path = environ.get("CORTEX_REVIEW_GUARD_RECEIPT")
    sha = environ.get("HEAD_SHA")
    if not all(
        isinstance(value, str) and value
        for value in (command, verdict, skill, receipt_path, sha)
    ):
        return False
    if Path(verdict).is_symlink() or not Path(verdict).is_file():
        return False
    name, inputs = payload.get("tool_name"), payload["tool_input"]
    if name in INPUT_AND_TASK_TOOLS:
        return True
    if name in ("Agent", "Task"):
        return not inputs.get("isolation") and inputs.get("mode") in (
            None,
            "default",
            "dontAsk",
        )
    if name == "Skill":
        return inputs.get("skill") == skill
    if name == "Bash":
        return inputs.get("command") == command
    if name == "Edit" and isinstance(inputs.get("file_path"), str):
        target = Path(verdict).resolve(strict=True)
        return (
            target.is_file()
            and Path(inputs["file_path"]).resolve(strict=True) == target
        )
    return False


def record(payload, permitted, environ):
    path = Path(environ["CORTEX_REVIEW_GUARD_RECEIPT"])
    if path.is_symlink():
        raise ValueError("receipt symlink")
    value = dict(
        sha=environ["HEAD_SHA"],
        skill=environ["CORTEX_REVIEW_SKILL"],
        verdict=environ["CORTEX_REVIEW_FILE"],
        tool=payload["tool_name"],
        decision="allow" if permitted else "deny",
    )
    # Concurrent subagent hooks serialize one append; no external work holds the lock.
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(value) + "\n")
        stream.flush()


def verify(path, skill, verdict, sha):
    if not all((skill, verdict, sha)):
        raise ValueError("missing context")
    allowed_tools = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not isinstance(row, dict) or (
            row.get("sha"),
            row.get("skill"),
            row.get("verdict"),
        ) != (sha, skill, verdict):
            raise ValueError("receipt context")
        if row.get("decision") not in ("allow", "deny") or not isinstance(
            row.get("tool"), str
        ):
            raise ValueError("receipt decision")
        if row["decision"] == "allow":
            allowed_tools.add(row["tool"])
    if not {"Skill", "Edit", "Bash"}.issubset(allowed_tools):
        raise ValueError("missing native guard events")


def settings(path):
    command = shlex.join([sys.executable, "-I", str(Path(__file__).resolve())])
    # A broken/missing guard must block, not become a non-blocking hook error.
    hook = {"type": "command", "command": command + " || exit 2"}
    value = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}}
    Path(path).write_text(json.dumps(value) + "\n", encoding="utf-8")


def main():
    try:
        payload = json.load(sys.stdin)
        permitted = allowed(payload, os.environ)
        record(payload, permitted, os.environ)
    except (ValueError, TypeError, KeyError, OSError):
        permitted = False
    decision = "allow" if permitted else "deny"
    result = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    result["permissionDecisionReason"] = (
        "Review inputs are read-only; only the fixed verdict edit "
        "and exact publication command may write."
    )
    print(json.dumps({"hookSpecificOutput": result}))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings")
    parser.add_argument("--verify")
    parser.add_argument("--skill")
    parser.add_argument("--verdict")
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.settings:
        settings(args.settings)
    elif args.verify:
        try:
            verify(args.verify, args.skill, args.verdict, args.sha)
        except (ValueError, TypeError, OSError):
            print(
                "Claude review guard: missing, invalid or incomplete native receipt",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        sys.exit(main())
