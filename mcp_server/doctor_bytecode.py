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
caches follow this interpreter's ``--check-hash-based-pycs`` policy: one whose
hash Python would not check is used as is, so it is compared without a check.

Only the caches this interpreter would read are checked: the paths
``importlib.util.cache_from_source`` gives for each hashed source, so its cache
tag and ``sys.pycache_prefix`` when one is set. Another interpreter's cache is
never imported by this one, and the receipt producer runs under the host's
interpreter and environment (scripts/native_receipt_artifact.py).

source: PEP 3147 (``__pycache__`` layout and cache tags); PEP 488 (``opt-N``
names); PEP 552 (the 16-byte header before the marshalled code object).
"""

from __future__ import annotations

import _imp  # the active --check-hash-based-pycs policy, as importlib reads it
import importlib.util
import marshal
from pathlib import Path
from types import CodeType

PACKAGE = "mcp_server"  # source: pyproject.toml [tool.hatch.build.targets.wheel]
_HEADER = 16  # source: PEP 552, magic + flags + two 4-byte fields
# source: PEP 488, the optimisation levels a cache file can be written for
# (`python`, `-O`, `-OO`); the host's level is not known here, so all are read.
_LEVELS = (0, 1, 2)
# source: PEP 552, flags field: bit 0 hash-based, bit 1 check_source
_HASH_BASED, _CHECK_SOURCE = 0b01, 0b10
_UINT32 = 0xFFFFFFFF  # source: importlib _validate_timestamp_pyc masks to 32 bits


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
    # importlib's SourceLoader.get_code: the policy decides whether the source
    # hash is checked at all (Codex review on #957).
    policy = _imp.check_hash_based_pycs
    checked = policy != "never" and (bool(flags & _CHECK_SOURCE) or policy == "always")
    if not checked:
        return True
    return data[8:16] == importlib.util.source_hash(source.read_bytes())


def _executable(code: CodeType) -> CodeType:
    """``code`` without its location table, nested code objects included.

    The table maps instructions to lines and columns for tracebacks only, and
    ``-X no_debug_ranges`` leaves the columns out, so a cache written under it
    differs from a plain compile without running other code (Codex review on
    #957). Instructions, constants and names still compare."""
    consts = tuple(
        _executable(const) if isinstance(const, CodeType) else const
        for const in code.co_consts
    )
    return code.replace(co_linetable=bytes(), co_consts=consts)


def _runs_other_code(pyc: Path, source: Path, level: int) -> bool:
    """True when the interpreter would run ``pyc`` and its code is not the
    compile of ``source`` (or holds no loadable code: the import would then
    fail). A cache that cannot be read is not used: ``SourceLoader.get_code``
    catches the ``OSError`` and compiles the source (Codex review on #957)."""
    try:
        data = pyc.read_bytes()
    except OSError:
        return False
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
    if not isinstance(cached, CodeType):
        return True  # importlib refuses a non-code payload: the import fails
    return _executable(cached) != _executable(built)


def clear_caches_fix(root: Path) -> str:
    """The repair for a source tree whose caches hold other code."""
    return (
        f"Delete the listed bytecode files of {root} (in its `__pycache__` "
        "directories, the `pycache_prefix` tree when one is set, or beside the "
        "sources): Python rebuilds the caches from the sources at the next import"
    )


def sourceless(root: Path) -> list[str]:
    """The ``.pyc`` files under the package ``root`` outside ``__pycache__``
    with no ``.py`` beside them: each imports as a module of its own, with no
    source to digest (PEP 3147 keeps sourceless imports). Beside its source a
    legacy ``.pyc`` never runs: the path finder tries sources before bytecode
    (Codex reviews on #957)."""
    return [
        _label(root, pyc)
        for pyc in sorted(root.rglob("*.pyc"))
        if "__pycache__" not in pyc.relative_to(root).parts
        and not pyc.with_suffix(".py").is_file()
    ]


def _label(root: Path, pyc: Path) -> str:
    if pyc.is_relative_to(root):
        return f"{PACKAGE}/{pyc.relative_to(root).as_posix()}"
    return str(pyc)  # outside the package: a `pycache_prefix` tree


def foreign_bytecode(root: Path, members: set[str]) -> list[str]:
    """The caches this interpreter would import in place of a hashed member of
    ``members`` (paths under ``root.parent``) and that hold other code.

    Each cache path comes from ``importlib.util.cache_from_source``, so it is
    the one the import system reads, ``sys.pycache_prefix`` included (Codex
    review on #957), never a scan of directories."""
    found = []
    for name in sorted(members):
        if not name.endswith(".py"):
            continue
        source = root.parent / name
        for level in _LEVELS:
            cache = importlib.util.cache_from_source(
                str(source), optimization=level or ""
            )
            pyc = Path(cache)
            if pyc.is_file() and _runs_other_code(pyc, source, level):
                found.append(_label(root, pyc))
    return found
