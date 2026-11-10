"""Bytecode an installed wheel would run in place of its recorded sources.

Python imports ``__pycache__/<module>.<cache_tag>.pyc`` instead of compiling the
``.py`` when the cache looks current, so a forged but timestamp-valid ``.pyc``
runs while every RECORD row still matches (Codex security review on #957). The
cache is not in RECORD: Python writes it at import, so its presence proves
nothing. What can be checked is its content: when the interpreter would accept
the cache (``_would_import``, the header checks of importlib's
``SourceLoader.get_code``), the code object it holds must be the one this
interpreter compiles from the hashed source next to it. A cache it would reject
(another magic number, a stale timestamp or source hash) is never run, so it is
no alteration: it is left after an upgrade (Codex review on #957). Hash-based
caches follow the default ``--check-hash-based-pycs``: an unchecked one is used
as is, so it is compared without a source check.

Only the caches of this interpreter (``sys.implementation.cache_tag``) are read:
another interpreter's cache is never imported by this one, and the receipt
producer runs under the host's interpreter (scripts/native_receipt_artifact.py).

source: PEP 3147 (``__pycache__`` layout and cache tags); PEP 488 (``opt-N``
names); PEP 552 (the 16-byte header before the marshalled code object).
"""

from __future__ import annotations

import importlib.util
import marshal
import sys
from pathlib import Path

PACKAGE = "mcp_server"  # source: pyproject.toml [tool.hatch.build.targets.wheel]
_HEADER = 16  # source: PEP 552, magic + flags + two 4-byte fields
_OPT = "opt-"  # source: PEP 488, `<name>.<tag>.opt-<level>.pyc`
# source: PEP 3147 `<name>.<tag>.pyc` and PEP 488 `<name>.<tag>.opt-<level>.pyc`
_PLAIN, _OPTIMISED = 3, 4
# source: PEP 552, flags field: bit 0 hash-based, bit 1 check_source
_HASH_BASED, _CHECK_SOURCE = 0b01, 0b10
_UINT32 = 0xFFFFFFFF  # source: importlib _validate_timestamp_pyc masks to 32 bits


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


def _uint32(value: int) -> bytes:
    return (value & _UINT32).to_bytes(4, "little")


def _would_import(data: bytes, source: Path) -> bool:
    """Whether importlib accepts ``data`` as the cache of ``source``."""
    if data[:4] != importlib.util.MAGIC_NUMBER or len(data) < _HEADER:
        return False
    flags = int.from_bytes(data[4:8], "little")
    if flags & ~(_HASH_BASED | _CHECK_SOURCE):
        return False
    if not flags & _HASH_BASED:
        stat = source.stat()
        return data[8:16] == _uint32(int(stat.st_mtime)) + _uint32(stat.st_size)
    if not flags & _CHECK_SOURCE:
        return True
    return data[8:16] == importlib.util.source_hash(source.read_bytes())


def _runs_other_code(pyc: Path, source: Path, level: int) -> bool:
    """True when the interpreter would run ``pyc`` and its code is not the
    compile of ``source`` (or cannot be read: the import would then fail)."""
    data = pyc.read_bytes()
    if not _would_import(data, source):
        return False
    try:
        # marshal.loads builds the code object without running it. A crafted
        # file could at worst crash this process, and the interpreter would
        # import the same bytes anyway.
        cached = marshal.loads(data[_HEADER:])
        # The code object does not compare its filename, so the source path
        # names the compile for tracebacks only.
        built = compile(
            source.read_bytes(), source, "exec", dont_inherit=True, optimize=level
        )
    except (EOFError, ValueError, TypeError, SyntaxError):
        return True
    return cached != built


def clear_caches_fix(root: Path) -> str:
    """The repair for a source tree whose caches hold other code."""
    return (
        f"Delete the `__pycache__` directories under {root}: Python rebuilds them "
        "from the sources at the next import"
    )


def foreign_bytecode(root: Path, members: set[str]) -> list[str]:
    """The caches under the package ``root`` that this interpreter would import
    in place of a hashed member of ``members`` and that hold other code. A cache
    whose source is absent is never imported (``SourceLoader`` starts from the
    source); a source outside ``members`` is already reported as unrecorded."""
    found = []
    for pyc in sorted(root.rglob("__pycache__/*.pyc")):
        target = _source_and_level(pyc)
        if target is None:
            continue
        source, level = target
        name = f"{PACKAGE}/{source.relative_to(root).as_posix()}"
        if name in members and _runs_other_code(pyc, source, level):
            found.append(f"{PACKAGE}/{pyc.relative_to(root).as_posix()}")
    return found
