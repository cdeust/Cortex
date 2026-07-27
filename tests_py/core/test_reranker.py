"""Tests for mcp_server.core.reranker — FlashRank cross-encoder + confidence."""

from unittest.mock import patch

import pytest

import mcp_server.core.reranker as reranker_mod
from mcp_server.core.reranker import (
    _compute_retrieval_confidence,
    _blend_scores,
    ensure_reranker_loaded,
    model_sha256,
    rerank_results,
    reranker_cache_dir,
    reranker_status,
)
from mcp_server.observability import silent_failure


@pytest.fixture(autouse=True)
def _neutral_offline_env(monkeypatch):
    """Pin ``$CORTEX_RERANKER_OFFLINE`` off for every test in this module.

    CI sets it to "1" for the whole pytest invocation (see ci.yml's "Run
    tests" step), which would otherwise make the load-path tests below
    depend on whether the real model happens to sit in the ambient
    ``~/.cache/flashrank`` — ambient env plus real disk state deciding a
    unit test's outcome. Tests that exercise the guard set the variable
    themselves; everything else gets the deterministic default.
    """
    monkeypatch.delenv("CORTEX_RERANKER_OFFLINE", raising=False)


class TestRetrievalConfidence:
    """Tests for Sufficient Context confidence gating (binary gate)."""

    def test_high_ce_scores_give_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.8, 0.6, 0.3])
        assert confidence == 1.0

    def test_above_gate_gives_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.2, 0.1])
        assert confidence == 1.0

    def test_below_gate_gives_suppression(self):
        confidence = _compute_retrieval_confidence([0.1, 0.05])
        assert confidence == 0.1

    def test_empty_scores_return_suppression(self):
        confidence = _compute_retrieval_confidence([])
        assert confidence == 0.1

    def test_negative_scores_give_suppression(self):
        confidence = _compute_retrieval_confidence([-1.0, -0.5])
        assert confidence == 0.1

    def test_custom_gate_threshold(self):
        confidence = _compute_retrieval_confidence([0.3], gate_threshold=0.5)
        assert confidence < 1.0

    def test_at_threshold_gives_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.15])
        assert confidence == 1.0


class TestBlendScoresWithConfidence:
    def test_high_confidence_preserves_scores(self):
        candidates = [(1, 0.5), (2, 0.3)]
        ce_scores = {0: 0.9, 1: 0.7}
        result = _blend_scores(candidates, ce_scores, alpha=0.55)
        # High CE → high confidence → scores close to raw blended
        top_score = result[0][1]
        assert top_score > 0.5

    def test_low_confidence_suppresses_scores(self):
        candidates = [(1, 0.5), (2, 0.3)]
        ce_scores = {0: 0.05, 1: 0.02}
        result = _blend_scores(candidates, ce_scores, alpha=0.55)
        # Low CE → low confidence → scores pulled down
        top_score = result[0][1]
        assert top_score < 0.3


class TestReranker:
    def test_passthrough_without_flashrank(self):
        """When FlashRank unavailable, returns original order."""
        candidates = [(1, 0.9), (2, 0.5), (3, 0.3)]
        with patch("mcp_server.core.reranker._ensure_reranker", return_value=None):
            result = rerank_results("test", candidates, {1: "a", 2: "b", 3: "c"})
        assert result == candidates

    def test_empty_candidates(self):
        result = rerank_results("test", [], {})
        assert result == []

    def test_empty_content_lookup(self):
        candidates = [(1, 0.9)]
        with patch("mcp_server.core.reranker._ensure_reranker", return_value=None):
            result = rerank_results("test", candidates, {})
        assert result == candidates


class _ResetSingleton:
    """Fixture helper: reset the process-global FlashRank singleton state.

    The singleton (module-level ``_flashrank_instance`` /
    ``_flashrank_failed`` / ``_flashrank_load_error``) persists across
    calls by design (see reranker.py's docstring — same shape as
    write_post_store.py's ``_global_buffer``). Tests that exercise the
    load-failure / status transitions must reset it before and after, or
    they leak state into unrelated tests in the same process.
    """

    def __enter__(self):
        self._saved = (
            reranker_mod._flashrank_instance,
            reranker_mod._flashrank_failed,
            reranker_mod._flashrank_load_error,
        )
        reranker_mod._flashrank_instance = None
        reranker_mod._flashrank_failed = False
        reranker_mod._flashrank_load_error = None
        return self

    def __exit__(self, *exc):
        (
            reranker_mod._flashrank_instance,
            reranker_mod._flashrank_failed,
            reranker_mod._flashrank_load_error,
        ) = self._saved


