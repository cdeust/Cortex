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

source: ADR-1060"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from mcp_server.hooks import _decision_gate_lex as lex

# A run of this many consecutive comment lines is prose, not a pointer.
# Measured over the tracked tree: outside headers and tests, only a handful
# of files reach it, and the blocks that motivated this were 10 and 12
# (source: ADR-1060).
PROSE_RUN_LIMIT = 8

# "#"-marker languages actually present in the tracked tree at the volume
# this threshold was measured against: 1418 ``.py`` and 18 ``.sh`` files
# (source: ADR-1060 measurement). "//" and "/* */" markers have no tracked
# instances to measure against and are not enforced until they do.
COMMENT_MARKERS = {
    ".py": "#",
    ".sh": "#",
    ".bash": "#",
    ".zsh": "#",
    ".rb": "#",
}

# Exact directory names, not a pattern: a pattern loose enough to match
# ``tests_js`` also matches pytest's own ``tmp_path`` fixture directories
# (``test_<name>0``), which would exempt every file a test writes rather
# than every file under a test root (source: ADR-1060 fix).
_TEST_DIRS = frozenset({"tests", "tests_py", "tests_js", "test", "fuzz"})
_TEST_FILE_RE = re.compile(r"(^test_|_test$|^test$|\.test$|\.spec$|^spec$)")

_OVERRIDE = "CORTEX_DECISION_GATE"


def is_test_path(path: str) -> bool:
    """Tests narrate scenarios at length and hold no decisions; the repo
    already exempts them from the file-size cap. Applied uniformly across
    languages: ``test_x.py``/``x_test.go``/``x.test.ts``/``x.spec.ts``, and
    any exact ``tests``/``tests_py``/``tests_js``/``test``/``fuzz``
    directory component — not just the Python-shaped forms."""
    stem = Path(path).stem
    if _TEST_FILE_RE.search(stem):
        return True
    return any(part in _TEST_DIRS for part in Path(path).parts)


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


def _scan(content: str, suffix: str) -> tuple[set[int], int] | None:
    """(full-line comment numbers, header boundary line) for this suffix, or
    None if the content could not be parsed for comment shape at all."""
    if suffix == lex.PYTHON_SUFFIX:
        return lex.python_comment_lines_and_header(content)
    return lex.shell_comment_lines(content), 0


def _is_header_run(suffix: str, lines: list[str], start: int, boundary: int) -> bool:
    """True iff nothing executable precedes the run beginning at ``start``.

    Python: nothing precedes the tokenizer's first executable statement, a
    leading module docstring included. Shell family: nothing precedes but
    blank lines, ``#`` comments and ``set`` options — the original,
    line-number-free definition.
    """
    if suffix == lex.PYTHON_SUFFIX:
        return start < boundary
    for line in lines[: start - 1]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if stripped.split(maxsplit=1)[:1] == ["set"]:
            continue
        return False
    return True


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


def _body_run_texts(content: str, suffix: str) -> set[str]:
    """Stripped text of every comment line already in a body (non-header)
    prose run, so a rewrap of a block already in the file — inserting or
    removing a bare marker line inside it — is recognised as unchanged
    rather than as new prose."""
    scanned = _scan(content, suffix)
    if scanned is None:
        return set()
    comment_lines, boundary = scanned
    lines = content.splitlines()
    texts: set[str] = set()
    for start, run in _line_runs(content, comment_lines).items():
        if _is_header_run(suffix, lines, start, boundary):
            continue
        texts.update(lines[n - 1].strip() for n in run)
    return texts


def introduced_block(tool: str, tool_input: dict) -> tuple[str, int] | None:
    """The longest prose block this call would newly add, with its line
    number in the resulting file, or None if nothing crosses the threshold.

    "Newly add" is judged by the set of body-comment line texts already in
    the file, not by exact run text: only what the call introduces, not
    what it merely reflows, is refused.
    """
    path = tool_input.get("file_path") or ""
    if is_test_path(path):
        return None
    if Path(path).suffix not in COMMENT_MARKERS:
        return None
    content = candidate_content(tool, tool_input)
    if not content:
        return None
    suffix = Path(path).suffix
    scanned = _scan(content, suffix)
    if scanned is None:
        return None
    comment_lines, boundary = scanned
    lines = content.splitlines()
    existing_texts = _body_run_texts(_read_text(path) or "", suffix)
    best: tuple[str, int, int] | None = None
    for start, run in _line_runs(content, comment_lines).items():
        if _is_header_run(suffix, lines, start, boundary):
            continue
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
