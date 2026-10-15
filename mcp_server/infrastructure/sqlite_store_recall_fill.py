"""Candidates from tie groups kept as predicates, newest first.

A row scored only through tie groups (``TieGroup``, ADR-1109) has the score
of the exact set of groups it belongs to (a class), plus the agent boost and
times the trust factor where those apply (a partition). Rows of one
partition all tie, so the final ranking (score, then ``created_at DESC, id
DESC``) can only keep a partition's newest ``top`` rows. With at most three
predicate groups (FTS5, heat, recency) there are at most 7 classes, times 2
agent and 2 trust partitions.

Each partition is read with one ``LIMIT top`` query over the group's
covering index; a class that holds no row at all is found with one probe
instead of one empty scan per partition. Measured on the production
arguments (ADR-1109, 2026-10-16): one ``ROW_NUMBER() OVER (PARTITION BY
...)`` statement per class sorts the whole class (42 to 74 ms against 4.6 to
14.9 ms at 40,000 rows); counting each partition first, to skip empty ones,
costs a predicate per group row on every recall and was slower on the
owner's store's origin and agent distribution (250,000 rows, uniform heat:
9.8 to 120.4 ms against 12.0 to 77.5 ms), faster only when no row is trusted.

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
_AGENT_MATCH = "COALESCE(m.agent_context = ?, 0)"
_TRUST_MATCH = f"COALESCE(m.capture_origin {_IN_JSON}, 0)"

Partition = tuple[bool | None, bool | None]
Where = tuple[list[str], list[Any]]


@dataclass(frozen=True)
class Adjustments:
    """The agent boost and trust factor ``recall_memories`` applies.

    source: ADR-0616"""

    agent_topic: str | None
    boost: float
    trusted_json: str
    untrusted_factor: float

    def partitions(self) -> list[Partition]:
        """(agent match, trust match) cases; None where no split applies.

        source: ADR-1109"""
        agents = (False, True) if self.agent_topic else (None,)
        trusts = (True, False) if self.untrusted_factor != 1.0 else (None,)
        return list(product(agents, trusts))


def _class_where(groups: list[TieGroup], members: tuple[bool, ...]) -> Where:
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


def _adjusted(base: float, part: Partition, adj: Adjustments) -> float:
    """The fusion's arithmetic: ``+= boost`` then ``*= factor``.

    source: ADR-0616"""
    agent, trusted = part
    score = base + adj.boost if agent else base
    return score if trusted is not False else score * adj.untrusted_factor


def _partition_conds(part: Partition, adj: Adjustments) -> Where:
    """source: ADR-1109"""
    agent, trusted = part
    conds: list[str] = []
    params: list[Any] = []
    if agent is not None:
        conds.append(_AGENT_MATCH if agent else f"NOT {_AGENT_MATCH}")
        params.append(adj.agent_topic)
    if trusted is not None:
        conds.append(_TRUST_MATCH if trusted else f"NOT {_TRUST_MATCH}")
        params.append(adj.trusted_json)
    return conds, params


def group_candidates(
    conn: PsycopgCompatConnection,
    groups: list[TieGroup],
    exclude_json: str,
    adj: Adjustments,
    top: int,
) -> list[tuple[float, str, int]]:
    """(score, created_at, id) of the newest ``top`` rows of every partition
    of every class.

    precondition: ``groups`` in fusion order; ``exclude_json`` lists the ids
    already scored row by row.

    source: ADR-1109"""
    out: list[tuple[float, str, int]] = []
    for members in product((False, True), repeat=len(groups)):
        if not any(members):
            continue
        inside = [g for g, m in zip(groups, members, strict=True) if m]
        base = ordered_sum([(g.signal, g.credit) for g in inside])
        index = next((g.index for g in inside if g.index), None)
        source = f"memories m INDEXED BY {index}" if index else "memories m"
        conds, params = _class_where(groups, members)
        where = ([*conds, f"m.id NOT {_IN_JSON}"], [*params, exclude_json])
        for part, rows in _class_fill(conn, source, where, adj, top).items():
            score = _adjusted(base, part, adj)
            out.extend((score, created, mid) for created, mid in rows)
    return out


def _class_fill(
    conn: PsycopgCompatConnection,
    source: str,
    where: Where,
    adj: Adjustments,
    top: int,
) -> dict[Partition, list[tuple[str, int]]]:
    """Each partition's newest ``top`` (created_at, id) of one class.

    source: ADR-1109"""
    parts = adj.partitions()
    if len(parts) > 1 and not _select(conn, source, where, 1):
        # One probe instead of one empty scan per partition: a class whose
        # group sets exclude every row is common (two groups covering the
        # same rows), and each of its partitions would scan the whole group.
        return {}
    return {
        part: [
            (r["created_at"], r["id"])
            for r in _select(conn, source, where, top, _partition_conds(part, adj))
        ]
        for part in parts
    }


def _select(
    conn: PsycopgCompatConnection,
    source: str,
    where: Where,
    limit: int,
    extra: Where = ([], []),
) -> list[Any]:
    """Rows of a class newest first, narrowed by the ``extra`` conditions.

    source: ADR-1109"""
    conds, params = where
    e_items, e_params = extra
    return conn.execute(
        "SELECT m.id AS id, m.created_at AS created_at "  # noqa: S608 — every condition is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        f"FROM {source} WHERE {' AND '.join([*conds, *e_items])} "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
        (*params, *e_params, limit),
    ).fetchall()
