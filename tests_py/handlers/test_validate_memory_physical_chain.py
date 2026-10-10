"""validate_memory re-grades the physical chain, superseded rows included.

Validation is a maintenance read. It must pass
``heads_only=False`` on every selection path; if it stopped, a retracted
version would silently drop out of the validation report.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.handlers.validate_memory import _select_memories
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DOMAIN = "validate-physical-chain"
_DIRECTORY = "/fixture/validate-physical-chain"
# source: mcp_server/infrastructure/pg_schema.py:29 (memories.embedding vector(384))
_DIM = 384


@pytest.fixture
def chain():
    store = SqliteMemoryStore()
    vec = np.random.default_rng(1).standard_normal(_DIM).astype(np.float32)
    common = {
        "embedding": (vec / np.linalg.norm(vec)).tobytes(),
        "source": "user",
        "domain": _DOMAIN,
        "directory_context": _DIRECTORY,
        "tags": [],
        "heat": 0.9,
    }
    old_id = store.insert_memory({**common, "content": "validated fact: old"})
    new_id, _ = store.supersede_atomic(
        {**common, "content": "validated fact: new"}, old_id
    )
    return store, old_id, new_id


@pytest.mark.parametrize(
    "args",
    [
        {"domain": _DOMAIN},
        {"directory": _DIRECTORY},
        {},
    ],
    ids=["by-domain", "by-directory", "whole-store"],
)
def test_every_selection_path_includes_the_superseded_row(chain, args):
    store, old_id, new_id = chain
    ids = {m["id"] for m in _select_memories(args, store)}
    assert {old_id, new_id} <= ids
