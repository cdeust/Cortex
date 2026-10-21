"""Session bounds on every PostgreSQL connection the store opens.

Not the fix for the 2026-10-20 incident (that is: no transaction spans a
request, no DDL outside the broker's start, one bounded pool; ADR-1112).
These are the backstops the three-pillar audit asks for (Track 0.2, probe A):
a connection that names itself and cannot hold a lock, a statement or an
idle transaction longer than any request that could have issued it.

- ``application_name``: ``cortex-store-<pool>-<pid>``, so
  ``pg_stat_activity`` attributes every backend to a pool and a process
  (acceptance A2's census: with the broker, one PID).
- ``statement_timeout`` and ``lock_timeout``: the deadline of the request
  class that uses the pool (interactive 30 s, background 1800 s); a
  statement still running after its requester gave up has no reader.
- ``idle_in_transaction_session_timeout``: the interactive deadline on every
  pool. A transaction lives inside one operation in the broker; idle in it
  for that long means a bug, and the server ends it instead of letting it
  block DDL and readers for hours (the incident: about 2 h).

source: ADR-1112 decision 4 (deadlines); docs/audits/2026-10-21-three-pillar-audit.md
Track 0.2; PostgreSQL 17 docs, 19.11.2 Statement Behavior
"""

from __future__ import annotations

import os

# source: ADR-1108 (a hook's 30 s budget) and ADR-0534 (the 30 min batch bound)
CLASS_DEADLINE_SECONDS = {"interactive": 30.0, "background": 1800.0}
# source: ADR-1112 the pool each request class runs on
_POOL_CLASS = {
    "interactive": "interactive",
    "batch": "background",
    "direct": "interactive",
}


def session_options(pool: str) -> dict[str, str]:
    """libpq connection keywords for a connection of ``pool``."""
    deadline_ms = int(CLASS_DEADLINE_SECONDS[_POOL_CLASS[pool]] * 1000)
    idle_ms = int(CLASS_DEADLINE_SECONDS["interactive"] * 1000)
    options = " ".join(
        (
            f"-c statement_timeout={deadline_ms}",
            f"-c lock_timeout={deadline_ms}",
            f"-c idle_in_transaction_session_timeout={idle_ms}",
        )
    )
    name = f"cortex-store-{pool}-{os.getpid()}"
    return {"application_name": name, "options": options}


def migration_name() -> str:
    """``application_name`` of a connection that runs the migration step or
    the runtime grants: ``cortex-migrate-<pid>``, so a census attributes it to
    its process (the broker at start). No timeouts: the owner rejected
    timeouts on DDL as the fix (ADR-1112, alternatives rejected)."""
    return f"cortex-migrate-{os.getpid()}"
