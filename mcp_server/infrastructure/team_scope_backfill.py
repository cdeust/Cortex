"""One-shot backfill: team propagation of decisions written before the fix.

Until #561 the live ``remember`` path never applied ADR-0200's rule (a
decision written under an agent context is marked is_global), so decisions
already stored carry is_global = FALSE. ``is_protected`` was set at write
time from the same decision cue the rule reads, which makes it the stored
trace of that cue. The rule applies only to origins allowed to claim a
content-derived privilege (capture_origin: deliberate, local_action) and to
deliberate writes, as on the write path; legacy and unknown rows keep their
scope. Anchored rows are
excluded: ``anchor`` sets is_protected as an explicit act with its own
is_global argument, not as a decision cue. Idempotent: a second run matches
no row.

source: ADR-0200"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import LiteralString

# source: ADR-0200
TEAM_DECISION_BACKFILL_PG: LiteralString = """
UPDATE memories SET is_global = TRUE
WHERE is_protected = TRUE
  AND is_global = FALSE
  AND is_benchmark = FALSE
  AND COALESCE(agent_context, '') <> ''
  AND superseded_by_id IS NULL
  AND capture_origin IN ('deliberate', 'local_action')
  AND write_class = 'deliberate'
  AND NOT COALESCE(tags @> '["_anchor"]'::jsonb, FALSE);
"""

# source: ADR-0200
TEAM_DECISION_BACKFILL_SQLITE: LiteralString = """
UPDATE memories SET is_global = 1
WHERE is_protected = 1
  AND COALESCE(is_global, 0) = 0
  AND COALESCE(is_benchmark, 0) = 0
  AND COALESCE(agent_context, '') <> ''
  AND superseded_by_id IS NULL
  AND capture_origin IN ('deliberate', 'local_action')
  AND write_class = 'deliberate'
  AND COALESCE(tags, '') NOT LIKE '%"_anchor"%'
"""
