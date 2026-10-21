"""Briefing limits shared by both backends. source: ADR-1085

Reuse ADR-0484's two passes and limits. The SQLite and PostgreSQL queries
are one store operation each (``infrastructure/hook_recall_queries.py``,
ADR-1112); the dialect follows the connection the store lends.
"""

from __future__ import annotations

# source: ADR-0484
_MAX_MEMORIES = 3
# source: ADR-0484
_MIN_HEAT = 0.2
