"""Tests for mcp_server.handlers.anchor — compaction-resistant memory pinning.

Contract under test (from anchor.py docstring and schema):
  POST-1: anchored=True + memory_id in response when memory exists.
  POST-2: heat_base=1.0, no_decay=TRUE, is_protected=TRUE, importance=1.0 written to store.
  POST-3: _anchor tag added to tag list; existing tags preserved.
  POST-4: reason stored as [ANCHOR: <reason>] content prefix; _anchor:<reason[:40]> tag added.
  POST-5: is_global flag stored to memories.is_global.
  POST-6: anchored=False + reason when memory_id is missing from args.
  POST-7: anchored=False + reason when memory_id refers to a nonexistent memory.
  POST-8: idempotent — anchoring an already-anchored memory does not duplicate _anchor tag.
"""

import pytest

from mcp_server.handlers.anchor import (
    handler as anchor_handler,
    _build_anchor_tags,
    _build_anchor_content,
)


# ── Pure-function unit tests (no DB, no skip) ─────────────────────────────


class TestBuildAnchorTags:
    """POST-3, POST-4 — pure logic, no I/O."""

    def test_adds_anchor_tag(self):
        tags = _build_anchor_tags({"tags": ["python"]}, reason="")
        assert "_anchor" in tags
        assert "python" in tags  # existing tag preserved

    def test_no_duplicate_anchor_tag(self):
        tags = _build_anchor_tags({"tags": ["_anchor", "other"]}, reason="")
        assert tags.count("_anchor") == 1

    def test_reason_appended_as_scoped_tag(self):
        tags = _build_anchor_tags({"tags": []}, reason="critical decision")
        assert "_anchor:critical decision" in tags

    def test_reason_truncated_to_40_chars(self):
        long_reason = "x" * 50
        tags = _build_anchor_tags({"tags": []}, reason=long_reason)
        scoped = [t for t in tags if t.startswith("_anchor:")]
        assert len(scoped) == 1
        suffix = scoped[0][len("_anchor:") :]
        assert len(suffix) <= 40

    def test_no_reason_no_scoped_tag(self):
        tags = _build_anchor_tags({"tags": ["existing"]}, reason="")
        scoped = [t for t in tags if t.startswith("_anchor:")]
        assert scoped == []

    def test_existing_tags_json_string_parsed(self):
        """Tags stored as JSON string in DB must be parsed correctly."""
        tags = _build_anchor_tags({"tags": '["tag1","tag2"]'}, reason="")
        assert "tag1" in tags
        assert "tag2" in tags
        assert "_anchor" in tags

    def test_empty_tag_list(self):
        tags = _build_anchor_tags({"tags": []}, reason="")
        assert "_anchor" in tags
        assert len(tags) == 1

    def test_no_tags_key(self):
        tags = _build_anchor_tags({}, reason="")
        assert "_anchor" in tags


class TestBuildAnchorContent:
    """POST-4 — content prefix logic."""

    def test_prefix_added_when_reason_given(self):
        content = _build_anchor_content("original content", reason="key insight")
        assert content.startswith("[ANCHOR: key insight]")
        assert "original content" in content

    def test_no_prefix_when_no_reason(self):
        content = _build_anchor_content("original content", reason="")
        assert content == "original content"

    def test_no_double_prefix(self):
        """Second anchor call must not nest the prefix."""
        already = "[ANCHOR: first] some content"
        content = _build_anchor_content(already, reason="second")
        assert content.count("[ANCHOR:") == 1


# ── Handler integration tests (hit the store; SQLite fallback when no PG) ─


class TestAnchorHandlerMissingArg:
    """POST-6 — missing memory_id: no DB required."""

    @pytest.mark.asyncio
    async def test_no_args_returns_error(self):
        result = await anchor_handler(None)
        assert result["anchored"] is False
        assert "memory_id" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_empty_args_returns_error(self):
        result = await anchor_handler({})
        assert result["anchored"] is False
        assert "memory_id" in result["reason"].lower()


class TestAnchorHandlerMissingMemory:
    """POST-7 — memory_id that does not exist."""

    @pytest.mark.asyncio
    async def test_nonexistent_memory_returns_error(self):
        result = await anchor_handler({"memory_id": 999_999_999})
        assert result["anchored"] is False
        assert "999999999" in result["reason"] or "memory not found" in result["reason"]


def _seed_memory(content: str, tags=None, **kwargs) -> int:
    """Seed a memory directly via anchor's own store singleton.

    Using the same _get_store() as anchor_handler guarantees write and
    handler-call share exactly one store instance, regardless of whether
    the conftest _test_isolation fixture has reset other handler singletons.
    Using remember_handler (a different module) lazily initialises a
    DIFFERENT singleton and causes commit-visibility races / different SQLite
    temp dirs — the root cause of the 30% flake rate (confirmed 2026-06-17).
    """
    from mcp_server.handlers.anchor import _get_store

    store = _get_store()

    data: dict = {
        "content": content,
        "tags": tags or [],
        "source": "test",
        "force": True,
    }
    data.update(kwargs)
    return store.insert_memory(data)


