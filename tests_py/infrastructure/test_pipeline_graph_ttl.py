"""Tests for pipeline graph TTL policy.

Source: docs/program/phase-5-pool-admission-design.md (pipeline
integration step 2), user directive "codebase analysis feeding the
memory and wiki".
"""

from __future__ import annotations

import os
import time


from mcp_server.infrastructure import pipeline_graph_ttl


class TestTtlValue:
    def test_default_is_24h(self, monkeypatch):
        monkeypatch.delenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", raising=False)
        assert pipeline_graph_ttl.graph_ttl_hours() == 24.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "2")
        assert pipeline_graph_ttl.graph_ttl_hours() == 2.0

    def test_malformed_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "not-a-number")
        assert pipeline_graph_ttl.graph_ttl_hours() == 24.0

    def test_negative_clamped_to_zero(self, monkeypatch):
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "-5")
        assert pipeline_graph_ttl.graph_ttl_hours() == 0.0


class TestStaleness:
    def test_missing_path_is_stale(self):
        assert pipeline_graph_ttl.graph_is_stale(None) is True
        assert pipeline_graph_ttl.graph_is_stale("") is True

    def test_nonexistent_file_is_stale(self, tmp_path):
        assert pipeline_graph_ttl.graph_is_stale(str(tmp_path / "no-such-file")) is True

    def test_fresh_file_not_stale(self, tmp_path):
        f = tmp_path / "graph.ladybug"
        f.write_text("content")
        assert pipeline_graph_ttl.graph_is_stale(str(f)) is False

    def test_old_file_stale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "1")
        f = tmp_path / "graph.ladybug"
        f.write_text("content")
        # Backdate 2 hours.
        old = time.time() - 2 * 3600
        os.utime(f, (old, old))
        assert pipeline_graph_ttl.graph_is_stale(str(f)) is True

    def test_ttl_zero_everything_stale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "0")
        f = tmp_path / "graph.ladybug"
        f.write_text("content")
        # Even a just-written file is older than "0 hours ago" by a tiny
        # amount — TTL 0 means always stale.
        assert pipeline_graph_ttl.graph_is_stale(str(f)) is True
