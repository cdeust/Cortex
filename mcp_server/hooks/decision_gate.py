#!/usr/bin/env python3
"""Claude Code PreToolUse hook — refuse a decision written into code.

The wiki is the only decision index; code carries a pointer, never the
decision itself. ``scripts/craftsmanship_decisions.py`` checks the converse
property, that a ``source:`` citation resolves, so a decision written as
prose where a pointer belongs passes every gate. CI would report it only
after the write is committed and pushed. This hook refuses the write.

Detection is by shape, not semantics: a decision is prose, and prose in code
is a long run of consecutive comment lines. Exit 2 blocks the tool call and
returns stderr to the agent.

source: ADR-1060"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# A run of this many consecutive comment lines is prose, not a pointer.
# Measured over the tracked tree: outside headers and tests, only a handful
# of files reach it, and the blocks that motivated this were 10 and 12
# (source: ADR-1060).
PROSE_RUN_LIMIT = 8

COMMENT_MARKERS = {
    ".py": "#",
    ".sh": "#",
    ".bash": "#",
    ".zsh": "#",
    ".rb": "#",
    ".js": "//",
    ".ts": "//",
    ".tsx": "//",
    ".jsx": "//",
    ".swift": "//",
    ".go": "//",
    ".rs": "//",
    ".java": "//",
    ".c": "//",
    ".h": "//",
    ".cpp": "//",
}

# The sanctioned form; a line carrying it never extends a run.
POINTER = "source:"

_TEST_DIRS = frozenset({"tests", "tests_py", "test", "fuzz"})

_OVERRIDE = "CORTEX_DECISION_GATE"


def is_test_path(path: str) -> bool:
    """Tests narrate scenarios at length and hold no decisions; the repo
    already exempts them from the file-size cap."""
    name = Path(path).name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in _TEST_DIRS for part in Path(path).parts)


def prose_runs(content: str, marker: str) -> dict[str, int]:
    """Every run of ``PROSE_RUN_LIMIT``+ comment lines, keyed by its text.

    Keying by text rather than position is what lets the caller tell a block
    this edit introduces from one that merely moved.
    """
    found: dict[str, int] = {}
    run: list[str] = []
    start = 0

    def flush() -> None:
        if len(run) >= PROSE_RUN_LIMIT:
            found.setdefault("\n".join(x.strip() for x in run), start)

    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(marker) and POINTER not in stripped:
            if not run:
                start = number
            run.append(line)
            continue
        flush()
        run = []
    flush()
    return found


def is_header(lines: list[str], start: int) -> bool:
    """True iff nothing executable precedes the run beginning at ``start``.

    A file's opening block orients the reader and is not a decision. Saying
    so this way avoids a line-number threshold, which would be a number to
    tune and a place for a decision to hide just inside.
    """
    for line in lines[: start - 1]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith(("#", "//")):
            continue
        if stripped.split(maxsplit=1)[:1] == ["set"]:
            continue
        return False
    return True


def body_runs(content: str, marker: str) -> dict[str, int]:
    """Prose runs that are not the file's header block."""
    lines = content.splitlines()
    return {
        text: start
        for text, start in prose_runs(content, marker).items()
        if not is_header(lines, start)
    }


def candidate_content(tool: str, tool_input: dict) -> str | None:
    """The full file text this call would produce, or None if not derivable."""
    if tool == "Write":
        return tool_input.get("content")
    if tool != "Edit":
        return None
    path = tool_input.get("file_path")
    old, new = tool_input.get("old_string"), tool_input.get("new_string")
    if not path or old is None or new is None:
        return None
    try:
        current = Path(path).read_text(encoding="utf-8")
    except OSError:
        return new  # New file, or unreadable: judge the fragment alone.
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def introduced_block(tool: str, tool_input: dict) -> tuple[str, int] | None:
    """The longest prose block this call would add, with its line number.

    A block already in the file is grandfathered, so editing an unrelated
    part of a legacy file is never refused: only what the call introduces
    is judged.
    """
    path = tool_input.get("file_path") or ""
    if is_test_path(path):
        return None
    marker = COMMENT_MARKERS.get(Path(path).suffix)
    if marker is None:
        return None
    content = candidate_content(tool, tool_input)
    if not content:
        return None
    try:
        existing = Path(path).read_text(encoding="utf-8")
    except OSError:
        existing = ""
    candidate = body_runs(content, marker)
    new = set(candidate) - set(body_runs(existing, marker))
    if not new:
        return None
    block = max(new, key=lambda text: text.count("\n"))
    return block, candidate[block]


def _refuse(path: str, block: str, line: int, marker: str) -> None:
    run = block.count("\n") + 1
    print(
        f"[decision-gate] BLOCKED: {path}:{line} would add {run} consecutive"
        " comment lines. A block that long is a decision, and the wiki is"
        " the only decision index.",
        file=sys.stderr,
    )
    print(
        "[decision-gate] Record it with the cortex wiki_adr tool, then leave"
        f" only `{marker} source: ADR-NNNN` here. If this is genuinely not a"
        f" decision (a worked example, a data table), split it or set"
        f" {_OVERRIDE}=off for the call and say why.",
        file=sys.stderr,
    )


def evaluate(event: dict) -> int:
    """0 to allow, 2 to block."""
    if os.environ.get(_OVERRIDE) == "off":
        return 0
    tool_input = event.get("tool_input", {}) or {}
    found = introduced_block(event.get("tool_name", ""), tool_input)
    if found is None:
        return 0
    path = tool_input.get("file_path") or ""
    block, line = found
    _refuse(path, block, line, COMMENT_MARKERS[Path(path).suffix])
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
