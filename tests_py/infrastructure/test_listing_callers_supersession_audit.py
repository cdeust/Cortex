"""Only a reviewed maintenance caller may ask a listing for the physical chain.

ADR-1100: listings that serve content return chain heads by default, and a
maintenance reader asks for the physical chain explicitly.

The shared listing primitives return supersession chain heads by default. A
caller that passes ``heads_only=False`` receives retracted rows, so every such
call site must be a reviewed maintenance site, named here. Two checks:

* a literal ``heads_only=False`` outside ``_MAINTENANCE_SITES`` fails;
* a maintenance module (``handlers/consolidation/``,
  ``handlers/validate_memory.py`` and everything under ``scripts/``) that
  calls a listing without stating ``heads_only`` at all fails, so a new
  maintenance caller cannot silently inherit the content-serving default;
* the ``heads_only`` default of every listing is the same on SQLite and
  PostgreSQL, compared from the declared signatures (no server needed), and
  every non-test class that defines a listing accepts the keyword.

The walk covers every Python file of the repository outside the tests, the
virtualenv and vendored trees, ``scripts/`` and ``benchmarks/`` included.

Limit of this test, by construction: it reads source text. It cannot see a
``heads_only`` value computed at run time, a listing reached through
``getattr``, or a maintenance caller living in a module that is not listed in
``_MAINTENANCE_MODULES``. The behavioural pins are in
``test_superseded_listing_defaults.py`` and in the per-handler tests.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_REPO = Path(__file__).resolve().parents[2]
_INFRA = _REPO / "mcp_server" / "infrastructure"
# source: directories that hold no production caller of a store listing. "deps"
# is the launcher's vendored install (.gitignore:77 /deps/), third-party code.
_SKIPPED_DIRS = frozenset(
    {".git", ".venv", ".claude", "deps", "node_modules", "tests_py", "tests_js", "wiki"}
)


def _listings(cls: type) -> frozenset[str]:
    return frozenset(
        name
        for name, fn in inspect.getmembers(cls, inspect.isfunction)
        if "heads_only" in inspect.signature(fn).parameters
    )


_LISTINGS = _listings(SqliteMemoryStore)

# source: reviewed 2026-10-10 by the author of this change. Each entry is a
# maintenance caller that needs the physical chain.
_VALIDATE = "mcp_server/handlers/validate_memory.py"
_CONSOLIDATION = "mcp_server/handlers/consolidation/"
_SCRIPTS = "scripts/"
_MAINTENANCE_SITES = frozenset(
    {
        # validation re-grades every row, superseded ones included
        f"{_VALIDATE}::get_memories_for_domain",
        f"{_VALIDATE}::get_memories_for_directory",
        f"{_VALIDATE}::get_all_memories_for_validation",
        # consolidation passes maintain the physical chain
        f"{_CONSOLIDATION}pruning.py::get_hot_memories",
        f"{_CONSOLIDATION}plasticity.py::get_hot_memories",
        f"{_CONSOLIDATION}memory_staleness_pass.py::get_all_memories_for_validation",
        # idempotency marker scans must still see a superseded carrier
        f"{_CONSOLIDATION}memify_derive.py::get_memories_by_tag",
        "mcp_server/handlers/curate_distill.py::get_memories_by_tag",
        # duplicate prevention: a retracted carrier must still block a re-write
        "mcp_server/handlers/ingest_findings_writers.py::get_memories_by_tag",
        "mcp_server/handlers/ingest_document_writers.py::get_memories_by_tag",
    }
)


def _is_maintenance_module(rel: str) -> bool:
    return rel.startswith((_CONSOLIDATION, _SCRIPTS)) or rel == _VALIDATE


def _python_files():
    for root, dirs, files in os.walk(_REPO):
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(root) / name


def _calls():
    for path in _python_files():
        rel = path.relative_to(_REPO).as_posix()
        if rel.startswith("mcp_server/infrastructure/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LISTINGS
            ):
                yield rel, node.func.attr, {k.arg: k.value for k in node.keywords}


def test_the_listing_set_is_the_same_on_both_backends():
    pg_store = pytest.importorskip(
        "mcp_server.infrastructure.pg_store", reason="psycopg not installed"
    )
    assert _listings(pg_store.PgMemoryStore) == _LISTINGS


def test_only_reviewed_maintenance_sites_request_the_physical_chain():
    found = {
        f"{rel}::{name}"
        for rel, name, kws in _calls()
        if isinstance(kws.get("heads_only"), ast.Constant)
        and kws["heads_only"].value is False
    }
    assert found == _MAINTENANCE_SITES


def test_a_maintenance_module_states_heads_only_on_every_listing_call():
    silent = sorted(
        f"{rel}::{name}"
        for rel, name, kws in _calls()
        if _is_maintenance_module(rel) and "heads_only" not in kws
    )
    assert silent == []


def _declared_defaults(prefix: str) -> dict[str, object]:
    """``heads_only`` default of every method declared in ``<prefix>_store*.py``."""
    found: dict[str, object] = {}
    for path in sorted(_INFRA.glob(f"{prefix}_store*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef):
                continue
            a = node.args
            positional = a.posonlyargs + a.args
            defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
            pairs = list(zip(positional, defaults, strict=True)) + list(
                zip(a.kwonlyargs, a.kw_defaults, strict=True)
            )
            for arg, default in pairs:
                if arg.arg == "heads_only":
                    found[node.name] = (
                        default.value if isinstance(default, ast.Constant) else default
                    )
    return found


def test_the_heads_only_defaults_are_the_same_on_both_backends():
    sqlite = _declared_defaults("sqlite")
    pg = _declared_defaults("pg")
    assert sqlite == pg
    assert set(sqlite) == _LISTINGS
    # ADR-1100 search_vectors is the one listing keyed by physical rows
    assert {n for n, d in sqlite.items() if d is not True} == {"search_vectors"}
    assert sqlite["search_vectors"] is False


def test_every_non_test_class_defining_a_listing_accepts_heads_only():
    refusing = []
    for path in _python_files():
        rel = path.relative_to(_REPO).as_posix()
        if rel.startswith("mcp_server/infrastructure/"):
            continue
        for cls in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name in _LISTINGS:
                    names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
                    if "heads_only" not in names and fn.args.kwarg is None:
                        refusing.append(f"{rel}::{cls.name}.{fn.name}")
    assert refusing == []
