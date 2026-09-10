#!/usr/bin/env python3
"""Claude Code PreToolUse hook — refuse a decision written into code.

The wiki is the only decision index; code carries a pointer, never the
decision itself. ``scripts/craftsmanship_decisions.py`` checks the converse
property, that a ``source:`` citation resolves, so a decision written as
prose where a pointer belongs passes every gate. CI would report it only
after the write is committed and pushed. This hook refuses the write.

Detection is by shape, not semantics: a decision is prose, and prose in code
is a long run of consecutive comment lines. Exit 2 blocks the tool call and
returns stderr to the agent. A read or parse failure never blocks: a false
negative here is cheap, a hook that makes editing impossible is not.

No path is exempt: the file header, a test file and a ``//`` language are
judged like any other code (owner ruling of 2026-09-10). Only what the call
introduces is judged, so a block already in the file stays editable.

source: ADR-1060"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp_server.hooks import _decision_gate_lex as lex

# A run of this many consecutive comment lines is prose, not a pointer.
# Measured over the tracked tree: outside headers and tests, only a handful
# of files reach it, and the blocks that motivated this were 10 and 12
# (source: ADR-1060).
PROSE_RUN_LIMIT = 8

_OVERRIDE = "CORTEX_DECISION_GATE"


def _read_text(path: str) -> str | None:
    """The file's current text, or None if it cannot be read or decoded.

    A missing file, a null byte in the path, and invalid UTF-8 content all
    land here rather than crashing the hook: each is equally "cannot read".
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


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
    current = _read_text(path)
    if current is None:
        return new  # new file, or unreadable: judge the fragment alone
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def _line_runs(content: str, comment_lines: set[int]) -> dict[int, list[int]]:
    """Consecutive comment-line numbers grouped into runs of at least
    ``PROSE_RUN_LIMIT`` lines, keyed by the run's first line number. A line
    carrying the sanctioned pointer never joins a run."""
    lines = content.splitlines()
    runs: dict[int, list[int]] = {}
    current: list[int] = []

    def flush() -> None:
        if len(current) >= PROSE_RUN_LIMIT:
            runs[current[0]] = list(current)

    for n in range(1, len(lines) + 1):
        if n in comment_lines and lex.POINTER not in lines[n - 1].strip():
            current.append(n)
            continue
        flush()
        current.clear()
    flush()
    return runs


def _run_texts(content: str, language: lex.Language) -> set[str]:
    """Stripped text of every comment line already in a prose run, so a
    rewrap of a block already in the file (inserting or removing a bare
    marker line inside it) is recognised as unchanged, not as new prose."""
    lines = content.splitlines()
    texts: set[str] = set()
    for run in _line_runs(content, language.scan(content)).values():
        texts.update(lines[n - 1].strip() for n in run)
    return texts


def introduced_block(tool: str, tool_input: dict) -> tuple[str, int] | None:
    """The longest prose block this call would newly add, with its line
    number in the resulting file, or None if nothing crosses the threshold.

    "Newly add" is judged by the set of comment line texts already in the
    file's prose runs, not by exact run text: only what the call introduces,
    not what it merely reflows, is refused.
    """
    path = tool_input.get("file_path") or ""
    language = lex.LANGUAGES.get(Path(path).suffix.lower())
    if language is None:
        return None
    content = candidate_content(tool, tool_input)
    if not content:
        return None
    lines = content.splitlines()
    existing_texts = _run_texts(_read_text(path) or "", language)
    best: tuple[str, int, int] | None = None
    for start, run in _line_runs(content, language.scan(content)).items():
        run_texts = [lines[n - 1].strip() for n in run]
        new_count = sum(1 for t in run_texts if t not in existing_texts)
        if new_count < PROSE_RUN_LIMIT:
            continue
        if best is None or new_count > best[2]:
            best = ("\n".join(run_texts), start, new_count)
    return None if best is None else (best[0], best[1])


def _refuse(path: str, block: str, line: int, marker: str) -> None:
    run = block.count("\n") + 1
    print(
        f"[decision-gate] BLOCKED: {path}:{line} would add {run} consecutive"
        " comment lines. A block that long is a decision, and the wiki is"
        " the only decision index. No header, test file or language is"
        " exempt (ADR-1060, revision 2026-09-10).",
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
    _refuse(path, block, line, lex.LANGUAGES[Path(path).suffix.lower()].marker)
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
