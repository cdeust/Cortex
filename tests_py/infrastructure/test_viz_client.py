"""Tests for infrastructure/viz_client — the live-graph read client.

Contract (module docstring): discover the live viz instance from the
registry file, drain the paginated slice endpoint COMPLETELY (the union
of pages, never a lossy cap), memoise per ``phase_seq``, and report
``None`` — never a partial graph posing as complete — when no instance
answers or a page fails mid-drain. HTTP is stubbed at the ``_get_json``
seam; the registry file is a real file under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.infrastructure import viz_client


@pytest.fixture(autouse=True)
def _fresh_memo():
    """Each test starts with an empty memo and leaves none behind."""
    viz_client._memo.update(port=None, phase_seq=None, graph=None)
    yield
    viz_client._memo.update(port=None, phase_seq=None, graph=None)


def _write_registry(tmp_path: Path, monkeypatch, port=8123) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    reg = tmp_path / ".cache" / "cortex" / "viz-server.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"pid": 1, "port": port, "started_at": "t"}))


# ── Registry discovery ────────────────────────────────────────────────


def test_live_port_reads_the_registry_file(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, port=9001)
    assert viz_client._live_port() == 9001


def test_live_port_missing_registry_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert viz_client._live_port() is None


def test_live_port_corrupt_registry_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    reg = tmp_path / ".cache" / "cortex" / "viz-server.json"
    reg.parent.mkdir(parents=True)
    reg.write_text("{not json")
    assert viz_client._live_port() is None


def test_live_port_registry_without_port_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    reg = tmp_path / ".cache" / "cortex" / "viz-server.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"pid": 1}))
    assert viz_client._live_port() is None


# ── HTTP probe ────────────────────────────────────────────────────────


def test_get_json_decodes_the_response_body(monkeypatch):
    import urllib.request
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.__enter__.return_value.read.return_value = b'{"ok": true}'
    seen = {}

    def _fake_urlopen(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    assert viz_client._get_json(8123, "/api/x") == {"ok": True}
    assert seen["url"] == "http://127.0.0.1:8123/api/x"
    assert seen["timeout"] == viz_client._TIMEOUT_S


def test_get_json_connection_failure_returns_none(monkeypatch):
    import urllib.request

    def _refuse(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)

    assert viz_client._get_json(8123, "/api/x") is None


# ── Graph drain ───────────────────────────────────────────────────────


def test_fetch_without_registered_instance_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert viz_client.fetch_live_graph() is None


def test_fetch_unanswering_instance_returns_none(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch)
    with patch.object(viz_client, "_get_json", return_value=None):
        assert viz_client.fetch_live_graph() is None


def test_fetch_drains_every_page_into_one_complete_graph(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch)
    pages = [
        {
            "nodes": [1, 2],
            "edges": ["a"],
            "done": False,
            "phase_seq": 7,
            "full_ready": True,
        },
        {"nodes": [3], "edges": ["b"], "done": True},
    ]
    with patch.object(viz_client, "_get_json", side_effect=pages) as get:
        graph = viz_client.fetch_live_graph()

    assert graph == {
        "nodes": [1, 2, 3],
        "edges": ["a", "b"],
        "meta": {"source": "live-cache", "phase_seq": 7, "full_ready": True},
    }
    # Second request advances the offset by the page limit.
    assert f"offset={viz_client._PAGE_LIMIT}" in get.call_args_list[1].args[1]


def test_fetch_page_failure_mid_drain_reports_no_graph(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch)
    pages = [
        {"nodes": [1], "edges": [], "done": False, "phase_seq": 1},
        None,  # a partial graph must never pose as complete
    ]
    with patch.object(viz_client, "_get_json", side_effect=pages):
        assert viz_client.fetch_live_graph() is None


def test_fetch_memoises_per_phase_seq(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch)
    first = [
        {"nodes": [1], "edges": [], "done": True, "phase_seq": 3, "full_ready": False},
    ]
    with patch.object(viz_client, "_get_json", side_effect=first):
        graph1 = viz_client.fetch_live_graph()

    # Same phase_seq: only the header probe runs; the memoised graph
    # object is returned as-is (no re-drain).
    probe = [{"nodes": [999], "edges": [], "done": True, "phase_seq": 3}]
    with patch.object(viz_client, "_get_json", side_effect=probe) as get:
        graph2 = viz_client.fetch_live_graph()

    assert graph2 is graph1
    assert get.call_count == 1


def test_fetch_new_phase_seq_re_drains(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch)
    with patch.object(
        viz_client,
        "_get_json",
        side_effect=[{"nodes": [1], "edges": [], "done": True, "phase_seq": 1}],
    ):
        viz_client.fetch_live_graph()

    with patch.object(
        viz_client,
        "_get_json",
        side_effect=[{"nodes": [2], "edges": [], "done": True, "phase_seq": 2}],
    ):
        graph = viz_client.fetch_live_graph()

    assert graph["nodes"] == [2]
    assert graph["meta"]["phase_seq"] == 2
