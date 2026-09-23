"""Handler: check_setup — MCP facade over mcp_server.doctor's checks.

source: ADR-0336"""

from __future__ import annotations

from typing import Any

from mcp_server.doctor import Check, active_checks
from mcp_server.handlers._tool_meta import READ_ONLY_EXTERNAL

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Check setup",
    "annotations": READ_ONLY_EXTERNAL,
    "description": (
        "Verify the local Cortex installation before first interactive "
        "use. Runs the identical check functions as `python -m "
        "mcp_server.doctor` (no duplicated logic), backend-aware. "
        "PostgreSQL backend: Python >= 3.10, "
        "psycopg/psycopg_pool/pgvector driver imports, DATABASE_URL set, "
        "live PostgreSQL connection, pgvector + pg_trgm extensions, "
        "~/.claude/methodology writability, I10 pool-capacity invariant, "
        "and an optional ai-architect-mcp-codebase codebase-tool probe. "
        "SQLite backend (zero-config default): the PG checks are replaced "
        "by a store-open check and a vector-search check that requires "
        "sqlite-vec to be loaded (it ships in every install's base "
        "package set; absence or a load failure blocks readiness). "
        "Checks run in doctor's own dependency order, so an early "
        "failure (e.g. missing DATABASE_URL) explains later ones (e.g. "
        "no PG connection) -- fix in list order. Call this once before "
        "first session, or whenever diagnosing a setup problem. "
        "Read-only but reaches outside the DB (env vars, filesystem, a "
        "live connection attempt). Takes no arguments. Returns "
        "{ready, summary, fixes_needed, checks: [{name, ok, optional, "
        "detail, fix_command}]}. `ready` is true iff every non-optional "
        "check passed; the codebase-pipeline probe is optional and "
        "never blocks readiness."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {},
        "additionalProperties": False,
    },
}


def _run_checks() -> list[Check]:
    """precondition: none.
    postcondition: returns one Check per `doctor.active_checks()` entry
    (backend-aware list), in doctor's own order -- this function performs
    no reordering or filtering; it only invokes doctor's callables and
    collects results.
    """
    return [check_fn() for check_fn in active_checks()]


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """precondition: none -- takes no arguments.
    postcondition: `checks` has exactly `len(active_checks())` entries in
    doctor's dependency order; `ready` is True iff no non-optional
    check failed; `fixes_needed` counts failing non-optional checks
    only (an optional-check failure, e.g. the codebase-pipeline probe,
    is a warning and never blocks readiness -- mirrors doctor's own
    exit-code semantics in `_run_full_check`).
    """
    checks = _run_checks()
    required_fails = [c for c in checks if not c.ok and not c.optional]
    ready = not required_fails

    summary = (
        "ready"
        if ready
        else (
            f"{len(required_fails)} "
            f"fix{'es' if len(required_fails) != 1 else ''} needed"
        )
    )

    return {
        "ready": ready,
        "summary": summary,
        "fixes_needed": len(required_fails),
        "checks": [
            {
                "name": c.name,
                "ok": c.ok,
                "optional": c.optional,
                "detail": c.detail,
                "fix_command": c.fix,
            }
            for c in checks
        ],
    }
