"""Integration tests: full memory session lifecycle.

Tests the end-to-end flow:
  store -> recall -> checkpoint -> restore -> consolidate -> decay
"""

import pytest


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_store_recall_checkpoint_restore(self):
        """Store memories, recall them, checkpoint, restore."""
        from mcp_server.handlers.remember import handler as remember
        from mcp_server.handlers.recall import handler as recall
        from mcp_server.handlers.checkpoint import handler as checkpoint

        # 1. Store memories
        r1 = await remember(
            {
                "content": "Always use UTC timestamps in the database layer",
                "tags": ["architecture", "decision"],
                "directory": "/project/src",
                "domain": "backend",
                "source": "user",
                "force": True,
            }
        )
        assert r1.get("stored") is True or r1.get("status") == "stored"

        r2 = await remember(
            {
                "content": "SQLite WAL mode improves concurrent read performance",
                "tags": ["database", "performance"],
                "directory": "/project/src",
                "domain": "backend",
                "source": "user",
                "force": True,
            }
        )
        assert r2.get("stored") is True or r2.get("status") == "stored"

        await remember(
            {
                "content": "Remember to add index on created_at column for the queries table",
                "tags": ["todo", "database"],
                "directory": "/project/src",
                "domain": "backend",
                "source": "user",
                "force": True,
            }
        )

        # 2. Recall
        recall_result = await recall(
            {
                "query": "database performance UTC",
                "max_results": 10,
                "min_heat": 0.0,
            }
        )
        assert recall_result["total"] > 0
        contents = [m["content"] for m in recall_result["results"]]
        # At least one of our memories should appear
        assert any("UTC" in c or "WAL" in c or "index" in c for c in contents)

        # 3. Checkpoint
        save_result = await checkpoint(
            {
                "action": "save",
                "current_task": "Building database layer",
                "files_being_edited": ["store.py", "schema.sql"],
                "key_decisions": ["Use WAL mode", "UTC timestamps"],
                "directory": "/project/src",
            }
        )
        assert save_result["status"] == "saved"

        # 4. Restore
        restore_result = await checkpoint(
            {
                "action": "restore",
                "directory": "/project/src",
            }
        )
        assert restore_result["status"] == "restored"
        assert restore_result["checkpoint"] is True
        assert "Building database layer" in restore_result["formatted"]
        assert "store.py" in restore_result["formatted"]

    @pytest.mark.asyncio
    async def test_store_consolidate_recall(self):
        """Store memories, run consolidation, verify they're still recallable."""
        from mcp_server.handlers.remember import handler as remember
        from mcp_server.handlers.recall import handler as recall
        from mcp_server.handlers.consolidate import handler as consolidate

        # Store
        await remember(
            {
                "content": "The authentication module uses JWT with RS256 signing",
                "tags": ["auth", "security"],
                "domain": "backend",
                "source": "user",
                "force": True,
            }
        )

        # Consolidate (should be no-op on fresh memories)
        con_result = await consolidate({"decay": True, "compress": True})
        assert "duration_ms" in con_result

        # Recall should still work
        recall_result = await recall(
            {
                "query": "authentication JWT signing",
                "max_results": 5,
                "min_heat": 0.0,
            }
        )
        assert recall_result["total"] > 0

    @pytest.mark.asyncio
    async def test_memory_stats_after_operations(self):
        """Memory stats reflect stored memories."""
        from mcp_server.handlers.remember import handler as remember
        from mcp_server.handlers.memory_stats import handler as stats

        # Baseline stats
        s0 = await stats()
        initial_count = s0.get("total_memories", 0)

        # Store
        await remember(
            {
                "content": "Important fact about the codebase architecture",
                "tags": ["architecture"],
                "source": "user",
                "force": True,
            }
        )

        # Stats should show increase
        s1 = await stats()
        assert s1["total_memories"] > initial_count

    @pytest.mark.asyncio
    async def test_domain_scoped_recall(self):
        """Memories stored with domain should be retrievable domain-scoped."""
        from mcp_server.handlers.remember import handler as remember
        from mcp_server.handlers.recall import handler as recall

        # Store in different domains
        await remember(
            {
                "content": "Frontend uses React with TypeScript strict mode",
                "tags": ["frontend"],
                "domain": "frontend",
                "source": "user",
                "force": True,
            }
        )
        await remember(
            {
                "content": "Backend uses FastAPI with Pydantic validation",
                "tags": ["backend"],
                "domain": "backend",
                "source": "user",
                "force": True,
            }
        )

        # Recall scoped to backend
        result = await recall(
            {
                "query": "framework validation",
                "domain": "backend",
                "max_results": 5,
                "min_heat": 0.0,
            }
        )
        # Should find the backend memory
        assert result["total"] > 0


class TestHookScripts:
    def test_session_lifecycle_process_event(self):
        """Session lifecycle hook processes events without crashing."""
        from mcp_server.hooks.session_lifecycle import process_event

        # No event — should not raise
        process_event(None)
        process_event({})

    def test_compaction_checkpoint_process_event(self):
        """Compaction hook creates checkpoint without crashing."""
        from mcp_server.hooks.compaction_checkpoint import process_event

        # Should create a checkpoint (or fail gracefully)
        process_event(None)
        process_event({"session_id": "test-compaction"})


class TestMicroCheckpointIntegration:
    @pytest.mark.asyncio
    async def test_error_triggers_micro_checkpoint(self):
        """When content contains errors, micro-checkpoint should trigger."""
        from mcp_server.core.replay import should_micro_checkpoint

        ok, reason = should_micro_checkpoint(
            "RuntimeError: database is locked", ["error"], tool_call_count=10
        )
        assert ok is True
        assert reason == "error_detected"

    @pytest.mark.asyncio
    async def test_checkpoint_preserves_across_save_restore(self):
        """Save then restore should reconstruct state."""
        from mcp_server.handlers.checkpoint import handler as checkpoint

        # Save detailed state
        await checkpoint(
            {
                "action": "save",
                "session_id": "micro-test",
                "current_task": "Debugging database lock",
                "files_being_edited": ["memory_store.py"],
                "active_errors": ["RuntimeError: database is locked"],
                "key_decisions": ["Switch to WAL mode"],
                "next_steps": ["Run tests again"],
            }
        )

        # Restore
        result = await checkpoint({"action": "restore"})
        formatted = result["formatted"]
        assert "Debugging database lock" in formatted
        assert "memory_store.py" in formatted
        assert "database is locked" in formatted
        assert "WAL mode" in formatted
