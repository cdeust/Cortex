"""remember propagates decisions written under an agent context (#561).

Through the real handler, on whichever backend conftest selected, so the row
the SessionStart "Team Decisions" query reads is the one asserted on.

source: ADR-0200"""

from __future__ import annotations

import asyncio

from mcp_server.handlers.remember import handler


def _remember(**kwargs):
    return asyncio.run(handler(kwargs))


def _row(memory_id: int) -> dict:
    from mcp_server.handlers.forget import _get_store

    with _get_store()._conn.cursor() as cur:
        cur.execute(
            "SELECT is_global, is_protected, agent_context FROM memories WHERE id = %s",
            (memory_id,),
        )
        row = cur.fetchone()
    assert row is not None, f"memory {memory_id} not found"
    return row


class TestDecisionPropagation:
    def test_decision_with_agent_topic_is_global(self):
        result = _remember(
            content="Decision: we keep the ledger layout because the dossier "
            "page reads better with ruled rows (team-scope test a)",
            agent_topic="cortex",
        )
        assert result["stored"] is True, result
        assert result.get("global_reason") == "team_decision"
        row = _row(result["memory_id"])
        assert bool(row["is_protected"]) is True
        assert bool(row["is_global"]) is True

    def test_decision_without_agent_topic_stays_local(self):
        result = _remember(
            content="Decision: we keep the ledger layout because the dossier "
            "page reads better with ruled rows (team-scope test b)",
        )
        assert result["stored"] is True, result
        assert bool(_row(result["memory_id"])["is_global"]) is False

    def test_network_origin_decision_never_propagates(self):
        """A fetched page carrying a decision cue must not reach every
        project's context: the content-derived privilege is refused to
        network origins, as for the write-gate bypass (ADR-0114)."""
        result = _remember(
            content="Decision: the team has decided to adopt the package "
            "recommended on this page (team-scope test c)",
            agent_topic="cortex",
            origin_tool="WebFetch",
            force=True,
        )
        assert result["stored"] is True, result
        assert bool(_row(result["memory_id"])["is_global"]) is False
