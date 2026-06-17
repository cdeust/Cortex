"""Tests for mcp_server.handlers.forget — hard/soft delete with is_protected guard.

Contract under test (from forget.py docstring and handler logic):
  - POST: memory_id is required; missing → {deleted: False, reason: "no_memory_id"}
  - POST: memory_id not in store → {deleted: False, reason: "not_found", memory_id: <id>}
  - POST: is_protected=True without force → {deleted: False, reason: "protected …", memory_id: <id>}
  - POST: is_protected=True with force=True → hard-delete proceeds
  - POST: soft=False (default) → hard delete, returns {deleted: True, method: "hard", memory_id, content_preview}
  - POST: soft=True → marks is_stale=True and heat=0, returns {deleted: True, method: "soft", memory_id, content_preview}

The handler delegates to MemoryStore which uses SQLite when PG is absent.
No PG-skip needed — the store backend auto-selects via conftest.

Seeding pattern: ALL helpers insert via forget's own _get_store() so that the
write and the handler call share exactly one store instance.  Using
remember_handler (or anchor_handler) for seeding causes a different singleton
to be initialized — _reset_all_singletons (conftest autouse) resets them
between tests, producing two separate stores in SQLite mode (different temp
paths), which is the root cause of the 30-80% flake rate observed before this
fix (incident 2026-06-17).
"""

from __future__ import annotations


import pytest

from mcp_server.handlers.forget import handler as forget_handler


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_forget_store():
    """Return the store instance that forget_handler uses (same singleton)."""
    from mcp_server.handlers.forget import _get_store

    return _get_store()


def _seed_memory(content: str = "forget test memory") -> int:
    """Insert a plain (unprotected) memory via forget's own store and return its id.

    Avoids remember_handler to ensure write + handler-call share one store instance.
    """
    store = _get_forget_store()
    mid = store.insert_memory({"content": content, "force": True})
    assert isinstance(mid, int) and mid > 0, (
        f"insert_memory returned unexpected value: {mid!r}"
    )
    return mid


def _seed_protected_memory(content: str = "protected forget test memory") -> int:
    """Insert a protected (anchored) memory via forget's own store and return its id.

    Sets is_protected=True directly in insert_memory so a single store
    instance handles the entire lifecycle — no anchor_handler involved.
    """
    store = _get_forget_store()
    mid = store.insert_memory({"content": content, "is_protected": True})
    assert isinstance(mid, int) and mid > 0, (
        f"insert_memory returned unexpected value: {mid!r}"
    )
    # Belt-and-suspenders: ensure the flag is visible via the same store.
    mem = store.get_memory(mid)
    assert mem is not None, "precondition: memory must exist after insert"
    assert mem.get("is_protected") in (True, 1), (
        f"precondition: memory must be protected after insert, got {mem.get('is_protected')!r}"
    )
    return mid


# ── Output shape ──────────────────────────────────────────────────────────


class TestForgetSchema:
    def test_schema_has_required_keys(self):
        from mcp_server.handlers.forget import schema

        assert "description" in schema
        assert "inputSchema" in schema
        assert "memory_id" in schema["inputSchema"]["properties"]
        assert schema["inputSchema"]["required"] == ["memory_id"]

    def test_schema_soft_and_force_properties(self):
        from mcp_server.handlers.forget import schema

        props = schema["inputSchema"]["properties"]
        assert "soft" in props
        assert "force" in props
        assert props["soft"]["type"] == "boolean"
        assert props["force"]["type"] == "boolean"


# ── Missing / invalid args ────────────────────────────────────────────────


class TestForgetMissingArgs:
    @pytest.mark.asyncio
    async def test_no_args_returns_not_deleted(self):
        result = await forget_handler(None)
        assert result["deleted"] is False
        assert result["reason"] == "no_memory_id"

    @pytest.mark.asyncio
    async def test_empty_dict_returns_not_deleted(self):
        result = await forget_handler({})
        assert result["deleted"] is False
        assert result["reason"] == "no_memory_id"

    @pytest.mark.asyncio
    async def test_nonexistent_id_returns_not_found(self):
        result = await forget_handler({"memory_id": 999_999_999})
        assert result["deleted"] is False
        assert result["reason"] == "not_found"
        assert result["memory_id"] == 999_999_999


# ── Hard delete (default) ─────────────────────────────────────────────────


