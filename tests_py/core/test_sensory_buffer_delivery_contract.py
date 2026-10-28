"""Buffered evidence survives displacement and is delivered only once.

source: sensory_buffer.SensoryBuffer public drain/peek contracts (ADR-0252).
"""

from mcp_server.core import sensory_buffer as sensory


def test_overflow_and_partial_drain_preserve_each_event(monkeypatch):
    # Score computation is a separate port; exercise delivery with known scores.
    scores = {"old": 0.2, "important": 0.6, "recent": 0.4, "urgent": 0.9}
    monkeypatch.setattr(
        sensory.thermodynamics,
        "compute_importance",
        lambda content, tags: scores[content],
    )
    buffer = sensory.SensoryBuffer(capacity=2, importance_threshold=0.8)
    for content in ("old", "important", "recent"):
        result = buffer.push(content, source="session", domain="cortex")
        assert result["buffered"] is True
    assert buffer.capacity == 2
    assert buffer.size == 2
    assert buffer.is_full
    assert [item.content for item in buffer.peek(1)] == ["recent"]
    assert [item.content for item in buffer.peek_important(0.5)] == ["important"]
    assert buffer.peek_important() == []
    stats = buffer.stats()
    assert stats["displaced_pending"] == 1
    assert stats["sources"] == ["session"]
    assert stats["fill_pct"] == 100.0

    displaced = buffer.drain_displaced()
    assert [(item.content, item.domain) for item in displaced] == [("old", "cortex")]
    assert buffer.drain_displaced() == []
    urgent = buffer.push("urgent", tags=["decision"], directory="/project")
    assert urgent["is_urgent"] is True
    assert urgent["buffered"] is False
    assert urgent["item"]["content"] == "urgent"
    assert urgent["item"]["directory"] == "/project"
    assert buffer.size == 2

    drained = buffer.drain(min_importance=0.3, max_items=1)
    assert [item.content for item in drained] == ["important"]
    assert [item.content for item in buffer.peek()] == ["recent"]
    assert buffer.drain(min_importance=0.5) == []
    assert [item.content for item in buffer.drain_all()] == ["recent"]
    assert buffer.drain_all() == []
    assert buffer.stats()["size"] == 0
    assert not buffer.is_full


def test_global_buffer_is_shared_until_explicit_reset(monkeypatch):
    monkeypatch.setattr(sensory, "_global_buffer", None)
    first = sensory.get_global_buffer(capacity=2)
    assert sensory.get_global_buffer(capacity=9) is first
    sensory.reset_global_buffer()
    replacement = sensory.get_global_buffer(capacity=3)
    assert replacement is not first
    assert replacement.capacity == 3
    assert replacement.size == 0
