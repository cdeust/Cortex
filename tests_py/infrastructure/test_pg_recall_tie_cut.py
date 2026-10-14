"""A pool's LIMIT never decides which tied rows a recall signal credits.

Each pool of ``recall_memories()`` keeps its best ``v_pool`` rows. On
origin/main b2e63876 (ADR-1106) a tie group larger than the pool was cut
newest first: the oldest tied rows lost that signal's contribution for no
reason the score gives (LoCoMo conv-41: 122 rows at effective_heat 0.05,
``v_pool`` 100). ADR-1109 keeps the whole boundary tie group
(``FETCH FIRST v_pool ROWS WITH TIES``).

Here 130 rows tie on one pool's score and one of them, the answer, also
carries a second signal the others lack. The answer must rank first, alone,
whether it is the oldest or the newest of the tied rows. On origin/main the
oldest case fails (the answer is cut from the tied pool and only ties the
other rows); the newest case passes there and pins that the fix does not
just reverse the tie-break.

Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-1109
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

# source: recall_memories() v_pool = p_max_results * 10 -> 100 for
# max_results 10; 130 tied rows put 30 of them past the pool's cut.
_ROWS = 130
# source: recall() default top_k (pg_recall.py), as the benchmarks call it.
_MAX_RESULTS = 10
# source: pg_schema.py memories.embedding vector(384)
_DIM = 384
_DOMAIN = "tie-cut"
_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
# source: test fixture -- the tied heat and the answer's higher heat when heat
# is the second signal; both no_decay, so effective_heat equals heat_base.
_HEAT, _ANSWER_HEAT = 0.5, 0.9

# tied pool -> (content, answer content, query, second signal's weight name)
_CASES = {
    "hot": ("zq row", "zq ledger row", "ledger", "p_w_fts"),
    "fts": ("ledger entry", "ledger entry", "ledger", "p_w_heat"),
    "ngram": ("ledger entry", "ledger entry", "ledger entry", "p_w_heat"),
    "vec": ("zq row", "zq row", "wxyv", "p_w_heat"),
    "recency": ("zq row", "zq row", "wxyv", "p_w_heat"),
}
_WEIGHT = {
    "hot": "p_w_heat",
    "fts": "p_w_fts",
    "ngram": "p_w_ngram",
    "vec": "p_w_vector",
    "recency": "p_w_recency",
}
_NAMES = ("p_w_vector", "p_w_fts", "p_w_heat", "p_w_ngram", "p_w_recency")


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("TRUNCATE memories CASCADE")
        yield c
        c.execute("TRUNCATE memories CASCADE")


def _axis() -> str:
    return str([1.0 if j == 3 else 0.0 for j in range(_DIM)])


def _insert(conn, content: str, heat: float, stamp: datetime) -> int:
    return conn.execute(
        "INSERT INTO memories (content, embedding, domain, source, heat_base,"
        " no_decay, created_at, heat_base_set_at, last_accessed)"
        " VALUES (%s, %s::vector, %s, 'lesson', %s, TRUE, %s, %s, %s)"
        " RETURNING id",
        (content, _axis(), _DOMAIN, heat, stamp, stamp, stamp),
    ).fetchone()[0]


def insert_case(conn, pool: str, answer_end: str) -> int:
    """130 rows tied on ``pool``; the answer is the oldest or the newest.

    Rows are inserted oldest first, so (created_at, id) order agrees; the
    recency case gives every row one created_at and leaves id to order them.
    """
    content, answer_content, _, second = _CASES[pool]
    answer_at = 0 if answer_end == "oldest" else _ROWS - 1
    answer_id = 0
    for i in range(_ROWS):
        stamp = _BASE if pool == "recency" else _BASE + timedelta(hours=i)
        is_answer = i == answer_at
        heat = _ANSWER_HEAT if is_answer and second == "p_w_heat" else _HEAT
        mid = _insert(conn, answer_content if is_answer else content, heat, stamp)
        answer_id = mid if is_answer else answer_id
    return answer_id


def recall(conn, query: str, weights: dict[str, float]) -> list[tuple[int, float]]:
    return conn.execute(
        "SELECT memory_id, score FROM recall_memories("
        " p_query_text => %s, p_query_emb => %s::vector, p_domain => %s,"
        " p_include_globals => FALSE, p_max_results => %s, p_min_heat => 0.05,"
        " p_w_vector => %s::real, p_w_fts => %s::real, p_w_heat => %s::real,"
        " p_w_ngram => %s::real, p_w_recency => %s::real)",
        (query, _axis(), _DOMAIN, _MAX_RESULTS, *(weights[n] for n in _NAMES)),
    ).fetchall()


@pytest.mark.parametrize("answer_end", ["oldest", "newest"])
@pytest.mark.parametrize("pool", sorted(_CASES))
def test_answer_keeps_the_tied_signal_whatever_its_age(conn, pool, answer_end):
    answer = insert_case(conn, pool, answer_end)
    _, _, query, second = _CASES[pool]
    weights = dict.fromkeys(_NAMES, 0.0) | {_WEIGHT[pool]: 1.0, second: 1.0}
    rows = recall(conn, query, weights)
    assert rows[0][0] == answer
    assert rows[0][1] > rows[1][1], "the answer must not merely tie the others"
