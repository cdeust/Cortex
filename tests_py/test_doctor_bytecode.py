"""Caches an installed wheel would import in place of its sources (#957 review)."""

import importlib.util
import marshal
import os
import py_compile
import sys
from pathlib import Path

from mcp_server import doctor_bytecode

TAG = sys.implementation.cache_tag
MEMBERS = {"mcp_server/a.py", "mcp_server/sub/b.py"}
EVIL = b"x = 2\n"
A_CACHE = f"mcp_server/__pycache__/a.{TAG}.pyc"


def _package(tmp_path):
    package = tmp_path / "mcp_server"
    (package / "sub").mkdir(parents=True)
    (package / "a.py").write_bytes(b'"""doc"""\nassert True\n')
    (package / "sub" / "b.py").write_bytes(b'"""doc"""\nassert True\n')
    return package


def _cache_path(source, level=0):
    return Path(importlib.util.cache_from_source(str(source), optimization=level or ""))


def _cache(source, *, level=0):
    cfile = _cache_path(source, level)
    py_compile.compile(str(source), cfile=str(cfile), doraise=True, optimize=level)
    return cfile


def _uint32(value):
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def _forge(source, *, level=0, flags=0, check=None, code=EVIL, magic=None):
    """A cache that names ``source`` in its header and holds ``code``: by
    default a timestamp header that importlib accepts for ``source``."""
    stat = source.stat()
    if flags & 0b01:
        check = check if check is not None else source.read_bytes()
        tail = importlib.util.source_hash(check)
    else:
        tail = _uint32(int(stat.st_mtime)) + _uint32(stat.st_size)
    header = (magic or importlib.util.MAGIC_NUMBER) + _uint32(flags) + tail
    cfile = _cache_path(source, level)
    cfile.parent.mkdir(parents=True, exist_ok=True)
    body = marshal.dumps(compile(code, str(source), "exec", optimize=level))
    cfile.write_bytes(header + body)
    return cfile


def _foreign(package):
    return doctor_bytecode.foreign_bytecode(package, MEMBERS)


def test_caches_compiled_from_their_sources_are_accepted(tmp_path):
    package = _package(tmp_path)
    _cache(package / "a.py")
    _cache(package / "sub" / "b.py", level=2)
    assert _foreign(package) == []


def test_a_forged_timestamp_cache_is_foreign(tmp_path):
    package = _package(tmp_path)
    cfile = _forge(package / "a.py")
    # A skipped name that sorts first must not end the scan.
    (cfile.parent / "_.aaa-1.pyc").write_bytes(b"\0")
    assert _foreign(package) == [A_CACHE]


def test_a_forged_optimised_cache_is_foreign(tmp_path):
    package = _package(tmp_path)
    _forge(package / "a.py", level=1)
    assert _foreign(package) == [f"mcp_server/__pycache__/a.{TAG}.opt-1.pyc"]


def test_forged_hash_based_caches_are_foreign(tmp_path):
    package = _package(tmp_path)
    _forge(package / "a.py", flags=0b11)  # checked, with the source's hash
    _forge(package / "sub" / "b.py", flags=0b01, check=b"other")  # unchecked
    assert _foreign(package) == [
        A_CACHE,
        f"mcp_server/sub/__pycache__/b.{TAG}.pyc",
    ]


def test_a_cache_at_the_wrong_optimisation_level_is_foreign(tmp_path):
    # `assert` and docstrings are stripped at -OO: opt-2 bytecode of b.py is
    # not the plain compile, so a plain cache file holding it is foreign.
    package = _package(tmp_path)
    source = package / "sub" / "b.py"
    plain = _cache_path(source)
    py_compile.compile(str(source), cfile=str(plain), doraise=True, optimize=2)
    assert _foreign(package) == [f"mcp_server/sub/__pycache__/b.{TAG}.pyc"]


def test_caches_the_interpreter_would_reject_are_not_alterations(tmp_path):
    # Codex review on #957: a stale cache (left after an upgrade) is never run,
    # importlib compiles the RECORD-matching source instead.
    package = _package(tmp_path)
    source = package / "a.py"
    _forge(source)
    stat = source.stat()
    os.utime(source, (stat.st_atime, stat.st_mtime + 10))
    _forge(package / "sub" / "b.py", flags=0b11, check=b"older source")
    assert _foreign(package) == []
    _forge(source, magic=b"\0\0\r\n")
    assert _foreign(package) == []
    _forge(source, flags=0b100)
    assert _foreign(package) == []


