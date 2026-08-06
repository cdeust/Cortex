"""Tests for mcp_server.handlers.forget — hard/soft delete with is_protected guard.

Contract under test (from forget.py docstring and handler logic):
  - POST: memory_id is required; missing → {deleted: False, reason: "no_memory_id"}
  - POST: memory_id not in store →
    {deleted: False, reason: "not_found", memory_id: <id>}
  - POST: is_protected=True without force →
    {deleted: False, reason: "protected …", memory_id: <id>}
  - POST: is_protected=True with force=True → hard-delete proceeds
  - POST: soft=False (default) → hard delete, returns
    {deleted: True, method: "hard", memory_id, content_preview}
  - POST: soft=True → marks is_stale=True and heat=0, returns
    {deleted: True, method: "soft", memory_id, content_preview}

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
        "precondition: memory must be protected after insert, "
        f"got {mem.get('is_protected')!r}"
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
        """Postcondition: hard delete returns {deleted, method, memory_id,
        content_preview}."""
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
        """Postcondition: soft delete returns {deleted, method, memory_id,
        content_preview}."""
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
        """Protected guard applies to soft deletes too — is_protected blocks any delete
        path."""
        mid = _seed_protected_memory("protected soft target")
        result = await forget_handler({"memory_id": mid, "soft": True})
        assert result["deleted"] is False
        assert "protected" in result["reason"].lower()


# ── Cross-substrate deletion (issue #366) ─────────────────────────────────
#
# PRIVACY.md tells users "The `forget` tool deletes individual memories."
# A gist+pointer memory keeps its FULL raw text in a content-addressed
# filesystem artifact (core/gist_extraction.py -> infrastructure/
# artifact_store.py). Deleting only the row leaves that content readable on
# disk, so the published control does not do what it says. These tests pin the
# contract the policy already claims.
#
# Two orderings are load-bearing and asserted separately below:
#   - wiki claims must go BEFORE the row (the FK is ON DELETE SET NULL, so
#     after the row is gone the claim no longer matches memory_id)
#   - the artifact reference check must run AFTER the row is gone (otherwise
#     the memory being forgotten counts itself as a live reference)


def _seed_artifact_backed_memory(raw: str) -> tuple[int, "object"]:
    """Store ``raw`` as an artifact and seed a memory whose body points at it.

    Returns (memory_id, artifact_path). Mirrors the production shape built by
    hooks/post_tool_capture._gist_or_full and handlers/backfill_helpers.
    """
    from mcp_server.core.gist_extraction import extract_gist, format_artifact_pointer
    from mcp_server.infrastructure.artifact_store import store_artifact

    path = store_artifact(raw)
    body = f"{extract_gist(raw)}\n\n{format_artifact_pointer(str(path), len(raw))}"
    return _seed_memory(body), path


class TestForgetDeletesArtifact:
    def test_hard_delete_removes_the_artifact_file(self):
        raw = "SECRET-CANARY-A " + ("x" * 60_000)
        mid, path = _seed_artifact_backed_memory(raw)
        assert path.exists(), "precondition: artifact must exist before forget"

        result = pytest.importorskip("asyncio").run(forget_handler({"memory_id": mid}))

        assert result["deleted"] is True
        assert not path.exists(), (
            "artifact still on disk after hard delete — PRIVACY.md claims the "
            "memory is deleted, but the full raw content survives"
        )

    def test_hard_delete_reports_artifact_removal(self):
        """The signal itself is asserted, not just the side effect (§13 F1)."""
        raw = "SECRET-CANARY-B " + ("y" * 60_000)
        mid, _path = _seed_artifact_backed_memory(raw)

        result = pytest.importorskip("asyncio").run(forget_handler({"memory_id": mid}))

        assert result.get("artifact_deleted") is True, (
            f"forget must report artifact removal in its result; got {result!r}"
        )

    def test_soft_delete_keeps_the_artifact(self):
        """Soft delete is recoverable, so its content must survive."""
        raw = "SECRET-CANARY-C " + ("z" * 60_000)
        mid, path = _seed_artifact_backed_memory(raw)

        result = pytest.importorskip("asyncio").run(
            forget_handler({"memory_id": mid, "soft": True})
        )

        assert result["method"] == "soft"
        assert path.exists(), "soft delete must NOT remove the artifact"
        assert result.get("artifact_deleted") is False

    def test_refused_delete_keeps_the_artifact(self):
        """A protected memory is not deleted, so nothing may be removed."""
        from mcp_server.core.gist_extraction import (
            extract_gist,
            format_artifact_pointer,
        )
        from mcp_server.infrastructure.artifact_store import store_artifact

        raw = "SECRET-CANARY-D " + ("w" * 60_000)
        path = store_artifact(raw)
        store = _get_forget_store()
        body = f"{extract_gist(raw)}\n\n{format_artifact_pointer(str(path), len(raw))}"
        mid = store.insert_memory({"content": body, "is_protected": True})

        result = pytest.importorskip("asyncio").run(forget_handler({"memory_id": mid}))

        assert result["deleted"] is False
        assert path.exists(), "refused delete must not touch the artifact"

    def test_shared_artifact_survives_while_another_memory_references_it(self):
        """Content addressing dedups: two identical outputs share ONE file.

        Deleting the artifact for one memory would corrupt the other, so the
        file must survive until the last referrer is gone.
        """
        raw = "SECRET-CANARY-E " + ("q" * 60_000)
        mid_a, path_a = _seed_artifact_backed_memory(raw)
        mid_b, path_b = _seed_artifact_backed_memory(raw)
        assert path_a == path_b, (
            "precondition: identical content must dedup to one path"
        )

        first = pytest.importorskip("asyncio").run(forget_handler({"memory_id": mid_a}))
        assert first["deleted"] is True
        assert path_a.exists(), (
            "artifact removed while a second memory still references it — "
            "the surviving memory's pointer now dangles"
        )
        assert first.get("artifact_deleted") is False

        second = pytest.importorskip("asyncio").run(
            forget_handler({"memory_id": mid_b})
        )
        assert second["deleted"] is True
        assert not path_a.exists(), "last referrer gone — artifact must be removed"
        assert second.get("artifact_deleted") is True

    def test_memory_without_artifact_reports_false_not_none(self):
        """Negative case: a plain memory has no artifact to remove."""
        mid = _seed_memory("plain memory, no artifact pointer")

        result = pytest.importorskip("asyncio").run(forget_handler({"memory_id": mid}))

        assert result["deleted"] is True
        assert result.get("artifact_deleted") is False
