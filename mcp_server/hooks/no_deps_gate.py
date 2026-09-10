#!/usr/bin/env python3
"""Claude Code PreToolUse hook — refuse a hashed install pip must re-derive.

``pyproject.toml``'s ``[tool.uv] override-dependencies`` steers ``mpmath``
past the ``mpmath<1.4`` bound ``sympy``'s own metadata still declares. uv's
resolver honours the override when it exports ``requirements/*.txt``; the
requirements-file format cannot carry the override itself. Installing that
file with ``--require-hashes`` but without ``--no-deps`` makes pip
re-derive the graph from the unresolved metadata and abort with
``ResolutionImpossible`` — exactly the failure PR #332 (ADR-0800) fixed
everywhere it then knew to look, and that came back the moment a new call
site (``scripts/setup.sh``, PR #539) was added without it. CI would report
a fresh instance only after the write is committed and pushed. This hook
refuses the write.

Detection is lexical, not semantic: ``mcp_server.hooks._no_deps_lex`` finds
any shell command that pairs ``--require-hashes`` with a generated
constraint file and lacks ``--no-deps``. Exit 2 blocks the tool call and
returns stderr to the agent. A read or parse failure never blocks: a false
negative here is cheap, a hook that makes editing impossible is not.

source: ADR-1062"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp_server.hooks import _no_deps_lex as lex
from mcp_server.hooks.decision_gate import candidate_content

_OVERRIDE = "CORTEX_NO_DEPS_GATE"

# Every place a generated, hash-pinned constraint file is installed today:
# CI workflows, the composite test-suite action, both Dockerfiles, the
# devcontainer, and the shell/Python setup scripts — see ADR-1062.
_SCOPED_DIR_NAMES = frozenset({"scripts", ".devcontainer"})


def in_scope(path: str) -> bool:
    """True iff a violation in this file would be a real, shipped call
    site, per ADR-1062's scope: ``scripts/``, ``.github/workflows/``,
    ``.github/actions/``, any ``Dockerfile*``, ``.devcontainer/``."""
    parts = Path(path).parts
    if _SCOPED_DIR_NAMES.intersection(parts):
        return True
    if ".github" in parts and ({"workflows", "actions"} & set(parts)):
        return True
    return Path(path).name.startswith("Dockerfile")


def introduced_violation(tool: str, tool_input: dict) -> tuple[int, str] | None:
    """The first offending command this call would write, or None."""
    path = tool_input.get("file_path") or ""
    if not in_scope(path):
        return None
    content = candidate_content(tool, tool_input)
    if not content:
        return None
    found = lex.find_violations(content)
    return found[0] if found else None


def _refuse(path: str, line: int, command: str) -> None:
    print(
        f"[no-deps-gate] BLOCKED: {path}:{line} installs a hash-pinned "
        f"requirements file with {lex.REQUIRE_HASHES} but no {lex.NO_DEPS}:"
        f"\n    {command}",
        file=sys.stderr,
    )
    print(
        "[no-deps-gate] The file is the complete uv-resolved closure; "
        f"without {lex.NO_DEPS} pip re-derives it and can abort with "
        "ResolutionImpossible (ADR-1062). Add the flag, or set "
        f"{_OVERRIDE}=off for the call and say why this install is not one "
        "of the generated constraint files.",
        file=sys.stderr,
    )


def evaluate(event: dict) -> int:
    """0 to allow, 2 to block."""
    if os.environ.get(_OVERRIDE) == "off":
        return 0
    tool_input = event.get("tool_input", {}) or {}
    found = introduced_violation(event.get("tool_name", ""), tool_input)
    if found is None:
        return 0
    line, command = found
    _refuse(tool_input.get("file_path") or "", line, command)
    return 2


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    return evaluate(event)


if __name__ == "__main__":
    from mcp_server.hooks._headless_guard import exit_if_headless_authoring_child

    exit_if_headless_authoring_child()
    sys.exit(main())
