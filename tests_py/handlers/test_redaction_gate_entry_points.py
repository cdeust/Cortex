"""No entry point persists a secret (ADR-1110; audit 2026-10-21, E16).

The audit found the scrubber called only by the PostToolUse capture hook:
``remember``, session import and session end stored text unfiltered. Each
entry point below is driven through its real handler with real-format fake
credentials, then the whole store (every text column of every table, in
normalised form) and the files it wrote are searched for them.

These tests use only the handlers' public entry points and the catalog
scanner, so they run unchanged against the pre-fix code (they fail there).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.infrastructure.config import METHODOLOGY_DIR
from scripts.secret_corpus import sample, samples
from tests_py._db_text_scan import locations

CORPUS = samples()
ANTHROPIC = sample("anthropic-api-key").value
GITHUB = sample("github-pat").value
OPENAI = sample("openai-api-key").value
JWT = sample("jwt").value
FAKES = (ANTHROPIC, GITHUB, OPENAI, JWT)


def _store():
    from mcp_server.handlers import remember

    return remember._get_store()


def _assert_store_clean():
    store = _store()
    for fake in FAKES:
        assert locations(store, fake) == [], fake[:8]


def _assert_tree_clean(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".json", ".jsonl", ".log", ""}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for fake in FAKES:
                assert fake not in text, f"{path}: {fake[:8]}"


def _sentence() -> str:
    return (
        f"We decided to rotate the CI credentials: the root cause was the token "
        f"{GITHUB} committed with {ANTHROPIC}, {OPENAI} and session {JWT}."
    )


def test_remember_stores_no_secret():
    from mcp_server.handlers.remember import handler

    result = asyncio.run(handler({"content": _sentence(), "force": True}))
    assert result.get("stored") is True
    _assert_store_clean()


def test_import_sessions_stores_no_secret_in_rows_or_artifacts(tmp_path):
    from mcp_server.handlers import import_sessions

    project = tmp_path / "projects" / "-Users-dev-Developments-gate"
    project.mkdir(parents=True)
    oversized = _sentence() + " " + "context line. " * 400  # > gist budget
    records = [
        {
            "type": "user",
            "message": {"content": text},
            "timestamp": "2026-10-21T10:00:00Z",
            "sessionId": "gate-session",
            "cwd": "/Users/dev/Developments/gate",
        }
        for text in (_sentence(), oversized)
    ]
    (project / "gate-session.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    with patch.object(import_sessions, "CLAUDE_DIR", tmp_path):
        result = asyncio.run(import_sessions.handler({"min_importance": 0.0}))
    assert result["imported"] >= 1, result
    _assert_store_clean()
    _assert_tree_clean(METHODOLOGY_DIR)


def test_session_end_stores_no_secret():
    from mcp_server.handlers.record_session_end import handler

    asyncio.run(
        handler(
            {
                "session_id": "gate-end",
                "cwd": "/Users/dev/Developments/gate",
                "tools_used": ["Bash", "Edit"],
                "keywords": [GITHUB, ANTHROPIC, "deploy"],
                "duration": 600,
                "turn_count": 12,
            }
        )
    )
    _assert_store_clean()
    _assert_tree_clean(METHODOLOGY_DIR)


def test_capture_hook_passes_only_redacted_content_and_artifacts(tmp_path):
    from mcp_server.hooks import post_tool_capture
    from mcp_server.infrastructure import artifact_store

    stored: list[str] = []
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": "env"},
        "tool_response": _sentence() + "\n" + "output line\n" * 400,
        "cwd": "/Users/dev/Developments/gate",
    }
    with (
        patch.object(post_tool_capture, "_should_capture", return_value=(True, "")),
        patch.object(post_tool_capture, "_maybe_run_cascade"),
        patch.object(
            post_tool_capture, "_store_memory", lambda t, c, g, d: stored.append(c)
        ),
        patch.object(artifact_store, "ARTIFACTS_DIR", tmp_path),
    ):
        post_tool_capture.process_event(event)
    assert stored
    for fake in FAKES:
        assert all(fake not in content for content in stored), fake[:8]
    _assert_tree_clean(tmp_path)


@pytest.mark.parametrize(
    ("module", "args", "stored_key"),
    [
        (
            "checkpoint",
            {"action": "save", "current_task": "TASK", "key_decisions": ["TASK"]},
            "checkpoint_id",
        ),
        (
            "add_rule",
            {"condition": "content contains RULE", "action": "boost:0.3"},
            "rule_id",
        ),
        (
            "create_trigger",
            {"content": "TASK", "trigger_condition": "deploy"},
            "trigger_id",
        ),
    ],
)
def test_text_taking_tools_store_no_secret(module, args, stored_key):
    import importlib

    handler = importlib.import_module(f"mcp_server.handlers.{module}").handler

    def fill(value):
        if value == "TASK":
            return _sentence()
        if value == ["TASK"]:
            return [_sentence()]
        return value.replace("RULE", GITHUB) if isinstance(value, str) else value

    result = asyncio.run(handler({k: fill(v) for k, v in args.items()}))
    assert result.get(stored_key), result  # the tool really stored something
    _assert_store_clean()


def test_anchor_reason_stores_no_secret():
    from mcp_server.handlers.anchor import handler as anchor
    from mcp_server.handlers.remember import handler as remember

    stored = asyncio.run(remember({"content": "anchor target memory", "force": True}))
    asyncio.run(anchor({"memory_id": stored["memory_id"], "reason": _sentence()}))
    _assert_store_clean()
