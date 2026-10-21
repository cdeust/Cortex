"""BLE001 sweep (issue #197, second family): hook-layer sites that gained
a ``_log`` emission.

Hooks log to stderr via ``_log``; each test forces the guarded operation
to fail and asserts BOTH the tolerant fallback (banner must never break)
and the now-visible stderr signal.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from mcp_server.hooks import (
    pipeline_impact_bump,
    session_start_curation,
    session_start_db,
    session_start_fetch,
    session_start_sqlite,
)


def _broken_conn(message: str = "pg down"):
    """A store whose operations fail on their connection (ADR-1112)."""
    from tests_py.hooks._store_fakes import ConnStore

    conn = MagicMock()
    conn.execute.side_effect = RuntimeError(message)
    return ConnStore(conn)


class TestSessionStartBannerFetches:
    def test_anchor_fetch_failure_degrades_to_empty_and_logs(self, capsys):
        assert session_start_fetch._fetch_anchors(_broken_conn()) == []
        assert "anchor fetch failed (non-fatal): pg down" in capsys.readouterr().err

    def test_team_decision_fetch_failure_degrades_to_empty_and_logs(self, capsys):
        assert session_start_fetch._fetch_team_decisions(_broken_conn(), set()) == []
        assert (
            "team-decision fetch failed (non-fatal): pg down" in capsys.readouterr().err
        )

    def test_hot_memory_fetch_failure_degrades_to_empty_and_logs(self, capsys):
        assert session_start_fetch._fetch_hot_memories(_broken_conn(), set()) == []
        assert "hot-memory fetch failed (non-fatal): pg down" in capsys.readouterr().err

    def test_pending_cluster_count_failure_degrades_to_zero_and_logs(self, capsys):
        assert session_start_curation._count_pending_curations(_broken_conn()) == 0
        assert (
            "pending-cluster count failed (non-fatal): pg down"
            in capsys.readouterr().err
        )

    def test_grooming_staleness_failure_degrades_to_empty_and_logs(self, capsys):
        assert session_start_curation._fetch_grooming_staleness(_broken_conn()) == []
        assert (
            "grooming-staleness fetch failed (non-fatal): pg down"
            in capsys.readouterr().err
        )

    def test_checkpoint_fetch_failure_degrades_to_none_and_logs(self, capsys):
        assert session_start_db._fetch_checkpoint(_broken_conn()) is None
        assert "checkpoint fetch failed (non-fatal): pg down" in capsys.readouterr().err

    def test_memory_count_failure_degrades_to_zero_and_logs(self, capsys):
        assert session_start_db._count_memories(_broken_conn()) == 0
        assert "memory count failed (non-fatal): pg down" in capsys.readouterr().err

    def test_sqlite_checkpoint_failure_degrades_to_none_and_logs(self, capsys):
        store = MagicMock()
        store.get_hot_memories.return_value = []
        store.get_active_checkpoint.side_effect = RuntimeError("sqlite locked")
        anchors, hot, checkpoint = session_start_sqlite._sqlite_banner_rows(store)
        assert anchors == [] and hot == []
        assert checkpoint is None
        assert (
            "SQLite checkpoint fetch failed (non-fatal): sqlite locked"
            in capsys.readouterr().err
        )


class TestPipelineImpactBumpCachedGraph:
    def test_store_failure_degrades_to_no_symbols_and_logs(self, capsys, monkeypatch):
        from mcp_server.infrastructure import memory_store

        def broken(*args, **kwargs):
            raise RuntimeError("store init broke")

        monkeypatch.setattr(memory_store, "get_shared_store", broken)
        out = asyncio.run(
            pipeline_impact_bump._pipeline_detect_changes("/proj", "/proj/a.py")
        )
        assert out == []
        assert "cached-graph lookup failed: store init broke" in capsys.readouterr().err
