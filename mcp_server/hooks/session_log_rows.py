"""One session-log row per transcript, and what replaces it.

A row is keyed on its ``sessionId`` (the transcript stem, ADR-0497). A
later SessionEnd under the same key used to be dropped as a replay, which
also dropped a transcript that had grown or had an earlier turn rewritten
(#716, acceptance item 3). The row now carries the fingerprint of its
transcript; a later version that is not the same bytes replaces the row,
and the new row names the version it replaced and how it differs.

source: ADR-1143"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.transcript_fingerprint import REPLAY, relation


def _logged_row(sessions: list[dict], session_id: str) -> dict | None:
    return next((row for row in sessions if row.get("sessionId") == session_id), None)


def append_session(
    session_log: dict, entry: dict[str, Any], transcript_path: object, cap: int
) -> str | None:
    """Add ``entry`` to the log unless it repeats the row already logged.

    Returns None for a new row, the relation (``transcript_fingerprint``)
    for a row already logged under the same ``sessionId``. A replay, or a
    version that cannot be compared (no fingerprint on either side), keeps
    the logged row. An appended or rewritten version removes it and appends
    ``entry`` with ``reconciliation``: the kind, the fingerprint and the
    timestamp of the row it replaced. The log keeps its last ``cap`` rows.
    """
    sessions = session_log.get("sessions") or []
    logged = _logged_row(sessions, entry["sessionId"])
    kind = None
    if logged is not None:
        kind = relation(transcript_path, logged.get("transcript"), entry["transcript"])
        if kind in (None, REPLAY):
            return kind
        sessions.remove(logged)
        entry["reconciliation"] = {
            "kind": kind,
            "replaced": logged.get("transcript"),
            "replacedTimestamp": logged.get("timestamp"),
        }
    sessions.append(entry)
    session_log["sessions"] = sessions[-cap:]
    return kind
