"""Stderr-only logging helper shared across the agent_briefing hook split.

Extracted so the query module (``agent_briefing_query.py``) can log a
degraded PG query without importing the hook's entry-point module
(``agent_briefing.py``) — that direction would be a cycle, since the entry
point imports the query module's functions. This module has zero
dependents other than the agent_briefing split, so it sits below both.
"""

from __future__ import annotations

import sys

_LOG_PREFIX = "[cortex-agent-briefing]"


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)
