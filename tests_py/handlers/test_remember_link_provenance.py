"""Tests for the 'link' curation action's provenance tag
(fix/memory-link-fk-violation).

source: ADR-0954"""

from __future__ import annotations

import asyncio

from mcp_server.handlers.remember import handler
from mcp_server.handlers.remember_prepared import ObservedNeighbors
from mcp_server.shared.memory_rows import MemoryRows
from mcp_server.handlers.remember_helpers import (
    _with_link_provenance,
    insert_and_post_process,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store


class TestWithLinkProvenance:
    def test_link_action_appends_marker_and_category(self):
        tags = _with_link_provenance("link", 42, ["existing"])
        assert "existing" in tags
        assert "link-derived" in tags
        assert "derived-src:42" in tags

    def test_create_action_is_unaffected(self):
        tags = _with_link_provenance("create", None, ["existing"])
        assert tags == ["existing"]

    def test_supersede_action_is_unaffected(self):
        tags = _with_link_provenance("supersede", 7, ["existing"])
        assert tags == ["existing"]

    def test_link_action_without_merged_id_is_unaffected(self):
        # Defensive: try_curation only ever returns ("link", cand_id) with a
        # real id, but the guard must hold even if that contract is ever
        # broken by a future caller.
        tags = _with_link_provenance("link", None, ["existing"])
        assert tags == ["existing"]

    def test_does_not_mutate_input_list(self):
        original = ["keep"]
        _with_link_provenance("link", 5, original)
        assert original == ["keep"]


_MOD = {
    "heat": 0.5,
    "importance": 0.5,
    "valence": 0.0,
    "theta": 0.0,
    "enc_mod": 1.0,
    "schema_match": 0.0,
    "schema_id": None,
    "emotional_tag": None,
    "emb_nov": 0.5,
    "ent_nov": 0.5,
    "temp_nov": 0.5,
    "struct_nov": 0.5,
    "neuro_mod": None,
}


class _NoopEngine:
    def encode(self, _text):
        return None

    def similarity(self, _a, _b) -> float:
        return 0.0


class TestInsertAndPostProcessLinkAction:
    """Integration proof against the real (test-configured) store: the
    'link' action must persist `derived-src:<merged_id>` on the new row and
    must never attempt the FK-violating `relationships` insert.

    embedding=None short-circuits `write_gate.apply_pattern_separation`
    before it touches `emb_engine`/`store` beyond the no-op path, so
    `_NoopEngine` is a safe stand-in — mirrors the existing conflict-path
    fixture in test_remember_supersede.py.
    """

    def test_link_row_carries_derived_src_tag(self):
        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)

        target = asyncio.run(
            handler(
                {
                    "content": "Link-provenance target fact: retries default to 3",
                    "force": True,
                }
            )
        )
        assert target["stored"] is True
        target_id = target["memory_id"]

        result = insert_and_post_process(
            content="Link-provenance derivative fact: retries default to 3, confirmed",
            embedding=None,
            tags=["unit-test"],
            source="user",
            domain="unit-test",
            directory="",
            action="link",
            merged_id=target_id,
            neighbors=ObservedNeighbors([], [], MemoryRows({})),
            ent_names=[],
            extracted=[],
            mod=_MOD,
            novelty_score=0.5,
            store=store,
            emb_engine=_NoopEngine(),
        )

        assert result["stored"] is True
        new_id = result["memory_id"]
        stored_row = store.get_memory(new_id)
        assert stored_row is not None
        tags = stored_row.get("tags") or []
        if isinstance(tags, str):
            import json as _json

            tags = _json.loads(tags)
        assert "link-derived" in tags
        assert f"derived-src:{target_id}" in tags
