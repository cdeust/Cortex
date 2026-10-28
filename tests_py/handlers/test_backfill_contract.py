"""Backfill contracts over real JSONL files; persistence and model I/O are isolated."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mcp_server.handlers import backfill_helpers
from mcp_server.handlers import backfill_memories as backfill


@pytest.fixture
def machine(monkeypatch, tmp_path):
    root = tmp_path / "claude"
    monkeypatch.setattr(backfill_helpers, "CLAUDE_DIR", root)
    store, encoder = Mock(), Mock()
    store.get_entity_by_name.return_value = {"id": 90}
    monkeypatch.setattr(backfill, "get_shared_store", lambda *args: store)
    monkeypatch.setattr(backfill, "get_embedding_engine", lambda: encoder)
    names = (
        "ensure_backfill_log",
        "is_already_backfilled",
        "mark_backfilled",
        "run_cascade_advancement",
    )
    boundary = {name: Mock() for name in names}
    boundary["is_already_backfilled"].return_value = False
    boundary["run_cascade_advancement"].return_value = {"advanced": 3}
    for name, mock in boundary.items():
        monkeypatch.setattr(backfill, name, mock)
    remember = AsyncMock(return_value={"stored": True, "memory_id": 401})
    pipeline = AsyncMock(return_value={"claims_inserted": 1, "pages_published": 2})
    monkeypatch.setattr(backfill, "remember_handler", remember)
    monkeypatch.setattr(backfill, "_pipeline", pipeline)
    return SimpleNamespace(
        root=root,
        store=store,
        encoder=encoder,
        remember=remember,
        pipeline=pipeline,
        **boundary,
    )


def transcript(machine, filename="session.jsonl", contents=None):
    folder = machine.root / "projects" / "-Users-alice-code-cortex"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    text = "We decided to preserve the knowledge graph when importing prior sessions."
    records = [
        {
            "type": "user",
            "cwd": "/projects/cortex",
            "timestamp": "2026-01-02T03:04:05Z",
            "message": {"content": text},
        },
        {
            "type": "assistant",
            "message": {"content": "This assistant text is not imported."},
        },
    ]
    path.write_text(
        "\n".join(
            json.dumps(record) for record in (records if contents is None else contents)
        )
        + "\n"
    )
    return path, text


@pytest.mark.asyncio
async def test_import_preserves_timestamp_scope_and_source_then_links_actual_memory_id(
    machine,
):
    path, text = transcript(machine)
    result = await backfill.handler({"project": "cortex"})
    assert result["backfilled"] == 1
    assert result["files_processed"] == 1
    assert result["cascade_advanced"] == 3
    assert result["pipeline"] == {
        "claims_inserted": 1,
        "concepts_inserted": 0,
        "drafts_approved": 0,
        "pages_published": 2,
    }
    machine.remember.assert_awaited_once_with(
        {
            "content": text,
            "tags": [
                "decision",
                "imported",
                "_backfill",
                "project:-Users-alice-code-cortex",
            ],
            "directory": "/projects/cortex",
            "domain": "",  # The isolated registry has no mapping for this fixture.
            "source": "backfill:-Users-alice-code-cortex",
            "write_class": "mechanical",
            "force": True,
            "created_at": "2026-01-02T03:04:05Z",
        }
    )
    machine.encoder.warm_cache.assert_called_once_with([text])
    machine.mark_backfilled.assert_called_once_with(
        machine.store, path, backfill.file_hash(path), 1
    )
    relationship = machine.store.insert_relationship.call_args.args[0]
    assert relationship["source_entity_id"] == 401
    assert relationship["target_entity_id"] == 90
    assert relationship["relationship_type"] == "mentions_concept"
    machine.pipeline.assert_awaited_once_with({"limit_per_stage": 1000})


@pytest.mark.asyncio
async def test_rejected_memory_does_not_mark_file_done_or_run_followup_pipeline(
    machine,
):
    transcript(machine)
    machine.remember.return_value = {"stored": False, "reason": "rejected"}
    result = await backfill.handler({})
    assert result["backfilled"] == 0
    assert result["files_processed"] == 0
    machine.mark_backfilled.assert_not_called()
    machine.store.insert_relationship.assert_not_called()
    machine.pipeline.assert_not_awaited()
    machine.run_cascade_advancement.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_extracts_real_transcript_without_memory_or_embedding_writes(
    machine,
):
    path, _ = transcript(machine)
    result = await backfill.handler({"dry_run": True})
    assert result == {
        "dry_run": True,
        "files_found": 1,
        "already_processed": 0,
        "would_import": 1,
        "preview": [
            {
                "file": path.name,
                "project": path.parent.name,
                "extractable_items": 1,
                "concepts": ["knowledge_graph"],
            }
        ],
    }
    machine.remember.assert_not_awaited()
    machine.encoder.warm_cache.assert_not_called()
    machine.mark_backfilled.assert_not_called()
    machine.pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_hash_skip_and_explicit_force_reprocess_have_different_write_effects(
    machine,
):
    transcript(machine)
    machine.is_already_backfilled.return_value = True
    skipped = await backfill.handler({"run_pipeline": False})
    assert skipped["files_already_done"] == 1
    assert skipped["backfilled"] == 0
    machine.remember.assert_not_awaited()
    forced = await backfill.handler({"force_reprocess": True, "run_pipeline": False})
    assert forced["backfilled"] == 1
    assert forced["files_already_done"] == 0
    assert machine.is_already_backfilled.call_count == 1
    machine.remember.assert_awaited_once()
    machine.pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_transcript_returns_explicit_empty_discovery(machine):
    result = await backfill.handler()
    assert result == {
        "backfilled": 0,
        "skipped_files": 0,
        "already_processed": 0,
        "error": "no_session_files_found",
    }
    machine.remember.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "empty", "no-memorable-content"])
async def test_import_file_with_no_extractable_records_does_not_warm_or_write(
    machine, tmp_path, kind
):
    path = tmp_path / "session.jsonl"
    if kind == "empty":
        path.write_text("")
    elif kind == "no-memorable-content":
        path.write_text(
            json.dumps({"type": "assistant", "message": {"content": "none"}})
        )
    assert await backfill._import_file(machine.store, path, "cortex", 0.35) == (0, 0)
    machine.encoder.warm_cache.assert_not_called()
    machine.remember.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_candidate_hash_does_not_prevent_other_file_import(
    machine, monkeypatch, tmp_path
):
    path, _ = transcript(machine)
    monkeypatch.setattr(
        backfill,
        "discover_files",
        lambda *args: [
            (tmp_path / "missing.jsonl", "cortex"),
            (path, path.parent.name),
        ],
    )
    result = await backfill.handler({"run_pipeline": False})
    assert result["total_files_found"] == 2
    assert result["files_processed"] == 1
    assert result["backfilled"] == 1


@pytest.mark.asyncio
async def test_prepared_short_item_is_ignored_and_missing_timestamp_is_not_fabricated(
    machine,
):
    short = {"content": "too short"}
    item = {"content": "A sufficiently detailed historical message with no timestamp."}
    prepared = [
        (entry, backfill._prepare_item_content(entry)) for entry in [short, item]
    ]
    backfill._warm_embedding_cache(prepared)
    imported = await backfill._store_prepared_items(
        machine.store, prepared, "/project", "auth", "project"
    )
    assert imported == 1
    machine.encoder.warm_cache.assert_called_once_with([item["content"]])
    machine.remember.assert_awaited_once()
    assert "created_at" not in machine.remember.await_args.args[0]
    machine.store.insert_relationship.assert_not_called()


@pytest.mark.asyncio
async def test_reader_failure_does_not_attempt_to_extract_or_write(
    machine, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        backfill, "read_head_tail", Mock(side_effect=OSError("read denied"))
    )
    assert await backfill._import_file(
        machine.store, tmp_path / "session.jsonl", "auth", 0.35
    ) == (0, 0)
    machine.encoder.warm_cache.assert_not_called()
    machine.remember.assert_not_awaited()
