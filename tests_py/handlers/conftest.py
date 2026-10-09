"""Fixtures shared by the handler tests that run the real profile pipeline."""

import pytest


@pytest.fixture
def hermetic_claude_dirs(tmp_path, monkeypatch):
    """Redirect every ~/.claude path constant the profile handlers touch at a
    synthetic tmp dir, so a rebuild runs against fixture data and never the
    developer's live session history or methodology store (issue #174).

    Returns the tmp root: transcripts go under ``<root>/projects/<project>/``,
    stored profiles under ``<root>/methodology/``.
    """
    methodology = tmp_path / "methodology"
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
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.DOMAINS_DIR", methodology / "domains"
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.INDEX_PATH",
        methodology / "index.json",
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.profile_store.LEGACY_BACKUP_PATH",
        methodology / "profiles.json.v1_backup",
    )
    return tmp_path
