"""Mine + persist procedural skills at session end (B1 capture path).

Pulled out of ``record_session_end`` so the handler stays small and the
writer is unit-testable on its own — the same split as
``auto_task_record_writer``.

The flow:

  1. Load the session log (``{sessions: [...]}``) — the same history
     ``record_session_end`` has just appended the current session to.
  2. Mine recurring successful action sequences with
     ``core.procedural_memory.mine_skills`` (Graybiel chunking + Schultz
     reinforced success rate). Mining runs over the *whole* recent history,
     not just this session, because a skill only exists once it recurs.
  3. Upsert each mined skill into ``procedural_skills`` (content-addressed by
     skill_id, so re-mining merges rather than duplicating).

Failure is non-fatal — ``record_session_end`` must continue regardless. This
writer only ADDS procedural rows; it never touches the episodic/semantic
memories table, so turning it on cannot alter existing recall behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.procedural_memory import mine_skills

logger = logging.getLogger(__name__)

# Only mine over a bounded recent window of sessions — old routines that have
# stopped recurring should age out of the candidate set naturally.
_MAX_SESSIONS_FOR_MINING: int = 400


def _session_log_to_mining_input(sessions: list[dict]) -> list[dict]:
    """Adapt session-log entries to the shape ``mine_skills`` expects.

    Session-log entries use ``toolsUsed``; ``mine_skills`` reads
    ``tools_used``/``tool_calls``. Outcome is derived from the entry's
    critique/score when present, else left unknown (neutral — neither
    success nor failure).
    """
    out: list[dict] = []
    for entry in sessions[-_MAX_SESSIONS_FOR_MINING:]:
        tools = entry.get("toolsUsed") or entry.get("tools_used") or []
        if not tools:
            continue
        out.append(
            {
                "tools_used": tools,
                "outcome": _entry_outcome(entry),
                "domain": entry.get("domain") or entry.get("domainId") or "",
                "cwd": entry.get("cwd") or entry.get("directory") or "",
                "timestamp": entry.get("timestamp") or entry.get("endedAt") or "",
            }
        )
    return out


def _entry_outcome(entry: dict) -> Any:
    """Best-effort session outcome for reinforcement.

    Prefers the session self-critique overall score (``score``, in [0,1] —
    written by record_session_end as the mean of tool-diversity, 1-reversal,
    decision-confidence and coverage-breadth). A score >= 0.5 counts as
    success. This is a session-*quality* proxy, not a ground-truth task-success
    label, but it is the only per-session reward signal the system records; a
    well-run session is a reasonable proxy for "this procedure worked." Falls
    back to an explicit ``outcome`` field, else None (unknown / neutral, which
    advances the occurrence count without moving proficiency).
    """
    score = entry.get("score")
    if score is None:
        score = entry.get("critiqueScore")
    if isinstance(score, (int, float)):
        return float(score)
    return entry.get("outcome")


def maybe_mine_skills(
    sessions: list[dict],
    store: Any,
) -> dict[str, Any]:
    """Mine skills from the session history and upsert them.

    Returns a small status dict for the handler to surface. Never raises —
    all failures are caught and reported as ``{"status": "error", ...}``.
    """
    try:
        mining_input = _session_log_to_mining_input(sessions)
        if len(mining_input) < 3:
            return {
                "status": "skipped",
                "reason": "insufficient_history",
                "skills_written": 0,
            }

        skills = mine_skills(mining_input)
        written = 0
        for skill in skills:
            d = skill.as_dict()
            store.upsert_procedural_skill(
                {
                    "skill_id": d["skill_id"],
                    "action_sequence": ">".join(d["sequence"]),
                    "context_signature": d["context_signature"],
                    "occurrences": d["occurrences"],
                    "success_count": d["success_count"],
                    "failure_count": d["failure_count"],
                    "proficiency": d["proficiency"],
                    "is_habitual": d["is_habitual"],
                }
            )
            written += 1
        return {"status": "ok", "skills_written": written, "candidates": len(skills)}
    except Exception as exc:  # noqa: BLE001 — non-fatal: session-end must continue
        logger.warning("procedural skill mining failed: %s", exc)
        return {
            "status": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "skills_written": 0,
        }
