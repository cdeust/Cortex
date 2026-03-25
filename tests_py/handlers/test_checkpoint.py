"""Tests for mcp_server.handlers.checkpoint — hippocampal replay."""

import os
from unittest.mock import patch

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings


def _clean_checkpoints():
    """Delete all checkpoints from the shared PG database."""
    from mcp_server.infrastructure.memory_store import MemoryStore

    store = MemoryStore()
    store._conn.execute("DELETE FROM checkpoints")
    store._conn.execute("DELETE FROM memories")
    store._conn.commit()
    store.close()


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    db_path = str(tmp_path / "test_checkpoint.db")
    with patch.dict(os.environ, {"CORTEX_MEMORY_DB_PATH": db_path}):
        get_memory_settings.cache_clear()
        import mcp_server.handlers.checkpoint as mod

        mod._store = None
        _clean_checkpoints()
        yield db_path
        mod._store = None
        _clean_checkpoints()
    get_memory_settings.cache_clear()


class TestCheckpointSave:
    @pytest.mark.asyncio
    async def test_save_returns_checkpoint_id(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler(
            {
                "action": "save",
                "session_id": "test-session",
                "current_task": "Writing tests",
                "files_being_edited": ["test.py"],
                "key_decisions": ["Use SQLite"],
                "open_questions": ["How to scale?"],
                "next_steps": ["Run tests"],
                "active_errors": [],
                "custom_context": "Extra info",
            }
        )
        assert result["status"] == "saved"
        assert "checkpoint_id" in result

    @pytest.mark.asyncio
    async def test_save_minimal(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler({"action": "save"})
        assert result["status"] == "saved"

    @pytest.mark.asyncio
    async def test_missing_action_returns_error(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_none_args_returns_error(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler(None)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler({"action": "delete"})
        assert "error" in result


class TestCheckpointRestore:
    @pytest.mark.asyncio
    async def test_restore_empty_state(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler({"action": "restore"})
        assert result["status"] == "restored"
        assert result["checkpoint"] is False
        assert result["anchored_count"] == 0
        assert result["recent_count"] == 0
        assert result["hot_count"] == 0
        assert "formatted" in result

    @pytest.mark.asyncio
    async def test_save_then_restore(self):
        from mcp_server.handlers.checkpoint import handler

        # Save
        save_result = await handler(
            {
                "action": "save",
                "current_task": "Building memory system",
                "files_being_edited": ["memory.py", "store.py"],
                "key_decisions": ["Use thermodynamic model"],
            }
        )
        assert save_result["status"] == "saved"

        # Restore
        restore_result = await handler({"action": "restore"})
        assert restore_result["status"] == "restored"
        assert restore_result["checkpoint"] is True
        assert "Building memory system" in restore_result["formatted"]
        assert "memory.py" in restore_result["formatted"]

    @pytest.mark.asyncio
    async def test_restore_with_directory(self):
        from mcp_server.handlers.checkpoint import handler

        result = await handler(
            {
                "action": "restore",
                "directory": "/project/src",
            }
        )
        assert result["status"] == "restored"

    @pytest.mark.asyncio
    async def test_multiple_saves_restore_latest(self):
        from mcp_server.handlers.checkpoint import handler

        await handler({"action": "save", "current_task": "First task"})
        await handler({"action": "save", "current_task": "Second task"})

        result = await handler({"action": "restore"})
        assert result["checkpoint"] is True
        assert "Second task" in result["formatted"]


class TestCheckpointSchema:
    def test_schema_exists(self):
        from mcp_server.handlers.checkpoint import schema

        assert "description" in schema
        assert "inputSchema" in schema
        assert schema["inputSchema"]["required"] == ["action"]
