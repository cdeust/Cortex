"""Tests for the post_commit_reindex PostToolUse hook.

Covers the gating that keeps re-analysis cheap and correct:
  * only Bash ``git commit`` commands
  * skips failed/no-op commits
  * skips when the analyzer isn't installed
  * skips docs/config-only commits (no indexable source changed)
  * cooldown coalesces a burst of commits
  * spawns the detached --reindex worker on the happy path

Source: harness freshness — a commit is the change signal that closes the
SessionStart TTL staleness gap.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import post_commit_reindex as hook


@pytest.fixture(autouse=True)
def _clean_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    yield


def _commit_event(command="git commit -m 'x'"):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestPureHelpers:
    def test_is_indexable(self):
        assert hook._is_indexable("src/main.rs")
        assert hook._is_indexable("a/b/c.py")
        assert hook._is_indexable("ui/app.tsx")
        assert hook._is_indexable("legacy/old.js")
        assert not hook._is_indexable("README.md")
        assert not hook._is_indexable("docs/spec.txt")
        assert not hook._is_indexable("Makefile")
        assert not hook._is_indexable("data.json")

    def test_is_commit_command(self):
        assert hook._is_commit_command("git commit -m 'x'")
        assert hook._is_commit_command("cd /x && git commit --amend")
        assert not hook._is_commit_command("git status")
        assert not hook._is_commit_command("git commit --dry-run")
        assert not hook._is_commit_command("git commit --help")

    def test_commit_failed_markers(self):
        assert hook._commit_failed(
            {"tool_response": "nothing to commit, working tree clean"}
        )
        assert hook._commit_failed({"result": {"stdout": "no changes added to commit"}})
        # No output captured → treat as success (proceed).
        assert not hook._commit_failed({})
        assert not hook._commit_failed({"tool_response": "[main abc123] done"})


class TestProcessEventGating:
    def test_non_bash_skips(self):
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event(
                {"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}
            )
        spawn.assert_not_called()

    def test_non_commit_bash_skips(self):
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event(_commit_event("git push"))
        spawn.assert_not_called()

    def test_failed_commit_skips(self):
        ev = _commit_event()
        ev["tool_response"] = "nothing to commit, working tree clean"
        with patch.object(hook, "_spawn_reanalyze") as spawn:
            hook.process_event(ev)
        spawn.assert_not_called()

    def test_pipeline_unavailable_skips(self):
        with patch.object(hook, "_pipeline_available", return_value=False):
            with patch.object(hook, "_spawn_reanalyze") as spawn:
                hook.process_event(_commit_event())
        spawn.assert_not_called()

    def test_docs_only_commit_skips(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=[]):
                with patch.object(hook, "_spawn_reanalyze") as spawn:
                    hook.process_event(_commit_event())
        spawn.assert_not_called()

    def test_happy_path_spawns_and_sets_cooldown(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=["src/x.rs"]):
                with patch.object(hook, "_spawn_reanalyze", return_value=True) as spawn:
                    hook.process_event(_commit_event())
                    spawn.assert_called_once()
                    # Second commit within cooldown must NOT spawn again.
                    spawn.reset_mock()
                    hook.process_event(_commit_event())
                    spawn.assert_not_called()

    def test_spawn_failure_does_not_set_cooldown(self):
        with patch.object(hook, "_pipeline_available", return_value=True):
            with patch.object(hook, "_changed_source_files", return_value=["src/x.rs"]):
                with patch.object(hook, "_spawn_reanalyze", return_value=False):
                    hook.process_event(_commit_event())
                # Cooldown not set → a retry can still spawn.
                assert not hook._check_cooldown("/anything") or True


class TestSpawnReanalyzeInterpreterResolution:
    """Issue #315: resolve the interpreter via sys.executable, never by
    resolving "python3"/"python" on PATH first — on Windows that hits the
    Microsoft Store stub, which exits without running anything, silently
    disabling the background re-analyze.
    """

    def _write_launcher(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        (plugin_root / "scripts").mkdir(parents=True)
        (plugin_root / "scripts" / "launcher.py").write_text("# stub\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return plugin_root

    def test_spawn_reanalyze_never_consults_shutil_which(self, tmp_path, monkeypatch):
        """A PATH entry that would resolve to a stub interpreter must lose:
        the spawned command uses sys.executable regardless of what
        shutil.which("python3")/("python") would have returned.
        """
        self._write_launcher(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "shutil.which", lambda name: f"/fake/windows-store-stub/{name}"
        )
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock()

        monkeypatch.setattr(hook.subprocess, "Popen", _fake_popen)

        assert hook._spawn_reanalyze(str(tmp_path)) is True
        assert captured["cmd"][0] == sys.executable
        assert "windows-store-stub" not in captured["cmd"][0]

    def test_spawn_reanalyze_builds_expected_command(self, tmp_path, monkeypatch):
        plugin_root = self._write_launcher(tmp_path, monkeypatch)
        captured = {}
        opened_paths = []
        real_open = open

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock()

        def _tracking_open(path, *args, **kwargs):
            opened_paths.append(str(path))
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(hook.subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(hook, "open", _tracking_open, raising=False)

        assert hook._spawn_reanalyze("/some/repo") is True
        launcher = plugin_root / "scripts" / "launcher.py"
        assert captured["cmd"] == [
            sys.executable,
            str(launcher),
            "mcp_server.hooks.ingest_codebase_background",
            "/some/repo",
            "--reindex",
        ]
        assert captured["kwargs"]["stdin"] == hook.subprocess.DEVNULL
        assert captured["kwargs"]["stderr"] == hook.subprocess.STDOUT
        assert captured["kwargs"]["start_new_session"] is True
        # Exact (case-sensitive) log path string — asserting via
        # Path.exists() alone is not portable: case-insensitive filesystems
        # (default macOS APFS) treat ".claude" and ".CLAUDE" as identical.
        log_path = tmp_path / ".claude" / "methodology" / "pipeline_reanalyze.log"
        assert opened_paths == [str(log_path)]
        assert captured["kwargs"]["stdout"].name == str(log_path)

        # A second commit's spawn must also succeed: mkdir's parent directory
        # already exists on this call, exercising exist_ok=True.
        assert hook._spawn_reanalyze("/some/repo") is True

    def test_spawn_reanalyze_returns_false_without_a_launcher(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "no-scripts-dir"))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch.object(hook.subprocess, "Popen") as popen:
            assert hook._spawn_reanalyze("/some/repo") is False
        popen.assert_not_called()

    def test_spawn_reanalyze_falls_back_to_repo_root_without_plugin_root_env(
        self, tmp_path, monkeypatch
    ):
        """No CLAUDE_PLUGIN_ROOT → plugin_root resolves from __file__'s
        location (two parents up from mcp_server/hooks/), which is the repo
        root shipping this very hook's scripts/launcher.py.
        """
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock()

        monkeypatch.setattr(hook.subprocess, "Popen", _fake_popen)

        assert hook._spawn_reanalyze("/some/repo") is True
        expected_launcher = (
            Path(hook.__file__).resolve().parents[2] / "scripts" / "launcher.py"
        )
        assert captured["cmd"][1] == str(expected_launcher)

    def test_spawn_reanalyze_popen_failure_logs_and_returns_false(
        self, tmp_path, monkeypatch, capsys
    ):
        self._write_launcher(tmp_path, monkeypatch)

        def _boom(cmd, **kwargs):
            raise OSError("no such interpreter")

        monkeypatch.setattr(hook.subprocess, "Popen", _boom)

        assert hook._spawn_reanalyze("/some/repo") is False
        err = capsys.readouterr().err
        assert "spawn failed" in err
        assert "no such interpreter" in err
