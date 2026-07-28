"""BLE001 sweep (issue #197, second family): core-layer sites that gained
a ``silent_failure`` signal.

Each test forces the guarded operation to fail and asserts the
now-visible ``silent_failure`` signal AND that the pre-existing fallback
behaviour is unchanged (same contract as test_s110_sweep_handlers.py).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_server.observability import silent_failure

WARN_LOGGER = "mcp_server.observability.silent_failure"


@pytest.fixture(autouse=True)
def _reset():
    silent_failure.reset()
    yield
    silent_failure.reset()


def _assert_noted(component: str, error_text: str) -> None:
    """Exact-component check via silent_failure.status() (mutation-hardened:
    pins the component name and the recorded exception, not just a substring
    in the log message)."""
    status = silent_failure.status()
    assert component in status
    assert error_text in str(status[component]["last_error"])


class TestSpreadingActivationSignal:
    def test_sa_failure_degrades_to_empty_and_is_logged(self, caplog):
        from mcp_server.core.retrieval_signals import _compute_sa

        store = MagicMock()
        store.spread_activation_memories.side_effect = RuntimeError("plpgsql broke")
        settings = SimpleNamespace(
            SA_DECAY=0.65, SA_THRESHOLD=0.1, SA_MAX_DEPTH=2, SA_MAX_NODES=50
        )
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = _compute_sa("alpha beta gamma", store, 0.0, settings)
        assert out == []
        assert any(
            "retrieval_signals.spreading_activation" in r.message
            for r in caplog.records
        )
        _assert_noted("retrieval_signals.spreading_activation", "plpgsql broke")


class TestWikiClassifierUserRules:
    def test_provider_failure_degrades_to_no_rules_and_is_logged(
        self, caplog, monkeypatch
    ):
        from mcp_server.core import wiki_classifier

        def broken():
            raise RuntimeError("rules dir unreadable")

        monkeypatch.setattr(wiki_classifier, "_USER_RULES_PROVIDER", broken)
        monkeypatch.setattr(wiki_classifier, "_USER_RULES_CACHE", None)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            rules = wiki_classifier._load_user_rules()
        assert rules == []
        _assert_noted("wiki_classifier.user_rules_load", "rules dir unreadable")
        wiki_classifier.reset_user_rules()


class TestDashboardRegistry:
    def test_registry_failure_degrades_to_no_dashboards_and_is_logged(
        self, caplog, monkeypatch, tmp_path
    ):
        from mcp_server.core import wiki_coverage_dashboard
        from mcp_server.core.wiki_coverage_dashboard import write_dashboards

        def broken():
            raise RuntimeError("registry unreadable")

        # Patch the consumer's own binding: the import is at module top
        # (#197 family 4), so patching domain_mapping no longer reaches it.
        monkeypatch.setattr(wiki_coverage_dashboard, "_build_registry", broken)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = write_dashboards(tmp_path)
        assert out == {}
        _assert_noted("wiki_coverage_dashboard.registry", "registry unreadable")
