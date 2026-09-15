"""Team scope of decisions: Transactive Memory Systems (Wegner 1987).

The team knows WHAT was decided regardless of WHO decided it, so a
decision written under an agent context is marked is_global.

source: ADR-0200"""

from __future__ import annotations

from mcp_server.core import capture_origin, thermodynamics
from mcp_server.shared.write_class import DELIBERATE


def propagates_to_team(is_decision: bool, agent_context: str) -> bool:
    """True when a decision written under an agent context must be team-visible.

    source: ADR-0200"""
    return is_decision and bool(agent_context)


def is_team_decision(
    content: str, origin: str, write_class: str, agent_context: str
) -> bool:
    """A decision cue counts for team scope only on a deliberate write from an
    origin allowed content-derived privileges (ADR-0114), under an agent context.

    source: ADR-0200"""
    attested = (
        write_class == DELIBERATE
        and capture_origin.may_bypass_write_gate_on_content(origin)
        and thermodynamics.is_decision_content(content)
    )
    return propagates_to_team(attested, agent_context)
