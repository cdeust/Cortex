"""The staleness script's default dry-run mode drives the real sweep.

ADR-1100: the sweep reads the physical chain (``heads_only=False``). The
script wraps the store in ``_DryRunStore`` unless ``--apply`` is given, so the
wrapper must accept and forward that keyword; before this test it did not and
the default mode raised ``TypeError``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from mcp_server.handlers.consolidation.memory_staleness_pass import (
    revalidate_staleness,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "memory_staleness_revalidate.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "memory_staleness_revalidate", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve(refs: list[str], _base: str) -> set[str]:
    return {r for r in refs if "gone" not in r}


@pytest.fixture
def store_with_a_retracted_row():
    store = SqliteMemoryStore()
    common = {"source": "user", "domain": "staleness-script", "heat": 0.5}
    old_id = store.insert_memory({**common, "content": "see src/gone.py"})
    new_id, _ = store.supersede_atomic({**common, "content": "see src/here.py"}, old_id)
    return store, old_id, new_id


def test_dry_run_sweeps_the_physical_chain_and_writes_nothing(
    store_with_a_retracted_row,
):
    store, old_id, new_id = store_with_a_retracted_row
    dry_run = _load_script()._DryRunStore(store)

    counts = revalidate_staleness(dry_run, _resolve)

    # both rows are graded (the retracted one too) and nothing is written
    assert counts == {"scanned": 2, "marked_stale": 1}
    assert not store.get_memory(old_id)["is_stale"]
    assert not store.get_memory(new_id)["is_stale"]


def test_the_wrapper_forwards_heads_only_to_the_real_store(store_with_a_retracted_row):
    store, old_id, new_id = store_with_a_retracted_row
    dry_run = _load_script()._DryRunStore(store)

    def ids(**kw):
        rows = dry_run.get_all_memories_for_validation(
            10, after_id=0, include_stale=False, **kw
        )
        return {r["id"] for r in rows}

    assert ids(heads_only=False) == {old_id, new_id}
    assert ids(heads_only=True) == {new_id}
