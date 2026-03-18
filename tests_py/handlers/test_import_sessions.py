"""Tests for mcp_server.handlers.import_sessions — session import handler."""

import json
from unittest.mock import patch, AsyncMock

import pytest

from mcp_server.handlers.import_sessions import (
    handler,
    _discover_jsonl_files,
    _detect_domain_from_path,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_claude_dir(tmp_path):
    """Create a temporary .claude/projects structure with sample JSONL files."""
    projects_dir = tmp_path / "projects"
    proj = projects_dir / "-Users-dev-Developments-jarvis"
    proj.mkdir(parents=True)

    # Create a sample JSONL file
    records = [
        {
            "type": "user",
            "message": {
                "content": "We decided to use clean architecture with six concentric layers"
            },
            "timestamp": "2026-01-01T10:00:00Z",
            "sessionId": "session-001",
            "cwd": "/Users/dev/Developments/jarvis",
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll implement that."},
                    {"type": "tool_use", "name": "Write", "input": {}},
                ]
            },
            "timestamp": "2026-01-01T10:01:00Z",
            "sessionId": "session-001",
        },
        {
            "type": "user",
            "message": {
                "content": "The root cause was the singleton not being reset between tests"
            },
            "timestamp": "2026-01-01T10:05:00Z",
            "sessionId": "session-001",
            "cwd": "/Users/dev/Developments/jarvis",
        },
    ]

    jsonl_path = proj / "session-001.jsonl"
    with open(jsonl_path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    # Create a second project
    proj2 = projects_dir / "-Users-dev-Developments-other"
    proj2.mkdir(parents=True)
    records2 = [
        {
            "type": "user",
            "message": {"content": "Just a short msg"},
            "timestamp": "2026-01-02T00:00:00Z",
            "sessionId": "session-002",
        },
    ]
    with open(proj2 / "session-002.jsonl", "w") as f:
        for rec in records2:
            f.write(json.dumps(rec) + "\n")

    return tmp_path


def _patch_claude_dir(tmp_claude_dir):
    return patch(
        "mcp_server.handlers.import_sessions.CLAUDE_DIR",
        tmp_claude_dir,
    )


def _patch_remember(stored=True):
    return patch(
        "mcp_server.handlers.import_sessions._store_memory",
        new_callable=AsyncMock,
        return_value=stored,
    )


# ── _detect_domain_from_path ──────────────────────────────────────────────


class TestDetectDomainFromPath:
    def test_standard_path(self):
        assert _detect_domain_from_path("/Users/dev/Developments/jarvis") == "jarvis"

    def test_nested_path(self):
        assert _detect_domain_from_path("/Users/dev/projects/myapp/src") == "myapp"

    def test_empty_path(self):
        assert _detect_domain_from_path("") == "unknown"

    def test_fallback_to_last(self):
        assert _detect_domain_from_path("/some/random/path") == "path"


# ── _discover_jsonl_files ─────────────────────────────────────────────────


class TestDiscoverJsonlFiles:
    def test_discovers_all(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir):
            files = _discover_jsonl_files("")
            assert len(files) == 2

    def test_filters_by_project(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir):
            files = _discover_jsonl_files("-Users-dev-Developments-jarvis")
            assert len(files) == 1
            assert files[0][1] == "-Users-dev-Developments-jarvis"

    def test_empty_when_no_match(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir):
            files = _discover_jsonl_files("nonexistent-project")
            assert len(files) == 0


# ── handler — dry_run ─────────────────────────────────────────────────────


class TestHandlerDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_preview(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir):
            result = await handler(
                {
                    "project": "-Users-dev-Developments-jarvis",
                    "dry_run": True,
                    "min_importance": 0.3,
                }
            )
            assert result["dry_run"] is True
            assert result["sessions_scanned"] >= 1
            assert result["imported"] >= 1
            assert "preview" in result

    @pytest.mark.asyncio
    async def test_dry_run_does_not_store(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir), _patch_remember() as mock_store:
            await handler(
                {
                    "project": "-Users-dev-Developments-jarvis",
                    "dry_run": True,
                }
            )
            mock_store.assert_not_called()


# ── handler — actual import ───────────────────────────────────────────────


class TestHandlerImport:
    @pytest.mark.asyncio
    async def test_imports_via_remember(self, tmp_claude_dir):
        with (
            _patch_claude_dir(tmp_claude_dir),
            _patch_remember(stored=True) as mock_store,
        ):
            result = await handler(
                {
                    "project": "-Users-dev-Developments-jarvis",
                    "min_importance": 0.3,
                }
            )
            assert result["imported"] >= 1
            assert mock_store.call_count >= 1

    @pytest.mark.asyncio
    async def test_counts_gated(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir), _patch_remember(stored=False):
            result = await handler(
                {
                    "project": "-Users-dev-Developments-jarvis",
                    "min_importance": 0.3,
                }
            )
            assert result["gated"] >= 1
            assert result["imported"] == 0

    @pytest.mark.asyncio
    async def test_max_sessions_limit(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir), _patch_remember():
            result = await handler({"max_sessions": 1, "min_importance": 0.3})
            assert result["total_files"] == 1

    @pytest.mark.asyncio
    async def test_no_sessions_found(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with _patch_claude_dir(empty_dir):
            result = await handler({})
            assert result["imported"] == 0
            assert "no_sessions_found" in result.get("error", "")


# ── handler — domain filter ──────────────────────────────────────────────


class TestHandlerDomainFilter:
    @pytest.mark.asyncio
    async def test_filters_by_domain(self, tmp_claude_dir):
        with _patch_claude_dir(tmp_claude_dir), _patch_remember():
            result = await handler(
                {
                    "domain": "nonexistent-domain",
                    "min_importance": 0.3,
                }
            )
            # All items should be skipped since domain doesn't match
            assert result["imported"] == 0
