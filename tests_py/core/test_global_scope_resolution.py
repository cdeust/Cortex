"""resolve_global_scope: explicit request, team propagation, detector (#561).

source: ADR-0200"""

from __future__ import annotations

from mcp_server.core.global_detector import propagates_to_team, resolve_global_scope

_DECISION = "Decision: we keep the ledger layout because the dossier needs it"
_PLAIN = "plain note about the weather in the fixture"


class TestPropagatesToTeam:
    def test_decision_with_agent_context_propagates(self):
        assert propagates_to_team(True, "cortex") is True

    def test_decision_without_agent_context_stays_local(self):
        assert propagates_to_team(True, "") is False

    def test_non_decision_never_propagates(self):
        assert propagates_to_team(False, "cortex") is False


class TestResolveGlobalScope:
    def test_explicit_request_wins(self):
        assert resolve_global_scope(_PLAIN, [], explicit=True, team_decision=False) == (
            True,
            "explicit",
        )

    def test_team_decision_is_global(self):
        assert resolve_global_scope(
            _DECISION, [], explicit=False, team_decision=True
        ) == (True, "team_decision")

    def test_no_team_decision_falls_back_to_detector(self):
        assert resolve_global_scope(
            _DECISION, [], explicit=False, team_decision=False
        ) == (False, "not_global")

    def test_detector_still_marks_cross_project_content(self):
        is_global, reason = resolve_global_scope(
            "Coding standard: always use dependency injection and clean architecture",
            ["global"],
            explicit=False,
            team_decision=False,
        )
        assert is_global is True
        assert reason.startswith("global_")