class TestAnchorHandlerSuccess:
    """POST-1 through POST-5 — requires a live store (PG or SQLite fallback)."""

    @pytest.mark.asyncio
    async def test_success_output_shape(self):
        """POST-1: response fields present and correct types."""
        mid = _seed_memory("Anchor shape test memory")
        result = await anchor_handler({"memory_id": mid})
        assert result["anchored"] is True
        assert result["memory_id"] == mid
        assert isinstance(result["tags"], list)
        assert isinstance(result["content_preview"], str)

    @pytest.mark.asyncio
    async def test_anchor_tag_added(self):
        """POST-3: _anchor tag present after anchoring."""
        mid = _seed_memory("Memory that needs anchoring", tags=["existing"])
        result = await anchor_handler({"memory_id": mid})
        assert result["anchored"] is True
        assert "_anchor" in result["tags"]
        assert "existing" in result["tags"]

    @pytest.mark.asyncio
    async def test_anchor_with_reason_prefix_and_tag(self):
        """POST-4: reason becomes content prefix AND scoped tag."""
        mid = _seed_memory("Load bearing decision content")
        result = await anchor_handler(
            {"memory_id": mid, "reason": "critical architecture decision"}
        )
        assert result["anchored"] is True
        assert result["content_preview"].startswith(
            "[ANCHOR: critical architecture decision]"
        )
        assert any(t.startswith("_anchor:critical") for t in result["tags"]), (
            f"scoped anchor tag missing from {result['tags']}"
        )

    @pytest.mark.asyncio
    async def test_store_flags_written(self):
        """POST-2: heat_base=1.0, no_decay=TRUE, is_protected=TRUE, importance=1.0."""
        mid = _seed_memory("Memory to verify DB flags after anchor")
        anchor_result = await anchor_handler({"memory_id": mid})
        assert anchor_result["anchored"] is True

        # Read back from the SAME store singleton and verify flags were set
        from mcp_server.handlers.anchor import _get_store

        store = _get_store()
        mem = store.get_memory(mid)
        assert mem is not None

        # heat_base must be 1.0 (post-A3: column is heat_base, not heat)
        heat_base = mem.get("heat_base")
        assert heat_base is not None, (
            f"heat_base column missing from get_memory() result: {list(mem.keys())}"
        )
        assert float(heat_base) == pytest.approx(1.0, abs=1e-6), (
            f"Expected heat_base=1.0, got {heat_base}"
        )

        # is_protected must be truthy
        assert mem.get("is_protected") is True or mem.get("is_protected") == 1, (
            f"Expected is_protected=True, got {mem.get('is_protected')}"
        )

        # importance must be 1.0
        importance = mem.get("importance")
        if importance is not None:
            assert float(importance) == pytest.approx(1.0, abs=1e-6), (
                f"Expected importance=1.0, got {importance}"
            )

    @pytest.mark.asyncio
    async def test_is_global_stored(self):
        """POST-5: is_global=True propagated to DB."""
        mid = _seed_memory("Global anchor test memory")
        result = await anchor_handler({"memory_id": mid, "is_global": True})
        assert result["anchored"] is True
        assert result["is_global"] is True

    @pytest.mark.asyncio
    async def test_idempotent_anchor_no_duplicate_tag(self):
        """POST-8: anchoring twice does not duplicate _anchor tag."""
        mid = _seed_memory("Idempotent anchor test memory")
        await anchor_handler({"memory_id": mid, "reason": "first anchor"})
        result = await anchor_handler({"memory_id": mid, "reason": "first anchor"})
        assert result["anchored"] is True
        assert result["tags"].count("_anchor") == 1

    @pytest.mark.asyncio
    async def test_reason_field_in_response(self):
        """reason field present in both success and no-reason paths."""
        mid = _seed_memory("Reason field test memory")

        # With reason
        result = await anchor_handler({"memory_id": mid, "reason": "why it matters"})
        assert result["reason"] == "why it matters"

        # Without reason — handler returns "no reason given"
        mid2 = _seed_memory("Reason field test memory 2")
        result2 = await anchor_handler({"memory_id": mid2})
        assert result2["reason"] == "no reason given"


class TestAnchorSchema:
    """Schema artifact must be present and well-formed."""

    def test_schema_exists(self):
        from mcp_server.handlers.anchor import schema

        assert "description" in schema
        assert "inputSchema" in schema

    def test_schema_requires_memory_id(self):
        from mcp_server.handlers.anchor import schema

        required = schema["inputSchema"].get("required", [])
        assert "memory_id" in required

    def test_schema_lists_optional_fields(self):
        from mcp_server.handlers.anchor import schema

        props = schema["inputSchema"]["properties"]
        assert "reason" in props
        assert "is_global" in props
