"""Tests for mcp_server.infrastructure.config."""

import importlib.util
from pathlib import Path

import pytest

from mcp_server.infrastructure import config as config_module
from mcp_server.infrastructure.config import (
    CLAUDE_DIR,
    METHODOLOGY_DIR,
    PROFILES_PATH,
    SESSION_LOG_PATH,
    BRAIN_INDEX_PATH,
    MCP_CONNECTIONS_PATH,
    WIKI_ROOT,
)


def _config_under(monkeypatch, override: str | None):
    """Import a fresh, private instance of the config module under `override`.

    The constants bind at import time, so the only way to observe a different
    ``CORTEX_CLAUDE_DIR`` is to import again. A private instance is used
    deliberately instead of ``importlib.reload``: reloading the cached module
    would rebind ``CLAUDE_DIR`` for the ~40 modules that already did
    ``from ...config import X`` (a value copy) at collection time, leaking one
    test's environment into the rest of the session.
    """
    if override is None:
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
    else:
        monkeypatch.setenv("CORTEX_CLAUDE_DIR", override)
    spec = importlib.util.spec_from_file_location(
        "_config_probe", config_module.__file__
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestConfig:
    def test_all_paths_are_absolute(self):
        for p in [
            CLAUDE_DIR,
            METHODOLOGY_DIR,
            PROFILES_PATH,
            SESSION_LOG_PATH,
            BRAIN_INDEX_PATH,
            MCP_CONNECTIONS_PATH,
            WIKI_ROOT,
        ]:
            assert p.is_absolute()

    def test_methodology_dir_under_claude(self):
        assert METHODOLOGY_DIR == CLAUDE_DIR / "methodology"

    def test_profiles_path(self):
        assert PROFILES_PATH == METHODOLOGY_DIR / "profiles.json"

    def test_session_log_path(self):
        assert SESSION_LOG_PATH == METHODOLOGY_DIR / "session-log.json"

    def test_brain_index_path(self):
        assert BRAIN_INDEX_PATH == CLAUDE_DIR / "brain-index.json"

    def test_mcp_connections_path(self):
        assert MCP_CONNECTIONS_PATH == METHODOLOGY_DIR / "mcp-connections.json"

    def test_wiki_root_under_methodology(self):
        assert WIKI_ROOT == METHODOLOGY_DIR / "wiki"


class TestClaudeDirOverride:
    """The ``CORTEX_CLAUDE_DIR`` seam (issue #219).

    This suite cannot assert the *ambient* ``CLAUDE_DIR``: conftest sets the
    override before the first import precisely so no test can touch the
    operator's real tree. What the production contract actually promises is
    tested here instead, both arms, on freshly imported instances.
    """

    def test_unset_defaults_to_home_dot_claude(self, monkeypatch):
        assert _config_under(monkeypatch, None).CLAUDE_DIR == Path.home() / ".claude"

    def test_override_relocates_the_root(self, monkeypatch, tmp_path):
        assert _config_under(monkeypatch, str(tmp_path)).CLAUDE_DIR == tmp_path

    def test_override_relocates_every_derived_path(self, monkeypatch, tmp_path):
        cfg = _config_under(monkeypatch, str(tmp_path))
        derived = [
            cfg.METHODOLOGY_DIR,
            cfg.PROFILES_PATH,
            cfg.SESSION_LOG_PATH,
            cfg.BRAIN_INDEX_PATH,
            cfg.MCP_CONNECTIONS_PATH,
            cfg.WIKI_ROOT,
        ]
        # The whole point of the seam: one variable moves the SQLite store,
        # the wiki tree, profiles, and the session log together. A path left
        # behind is a real-data root the suite would still write to.
        for path in derived:
            assert tmp_path in path.parents or path == tmp_path

    def test_override_is_user_expanded(self, monkeypatch):
        assert _config_under(monkeypatch, "~/cortex-elsewhere").CLAUDE_DIR == (
            Path.home() / "cortex-elsewhere"
        )

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_blank_override_falls_back_to_default(self, monkeypatch, blank):
        # An exported-but-empty variable is the shell's "unset" (`export
        # CORTEX_CLAUDE_DIR=` / a compose file with no value). Treating it as
        # a path would resolve the root to the process CWD.
        assert _config_under(monkeypatch, blank).CLAUDE_DIR == Path.home() / ".claude"
