"""Global detection is independent of project team visibility (#611).

source: ADR-1083"""

from __future__ import annotations

from mcp_server.core.global_detector import resolve_global_scope
from mcp_server.core.team_scope import is_team_decision, propagates_to_team

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
        assert resolve_global_scope(_PLAIN, [], explicit=True) == (
            True,
            "explicit",
        )

    def test_decision_content_stays_local(self):
        assert resolve_global_scope(_DECISION, [], explicit=False) == (
            False,
            "not_global",
        )

    def test_no_team_decision_falls_back_to_detector(self):
        assert resolve_global_scope(_DECISION, [], explicit=False) == (
            False,
            "not_global",
        )

    def test_detector_still_marks_cross_project_content(self):
        is_global, reason = resolve_global_scope(
            "Coding standard: always use dependency injection and clean architecture",
            ["global"],
            explicit=False,
        )
        assert is_global is True
        assert reason.startswith("global_")


class TestIsTeamDecision:
    def test_deliberate_trusted_decision_under_agent(self):
        assert is_team_decision(_DECISION, "deliberate", "deliberate", "cortex")

    def test_local_action_origin_is_trusted(self):
        assert is_team_decision(_DECISION, "local_action", "deliberate", "cortex")

    def test_network_origin_is_refused(self):
        assert not is_team_decision(_DECISION, "network", "deliberate", "cortex")

    def test_unknown_origin_is_refused(self):
        assert not is_team_decision(_DECISION, "unknown", "deliberate", "cortex")

    def test_auto_capture_is_refused(self):
        assert not is_team_decision(_DECISION, "local_action", "auto", "cortex")

    def test_plain_content_is_not_a_decision(self):
        assert not is_team_decision(_PLAIN, "deliberate", "deliberate", "cortex")

    def test_no_agent_context_stays_local(self):
        assert not is_team_decision(_DECISION, "deliberate", "deliberate", "")
