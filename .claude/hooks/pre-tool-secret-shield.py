#!/usr/bin/env python3
"""PreToolUse hook — block reads of credential-bearing files & commands.

Reads the Claude Code tool-event JSON from stdin:
    {"tool_name": "Read"|"Bash"|"Grep"|..., "tool_input": {...}}

Exits with code 2 (blocking) when the call would surface credentials,
emitting a one-line reason to stderr that Claude sees. Allows everything
else with exit 0 — so this hook adds zero friction for non-secret paths.

Threat model
------------
The agent must never have any reason to *read* the contents of:
- `.env*` files anywhere in the tree
- shell-credential files (`.aws/credentials`, `.netrc`, `.git-credentials`,
  `gh/hosts.yml`)
- private keys (`*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `*.p12`, `*.pfx`)
- explicit secret directories (`secrets/`, `secret/`, `vault/`)
- known-bait fixtures (`pii-fixtures/tp-*`)
- shell history (`.bash_history`, `.zsh_history`)
- keychain / keyring files

If you legitimately need to inspect one of these, override per-call via the
permissions allow-list, or relocate the file to a non-matched path.

Why blocking READS is enough
----------------------------
Writing/Editing a credential file (e.g. setting up a fresh `.env`) does not
require reading existing contents — the content the agent writes is from the
prompt, not from the file. So Edit/Write to these paths is allowed but
flagged with a stderr note. The agent is asked to confirm intent.

Tools intercepted: Read, Bash, Grep, Edit, Write, NotebookEdit.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

BLOCKED_PATH_PATTERNS: list[str] = [
    r"(^|/)\.env(\.[^/]+)?$",
    r"(^|/)credentials(\.[^/]+)?$",
    r"(^|/)\.aws/credentials$",
    r"(^|/)\.aws/config$",
    r"(^|/)\.netrc$",
    r"(^|/)\.git-credentials$",
    r"(^|/)\.config/gh/hosts\.yml$",
    r"(^|/)\.docker/config\.json$",
    r"(^|/)\.npmrc$",
    r"(^|/)\.pypirc$",
    r"(^|/)\.gem/credentials$",
    r"(^|/)id_(rsa|ed25519|ecdsa|dsa)(\.[^/]+)?$",
    r"(^|/)\.ssh/.*$",
    r"(^|/)\.gnupg/.*$",
    r"\.(pem|key|p12|pfx|jks|keystore)$",
    r"(^|/)secrets?/",
    r"(^|/)vault/",
    r"(^|/)pii-fixtures/tp-[^/]*$",
    r"(^|/)tp-known-secrets",
    r"(^|/)\.(bash|zsh|fish)_history$",
    r"(^|/)\.python_history$",
    r"(^|/)\.psql_history$",
    r"(^|/)\.mysql_history$",
    r"(^|/)\.node_repl_history$",
    r"keychain",
    r"keyring",
    r"login\.keychain-db$",
]

BLOCKED_PATH_RE = re.compile("|".join(BLOCKED_PATH_PATTERNS), re.IGNORECASE)

BASH_READ_VERBS = re.compile(
    r"\b(cat|less|more|head|tail|bat|grep|rg|ag|awk|sed|cut|sort|uniq|wc|"
    r"file|tee|cp|mv|rsync|scp|curl|wget|base64|xxd|od|strings|jq|yq|"
    r"python3?|node|ruby|perl|sh|bash|zsh|fish|env|printenv|"
    r"openssl|gpg|ssh-keygen)\b",
    re.IGNORECASE,
)

BASH_ENV_LEAK = re.compile(
    r"\b(printenv|env\s*$|export\s*-p|set\s*$|"
    r"echo\s+\$\{?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|"
    r"API|AUTH|PRIVATE|CERT)[A-Z_]*\}?)\b",
    re.IGNORECASE,
)

BLOCKED_PATTERNS_EMBEDDED = re.compile(
    r"(?<![A-Za-z0-9])("
    r"\.env(\.[A-Za-z0-9_-]+)?"
    r"|\.aws/(credentials|config)"
    r"|\.(netrc|git-credentials|npmrc|pypirc)"
    r"|\.config/gh/hosts\.yml"
    r"|\.ssh/[A-Za-z0-9._/-]+"
    r"|\.gnupg/[A-Za-z0-9._/-]+"
    r"|id_(rsa|ed25519|ecdsa|dsa)(\.[A-Za-z0-9]+)?"
    r"|credentials(\.[A-Za-z0-9_-]+)?"
    r"|(secrets?|vault)/[A-Za-z0-9._/-]*"
    r"|tp-known-secrets[A-Za-z0-9._-]*"
    r"|\.(bash|zsh|fish|python|psql|mysql|node_repl)_history"
    r"|[A-Za-z0-9_-]+\.(pem|key|p12|pfx|jks|keystore)"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def is_blocked_path(p: str) -> tuple[bool, str | None]:
    if not p:
        return False, None
    m = BLOCKED_PATH_RE.search(p)
    return (bool(m), m.group(0) if m else None)


def bash_blocked(cmd: str) -> tuple[bool, str | None]:
    if not cmd:
        return False, None
    if BASH_ENV_LEAK.search(cmd):
        return True, "env-var dump (printenv/env/export -p / echo $SECRET)"
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        tokens = cmd.split()
    has_read_verb = bool(BASH_READ_VERBS.search(cmd))
    if not has_read_verb:
        return False, None
    for tok in tokens:
        candidate = tok.lstrip("@-+")
        is_b, pattern = is_blocked_path(candidate)
        if is_b:
            return True, (
                f"read of credential-bearing path '{candidate}' (pattern '{pattern}')"
            )
    m = BLOCKED_PATTERNS_EMBEDDED.search(cmd)
    if m:
        return True, f"credential path embedded in command: '{m.group(0)}'"
    return False, None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    tool = event.get("tool_name", "")
    tin = event.get("tool_input", {}) or {}

    blocked_reason: str | None = None

    if tool == "Read":
        path = tin.get("file_path", "")
        is_blocked, pattern = is_blocked_path(path)
        if is_blocked:
            blocked_reason = (
                f"Read blocked: {path} matches credential pattern '{pattern}'"
            )
    elif tool == "Bash":
        cmd = tin.get("command", "")
        is_blocked, reason = bash_blocked(cmd)
        if is_blocked:
            blocked_reason = f"Bash blocked: {reason}. Command: {cmd[:160]}" + (
                "…" if len(cmd) > 160 else ""
            )
    elif tool == "Grep":
        for key in ("path", "include"):
            v = tin.get(key, "")
            is_blocked, pattern = is_blocked_path(v) if v else (False, None)
            if is_blocked:
                blocked_reason = (
                    f"Grep blocked: {key}={v} matches credential pattern '{pattern}'"
                )
                break
    elif tool in ("Edit", "Write", "NotebookEdit"):
        path = tin.get("file_path", "")
        is_blocked, pattern = is_blocked_path(path)
        if is_blocked:
            print(
                f"[secret-shield] WARNING: writing to credential path {path} "
                f"(matched '{pattern}'). Read of this path will remain blocked.",
                file=sys.stderr,
            )

    if blocked_reason:
        print(f"[secret-shield] {blocked_reason}", file=sys.stderr)
        print(
            "[secret-shield] If this is a false positive, override per-call "
            "via the user's permissions allow-list, or relocate the file to "
            "a non-matched path. To extend the allow-list permanently, edit "
            f"{Path(__file__).resolve()} BLOCKED_PATH_PATTERNS.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
