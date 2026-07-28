"""Tests for mcp_server.handlers.rebuild_profiles — ported from
rebuild-profiles.test.js."""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from mcp_server.handlers.rebuild_profiles import handler


def _write_session(proj_dir, name="s1.jsonl"):
    """Write a minimal-but-real JSONL session (scanner convention)."""
    proj_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "user",
                "slug": "s",
                "cwd": str(proj_dir),
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the bug please"},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:05:00Z",
                "message": {
                    "content": [{"type": "tool_use", "name": "Read", "input": {}}]
                },
            }
        ),
    ]
    (proj_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_memory(proj_dir, name="note.md", body="We chose JWT over sessions."):
    """Write a real memory .md so the scanner emits a 9-key record.

    That list-of-records shape is precisely what triggered the issue #174
    ValueError once it reached ``bridge_finder.find_bridges`` — pinning it
    through the real pipeline is the point of this fixture.
    """
    mem_dir = proj_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / name).write_text(
        "---\nname: note\ntype: decision\n---\n" + body + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def hermetic_claude_home(tmp_path, monkeypatch):
    """Redirect every ~/.claude path constant the handler touches at a
    synthetic tmp dir, so the rebuild runs against fixture data — never the
    developer's live session history (issue #174 isolation violation).

    Seeds two real projects, each with a session and a memory file, so the
    scanner yields a non-empty ``list`` of memory records and the full
    scan → group → assemble → bridge pipeline executes for real.
    """
    projects = tmp_path / "projects"
    _write_session(projects / "proj-a")
    _write_memory(projects / "proj-a", body="cache works just as a free energy filter")
    _write_session(projects / "proj-b")
    _write_memory(projects / "proj-b", body="a second decision note")

    methodology = tmp_path / "methodology"
    domains = methodology / "domains"
    monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(
        "mcp_server.infrastructure.brain_index_store.BRAIN_INDEX_PATH",
        tmp_path / "brain-index.json",
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.PROFILES_PATH",
        methodology / "profiles.json",
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.METHODOLOGY_DIR", methodology
    )
    monkeypatch.setattr("mcp_server.infrastructure.profile_store.DOMAINS_DIR", domains)
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.INDEX_PATH",
        methodology / "index.json",
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.LEGACY_BACKUP_PATH",
        methodology / "profiles.json.v1_backup",
    )
    return tmp_path


class TestRebuildProfilesHandler:
    def test_returns_domains_array_with_force(self, hermetic_claude_home):
        result = asyncio.run(handler({"force": True}))
        assert result is not None
        assert "domains" in result
        assert isinstance(result["domains"], list)

    def test_includes_total_sessions_and_memories(self, hermetic_claude_home):
        result = asyncio.run(handler({"force": True}))
        assert "totalSessions" in result
        assert "totalMemories" in result
        assert isinstance(result["totalSessions"], (int, float))
        assert isinstance(result["totalMemories"], (int, float))
        # The fixture seeds two real memory files; the scan must find them —
        # proving the pipeline consumed a non-empty list of scanner records
        # (the shape that raised the issue #174 ValueError) without erroring.
        assert result["totalMemories"] == 2

    def test_includes_duration_metric(self, hermetic_claude_home):
        result = asyncio.run(handler({"force": True}))
        assert "duration" in result
        assert isinstance(result["duration"], (int, float))
        assert result["duration"] >= 0

    def test_default_args_is_none(self):
        """handler(None) should work same as handler({})."""
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler(None))
        assert "domains" in result


class TestRebuildSmartCaching:
    def test_skips_rebuild_when_recent(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {"test-domain": {"label": "Test"}},
        }
        with patch(
            "mcp_server.handlers.rebuild_profiles.load_profiles", return_value=profiles
        ):
            result = asyncio.run(handler({"force": False}))
        assert result.get("skipped") is True
        assert "less than 1 hour" in result["reason"]
        assert "test-domain" in result["domains"]

    def test_does_not_skip_when_old(self):
        old_time = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        profiles = {
            "updatedAt": old_time,
            "domains": {"old-domain": {"label": "Old"}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {"rebuilt": {}}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({"force": False}))
        assert "skipped" not in result
        assert "domains" in result

    def test_force_overrides_cache(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {"test-domain": {"label": "Test"}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({"force": True}))
        assert "skipped" not in result

    def test_does_not_skip_when_no_domains(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        assert "skipped" not in result

    def test_handles_invalid_updated_at_gracefully(self):
        profiles = {
            "updatedAt": "not-a-date",
            "domains": {"d": {}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        # Should not skip (exception in date parsing is caught)
        assert "skipped" not in result

    def test_does_not_skip_when_no_updated_at(self):
        profiles = {"domains": {"d": {}}}
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        assert "skipped" not in result

    def test_passes_target_domain(self):
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ) as mock_build,
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            asyncio.run(handler({"domain": "my-domain", "force": True}))
        assert mock_build.call_args[1]["target_domain"] == "my-domain"
