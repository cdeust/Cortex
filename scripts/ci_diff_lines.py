"""Changed lines of a `git diff -U0`, per Python file under mcp_server (ADR-1122).

Split from ci_mutation_diff.py to keep both under the craftsmanship file cap.
"""

from __future__ import annotations

import ast
import re

# source: pyproject.toml [tool.mutmut] source_paths = ["mcp_server"].
SOURCE_ROOT = "mcp_server/"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_HEADER = re.compile(r"-\s*(?:async\s+def\b|def\b|class\b)")
# A file header ends the hunk before it: `diff --git`, or `--- a/f` / `--- /dev/null`.
_FILE_START = re.compile(r"(?:diff --git |--- (?:a/|/dev/null))")


def _indent(line: str) -> int:
    body = line[1:]
    return len(body) - len(body.lstrip())


def _is_decorator(line: str) -> bool:
    return line[1:].lstrip().startswith("@")


def _touched_by_deletion(
    removed: list[str], start: int
) -> tuple[set[int], tuple[int, int] | None]:
    """(surviving lines a pure deletion changed, (anchor, indent) of an indented cut).

    `start` is the line before the cut.
    - a whole top-level definition removed: nothing that survives changed, except the
      function whose decorators ended the block, whose header is line `start + 1`;
    - a whole definition removed: the anchor and the removed header's indent are
      returned for `touched_prefixes`. The source tells a method from a nested
      function, and a string whose content looked like a definition;
    - comments and blank lines are ignored, so a note above a removed definition does
      not turn it into a cut inside a function;
    - only decorators and blanks removed: the function below lost them, `start + 1`;
    - anything else is a cut inside a function: the anchor and the next line.
    """
    body = [
        line
        for line in removed
        if line[1:].strip() and not line[1:].lstrip().startswith("#")
    ]
    header = next((i for i, line in enumerate(body) if _HEADER.match(line)), None)
    leading = 0
    while leading < len(body) and _is_decorator(body[leading]):
        leading += 1
    if header is not None and header == leading:
        trailing = len(body) > header + 1 and _is_decorator(body[-1])
        after = {start + 1} if trailing else set()
        indent = _indent(body[header])
        return after, (start, indent)
    if body and leading == len(body):
        return {start + 1}, None
    return {start, start + 1}, None


def _string_spans(tree: ast.AST) -> list[tuple[int, int]]:
    """(first, last) line of every string literal that spans several lines."""
    return [
        (n.lineno, n.end_lineno)
        for n in ast.walk(tree)
        if (isinstance(n, ast.JoinedStr) or isinstance(n, ast.Constant))
        and (isinstance(n, ast.JoinedStr) or isinstance(n.value, str))
        and n.end_lineno > n.lineno
    ]


def drop_inert(source: str, lines: set[int], inert: set[int]) -> set[int]:
    """`lines` without the `inert` ones that lie outside every multiline string.

    An added blank or comment-only line changes no behaviour, so it must not touch the
    function whose span it falls in (the blank lines above a new function fall in the
    span of the one before it). Inside a multiline string it changes the string.
    """
    spans = _string_spans(ast.parse(source))
    return lines - {
        n for n in inert if not any(first < n <= last for first, last in spans)
    }


def string_cut_lines(tree: ast.AST, cuts) -> set[int]:
    """Lines around cuts that fall inside a multiline string.

    Removed text that reads like a definition or a comment but sits in a string
    changed the string, so the function holding it is touched.
    """
    spans = _string_spans(tree)
    return {
        line
        for anchor, _ in cuts
        if any(first <= anchor and anchor + 1 <= last for first, last in spans)
        for line in (anchor, anchor + 1)
    }


def _is_inert(line: str) -> bool:
    """A diff line (with its +/- sign) that is blank or only a comment."""
    return not line[1:].strip() or line[1:].lstrip().startswith("#")


def _hunk_effect(first: int, count: int, removed: list[str], added: list[str]):
    """(touched lines, cut or None, inert added lines) of one `-U0` hunk.

    An added line is inert when blank or only a comment, in a hunk that removed no
    code; a hunk that replaced code keeps every line it touched.
    """
    if not count:
        return *_touched_by_deletion(removed, first), set()
    replaced_code = not all(_is_inert(line) for line in removed)
    inert = (
        set()
        if replaced_code
        else {first + i for i, line in enumerate(added) if _is_inert(line)}
    )
    return set(range(first, first + count)), None, inert


def changed_lines_ex(
    diff_text: str, inert: dict[str, set[int]] | None = None
) -> tuple[dict[str, set[int]], dict[str, set[tuple[int, int]]]]:
    """(touched lines, indented-definition cuts) per Python file under mcp_server;
    `inert` collects the inert added lines of `_hunk_effect`, see `drop_inert`."""
    result: dict[str, set[int]] = {}
    cuts: dict[str, set[tuple[int, int]]] = {}
    current = None
    pending: tuple[int, int] | None = None
    removed: list[str] = []
    added: list[str] = []

    def close() -> None:
        nonlocal pending, removed, added
        if pending and current:
            touched, cut, blank = _hunk_effect(*pending, removed, added)
            if inert is not None and blank:
                inert.setdefault(current, set()).update(blank)
            if touched:
                result.setdefault(current, set()).update(touched)
            if cut is not None:
                cuts.setdefault(current, set()).add(cut)
        pending, removed, added = None, [], []

    for line in diff_text.splitlines():
        if _FILE_START.match(line):
            close()
        elif line.startswith("+++ "):
            close()
            path = line[4:].removeprefix("b/")
            current = (
                path if path.startswith(SOURCE_ROOT) and path.endswith(".py") else None
            )
        elif current and (hunk := _HUNK.match(line)):
            close()
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            pending = (int(hunk.group(1)), count)
        elif pending and line[:1] in ("-", "+"):
            (removed if line[0] == "-" else added).append(line)
    close()
    return result, cuts


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Lines added or touched per Python file under mcp_server, from `git diff -U0`."""
    return changed_lines_ex(diff_text)[0]