class TestRerankerCacheDir:
    """The durable cache_dir fix (2026-07-10 incident)."""

    def test_default_is_not_tmp(self):
        """FlashRank's own default (/tmp) must never be what we pass it."""
        assert str(reranker_cache_dir()) != "/tmp"
        assert "flashrank" in str(reranker_cache_dir())

    def test_honors_xdg_cache_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert reranker_cache_dir() == tmp_path / "flashrank"

    def test_falls_back_to_home_cache(self, monkeypatch):
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setenv("HOME", "/fake/home")
        assert str(reranker_cache_dir()) == "/fake/home/.cache/flashrank"


class TestReRankerNonSilentFailure:
    """Load failures must be logged, not swallowed (root cause of the
    2026-07-10 incident: a bare except made a permanently-broken reranker
    indistinguishable from a healthy one across 6 benchmark runs)."""

    def test_load_failure_logs_warning_with_path_and_exception(self, caplog):
        with _ResetSingleton():
            with patch("flashrank.Ranker", side_effect=OSError("NoSuchFile")):
                with caplog.at_level("WARNING", logger="mcp_server.core.reranker"):
                    result = reranker_mod._ensure_reranker()
            assert result is None
            assert any("NoSuchFile" in rec.message for rec in caplog.records)
            # The searched cache directory must be named in the log line.
            assert any(
                str(reranker_cache_dir()) in rec.message for rec in caplog.records
            )

    def test_second_failure_does_not_log_again(self, caplog):
        """Singleton flag suppresses spam after the first logged failure."""
        with _ResetSingleton():
            with patch("flashrank.Ranker", side_effect=OSError("NoSuchFile")):
                with caplog.at_level("WARNING", logger="mcp_server.core.reranker"):
                    reranker_mod._ensure_reranker()
                    first_count = len(caplog.records)
                    reranker_mod._ensure_reranker()
                    second_count = len(caplog.records)
            assert second_count == first_count


class TestRerankerStatus:
    def test_not_attempted_before_any_call(self):
        with _ResetSingleton():
            status = reranker_status()
            assert status.state == "not_attempted"
            assert status.error is None

    def test_status_reflects_failed_load(self):
        with _ResetSingleton():
            with patch("flashrank.Ranker", side_effect=OSError("NoSuchFile")):
                ensure_reranker_loaded()
            status = reranker_status()
            assert status.state == "failed"
            assert status.error is not None
            assert "NoSuchFile" in status.error

    def test_status_reflects_loaded(self):
        with _ResetSingleton():
            fake_ranker = object()
            with patch("flashrank.Ranker", return_value=fake_ranker):
                status = ensure_reranker_loaded()
            assert status.state == "loaded"
            assert reranker_status().state == "loaded"

    def test_status_does_not_trigger_a_load(self):
        """reranker_status() must be side-effect-free (preflight-safe)."""
        with _ResetSingleton():
            with patch("flashrank.Ranker") as mock_ranker:
                reranker_status()
                mock_ranker.assert_not_called()


class TestModelSha256:
    def test_returns_none_when_model_absent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert model_sha256() is None

    def test_returns_hex_digest_when_model_present(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        model_path = reranker_mod._model_path()
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"fake-onnx-weights")
        digest = model_sha256()
        assert digest is not None
        assert len(digest) == 64  # sha256 hex digest length
        # Deterministic: same bytes -> same digest.
        import hashlib

        assert digest == hashlib.sha256(b"fake-onnx-weights").hexdigest()


class TestRerankResultsInferenceFailureIsObservable:
    """Audit 2026-07-11, silent-except sweep: a load failure was already
    made observable by bb1c581f (_ensure_reranker). This covers the
    SEPARATE failure point -- the model loads fine but the per-call
    ``ranker.rerank(...)`` invocation itself raises -- which was still a
    bare ``except Exception: return candidates`` with zero signal."""

    def test_inference_failure_falls_back_and_is_logged(self, caplog):
        from unittest.mock import MagicMock

        silent_failure.reset()
        fake_ranker = MagicMock()
        fake_ranker.rerank.side_effect = RuntimeError("onnx runtime error")
        with patch.object(reranker_mod, "_ensure_reranker", return_value=fake_ranker):
            with caplog.at_level(
                "WARNING", logger="mcp_server.observability.silent_failure"
            ):
                candidates = [(1, 0.5), (2, 0.4)]
                result = rerank_results("q", candidates, {1: "a", 2: "b"})

        # Behavior-preserving: falls back to the unblended first-stage list.
        assert result == candidates
        # But now observable, unlike the pre-fix bare except.
        assert any(
            "reranker.rerank_call" in rec.message
            and "onnx runtime error" in rec.message
            for rec in caplog.records
        )
        silent_failure.reset()

    def test_get_raw_ce_score_failure_is_logged(self, caplog):
        from unittest.mock import MagicMock

        silent_failure.reset()
        fake_ranker = MagicMock()
        fake_ranker.rerank.side_effect = RuntimeError("bad passage")
        with patch.object(reranker_mod, "_ensure_reranker", return_value=fake_ranker):
            with caplog.at_level(
                "WARNING", logger="mcp_server.observability.silent_failure"
            ):
                result = reranker_mod.get_raw_ce_score("q", "content")

        assert result is None
        assert any("reranker.raw_ce_score" in rec.message for rec in caplog.records)
        silent_failure.reset()


