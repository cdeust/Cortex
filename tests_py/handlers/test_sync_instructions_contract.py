"""Instruction synchronization preserves owner text and supports write-free previews."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_server.handlers import sync_instructions as sync


@pytest.fixture
def store(monkeypatch):
    adapter = Mock()
    adapter.get_memories_for_directory.return_value = []
    adapter.get_hot_memories.return_value = []
    monkeypatch.setattr(sync, "_store", None)
    # source: synthetic isolated adapter configuration, no embedding service used.
    settings = SimpleNamespace(DB_PATH="isolated", EMBEDDING_DIM=3)
    monkeypatch.setattr(sync, "get_memory_settings", lambda: settings)
    monkeypatch.setattr(sync, "get_shared_store", Mock(return_value=adapter))
    return adapter


@pytest.mark.asyncio
async def test_create_then_refresh_preserves_owner_text_and_is_byte_idempotent(
    store, tmp_path
):
    target = tmp_path / "CLAUDE.md"
    store.get_memories_for_directory.return_value = [
        {"content": "Chose SQLite for offline installation."}
    ]
    created = await sync.handler({"directory": str(tmp_path)})
    assert created["action"] == "created"
    first_section = target.read_text()
    target.write_text("# Owner instructions\n" + first_section + "\n## Keep this\n")
    store.get_memories_for_directory.return_value = [
        {"content": "Adopted atomic writes for the settings file."}
    ]
    updated = await sync.handler({"directory": str(tmp_path)})
    expected = target.read_bytes()
    assert updated["action"] == "updated"
    assert b"Chose SQLite" not in expected
    assert b"Adopted atomic writes" in expected
    assert expected.startswith(b"# Owner instructions\n")
    assert expected.endswith(b"\n## Keep this\n")
    assert await sync.handler({"directory": str(tmp_path)}) == updated
    assert target.read_bytes() == expected
    sync.get_shared_store.assert_called_once_with("isolated", 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "existing",
    [
        None,
        "# Owner instructions\n",
        "<!-- cortex:memory-insights:start -->\nold\n"
        "<!-- cortex:memory-insights:end -->\n",
    ],
)
async def test_dry_run_does_not_create_or_rewrite_files(store, tmp_path, existing):
    target = tmp_path / "CLAUDE.md"
    if existing is not None:
        target.write_text(existing)
    store.get_memories_for_directory.return_value = [
        {"content": "Chose isolated databases for test execution."}
    ]
    result = await sync.handler({"directory": str(tmp_path), "dry_run": True})
    assert result["synced"] is True
    assert result["dry_run"] is True
    assert result["action"].startswith("would_")
    assert target.exists() == (existing is not None)
    if existing is not None:
        assert target.read_text() == existing
        assert "Chose isolated databases" in result["preview"]


@pytest.mark.asyncio
async def test_parent_instructions_used_for_subdirectory_and_fallback_keeps_heat_filter(
    store, tmp_path, monkeypatch
):
    (tmp_path / "CLAUDE.md").write_text("# Existing owner notes\n")
    child = tmp_path / "src"
    child.mkdir()
    monkeypatch.chdir(child)
    store.get_hot_memories.return_value = [
        {"content": "Adopted one canonical schema for ingestion."}
    ]
    result = await sync.handler({"min_heat": 0.7})
    assert result["action"] == "appended"
    assert result["path"] == str(tmp_path / "CLAUDE.md")
    assert not (child / "CLAUDE.md").exists()
    assert (tmp_path / "CLAUDE.md").read_text().startswith("# Existing owner notes\n\n")
    store.get_memories_for_directory.assert_called_once_with(str(child), min_heat=0.7)
    store.get_hot_memories.assert_called_once_with(min_heat=0.7, limit=50)


@pytest.mark.asyncio
async def test_insight_priority_deduplicates_and_flattens_content_before_writing(
    store, tmp_path
):
    store.get_memories_for_directory.return_value = [
        {"content": "Important owner note", "importance": 1},
        {"content": "Chose SQLite.\nOffline startup works.", "heat": 0.9},
        {"content": "Chose SQLite.\nOffline startup works.", "heat": 0.8},
        {"content": "Adopted atomic writes.", "heat": 0.7},
        {"content": ""},
    ]
    result = await sync.handler({"directory": str(tmp_path), "max_insights": 3})
    bullets = [
        line
        for line in (tmp_path / "CLAUDE.md").read_text().splitlines()
        if line.startswith("- ")
    ]
    assert bullets == [
        "- Chose SQLite. Offline startup works.",
        "- Adopted atomic writes.",
        "- Important owner note",
    ]
    assert result["insights_count"] == 3
    assert result["memory_count"] == 5
    store.get_hot_memories.assert_not_called()


@pytest.mark.asyncio
async def test_long_memory_is_bounded_at_output_without_mutating_source(
    store, tmp_path
):
    original = "A" * 140
    store.get_memories_for_directory.return_value = [{"content": original}]
    await sync.handler({"directory": str(tmp_path)})
    assert "- " + "A" * 120 + "\n" in (tmp_path / "CLAUDE.md").read_text()
    assert store.get_memories_for_directory.return_value == [{"content": original}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memories,reason",
    [([], "no_memories_found"), ([{"content": ""}], "no_insights_extracted")],
)
async def test_empty_input_reports_reason_without_creating_instructions(
    store, tmp_path, memories, reason
):
    store.get_memories_for_directory.return_value = memories
    result = await sync.handler({"directory": str(tmp_path)})
    assert result["synced"] is False
    assert result["reason"] == reason
    assert not (tmp_path / "CLAUDE.md").exists()
