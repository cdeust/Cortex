"""Explicit file operands of simple read commands; never execute shell text.

source: ADR-1086
POSIX Shell Command Language (token recognition), and
cat/head/tail/sed utility operand grammars; ripgrep --help option grammar.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path


def _tokens(command: str) -> list[str]:
    """Reject expansion and control syntax instead of guessing its result."""
    if any(char in command for char in ("$", "`", "\n", "\r")):
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    if any(token and all(c in ";&|<>()" for c in token) for token in tokens):
        return []
    return tokens


def _cat_operands(args: list[str]) -> list[str]:
    return _operands(args, frozenset("benstuvAET"), frozenset())


def _operands(
    args: list[str], flags: frozenset[str], value_options: frozenset[str]
) -> list[str]:
    """Parse options before operands; unknown options invalidate the command."""
    files: list[str] = []
    options = True
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if options and arg == "--":
            options = False
        elif options and arg in value_options:
            if index == len(args):
                return []
            index += 1
        elif options and arg.startswith("--"):
            name, sep, _ = arg.partition("=")
            if name not in flags and not (sep and name in value_options):
                return []
        elif options and arg.startswith("-") and arg != "-":
            if not all(char in flags for char in arg[1:]):
                return []
        elif arg != "-":
            files.append(arg)
    return files


def _head_tail_operands(args: list[str]) -> list[str]:
    normalized = []
    for arg in args:
        if re.fullmatch(r"-[nc][+-]?\d+", arg):
            normalized.extend((arg[:2], arg[2:]))
        elif re.fullmatch(r"-\d+", arg):
            normalized.extend(("-n", arg[1:]))
        else:
            normalized.append(arg)
    return _operands(
        normalized,
        frozenset(("q", "v", "--quiet", "--silent", "--verbose")),
        frozenset(("-n", "-c", "--lines", "--bytes")),
    )


def _sed_operands(args: list[str]) -> list[str]:
    # Only explicit print scripts: sed's e/w commands and -i are not reads.
    if args and args[0] == "-n":
        args = args[1:]
    if args and args[0] == "-e":
        args = args[1:]
    if not args or not re.fullmatch(r"(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?p", args[0]):
        return []
    return _operands(args[1:], frozenset(), frozenset())


_RG_FLAGS = frozenset(
    "n i s S F w x l L c o v --line-number --ignore-case "
    "--fixed-strings --hidden --no-ignore --files-with-matches --count".split()
)
_RG_VALUE_OPTIONS = frozenset(
    "-e --regexp -g --glob -t --type -T --type-not -m "
    "--max-count -A -B -C --after-context --before-context --context".split()
)


def _rg_pattern_supplied(args: list[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if arg in {"-e", "--regexp"} or arg.startswith("--regexp="):
            return True
        index += 2 if arg in _RG_VALUE_OPTIONS else 1
    return False


def _rg_operands(args: list[str]) -> list[str]:
    # -e supplies the pattern; otherwise the first positional is the pattern.
    explicit_pattern = _rg_pattern_supplied(args)
    operands = _operands(args, _RG_FLAGS, _RG_VALUE_OPTIONS)
    return operands if explicit_pattern else operands[1:]


_READERS = {
    "cat": _cat_operands,
    "head": _head_tail_operands,
    "tail": _head_tail_operands,
    "sed": _sed_operands,
    "rg": _rg_operands,
}


def shell_read_paths(command: str, cwd: str) -> list[str]:
    """Return distinct existing explicit file paths; never expand directories."""
    tokens = _tokens(command)
    if not tokens:
        return []
    executable = Path(tokens[0])
    if "/" in tokens[0] and executable.parent.as_posix() not in {"/bin", "/usr/bin"}:
        return []
    reader = _READERS.get(executable.name)
    if reader is None:
        return []
    paths = []
    for operand in reader(tokens[1:]):
        if any(char in operand for char in "*?[]~"):
            return []
        path = (Path(cwd) / operand).resolve()
        if path.is_file() and str(path) not in paths:
            paths.append(str(path))
    return paths
