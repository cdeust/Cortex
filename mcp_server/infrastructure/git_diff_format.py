"""Diff-result formatting helpers for ``git_diff``.

Pure functions that turn raw git output (or raw file contents) into the
``{file, diff_type, lines, truncated}`` shape that the UI renders. No
I/O, no subprocess; lives in ``infrastructure`` solely because
``git_diff`` (its sole caller) lives there.
"""

from __future__ import annotations


def parse_diff_lines(raw: str) -> list[dict]:
    """Turn unified-diff text into typed line records.

    ``diff``/``index``/``+++``/``---`` headers are dropped; ``@@`` hunks
    keep their type as ``hunk``; ``+``/``-``/context lines are typed as
    ``add``/``del``/``ctx`` respectively.
    """
    result: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("diff ") or line.startswith("index "):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            result.append({"text": line, "type": "hunk"})
        elif line.startswith("+"):
            result.append({"text": line, "type": "add"})
        elif line.startswith("-"):
            result.append({"text": line, "type": "del"})
        else:
            result.append({"text": line, "type": "ctx"})
    return result


def build_result(filepath: str, diff_type: str, raw: str, max_lines: int) -> dict:
    """Standard diff response from raw ``git diff`` output."""
    lines = parse_diff_lines(raw)
    return {
        "file": filepath,
        "diff_type": diff_type,
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def content_as_new(
    filepath: str,
    content: str,
    max_lines: int,
    diff_type: str = "new_file",
) -> dict:
    """Render raw file content as an all-add diff (new-file view)."""
    raw_lines = content.splitlines()
    lines = [{"text": "+" + ln, "type": "add"} for ln in raw_lines]
    return {
        "file": filepath,
        "diff_type": diff_type,
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def content_as_delete(filepath: str, content: str, max_lines: int) -> dict:
    """Render raw file content as an all-delete diff."""
    raw_lines = content.splitlines()
    lines = [{"text": "-" + ln, "type": "del"} for ln in raw_lines]
    return {
        "file": filepath,
        "diff_type": "deleted",
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def content_as_context(filepath: str, content: str, max_lines: int) -> dict:
    """Render raw file content as an unchanged / context-only view."""
    raw_lines = content.splitlines()
    lines = [{"text": " " + ln, "type": "ctx"} for ln in raw_lines]
    return {
        "file": filepath,
        "diff_type": "unchanged",
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }
