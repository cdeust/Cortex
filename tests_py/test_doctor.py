"""Tests for the `cortex doctor` diagnostic CLI.

Covers the individual check functions without requiring a live PG —
connection checks are skipped when DATABASE_URL is absent so the test
suite stays hermetic.

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from mcp_server.doctor import (
    CHECKS,
    SQLITE_CHECKS,
    _i10_config,
    _methodology_dir,
    _pg_driver,
    _python_version,
    _sqlite_store,
    _worktree_locations,
    _worktree_classification,
    active_checks,
    ensure_reranker_ready,
    run,
)


class TestIndividualChecks:
    def test_python_version_passes_on_supported_runtime(self):
        check = _python_version()
        # This test suite requires 3.10+ anyway
        assert check.ok is True

    def test_pg_driver_passes_in_dev_env(self):
        check = _pg_driver()
        assert check.ok is True  # dev env has postgresql extras installed

    def test_i10_config_reports_capacity(self):
        check = _i10_config()
        assert check.ok is True
        assert "interactive=" in check.detail
        assert "batch=" in check.detail

    def test_methodology_dir_creates_if_missing(self, tmp_path, monkeypatch):
        # Point HOME at tmp so we don't touch ~/.claude for real
        monkeypatch.setenv("HOME", str(tmp_path))
        check = _methodology_dir()
        assert check.ok is True
        assert (tmp_path / ".claude" / "methodology").exists()


class TestRunReportFormat:
    def test_run_returns_int(self, capsys):
        rc = run()
        assert isinstance(rc, int)
        # With DATABASE_URL set by the surrounding harness, should be 0
        out = capsys.readouterr().out
        assert "Cortex doctor" in out

    def test_check_registry_nonempty(self):
        assert len(CHECKS) >= 5
        for c in CHECKS:
            assert callable(c)


class TestBackendAwareChecks:
    """active_checks() mirrors the launcher/hook backend resolution
    (sqlite-first install): SQLite installs must not fail four PG checks."""

    def test_sqlite_backend_selects_sqlite_list(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
        assert active_checks() is SQLITE_CHECKS

    def test_postgresql_backend_selects_pg_list(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
        assert active_checks() is CHECKS

    def test_sqlite_list_has_no_pg_checks(self):
        assert _pg_driver not in SQLITE_CHECKS
        assert _sqlite_store in SQLITE_CHECKS

    def test_sqlite_store_check_passes_on_fresh_store(self, tmp_path, monkeypatch):
        from mcp_server.infrastructure import memory_config

        monkeypatch.setenv(
            "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
        )
        memory_config.get_memory_settings.cache_clear()
        try:
            check = _sqlite_store()
        finally:
            memory_config.get_memory_settings.cache_clear()
        assert check.ok is True
        assert "memories" in check.detail


@pytest.fixture
def real_git_repo(tmp_path):
    """Bare-bones repo with an initial commit, git identity set explicitly
    (CI runners have none) — mirrors
    tests_py/handlers/test_auto_task_record_writer_git_commits.py's
    module-local fixture rather than importing across modules."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial commit"], cwd=repo, check=True
    )
    return repo


class TestWorktreeLocations:
    """source: ADR-1079 — the check reports docs/agent-guidance.md, What NOT to do,
    never blocks (optional=True), never rewrites the rule."""

    @pytest.mark.parametrize("host", [".claude", ".Codex"])
    def test_host_worktree_passes_from_linked_checkout(
        self, real_git_repo, monkeypatch, host
    ):
        linked = real_git_repo / host / "worktrees" / "good"
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(linked)],
            cwd=real_git_repo,
            check=True,
        )
        monkeypatch.chdir(linked)
        check = _worktree_locations()
        assert check.ok is True
        assert check.optional is True

    def test_both_hosts_and_prunable_entries(self, tmp_path):
        entries = [{"path": str(tmp_path)}] + [
            {"path": str(tmp_path / host / "worktrees" / "good")}
            for host in (".claude", ".Codex")
        ]
        entries.append({"path": str(tmp_path / "removed"), "prunable": True})
        assert _worktree_classification(entries)[0] is True
        assert _worktree_classification([{"path": str(tmp_path), "bare": True}])[0]

    def test_rejects_prefix_sibling_and_symlink_escape(self, tmp_path):
        allowed = tmp_path / ".Codex" / "worktrees"
        allowed.mkdir(parents=True)
        outside = tmp_path / ".Codex" / "worktrees-other"
        outside.mkdir()
        link = allowed / "escape"
        link.symlink_to(outside, target_is_directory=True)
        for path in (outside, link):
            ok, detail = _worktree_classification(
                [{"path": str(tmp_path)}, {"path": str(path)}]
            )
            assert ok is False
            assert str(outside.resolve()) in detail

    def test_main_checkout_only_passes(self, real_git_repo, monkeypatch):
        monkeypatch.chdir(real_git_repo)
        check = _worktree_locations()
        assert check.ok is True
        assert check.optional is True

    def test_not_a_git_checkout_warns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # plain dir, no .git
        check = _worktree_locations()
        assert check.ok is False
        assert "Unable to inspect" in check.detail
        assert check.optional is True

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows forbids newlines in paths"
    )
    def test_reports_exact_path_with_newline(self, real_git_repo, monkeypatch):
        outside = real_git_repo.parent / "outside\nworktree "
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(outside)],
            cwd=real_git_repo,
            check=True,
        )
        monkeypatch.chdir(real_git_repo)
        check = _worktree_locations()
        assert check.ok is False
        assert str(outside.resolve()) in check.detail

    def test_flags_worktree_outside_claude_worktrees(self, real_git_repo, monkeypatch):
        subprocess.run(
            ["git", "worktree", "add", "-q", ".claude/worktrees/good", "-b", "good"],
            cwd=real_git_repo,
            check=True,
        )
        outside = real_git_repo.parent / "outside-wt"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(outside), "-b", "bad"],
            cwd=real_git_repo,
            check=True,
        )
        monkeypatch.chdir(real_git_repo)

        check = _worktree_locations()

        assert check.ok is False
        assert check.optional is True
        good_path = str((real_git_repo / ".claude" / "worktrees" / "good").resolve())
        assert good_path not in check.detail
        assert str(outside.resolve()) in check.detail


class TestEnsureRerankerReady:
    """core/reranker_model.py's filesystem seam (issue #560) is unwired
    unless a composition root configured it first; ensure_reranker_ready()
    is the one bare scripts (CI's reranker preload, this test) must call
    instead of core.reranker.ensure_reranker_loaded() directly. Regression
    cover for the 2026-09-15 CI failure: `.github/actions/test-suite`'s
    preload step called the unwired core function and raised RuntimeError
    on every Python version. Asserts the wiring only, not a downloaded
    model: the SQLite CI job does not preload FlashRank, so asserting
    `status.state == "loaded"` here failed in that job (2026-09-16
    review)."""

    @staticmethod
    def _reset_reranker_state(reranker, reranker_model):
        """Simulate a bare script that never imported __main__.py or
        conftest.py's composition-root wiring, and force a fresh load
        attempt regardless of what earlier tests already cached. Returns
        the saved state for restoration."""
        saved = (
            reranker_model._cache_dir_provider,
            reranker_model._model_exists_provider,
            reranker_model._model_sha256_provider,
            reranker._flashrank_instance,
            reranker._flashrank_failed,
            reranker._flashrank_load_error,
        )
        reranker_model._cache_dir_provider = None
        reranker_model._model_exists_provider = None
        reranker_model._model_sha256_provider = None
        reranker._flashrank_instance = None
        reranker._flashrank_failed = False
        reranker._flashrank_load_error = None
        return saved

    @staticmethod
    def _restore_reranker_state(reranker, reranker_model, saved):
        (
            reranker_model._cache_dir_provider,
            reranker_model._model_exists_provider,
            reranker_model._model_sha256_provider,
            reranker._flashrank_instance,
            reranker._flashrank_failed,
            reranker._flashrank_load_error,
        ) = saved

    def test_self_wires_and_loads_even_when_the_seam_was_reset(self):
        from mcp_server.core import reranker, reranker_model

        saved = self._reset_reranker_state(reranker, reranker_model)
        try:
            with pytest.raises(RuntimeError, match="not configured"):
                reranker_model.reranker_cache_dir()

            # Assert the wiring, not a downloaded model: the SQLite CI job
            # does not preload FlashRank, so status.state could legitimately
            # be "failed" there. What this test must prove is that the
            # seam is configured -- reranker_cache_dir() no longer raises,
            # regardless of whether the real model file is on disk.
            status = ensure_reranker_ready()

            assert status is not None
            assert reranker_model._cache_dir_provider is not None
            assert reranker_model._model_exists_provider is not None
            assert reranker_model._model_sha256_provider is not None
            reranker_model.reranker_cache_dir()  # must not raise
        finally:
            self._restore_reranker_state(reranker, reranker_model, saved)
