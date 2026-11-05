"""Changed lines of a `git diff -U0`, per Python file under mcp_server (ADR-1122).

Split from ci_mutation_diff.py to keep both under the craftsmanship file cap.
"""

from __future__ import annotations

import re

# source: pyproject.toml [tool.mutmut] source_paths = ["mcp_server"].
SOURCE_ROOT = "mcp_server/"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_HEADER = re.compile(r"-\s*(?:async\s+def\b|def\b|class\b)")


def _indent(line: str) -> int:
    body = line[1:]
    return len(body) - len(body.lstrip())


def _is_decorator(line: str) -> bool:
    return line[1:].lstrip().startswith("@")


def _touched_by_deletion(
    removed: list[str], start: int
) -> tuple[set[int], tuple[int, int] | None]:
    """(surviving lines a pure deletion changed, (anchor, indent) of an indented definition cut).

    `start` is the line before the cut.
    - a whole top-level definition removed: nothing that survives changed, except the
      function whose decorators ended the block, whose header is line `start + 1`;
    - an indented whole definition removed: a method or a nested function. The
      source tells which, so the anchor and the removed header's indent are returned
      for `touched_prefixes`;
    - only decorators and blanks removed: the function below lost them, `start + 1`;
    - anything else is a cut inside a function: the anchor and the next line.
    """
    body = [line for line in removed if line[1:].strip()]
    header = next((i for i, line in enumerate(body) if _HEADER.match(line)), None)
    leading = 0
    while leading < len(body) and _is_decorator(body[leading]):
        leading += 1
    if header is not None and header == leading:
        trailing = len(body) > header + 1 and _is_decorator(body[-1])
        after = {start + 1} if trailing else set()
        indent = _indent(body[header])
        return after, (None if indent == 0 else (start, indent))
    if body and leading == len(body):
        return {start + 1}, None
    return {start, start + 1}, None


def changed_lines_ex(
    diff_text: str,
) -> tuple[dict[str, set[int]], dict[str, set[tuple[int, int]]]]:
    """(touched lines, indented-definition cuts) per Python file under mcp_server."""
    result: dict[str, set[int]] = {}
    cuts: dict[str, set[tuple[int, int]]] = {}
    current = None
    pending: tuple[int, int] | None = None
    removed: list[str] = []

    def close() -> None:
        nonlocal pending, removed
        if pending and current:
            first, count = pending
            if count:
                touched, cut = set(range(first, first + count)), None
            else:
                touched, cut = _touched_by_deletion(removed, first)
            if touched:
                result.setdefault(current, set()).update(touched)
            if cut is not None:
                cuts.setdefault(current, set()).add(cut)
        pending, removed = None, []

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            close()
            path = line[4:].removeprefix("b/")
            current = (
                path if path.startswith(SOURCE_ROOT) and path.endswith(".py") else None
            )
        elif current and (hunk := _HUNK.match(line)):
            close()
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            pending = (int(hunk.group(1)), count)
        elif pending and line.startswith("-") and pending[1] == 0:
            removed.append(line)
    close()
    return result, cuts


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Lines added or touched per Python file under mcp_server, from `git diff -U0`."""
    return changed_lines_ex(diff_text)[0]
