"""Direct unit test for `buffer_item_to_dict` (issue #282).

`BufferItem` is a plain `@dataclass`; mutmut categorically skips the body
of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:236`),
so the serialization logic that used to live on `BufferItem.to_dict` carries
zero mutation coverage unless exercised directly against the extracted free
function. No dedicated test module for `sensory_buffer.py` existed prior to
this file — `SensoryBuffer` itself is exercised indirectly via
`recall_pipeline` / `write_post_store` tests.
"""

from __future__ import annotations

from mcp_server.core.sensory_buffer import BufferItem, buffer_item_to_dict


def test_buffer_item_to_dict_round_trips_all_fields():
    item = BufferItem(
        content="hello world",
        tags=["a", "b"],
        source="buffer",
        directory="/tmp/proj",
        domain="cortex",
        importance=0.42,
        valence=0.1,
        created_at="2026-01-01T00:00:00+00:00",
    )
    d = buffer_item_to_dict(item)
    assert d == {
        "content": "hello world",
        "tags": ["a", "b"],
        "source": "buffer",
        "directory": "/tmp/proj",
        "domain": "cortex",
        "importance": 0.42,
        "valence": 0.1,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_buffer_item_to_dict_is_not_the_same_object_field_references_reused():
    """A snapshot dict, not a mutation-hiding alias trick."""
    item = BufferItem(
        content="x",
        tags=["t"],
        source="s",
        directory="d",
        domain="dom",
        importance=1.0,
        valence=-1.0,
    )
    d = buffer_item_to_dict(item)
    assert d["tags"] is item.tags  # same list object — no defensive copy claimed
    assert d["importance"] == 1.0
    assert d["valence"] == -1.0
