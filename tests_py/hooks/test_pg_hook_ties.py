"""PostgreSQL hook queries cut exact heat ties newest first in every layout.

The agent briefing's role-prior pass and the SessionStart banner's anchor,
team-decision and hot queries end in ``ORDER BY <heat> DESC LIMIT``. On
cfd03db9 that order was not total: with more tied rows than the LIMIT, the
survivors followed heap order. Here 130 rows tie on heat; the heap is
rewritten in three orders and each query must keep the newest rows,
``created_at DESC, id DESC`` (ADR-1106).

Live PG (throwaway test database via conftest); skipped on SQLite, where
``tests_py/infrastructure/test_sqlite_listing_ties.py`` covers the twins.

source: ADR-1106
"""

from __future__ import annotations

import os

import pytest

from mcp_server.hooks.agent_briefing_role import _pg_role_rows
from mcp_server.hooks.agent_briefing_sqlite import _MAX_MEMORIES
from mcp_server.hooks.session_start_common import (
    _ANCHOR_LIMIT,
    _HOT_LIMIT,
    _MIN_HEAT,
)
from mcp_server.hooks.session_start_fetch import (
    _ANCHORS_SQL,
    _HOT_SQL,
    _TEAM_DECISIONS_SQL,
)
from tests_py._tie_layouts import (
    inserted_newest_first,
    newest_first,
    same_in_every_layout,
    stamps,
)
from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402 — after the importorskip guard
from psycopg.types.json import Jsonb  # noqa: E402 — after the importorskip guard

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

_PROJECT = "/p"


@pytest.fixture
def conn():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as c:
        c.execute("TRUNCATE memories CASCADE")
        yield c
        c.execute("TRUNCATE memories CASCADE")


def insert_tied(conn, **columns) -> list[int]:
    """130 rows tied on heat (no decay), plus ``columns``; ids newest first."""
    keys = []
    for stamp in stamps():
        row = {
            "content": "zq tied row",
            "domain": "ties",
            "source": "lesson",
            "heat_base": 0.5,
            "no_decay": True,
            "directory_context": _PROJECT,
            "agent_context": "worker",
            "created_at": stamp,
            "heat_base_set_at": stamp,
            "last_accessed": stamp,
            **columns,
        }
        names = ", ".join(row)
        marks = ", ".join(["%s"] * len(row))
        new = conn.execute(
            f"INSERT INTO memories ({names}) VALUES ({marks}) RETURNING id",  # noqa: S608 — column names are this test's literals; values are bound
            tuple(row.values()),
        ).fetchone()
        keys.append((stamp, new["id"]))
    return newest_first(keys)


def _ids(conn, sql: str, params: tuple) -> list[int]:
    return [r["id"] for r in conn.execute(sql, params).fetchall()]


def test_banner_anchors_keep_the_newest_ties(conn):
    expected = insert_tied(conn, is_protected=True, tags=Jsonb(["_anchor"]))
    got = same_in_every_layout(
        conn,
        "memories",
        lambda: _ids(conn, _ANCHORS_SQL, ([_PROJECT], _ANCHOR_LIMIT)),
    )
    assert got == expected[:_ANCHOR_LIMIT]


def test_banner_team_decisions_keep_the_newest_ties(conn):
    expected = insert_tied(conn, is_team_decision=True)
    got = same_in_every_layout(
        conn, "memories", lambda: _ids(conn, _TEAM_DECISIONS_SQL, ([_PROJECT],))
    )
    # source: session_start_fetch._TEAM_DECISIONS_SQL ends in LIMIT 5
    assert got == expected[:5]


def test_banner_hot_memories_keep_the_newest_ties(conn):
    expected = insert_tied(conn)
    got = same_in_every_layout(
        conn,
        "memories",
        lambda: _ids(conn, _HOT_SQL, (_MIN_HEAT, [_PROJECT], _HOT_LIMIT)),
    )
    assert got == inserted_newest_first(expected)[:_HOT_LIMIT]


def test_briefing_role_prior_keeps_the_newest_ties(conn):
    expected = insert_tied(conn)
    got = same_in_every_layout(
        conn,
        "memories",
        lambda: [
            r["id"] for r in _pg_role_rows(conn, "worker", _PROJECT, _MAX_MEMORIES)
        ],
    )
    assert got == expected[:_MAX_MEMORIES]