def test_a_short_header_is_rejected(tmp_path):
    package = _package(tmp_path)
    cfile = _forge(package / "a.py")
    cfile.write_bytes(cfile.read_bytes()[:12])
    assert _foreign(package) == []


def test_a_cache_without_its_source_is_never_imported(tmp_path):
    package = _package(tmp_path)
    (package / "c.py").write_bytes(b"y = 1\n")
    _forge(package / "c.py")
    (package / "c.py").unlink()
    assert _foreign(package) == []


def test_an_accepted_cache_that_does_not_load_is_foreign(tmp_path):
    # importlib accepts a 16-byte header, then fails to load what follows.
    package = _package(tmp_path)
    for size in (20, 16):
        cfile = _cache(package / "a.py")
        cfile.write_bytes(cfile.read_bytes()[:size])
        assert _foreign(package) == [A_CACHE]


def test_another_interpreters_cache_and_other_names_are_skipped(tmp_path):
    package = _package(tmp_path)
    cache = package / "__pycache__"
    cache.mkdir()
    names = ("a.other-99.pyc", "a.pyc", f"a.{TAG}.opt-x.pyc", f"a.{TAG}.xxxx1.pyc")
    for name in (*names, f"a.{TAG}.x.y.pyc"):
        (cache / name).write_bytes(b"\0")
    # A forged cache under another tag is not this interpreter's to import.
    _forge(package / "a.py").rename(cache / "a.other-99.pyc")
    assert _foreign(package) == []


def test_the_fix_names_the_caches_to_delete(tmp_path):
    assert doctor_bytecode.clear_caches_fix(tmp_path) == (
        f"Delete the listed bytecode files of {tmp_path} (in its `__pycache__` "
        "directories, the `pycache_prefix` tree when one is set, or beside the "
        "sources): Python rebuilds the caches from the sources at the next import"
    )


def test_a_pycache_prefix_is_where_the_caches_are_read(monkeypatch, tmp_path):
    # Codex review on #957: with `-X pycache_prefix`, Python reads the external
    # tree and ignores the package's `__pycache__`.
    package = _package(tmp_path)
    _forge(package / "sub" / "b.py")  # in-tree: not read under a prefix
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "prefix"))
    cfile = _forge(package / "a.py")
    assert not cfile.is_relative_to(package)
    assert _foreign(package) == [str(cfile)]


def test_members_that_are_not_python_sources_have_no_cache(tmp_path):
    package = _package(tmp_path)
    _forge(package / "a.py")
    (package / "0.txt").write_bytes(b"")
    assert doctor_bytecode.foreign_bytecode(package, {"mcp_server/0.txt"}) == []
    # A non-source member that sorts first must not end the scan.
    members = {"mcp_server/0.txt", "mcp_server/a.py"}
    assert doctor_bytecode.foreign_bytecode(package, members) == [A_CACHE]


def test_the_hash_check_policy_of_the_interpreter_applies(monkeypatch, tmp_path):
    # Codex review on #957: under `--check-hash-based-pycs never` a checked
    # cache with a stale hash is still imported; under `always` an unchecked one
    # is validated against its source.
    package = _package(tmp_path)
    _forge(package / "a.py", flags=0b11, check=b"older source")
    _forge(package / "sub" / "b.py", flags=0b01, check=b"older source")
    monkeypatch.setattr(doctor_bytecode._imp, "check_hash_based_pycs", "never")
    assert _foreign(package) == [A_CACHE, f"mcp_server/sub/__pycache__/b.{TAG}.pyc"]
    monkeypatch.setattr(doctor_bytecode._imp, "check_hash_based_pycs", "always")
    assert _foreign(package) == []


def test_sourceless_modules_are_listed_but_caches_are_not(tmp_path):
    package = _package(tmp_path)
    _cache(package / "a.py")
    (package / "loose.pyc").write_bytes(b"\0")
    (package / "sub" / "deep.pyc").write_bytes(b"\0")
    assert doctor_bytecode.sourceless(package) == [
        "mcp_server/loose.pyc",
        "mcp_server/sub/deep.pyc",
    ]
