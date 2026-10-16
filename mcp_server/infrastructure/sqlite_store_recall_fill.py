"""Candidates from tie groups kept as predicates, newest first.

A row scored only through tie groups (``TieGroup``, ADR-1109) has the score
of the exact set of groups it belongs to (a class), plus the agent boost and
times the trust factor where those apply (a partition). Rows of one
partition all tie, so the final ranking (score, then ``created_at DESC, id
DESC``) can only keep a partition's newest ``top`` rows. With at most three
predicate groups (FTS5, heat, recency) there are at most 7 classes, times 2
agent and 2 trust partitions.

A class containing an indexed (heat or recency) group is read through the
smallest such group, its anchor. The anchor's count pass
(``sqlite_store_recall_groups.py``) listed its (capture_origin,
agent_context) pairs and, per pair, the rows of each class; every pair with
rows in the class is read with one seek on the anchor's covering index, in
``created_at DESC, id DESC`` order with no sort and ``LIMIT top``, and the
seeks of one partition are merged in one statement. A pair decides its
partition: agent = its agent_context is the topic, trust = its origin is a
trusted one. A class with no indexed group (FTS5 only) is read with one
``LIMIT top`` query per partition, after a one-row probe.

Measured on the production arguments (ADR-1109, 2026-10-16): scanning the
group once per partition cost 12 to 155 ms at 250,000 rows on one heat;
one ``ROW_NUMBER() OVER (PARTITION BY ...)`` statement per class sorts the
whole class (42 to 74 ms at 40,000 rows).

source: ADR-1109
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from typing import Any

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.infrastructure.sqlite_store_recall_groups import class_count
from mcp_server.shared.tie_groups import TieGroup, ordered_sum

# One bound parameter, a JSON array.
_IN_JSON = "IN (SELECT value FROM json_each(?))"
_AGENT_MATCH = "COALESCE(m.agent_context = ?, 0)"
_TRUST_MATCH = f"COALESCE(m.capture_origin {_IN_JSON}, 0)"

Partition = tuple[bool | None, bool | None]
Where = tuple[list[str], list[Any]]
Rows = list[tuple[str, int]]


@dataclass(frozen=True)
class Adjustments:
    """The agent boost and trust factor ``recall_memories`` applies.

    source: ADR-0616"""

    agent_topic: str | None
    boost: float
    trusted: tuple[str, ...]
    untrusted_factor: float

    @property
    def trusted_json(self) -> str:
        """source: ADR-1109"""
        return json.dumps(list(self.trusted))

    def partitions(self) -> list[Partition]:
        """(agent match, trust match) cases; None where no split applies.

        source: ADR-1109"""
        agents = (False, True) if self.agent_topic else (None,)
        trusts = (True, False) if self.untrusted_factor != 1.0 else (None,)
        return list(product(agents, trusts))

    def partition_of(self, origin: str, agent: str | None) -> Partition:
        """The partition of a (capture_origin, agent_context) pair, matching
        ``_AGENT_MATCH`` and ``_TRUST_MATCH`` (a NULL agent never matches).

        source: ADR-1109"""
        return (
            None if not self.agent_topic else agent == self.agent_topic,
            None if self.untrusted_factor == 1.0 else origin in self.trusted,
        )


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


def group_candidates(
    conn: PsycopgCompatConnection,
    groups: list[TieGroup],
    exclude_json: str,
    adj: Adjustments,
    top: int,
) -> list[tuple[float, str, int]]:
    """(score, created_at, id) of the newest ``top`` rows of every partition
    of every class.

    precondition: ``groups`` in fusion order, indexed ones counted
    (``finalize_groups``); ``exclude_json`` lists the ids already scored
    row by row.

    source: ADR-1109"""
    out: list[tuple[float, str, int]] = []
    for members in product((False, True), repeat=len(groups)):
        if not any(members):
            continue
        inside = [g for g, m in zip(groups, members, strict=True) if m]
        base = ordered_sum([(g.signal, g.credit) for g in inside])
        conds, params = _class_where(groups, members)
        where = ([*conds, f"m.id NOT {_IN_JSON}"], [*params, exclude_json])
        anchor = min((g for g in inside if g.index), key=lambda g: g.size, default=None)
        if anchor is None:
            fill = _fill_by_partition(conn, where, adj, top)
        else:
            outside = {g.signal for g, m in zip(groups, members, strict=True) if not m}
            inner = {g.signal for g in inside} - {anchor.signal}
            pairs = _class_pairs(anchor, inner, outside, adj)
            fill = {
                part: _seek_pairs(conn, anchor, pp, where, top)
                for part, pp in pairs.items()
            }
        for part, rows in fill.items():
            score = _adjusted(base, part, adj)
            out.extend((score, created, mid) for created, mid in rows)
    return out


def _class_pairs(
    anchor: TieGroup, inside: set[int], outside: set[int], adj: Adjustments
) -> dict[Partition, list[list[Any]]]:
    """The anchor's pairs holding rows of the class, by partition.

    source: ADR-1109"""
    by_part: dict[Partition, list[list[Any]]] = {}
    for origin, agent, counts in anchor.pairs:
        if counts is None or class_count(anchor, counts, inside, outside) > 0:
            part = adj.partition_of(origin, agent)
            by_part.setdefault(part, []).append([origin, agent])
    return by_part


def _seek_pairs(
    conn: PsycopgCompatConnection,
    anchor: TieGroup,
    pairs: list[list[Any]],
    where: Where,
    top: int,
) -> Rows:
    """The newest ``top`` class rows over ``pairs``: one ordered seek per
    pair on the anchor's index, merged in the same statement.

    source: ADR-1109"""
    conds, params = where
    rows = conn.execute(
        "SELECT r.id AS id, r.created_at AS created_at FROM json_each(?) p "  # noqa: S608 — index and conditions are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        "JOIN memories r ON r.id IN (SELECT m.id FROM memories m "
        f"INDEXED BY {anchor.index} "
        "WHERE m.capture_origin = json_extract(p.value, '$[0]') "
        "AND m.agent_context IS json_extract(p.value, '$[1]') "
        f"AND {' AND '.join(conds)} "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?) "
        "ORDER BY r.created_at DESC, r.id DESC LIMIT ?",
        (json.dumps(pairs), *params, top, top),
    ).fetchall()
    return [(r["created_at"], r["id"]) for r in rows]


def _fill_by_partition(
    conn: PsycopgCompatConnection, where: Where, adj: Adjustments, top: int
) -> dict[Partition, Rows]:
    """A class with no indexed group: one ``LIMIT top`` query per partition,
    after a one-row probe (an empty class would scan once per partition).

    source: ADR-1109"""
    parts = adj.partitions()
    if len(parts) > 1 and not _select(conn, where, ([], []), 1):
        return {}
    return {
        part: _select(conn, where, _partition_conds(part, adj), top) for part in parts
    }


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


def _select(
    conn: PsycopgCompatConnection, where: Where, extra: Where, limit: int
) -> Rows:
    """Rows of a class newest first, narrowed by ``extra``.

    source: ADR-1109"""
    conds, params = where
    e_items, e_params = extra
    rows = conn.execute(
        "SELECT m.id AS id, m.created_at AS created_at FROM memories m "  # noqa: S608 — every condition is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        f"WHERE {' AND '.join([*conds, *e_items])} "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
        (*params, *e_params, limit),
    ).fetchall()
    return [(r["created_at"], r["id"]) for r in rows]
