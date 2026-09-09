"""Language-aware comment-line extraction for ``decision_gate``.

Split out of ``decision_gate.py`` to keep that module under the repo's
300-line cap. A regex that treats every line starting with ``#`` or ``//``
as a comment confuses string and heredoc bodies for prose; this module gives
each supported marker family a scanner that does not.
"""

from __future__ import annotations

import io
import re
import tokenize

POINTER = "source:"

_HEREDOC_START = re.compile(r"<<-?\s*['\"]?(?P<delim>\w+)['\"]?")

# Marker families that get a language-aware scanner. Every other suffix in
# COMMENT_MARKERS falls back to a plain per-line prefix check.
PYTHON_SUFFIX = ".py"


def shell_comment_lines(content: str) -> set[int]:
    """Full-line ``#`` comments, skipping heredoc bodies.

    ``cat <<'CFG' ... CFG`` feeds its body to a command as data; a commented
    line inside it is a data row, not a decision, and must not be counted.
    """
    lines = content.splitlines()
    comment_lines: set[int] = set()
    delim: str | None = None
    for number, line in enumerate(lines, start=1):
        if delim is not None:
            if line.strip() == delim:
                delim = None
            continue
        started = _HEREDOC_START.search(line)
        if started:
            delim = started.group("delim")
            continue
        if line.strip().startswith("#"):
            comment_lines.add(number)
    return comment_lines


def python_comment_lines_and_header(content: str) -> tuple[set[int], int]:
    """Full-line ``#`` comments via ``tokenize.COMMENT``, plus the first
    line carrying executable code.

    ``tokenize`` never mistakes a string body for a comment, unlike a
    ``line.strip().startswith("#")`` regex. The header boundary tolerates a
    leading module docstring: a bare string expression statement is not
    executable, so a licence block right after it is still header material.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenizeError, SyntaxError, IndentationError, ValueError):
        return set(), 0  # unparsable: no comment lines, no header exemption
    comment_lines: set[int] = set()
    header_boundary = len(content.splitlines()) + 1
    executable_seen = False
    stmt: list[tokenize.TokenInfo] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            comment_lines.add(tok.start[0])
            continue
        if tok.type in (
            tokenize.NL,
            tokenize.ENCODING,
            tokenize.INDENT,
            tokenize.DEDENT,
        ):
            continue
        if tok.type != tokenize.NEWLINE:
            stmt.append(tok)
            continue
        is_bare_docstring = len(stmt) == 1 and stmt[0].type == tokenize.STRING
        if stmt and not is_bare_docstring and not executable_seen:
            executable_seen = True
            header_boundary = stmt[0].start[0]
        stmt = []
    return comment_lines, header_boundary
