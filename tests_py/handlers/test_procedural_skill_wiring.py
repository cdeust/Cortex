"""Integration tests for the B1 procedural-memory wiring.

Covers the capture writer (mine session log -> upsert skills) and the
recall handler (rebuild skills from stored rows -> situational match),
using a fake store so no Postgres is required.
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers.procedural_skill_writer import (
    maybe_mine_skills,
    _session_log_to_mining_input,
)
from mcp_server.handlers import recall_skills


class _FakeStore:
    """In-memory stand-in for PgAuxiliaryMixin's procedural methods."""

    def __init__(self, rows=None):
        self.skills: dict[str, dict] = {}
        for r in rows or []:
            self.skills[r["skill_id"]] = r

    def upsert_procedural_skill(self, data: dict) -> int:
        self.skills[data["skill_id"]] = dict(data)
        return len(self.skills)

    def get_procedural_skills(self, min_proficiency: float = 0.0, limit: int = 500):
        return [
            r
            for r in self.skills.values()
            if r.get("proficiency", 0.0) >= min_proficiency
        ][:limit]


def _log_entry(tools, score=1.0, cwd="/repo/cortex", domain="cortex", ts="2026-07-01"):
    return {
        "toolsUsed": tools,
        "score": score,
        "cwd": cwd,
        "domainId": domain,
        "timestamp": ts,
    }


# ── Capture writer ──────────────────────────────────────────────────────────
def test_session_log_adapter_maps_fields():
    entries = [_log_entry(["read_file", "edit_file"], score=1.0)]
    out = _session_log_to_mining_input(entries)
    assert out[0]["tools_used"] == ["read_file", "edit_file"]
    assert out[0]["outcome"] == 1.0
    assert out[0]["domain"] == "cortex"
    assert out[0]["cwd"] == "/repo/cortex"


def test_adapter_skips_empty_tools():
    entries = [_log_entry([], score=1.0), _log_entry(["a", "b"])]
    out = _session_log_to_mining_input(entries)
    assert len(out) == 1


def test_adapter_reads_persisted_score_as_outcome():
    # The score field record_session_end now persists must drive the outcome.
    good = _session_log_to_mining_input([_log_entry(["a", "b"], score=0.8)])
    bad = _session_log_to_mining_input([_log_entry(["a", "b"], score=0.2)])
    assert good[0]["outcome"] == 0.8
    assert bad[0]["outcome"] == 0.2


def test_adapter_missing_score_is_neutral():
    # An entry with no score field (e.g. legacy log) -> unknown outcome.
    entry = {"toolsUsed": ["a", "b"], "cwd": "/x", "domainId": "d"}
    out = _session_log_to_mining_input([entry])
    assert out[0]["outcome"] is None


def test_session_entry_persists_score():
    # Guard the wiring: _build_session_entry must carry the score field so the
    # reward signal reaches the log the miner reads.
    from mcp_server.handlers.record_session_end import _build_session_entry

    entry = _build_session_entry(
        "sid",
        "cortex",
        "/repo/cortex",
        None,
        1000,
        5,
        ["read_file", "edit_file"],
        "general",
        ["kw"],
        score=0.73,
    )
    assert entry["score"] == 0.73
    assert entry["toolsUsed"] == ["read_file", "edit_file"]


def test_writer_mines_and_upserts_recurring_skill():
    routine = ["read_file", "grep", "edit_file", "bash"]
    sessions = [_log_entry(routine, score=1.0) for _ in range(4)]
    store = _FakeStore()
    status = maybe_mine_skills(sessions, store)
    assert status["status"] == "ok"
    assert status["skills_written"] > 0
    # The full routine must be persisted.
    seqs = {r["action_sequence"] for r in store.skills.values()}
    assert "read_file>grep>edit_file>bash" in seqs
    # Every stored row carries the aggregate fields.
    any_row = next(iter(store.skills.values()))
    assert {
        "skill_id",
        "action_sequence",
        "proficiency",
        "occurrences",
        "is_habitual",
    } <= set(any_row)


def test_writer_skipped_on_thin_history():
    store = _FakeStore()
    status = maybe_mine_skills([_log_entry(["a", "b"])], store)
    assert status["status"] == "skipped"
    assert status["skills_written"] == 0


def test_writer_is_non_fatal_on_store_error():
    class _Boom:
        def upsert_procedural_skill(self, data):
            raise RuntimeError("db down")

    routine = ["read_file", "edit_file", "bash"]
    sessions = [_log_entry(routine) for _ in range(4)]
    status = maybe_mine_skills(sessions, _Boom())
    assert status["status"] == "error"
    assert "db down" in status["reason"]


# ── Recall handler ──────────────────────────────────────────────────────────
def test_recall_rebuilds_and_matches(monkeypatch):
    rows = [
        {
            "skill_id": "abc123",
            "action_sequence": "read_file>grep>edit_file",
            "context_signature": "cortex|cortex",
            "occurrences": 6,
            "success_count": 6,
            "failure_count": 0,
            "proficiency": 0.9,
            "is_habitual": True,
            "last_seen": "2026-07-01",
        }
    ]
    store = _FakeStore(rows)
    monkeypatch.setattr(
        "mcp_server.handlers.recall_skills.get_shared_store",
        lambda: store,
    )
    out = asyncio.run(
        recall_skills.handler(
            {
                "domain": "cortex",
                "cwd": "/repo/cortex",
                "recent_tools": ["read_file"],
                "top_k": 5,
            }
        )
    )
    assert out["count"] == 1
    top = out["skills"][0]
    assert top["skill"]["sequence"] == ["read_file", "grep", "edit_file"]
    assert "primed by current action" in top["why"]


def test_recall_filters_low_proficiency(monkeypatch):
    rows = [
        {
            "skill_id": "weak1",
            "action_sequence": "a>b",
            "context_signature": "cortex",
            "occurrences": 5,
            "success_count": 1,
            "failure_count": 4,
            "proficiency": 0.2,
            "is_habitual": False,
            "last_seen": "2026-07-01",
        }
    ]
    store = _FakeStore(rows)
    monkeypatch.setattr(
        "mcp_server.handlers.recall_skills.get_shared_store",
        lambda: store,
    )
    out = asyncio.run(
        recall_skills.handler(
            {"domain": "cortex", "cwd": "/repo/cortex", "min_proficiency": 0.5}
        )
    )
    assert out["count"] == 0


def test_recall_empty_store_returns_empty(monkeypatch):
    store = _FakeStore([])
    monkeypatch.setattr(
        "mcp_server.handlers.recall_skills.get_shared_store",
        lambda: store,
    )
    out = asyncio.run(recall_skills.handler({"domain": "cortex", "cwd": "/x"}))
    assert out == {"skills": [], "count": 0}
