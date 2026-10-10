"""Only a reviewed maintenance caller may ask a listing for the physical chain.

Decision: listings that serve content return chain heads by default (the
ADR is cited here once it is applied on this branch).

The shared listing primitives return supersession chain heads by default. A
caller that passes ``heads_only=False`` receives retracted rows, so every such
call site must be a reviewed maintenance site, named here. Two checks:

* a literal ``heads_only=False`` outside ``_MAINTENANCE_SITES`` fails;
* a maintenance module (``handlers/consolidation/`` and
  ``handlers/validate_memory.py``) that calls a listing without stating
  ``heads_only`` at all fails, so a new maintenance caller cannot silently
  inherit the content-serving default.

Limit of this test, by construction: it reads source text. It cannot see a
``heads_only`` value computed at run time, a listing reached through
``getattr``, or a maintenance caller living in a module that is not listed in
``_MAINTENANCE_MODULES``. The behavioural pins are in
``test_superseded_listing_defaults.py`` and in the per-handler tests.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"


def _listings(cls: type) -> frozenset[str]:
    return frozenset(
        name
        for name, fn in inspect.getmembers(cls, inspect.isfunction)
        if "heads_only" in inspect.signature(fn).parameters
    )


_LISTINGS = _listings(SqliteMemoryStore)

# source: reviewed 2026-10-10 by the author of this change. Each entry is a
# maintenance caller that needs the physical chain.
_VALIDATE = "handlers/validate_memory.py"
_CONSOLIDATION = "handlers/consolidation/"
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
        "handlers/curate_distill.py::get_memories_by_tag",
    }
)


def _is_maintenance_module(rel: str) -> bool:
    return rel.startswith(_CONSOLIDATION) or rel == _VALIDATE


def _calls():
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("infrastructure/"):
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
