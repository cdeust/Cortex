"""Handler: calibration — score stated confidence against what happened.

Reads the resolved predictions and reports their Brier score with the
reliability breakdown that says, per confidence band, how often the
prediction actually held (issue #597).

source: ADR-1076"""

from __future__ import annotations

from typing import Any

from mcp_server.core.calibration import UNINFORMATIVE_BRIER, calibration_report
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.prediction_store import list_predictions

# Enough rows to score a year of a slow-filling store without paging.
# source: the predictions table is written one row per deliberate forecast;
# the maintainer's store held 0 on 2026-09-16, the day the table shipped.
_MAX_SCORED = 5000

schema = {
    "annotations": READ_ONLY,
    "description": (
        "Score the confidences of resolved predictions. Returns the Brier "
        "score (mean squared distance between stated confidence and "
        "outcome, Brier 1950) with its reference point: a forecaster who "
        "always says 0.5 scores 0.25, so anything above that carries less "
        "information than a coin, and perfect certainty that holds scores "
        "0. Also returns the reliability breakdown per confidence band, "
        "which the mean cannot show: a well-calibrated band around 0.7 is "
        "confirmed about seventy percent of the time. Abandoned "
        "predictions are counted apart and scored nowhere. Read-only. "
        "Returns {scored, abandoned, brier, uninformative_brier, "
        "confirmed, refuted, reliability, open}."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Score one cognitive domain; omit to score them all.",
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    domain = args.get("domain") or None
    conn = _get_store()._conn

    resolved = list_predictions(
        conn, status="resolved", domain=domain, limit=_MAX_SCORED
    )
    report = calibration_report(resolved)
    report["open"] = len(
        list_predictions(conn, status="open", domain=domain, limit=_MAX_SCORED)
    )
    report["domain"] = domain or "all"
    if report["brier"] is None:
        report["note"] = (
            "no resolved prediction carries an outcome yet; "
            f"a constant 0.5 forecast would score {UNINFORMATIVE_BRIER}"
        )
    return report
