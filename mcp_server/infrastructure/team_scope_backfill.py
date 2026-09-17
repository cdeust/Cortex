"""Mark legacy team decisions without granting cross-project visibility.

Global reclassification is a separate reviewed migration.
source: ADR-1083
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import LiteralString

# source: ADR-1083 (project visibility).
TEAM_DECISION_BACKFILL_PG: LiteralString = """
UPDATE memories SET is_team_decision = TRUE
WHERE is_protected = TRUE
  AND is_team_decision = FALSE
  AND is_benchmark = FALSE
  AND COALESCE(agent_context, '') <> ''
  AND superseded_by_id IS NULL
  AND capture_origin IN ('deliberate', 'local_action')
  AND write_class = 'deliberate'
  AND NOT COALESCE(tags @> '["_anchor"]'::jsonb, FALSE);
"""

# source: ADR-1083 (project visibility).
TEAM_DECISION_BACKFILL_SQLITE: LiteralString = """
UPDATE memories SET is_team_decision = 1
WHERE is_protected = 1
  AND COALESCE(is_team_decision, 0) = 0
  AND COALESCE(is_benchmark, 0) = 0
  AND COALESCE(agent_context, '') <> ''
  AND superseded_by_id IS NULL
  AND capture_origin IN ('deliberate', 'local_action')
  AND write_class = 'deliberate'
  AND COALESCE(tags, '') NOT LIKE '%"_anchor"%'
"""
