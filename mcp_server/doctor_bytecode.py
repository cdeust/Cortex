"""Bytecode an installed wheel would run in place of its recorded sources.

Python imports ``__pycache__/<module>.<cache_tag>.pyc`` instead of compiling the
``.py`` when the cache looks current, so a forged but timestamp-valid ``.pyc``
runs while every RECORD row still matches (Codex security review on #957). The
cache is not in RECORD: Python writes it at import, so its presence proves
nothing. What can be checked is its content: the code object it holds must be
the one this interpreter compiles from the hashed source next to it.

Only the caches of this interpreter (``sys.implementation.cache_tag``) are read:
another interpreter's cache is never imported by this one, and the receipt
producer runs under the host's interpreter (scripts/native_receipt_artifact.py).

source: PEP 3147 (``__pycache__`` layout and cache tags); PEP 488 (``opt-N``
names); PEP 552 (the 16-byte header before the marshalled code object).
"""

from __future__ import annotations

import marshal
import sys
from pathlib import Path

PACKAGE = "mcp_server"  # source: pyproject.toml [tool.hatch.build.targets.wheel]
_HEADER = 16  # source: PEP 552, magic + flags + two 4-byte fields
_OPT = "opt-"  # source: PEP 488, `<name>.<tag>.opt-<level>.pyc`
# source: PEP 3147 `<name>.<tag>.pyc` and PEP 488 `<name>.<tag>.opt-<level>.pyc`
_PLAIN, _OPTIMISED = 3, 4


def _source_and_level(pyc: Path) -> tuple[Path, int] | None:
    """The source a cache file stands for and its optimisation level, or None
    when the file is not a cache of this interpreter."""
    parts = pyc.name.split(".")
    if (
        len(parts) not in (_PLAIN, _OPTIMISED)
        or parts[1] != sys.implementation.cache_tag
    ):
        return None
    level = 0
    if len(parts) == _OPTIMISED:
        if not parts[2].startswith(_OPT) or not parts[2][len(_OPT) :].isdigit():
            return None
        level = int(parts[2][len(_OPT) :])
    return pyc.parent.parent / f"{parts[0]}.py", level


def _same_code(pyc: Path, source: Path, level: int) -> bool:
    try:
        # marshal.loads builds the code object without running it. A crafted
        # file could at worst crash this process, and the interpreter would
        # import the same bytes anyway.
        cached = marshal.loads(pyc.read_bytes()[_HEADER:])
        # The code object does not compare its filename, so the source path
        # names the compile for tracebacks only.
        built = compile(
            source.read_bytes(), source, "exec", dont_inherit=True, optimize=level
        )
    except (EOFError, ValueError, TypeError, SyntaxError):
        return False
    return cached == built


def foreign_bytecode(root: Path, members: set[str]) -> list[str]:
    """The caches under the package ``root`` that this interpreter would import
    and that are not the compile of a hashed member of ``members``."""
    found = []
    for pyc in sorted(root.rglob("__pycache__/*.pyc")):
        target = _source_and_level(pyc)
        if target is None:
            continue
        source, level = target
        name = f"{PACKAGE}/{source.relative_to(root).as_posix()}"
        if name not in members or not _same_code(pyc, source, level):
            found.append(f"{PACKAGE}/{pyc.relative_to(root).as_posix()}")
    return found
