"""Caches an installed wheel would import in place of its sources (#957 review)."""

import importlib.util
import py_compile
import sys
from pathlib import Path

from mcp_server import doctor_bytecode

TAG = sys.implementation.cache_tag
MEMBERS = {"mcp_server/a.py", "mcp_server/sub/b.py"}


def _package(tmp_path):
    package = tmp_path / "mcp_server"
    (package / "sub").mkdir(parents=True)
    (package / "a.py").write_bytes(b'"""doc"""\nassert True\n')
    (package / "sub" / "b.py").write_bytes(b'"""doc"""\nassert True\n')
    return package


def _cache(source, *, level=0, built_from=None):
    cfile = importlib.util.cache_from_source(
        str(source), optimization=level if level else ""
    )
    py_compile.compile(
        str(built_from or source), cfile=cfile, doraise=True, optimize=level
    )
    return cfile


def test_caches_compiled_from_their_sources_are_accepted(tmp_path):
    package = _package(tmp_path)
    _cache(package / "a.py")
    _cache(package / "sub" / "b.py", level=2)
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == []


def test_a_forged_optimised_cache_is_foreign(tmp_path):
    package = _package(tmp_path)
    (tmp_path / "evil.py").write_bytes(b"x = 2\n")
    _cache(package / "a.py", level=1, built_from=tmp_path / "evil.py")
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == [
        f"mcp_server/__pycache__/a.{TAG}.opt-1.pyc"
    ]


def test_a_cache_built_from_other_code_is_foreign(tmp_path):
    package = _package(tmp_path)
    (tmp_path / "evil.py").write_bytes(b"x = 2\n")
    cfile = _cache(package / "a.py", built_from=tmp_path / "evil.py")
    # A skipped name that sorts first must not end the scan.
    (Path(cfile).parent / "_.aaa-1.pyc").write_bytes(b"\0")
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == [
        f"mcp_server/__pycache__/a.{TAG}.pyc"
    ]


def test_a_cache_at_the_wrong_optimisation_level_is_foreign(tmp_path):
    # `assert` and docstrings are stripped at -OO: opt-2 bytecode of b.py is
    # not the plain compile, so a plain cache file holding it is foreign.
    package = _package(tmp_path)
    source = package / "sub" / "b.py"
    plain = importlib.util.cache_from_source(str(source))
    py_compile.compile(str(source), cfile=plain, doraise=True, optimize=2)
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == [
        f"mcp_server/sub/__pycache__/b.{TAG}.pyc"
    ]


def test_a_cache_without_a_hashed_source_is_foreign(tmp_path):
    package = _package(tmp_path)
    (package / "c.py").write_bytes(b"y = 1\n")
    _cache(package / "c.py")
    (package / "c.py").unlink()
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == [
        f"mcp_server/__pycache__/c.{TAG}.pyc"
    ]


def test_an_unreadable_cache_is_foreign(tmp_path):
    package = _package(tmp_path)
    cfile = _cache(package / "a.py")
    with open(cfile, "r+b") as handle:
        handle.truncate(20)
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == [
        f"mcp_server/__pycache__/a.{TAG}.pyc"
    ]


def test_another_interpreters_cache_and_other_names_are_skipped(tmp_path):
    package = _package(tmp_path)
    cache = package / "__pycache__"
    cache.mkdir()
    names = ("a.other-99.pyc", "a.pyc", f"a.{TAG}.opt-x.pyc", f"a.{TAG}.xxxx1.pyc")
    for name in (*names, f"a.{TAG}.x.y.pyc"):
        (cache / name).write_bytes(b"\0")
    assert doctor_bytecode.foreign_bytecode(package, MEMBERS) == []