class TestForgetHardDelete:
    @pytest.mark.asyncio
    async def test_hard_delete_output_shape(self):
        """Postcondition: hard delete returns {deleted, method, memory_id, content_preview}."""
        mid = _seed_memory("hard delete target")
        result = await forget_handler({"memory_id": mid})
        assert result["deleted"] is True
        assert result["method"] == "hard"
        assert result["memory_id"] == mid
        assert "content_preview" in result
        assert isinstance(result["content_preview"], str)

    @pytest.mark.asyncio
    async def test_hard_delete_content_preview_is_truncated(self):
        """content_preview must be at most 80 chars (handler slices [:80])."""
        long_content = "X" * 200
        mid = _seed_memory(long_content)
        result = await forget_handler({"memory_id": mid})
        assert result["deleted"] is True
        assert len(result["content_preview"]) <= 80

    @pytest.mark.asyncio
    async def test_hard_delete_removes_memory_from_store(self):
        """After hard delete, get_memory returns None — the row is gone."""
        mid = _seed_memory("memory that will be hard-deleted")
        store = _get_forget_store()
        assert store.get_memory(mid) is not None, "precondition: memory exists"

        result = await forget_handler({"memory_id": mid})
        assert result["deleted"] is True

        assert store.get_memory(mid) is None, (
            "postcondition: hard delete must remove the row"
        )

    @pytest.mark.asyncio
    async def test_hard_delete_second_call_returns_not_found(self):
        """Deleting the same ID twice: first succeeds, second is not_found."""
        mid = _seed_memory("double delete target")
        first = await forget_handler({"memory_id": mid})
        assert first["deleted"] is True

        second = await forget_handler({"memory_id": mid})
        assert second["deleted"] is False
        assert second["reason"] == "not_found"


# ── Soft delete ───────────────────────────────────────────────────────────


class TestForgetSoftDelete:
    @pytest.mark.asyncio
    async def test_soft_delete_output_shape(self):
        """Postcondition: soft delete returns {deleted, method, memory_id, content_preview}."""
        mid = _seed_memory("soft delete target")
        result = await forget_handler({"memory_id": mid, "soft": True})
        assert result["deleted"] is True
        assert result["method"] == "soft"
        assert result["memory_id"] == mid
        assert "content_preview" in result

    @pytest.mark.asyncio
    async def test_soft_delete_leaves_row_in_store(self):
        """Soft delete must NOT remove the row — it is recoverable via SQL."""
        mid = _seed_memory("memory that will be soft-deleted")
        result = await forget_handler({"memory_id": mid, "soft": True})
        assert result["deleted"] is True
        assert result["method"] == "soft"

        store = _get_forget_store()
        mem = store.get_memory(mid)
        assert mem is not None, "postcondition: soft delete must keep the row"

    @pytest.mark.asyncio
    async def test_soft_delete_sets_heat_to_zero(self):
        """Soft delete must set heat=0 (handler calls update_memory_heat(id, 0.0))."""
        mid = _seed_memory("heat-check soft delete")
        await forget_handler({"memory_id": mid, "soft": True})

        store = _get_forget_store()
        mem = store.get_memory(mid)
        assert mem is not None
        assert float(mem.get("heat", -1)) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_soft_delete_marks_is_stale(self):
        """Soft delete must set is_stale=True."""
        mid = _seed_memory("stale-check soft delete")
        await forget_handler({"memory_id": mid, "soft": True})

        store = _get_forget_store()
        mem = store.get_memory(mid)
        assert mem is not None
        # is_stale can be stored as bool True or integer 1
        assert mem.get("is_stale") in (True, 1), (
            f"expected is_stale=True/1 after soft delete, got {mem.get('is_stale')!r}"
        )


# ── Protected / anchored guard ────────────────────────────────────────────


class TestForgetProtectedGuard:
    @pytest.mark.asyncio
    async def test_protected_memory_refused_without_force(self):
        """Invariant: is_protected=True (anchored) blocks delete unless force=True."""
        mid = _seed_protected_memory("protected content")
        result = await forget_handler({"memory_id": mid})
        assert result["deleted"] is False
        assert "protected" in result["reason"].lower()
        assert result["memory_id"] == mid

    @pytest.mark.asyncio
    async def test_protected_memory_deleted_with_force(self):
        """Invariant: force=True overrides is_protected and hard-deletes."""
        mid = _seed_protected_memory("protected but forced")
        result = await forget_handler({"memory_id": mid, "force": True})
        assert result["deleted"] is True
        assert result["method"] == "hard"
        assert result["memory_id"] == mid

    @pytest.mark.asyncio
    async def test_protected_row_survives_without_force(self):
        """After a refused delete, the row must still be in the store."""
        mid = _seed_protected_memory("protected survivor")
        await forget_handler({"memory_id": mid})  # refused — no force

        store = _get_forget_store()
        assert store.get_memory(mid) is not None, (
            "postcondition: refused delete must not remove the row"
        )

    @pytest.mark.asyncio
    async def test_unprotected_memory_deleted_without_force(self):
        """Unprotected memories must not require force=True."""
        mid = _seed_memory("unprotected memory")
        result = await forget_handler({"memory_id": mid})
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_protected_soft_delete_refused_without_force(self):
        """Protected guard applies to soft deletes too — is_protected blocks any delete path."""
        mid = _seed_protected_memory("protected soft target")
        result = await forget_handler({"memory_id": mid, "soft": True})
        assert result["deleted"] is False
        assert "protected" in result["reason"].lower()