class TestOfflineGuard:
    """``$CORTEX_RERANKER_OFFLINE`` bounds FlashRank's timeout-less download.

    Regression cover for CI run 30263190266 (main, Python 3.13,
    2026-07-27), where ``Ranker.__init__`` hung in ``sock.connect``
    fetching the model until pytest-timeout killed the suite at 300s.
    """

    def _cache_with_model(self, monkeypatch, tmp_path, present):
        """Point the cache at tmp_path; create the model file iff present."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        path = reranker_mod._model_path()
        if present:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not-a-real-onnx")
        return path

    def test_unset_env_does_not_request_offline(self, monkeypatch):
        monkeypatch.delenv("CORTEX_RERANKER_OFFLINE", raising=False)
        assert reranker_mod._offline_requested() is False

    def test_falsey_values_do_not_request_offline(self, monkeypatch):
        """Unset, empty, 0, false, no — case- and whitespace-insensitive."""
        for value in ("", "0", "false", "FALSE", "no", "  No  "):
            monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", value)
            assert reranker_mod._offline_requested() is False, value

    def test_truthy_values_request_offline(self, monkeypatch):
        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", value)
            assert reranker_mod._offline_requested() is True, value

    def test_offline_with_absent_model_degrades_instead_of_downloading(
        self, monkeypatch, tmp_path, caplog
    ):
        """The observable effect: None returned, status 'failed', no download."""
        monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", "1")
        self._cache_with_model(monkeypatch, tmp_path, present=False)

        with _ResetSingleton():
            with patch("flashrank.Ranker") as ranker_cls:
                with caplog.at_level("WARNING"):
                    result = reranker_mod._ensure_reranker()

            assert result is None
            assert reranker_status().state == "failed"
            # Negative assertion: absence of the network fetch IS the behavior.
            ranker_cls.assert_not_called()

    def test_offline_refusal_emits_an_actionable_warning(
        self, monkeypatch, tmp_path, caplog
    ):
        """The signal itself is asserted, not merely its downstream effect."""
        monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", "1")
        model_path = self._cache_with_model(monkeypatch, tmp_path, present=False)

        with _ResetSingleton():
            with patch("flashrank.Ranker"):
                with caplog.at_level("WARNING"):
                    reranker_mod._ensure_reranker()

            # Inside the reset block: the helper restores the singleton on
            # exit, so the recorded error is only observable here.
            assert reranker_status().error is not None

        message = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "CORTEX_RERANKER_OFFLINE" in message
        assert str(model_path) in message

    def test_offline_with_present_model_still_loads(self, monkeypatch, tmp_path):
        """The guard fires on absence only — a warm cache is untouched."""
        monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", "1")
        self._cache_with_model(monkeypatch, tmp_path, present=True)

        with _ResetSingleton():
            with patch("flashrank.Ranker") as ranker_cls:
                result = reranker_mod._ensure_reranker()

            assert result is ranker_cls.return_value
            assert reranker_status().state == "loaded"
            ranker_cls.assert_called_once()

    def test_online_with_absent_model_still_attempts_the_download(
        self, monkeypatch, tmp_path
    ):
        """Opt-in only: production keeps FlashRank's first-run self-provisioning."""
        monkeypatch.delenv("CORTEX_RERANKER_OFFLINE", raising=False)
        self._cache_with_model(monkeypatch, tmp_path, present=False)

        with _ResetSingleton():
            with patch("flashrank.Ranker") as ranker_cls:
                result = reranker_mod._ensure_reranker()

            assert result is ranker_cls.return_value
            ranker_cls.assert_called_once()
