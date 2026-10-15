"""Candidates from tie groups kept as predicates, newest first.

A row scored only through tie groups (``TieGroup``, ADR-1109) has the score
of the exact set of groups it belongs to, plus the agent boost and times the
trust factor where those apply. Rows of one such class all tie, so the final
ranking (score, then ``created_at DESC, id DESC``) can only keep a class's
newest ``top`` rows: one ``ORDER BY m.created_at DESC, m.id DESC LIMIT top``
per class reads them. With at most three predicate groups (FTS5, heat,
recency) there are at most 7 group sets, times 2 agent and 2 trust cases.

source: ADR-1109
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.shared.tie_groups import TieGroup, ordered_sum

# One bound parameter, a JSON array.
_IN_JSON = "IN (SELECT value FROM json_each(?))"


@dataclass(frozen=True)
class Adjustments:
    """The agent boost and trust factor ``recall_memories`` applies.

    source: ADR-0616"""

    agent_topic: str | None
    boost: float
    trusted_json: str
    untrusted_factor: float


def _class_where(
    groups: list[TieGroup], members: tuple[bool, ...]
) -> tuple[list[str], list[Any]]:
    """Exactly the groups flagged in ``members``: inside those, outside the
    rest (``NOT COALESCE``, so a NULL predicate counts as outside).

    source: ADR-1109"""
    conds: list[str] = []
    params: list[Any] = []
    for group, inside in zip(groups, members, strict=True):
        conds.append(
            f"({group.where})" if inside else f"NOT COALESCE(({group.where}), 0)"
        )
        params.extend(group.params)
    return conds, params


def _adjusted(
    base: float, agent: bool | None, trusted: bool | None, adj: Adjustments
) -> float:
    """The fusion's arithmetic: ``+= boost`` then ``*= factor``.

    source: ADR-0616"""
    score = base + adj.boost if agent else base
    return score if trusted is not False else score * adj.untrusted_factor


def _adjustment_conds(
    agent: bool | None, trusted: bool | None, adj: Adjustments
) -> tuple[list[str], list[Any]]:
    """source: ADR-0616"""
    conds: list[str] = []
    params: list[Any] = []
    if agent is not None:
        conds.append(
            "m.agent_context = ?" if agent else "NOT COALESCE(m.agent_context = ?, 0)"
        )
        params.append(adj.agent_topic)
    if trusted is not None:
        inside = f"m.capture_origin {_IN_JSON}"
        conds.append(inside if trusted else f"NOT COALESCE({inside}, 0)")
        params.append(adj.trusted_json)
    return conds, params


def group_candidates(
    conn: PsycopgCompatConnection,
    groups: list[TieGroup],
    exclude_json: str,
    adj: Adjustments,
    top: int,
) -> list[tuple[float, str, int]]:
    """(score, created_at, id) of the newest ``top`` rows of every class.

    precondition: ``groups`` in fusion order; ``exclude_json`` lists the ids
    already scored row by row.

    source: ADR-1109"""
    agents = (False, True) if adj.agent_topic else (None,)
    trusts = (True, False) if adj.untrusted_factor != 1.0 else (None,)
    out: list[tuple[float, str, int]] = []
    for members in product((False, True), repeat=len(groups)):
        if not any(members):
            continue
        base = ordered_sum(
            [(g.signal, g.credit) for g, m in zip(groups, members, strict=True) if m]
        )
        g_conds, g_params = _class_where(groups, members)
        index = next(
            (g.index for g, m in zip(groups, members, strict=True) if m and g.index),
            None,
        )
        source = f"memories m INDEXED BY {index}" if index else "memories m"
        for agent, trusted in product(agents, trusts):
            a_conds, a_params = _adjustment_conds(agent, trusted, adj)
            rows = conn.execute(
                f"SELECT m.id AS id, m.created_at AS created_at FROM {source} "  # noqa: S608 — every condition is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                f"WHERE {' AND '.join([*g_conds, *a_conds, f'm.id NOT {_IN_JSON}'])} "
                "ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                (*g_params, *a_params, exclude_json, top),
            ).fetchall()
            score = _adjusted(base, agent, trusted, adj)
            out.extend((score, r["created_at"], r["id"]) for r in rows)
    return out
