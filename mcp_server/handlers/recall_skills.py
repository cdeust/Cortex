"""Handler for the recall_skills tool — procedural memory retrieval (B1).

Read-only. Returns the learned procedures (recurring successful action
sequences) that apply to the current situation, ranked by context match x
proficiency x support. This is a NEW, additive retrieval surface — it does not
touch the declarative recall_memories() path, so enabling it cannot change
existing episodic/semantic recall behaviour.

"In this situation, the routine that usually works is X."
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import logging

from mcp_server.core.procedural_memory import (
    ProceduralSkill,
    ActionStep,
    match_skills,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.memory_store import get_shared_store

logger = logging.getLogger(__name__)

schema = {
    "title": "Recall procedural skills for the current situation",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["skills"],
        "properties": {
            "skills": {
                "type": "array",
                "description": "Applicable procedures, strongest first.",
                "items": {"type": "object"},
            },
            "count": {"type": "integer"},
        },
    },
    "description": (
        "Retrieve learned procedures (recurring successful tool-use "
        "sequences) that apply to the current situation — domain, working "
        "directory, and recent actions. Procedural memory is retrieved by "
        "SITUATION, not by content similarity, which is what distinguishes "
        "it from recall_memories (episodic/semantic). Read-only; returns "
        "each skill's action sequence, proficiency, use count, and a "
        "human-readable rationale. Additive surface — does not alter "
        "declarative recall."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Cognitive-profile domain id to match skills against "
                    "(e.g. from detect_domain). Omit to match on the "
                    "other situation signals only."
                ),
            },
            "cwd": {
                "type": "string",
                "description": (
                    "Working directory of the current session; matched "
                    "against the directory context each skill was "
                    "learned in."
                ),
            },
            "recent_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Names of the most recently used tools, oldest "
                    "first; matched against each skill's action "
                    "sequence."
                ),
            },
            "top_k": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of skills to return.",
            },
            "min_proficiency": {
                "type": "number",
                "default": 0.5,
                "description": (
                    "Proficiency floor in [0, 1]; skills below it are "
                    "filtered out before ranking."
                ),
            },
        },
    },
}


@runtime_checkable
class _ProceduralSkillsStore(Protocol):
    """Capability contract for the procedural-skills subsystem (PG-only).

    The SQLite backend has no procedural_skills table; the empty result is
    the named degraded mode, decided by a static member check rather than
    an AttributeError swallowed by the broad except below.
    """

    def get_procedural_skills(
        self, min_proficiency: float = ..., limit: int = ...
    ) -> list[dict]: ...


def _row_to_skill(row: dict) -> ProceduralSkill:
    """Rebuild a ProceduralSkill from a stored procedural_skills row.

    The action_sequence is a ``>``-joined string of step keys
    (``tool`` or ``tool:target_kind``).
    """
    steps: list[ActionStep] = []
    for key in (row.get("action_sequence") or "").split(">"):
        key = key.strip()
        if not key:
            continue
        if ":" in key:
            tool, kind = key.split(":", 1)
            steps.append(ActionStep(tool=tool, target_kind=kind))
        else:
            steps.append(ActionStep(tool=key))
    return ProceduralSkill(
        sequence=tuple(steps),
        context_signature=row.get("context_signature", "") or "",
        occurrences=row.get("occurrences", 0) or 0,
        success_count=row.get("success_count", 0) or 0,
        failure_count=row.get("failure_count", 0) or 0,
        proficiency=float(row.get("proficiency", 0.0) or 0.0),
        last_seen=str(row.get("last_seen", "") or ""),
        skill_id=row.get("skill_id", "") or "",
    )


async def handler(args: dict) -> dict:

    cwd = args.get("cwd") or ""
    domain = args.get("domain") or ""
    recent_tools = args.get("recent_tools") or []
    top_k = int(args.get("top_k", 5))
    min_proficiency = float(args.get("min_proficiency", 0.5))

    store = get_shared_store()
    if not isinstance(store, _ProceduralSkillsStore):
        logger.info("recall_skills: backend has no procedural-skills store")
        return {"skills": [], "count": 0}
    try:
        rows = store.get_procedural_skills(min_proficiency=min_proficiency)
    except Exception as exc:  # noqa: BLE001 — store not migrated / unavailable
        logger.warning("recall_skills store read failed: %s", exc)
        return {"skills": [], "count": 0}

    skills = [_row_to_skill(r) for r in rows]
    matches = match_skills(
        {"domain": domain, "cwd": cwd, "tools_used": recent_tools},
        skills,
        top_k=top_k,
        min_proficiency=min_proficiency,
    )
    return {"skills": matches, "count": len(matches)}
