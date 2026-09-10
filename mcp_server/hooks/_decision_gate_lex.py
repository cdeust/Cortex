"""Language-aware comment-line extraction for ``decision_gate``.

Split out of ``decision_gate.py`` to keep that module under the repo's
300-line cap. A regex that treats every line starting with ``#`` or ``//``
as a comment confuses string and heredoc bodies for prose; this module gives
each supported marker family a scanner that does not. Python goes through
``tokenize``, the shell family skips heredoc bodies, and every other family
goes through one character-level scanner that tracks string literals and
block comments (``_Scanner``).

source: ADR-1060"""

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass
from functools import partial
from typing import Callable

POINTER = "source:"

_HEREDOC_START = re.compile(r"<<-?\s*['\"]?(?P<delim>\w+)['\"]?")
_RAW_STRING = re.compile(r'r(#*)"')
_CHAR_LITERAL = re.compile(r"'(?:\\.[^'\\\n]{0,8}|[^'\\\n])'")


@dataclass(frozen=True)
class Family:
    """How one comment-marker family is lexed by ``_Scanner``."""

    line: tuple[str, ...]
    block: tuple[str, str] | None
    quotes: str
    char_literal: bool = False
    multiline_strings: bool = False
    raw_strings: bool = False


@dataclass(frozen=True)
class Language:
    """The pointer marker shown in a refusal, and the scanner for the suffix."""

    marker: str
    scan: Callable[[str], set[int]]


C_FAMILY = Family(("//",), ("/*", "*/"), '"`', char_literal=True)
RUST = Family(
    ("//",),
    ("/*", "*/"),
    '"',
    char_literal=True,
    multiline_strings=True,
    raw_strings=True,
)
SCRIPT_FAMILY = Family(("//",), ("/*", "*/"), "\"'`")
PHP = Family(("//", "#"), ("/*", "*/"), "\"'`")
SQL = Family(("--",), ("/*", "*/"), "\"'", multiline_strings=True)
LUA = Family(("--",), ("--[[", "]]"), "\"'")
HASKELL = Family(("--",), ("{-", "-}"), '"', char_literal=True)
LISP = Family((";",), ("#|", "|#"), '"', multiline_strings=True)
R_LANG = Family(("#",), None, "\"'")
HASH_CONFIG = Family(("#",), None, "")


class _Scanner:
    """Full-line comments: lines holding comment text and no code outside it.

    A string literal is code, so a ``//`` or ``/* */`` inside one never reads
    as a comment; a block comment marks every line it crosses as comment.
    """

    def __init__(self, text: str, family: Family) -> None:
        self.text = text
        self.family = family
        self.i = 0
        self.line = 1
        self.has_code = False
        self.has_comment = False
        self.comment_lines: set[int] = set()

    def run(self) -> set[int]:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch == "\n":
                self._end_line()
            elif ch in " \t\r\f\v":
                self.i += 1
            elif not self._comment_at() and not self._string_at():
                self.has_code = True
                self.i += 1
        self._end_line()
        return self.comment_lines

    def _end_line(self) -> None:
        if self.has_comment and not self.has_code:
            self.comment_lines.add(self.line)
        self.has_code = self.has_comment = False
        self.line += 1
        self.i += 1

    def _mark(self, comment: bool) -> None:
        if comment:
            self.has_comment = True
        else:
            self.has_code = True

    def _consume_span(self, stop: int, *, comment: bool) -> None:
        """Advance to ``stop``, closing each line crossed as comment or code."""
        while self.i < stop:
            if self.text[self.i] == "\n":
                self._mark(comment)
                self._end_line()
            else:
                self.i += 1
        self._mark(comment)

    def _comment_at(self) -> bool:
        family, text = self.family, self.text
        if family.block and text.startswith(family.block[0], self.i):
            opener, closer = family.block
            end = text.find(closer, self.i + len(opener))
            stop = len(text) if end < 0 else end + len(closer)
            self._consume_span(stop, comment=True)
            return True
        if any(text.startswith(marker, self.i) for marker in family.line):
            end = text.find("\n", self.i)
            self._consume_span(len(text) if end < 0 else end, comment=True)
            return True
        return False

    def _string_at(self) -> bool:
        ch, family = self.text[self.i], self.family
        if family.raw_strings and self._raw_string_at():
            return True
        if ch in family.quotes:
            self._consume_quoted(ch)
            return True
        if family.char_literal and ch == "'":
            match = _CHAR_LITERAL.match(self.text, self.i)
            if match:
                self._consume_span(match.end(), comment=False)
                return True
        return False

    def _raw_string_at(self) -> bool:
        match = _RAW_STRING.match(self.text, self.i)
        if not match:
            return False
        closer = '"' + match.group(1)
        end = self.text.find(closer, match.end())
        stop = len(self.text) if end < 0 else end + len(closer)
        self._consume_span(stop, comment=False)
        return True

    def _consume_quoted(self, quote: str) -> None:
        """A quoted literal ends at its closing quote; unless the family lets
        strings span lines (or the quote is a backtick), at the end of the
        line too, so a stray apostrophe swallows one line, never a file."""
        text = self.text
        spans_lines = quote == "`" or self.family.multiline_strings
        j = self.i + 1
        while j < len(text):
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == quote:
                j += 1
                break
            if ch == "\n" and not spans_lines:
                break
            j += 1
        self._consume_span(min(j, len(text)), comment=False)


def family_comment_lines(content: str, family: Family) -> set[int]:
    return _Scanner(content, family).run()


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


def python_comment_lines(content: str) -> set[int]:
    """Full-line ``#`` comments via ``tokenize.COMMENT``.

    ``tokenize`` never mistakes a string body for a comment, unlike a
    ``line.strip().startswith("#")`` regex. Unparsable content yields no
    comment lines at all: the gate fails open rather than guessing.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError):
        return set()
    return {
        tok.start[0]
        for tok in tokens
        if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip()
    }


def _languages(
    marker: str, scan: Callable[[str], set[int]], *suffixes: str
) -> dict[str, Language]:
    return {suffix: Language(marker, scan) for suffix in suffixes}


def _family_languages(
    marker: str, family: Family, *suffixes: str
) -> dict[str, Language]:
    return _languages(marker, partial(family_comment_lines, family=family), *suffixes)


# Every suffix the gate judges, with the scanner that reads it. No suffix
# here is exempt for any path (source: ADR-1060, revision 2026-09-10).
LANGUAGES: dict[str, Language] = {
    **_languages("#", python_comment_lines, ".py"),
    **_languages("#", shell_comment_lines, ".sh", ".bash", ".zsh", ".rb", ".pl"),
    **_family_languages("#", R_LANG, ".r"),
    **_family_languages("#", HASH_CONFIG, ".toml", ".yaml", ".yml", ".cfg", ".ini"),
    **_family_languages("//", RUST, ".rs"),
    **_family_languages(
        "//", C_FAMILY, ".go", ".java", ".c", ".h", ".cpp", ".hpp", ".cc"
    ),
    **_family_languages(
        "//", C_FAMILY, ".swift", ".kt", ".kts", ".cs", ".scala", ".m", ".mm"
    ),
    **_family_languages("//", SCRIPT_FAMILY, ".js", ".jsx", ".ts", ".tsx", ".dart"),
    **_family_languages("//", PHP, ".php"),
    **_family_languages("--", SQL, ".sql"),
    **_family_languages("--", LUA, ".lua"),
    **_family_languages("--", HASKELL, ".hs"),
    **_family_languages(";", LISP, ".el", ".clj", ".lisp"),
}
