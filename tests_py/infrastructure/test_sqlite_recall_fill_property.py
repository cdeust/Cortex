"""SQLite recall equals a naive reference on random stores full of ties.

``recall_memories`` reads a boundary tie group past the pool as a predicate
and fills from it newest first (ADR-1109). The reference below reads every
signal in full with no LIMIT, cuts it WITH TIES in Python, fuses every row,
boosts, applies trust, ranks all of it by (score, created_at, id) and keeps
the top ``max_results * 3`` visible rows. Random stores use few distinct
values on every signal so groups regularly run past the pool; the two must
return the same ids, in the same order, with bit-identical scores.

source: ADR-1109
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.shared.code_tokenize import expand_fts_query
from mcp_server.shared.tie_groups import ordered_sum, tied_rrf

# source: sqlite_schema.py memories_vec embedding float[384]
_DIM = 384
# source: test fixture -- seeds of the random stores.
_SEEDS = range(60)
# source: SqliteRecallMixin.recall_memories wrrf_k default.
_K = 60
_KEYS = ("vector", "fts", "heat", "recency")
_WORDS = ("ledger", "harbour", "zq")
_STAMPS = (
    "2026-01-01T00:00:00+00:00",
    "2026-01-02T00:00:00+00:00",
    "2026-01-03T00:00:00+00:00",
)


def _vector(i: int) -> bytes:
    v = np.zeros(_DIM, dtype=np.float32)
    v[i % 3] = 1.0 + 0.5 * (i // 3)
    return v.tobytes()


def build_store(rnd: random.Random) -> SqliteMemoryStore:
    """Rows with 2-3 distinct values per signal, so ties run past the pool."""
    store = SqliteMemoryStore()
    heats = rnd.sample([0.2, 0.5, 0.9], rnd.choice([2, 3]))
    # Skewed stores too: no trusted row, only trusted rows, no or only agent
    # matches, so whole agent and trust partitions are empty.
    agents = rnd.choice([["t", "u", None], ["u", None], ["t"], ["t", None, None, None]])
    origins = rnd.choice([["user", "auto", "hook"], ["auto", "hook"], ["user"]])
    n = rnd.randint(20, 160)
    for _ in range(n):
        words = rnd.choice([1, 2])
        content = " ".join(rnd.choice(_WORDS) for _ in range(words))
        emb = _vector(rnd.randrange(4)) if rnd.random() < 0.8 else None
        mid = store.insert_memory(
            {
                "content": content,
                "embedding": emb,
                "domain": "a",
                "source": "lesson",
                "heat": 0.5,
            }
        )
        store._conn.execute(
            "UPDATE memories SET heat_base = ?, created_at = ?, agent_context = ?,"
            " capture_origin = ?, domain = ?, is_global = ?, is_stale = ?,"
            " directory_context = ? WHERE id = ?",
            (rnd.choice(heats), rnd.choice(_STAMPS[: rnd.choice([1, 2, 3])]),
             rnd.choice(agents), rnd.choice(origins),
             rnd.choice(["a", "b"]), int(rnd.random() < 0.1),
             int(rnd.random() < 0.05), rnd.choice(["/p", "/q"]), mid),
        )  # fmt: skip
    ids = [r["id"] for r in store._conn.execute("SELECT id FROM memories").fetchall()]
    for mid in rnd.sample(ids, max(1, n // 15)):
        store._conn.execute(
            "UPDATE memories SET superseded_by_id = ? WHERE id = ?",
            (rnd.choice(ids), mid),
        )
    return store


def _with_ties(rows: list, pool: int) -> list:
    """WITH TIES on rows ordered best first by ``r[1]``."""
    if len(rows) <= pool:
        return rows
    boundary = rows[pool - 1][1]
    return [r for i, r in enumerate(rows) if i < pool or r[1] == boundary]


def _signal_rows(store, args: dict, pool: int) -> list[list]:
    c, (min_heat, domain) = store._conn, (args["min_heat"], args["domain"])
    w = args["weights"]
    cond, params = "heat_base >= ? AND NOT is_stale", [min_heat]
    if domain:
        cond, params = cond + " AND (domain = ? OR is_global = 1)", [*params, domain]
    if args["directory"]:
        cond += " AND (directory_context = ? OR is_global = 1)"
        params = [*params, args["directory"]]
    out = [[], [], [], []]
    if w["vector"] > 0 and args["emb"] is not None:
        out[0] = [
            (r["rowid"], r["d"])
            for r in c.execute(
                "SELECT rowid, vec_distance_l2(embedding, ?) AS d"
                " FROM memories_vec ORDER BY d",
                (args["emb"],),
            ).fetchall()
        ]
    match = expand_fts_query(args["text"])
    if w["fts"] > 0 and match:
        out[1] = [
            (r["rowid"], r["s"])
            for r in c.execute(
                "SELECT rowid, bm25(memories_fts) AS s FROM memories_fts"
                " WHERE memories_fts MATCH ? ORDER BY s",
                (match,),
            ).fetchall()
        ]
    for i, col in ((2, "heat_base"), (3, "created_at")):
        if w[("heat", "recency")[i - 2]] > 0:
            out[i] = [
                (r["id"], r["v"])
                for r in c.execute(
                    f"SELECT id, {col} AS v FROM current_memories"  # noqa: S608 — test fixture literals
                    f" WHERE {cond} ORDER BY {col} DESC",
                    params,
                ).fetchall()
            ]
    return [_with_ties(rows, pool) for rows in out]  # fmt: skip


def reference(store: SqliteMemoryStore, args: dict) -> list[tuple[int, float]]:
    """The fusion with every signal read in full: the naive definition."""
    pool, w = args["max_results"] * 10, args["weights"]
    contribs: dict[int, list] = {}
    keys = ("vector", "fts", "heat", "recency")
    for sig, rows in enumerate(_signal_rows(store, args, pool)):
        for mid, credit in tied_rrf(rows, w[keys[sig]], _K).items():
            contribs.setdefault(mid, []).append((sig, credit))
    scores = {mid: ordered_sum(cs) for mid, cs in contribs.items()}
    meta = {
        r["id"]: r for r in store._conn.execute("SELECT * FROM memories").fetchall()
    }
    for mid in scores:
        if args["agent_topic"] and meta[mid]["agent_context"] == args["agent_topic"]:
            scores[mid] += 0.3 * (w["vector"] / _K)
    for mid in scores:
        if args["untrusted_factor"] != 1.0 and meta[mid]["capture_origin"] not in (
            "user",
        ):
            scores[mid] *= args["untrusted_factor"]
    best = sorted(
        ((s, meta[m]["created_at"], m) for m, s in scores.items()), reverse=True
    )
    out = []
    for s, _, mid in best[: args["max_results"] * 3]:
        r = meta[mid]
        visible = (
            r["superseded_by_id"] is None
            and r["heat_base"] >= args["min_heat"]
            and not r["is_stale"]
        )
        in_dir = not args["directory"] or r["directory_context"] == args["directory"]
        in_domain = not args["domain"] or r["domain"] == args["domain"]
        if visible and (r["is_global"] or (in_domain and in_dir)):
            out.append((mid, s))
    return out


def random_args(rnd: random.Random) -> dict:
    weights = {
        k: rnd.choice([0.0, 0.3, 1.0]) for k in ("vector", "fts", "heat", "recency")
    }
    untrusted = rnd.choice([1.0, 0.5])
    return {
        "text": " ".join(rnd.sample(_WORDS, rnd.choice([1, 2]))),
        "emb": _vector(rnd.randrange(4)) if rnd.random() < 0.8 else None,
        "weights": weights,
        "max_results": rnd.choice([1, 2, 3]),
        "min_heat": rnd.choice([0.0, 0.4]),
        "domain": rnd.choice([None, "a"]),
        "directory": rnd.choice([None, "/p"]),
        "agent_topic": rnd.choice([None, "t"]),
        "untrusted_factor": untrusted,
    }


@pytest.mark.parametrize("seed", _SEEDS)
def test_recall_equals_the_naive_reference(seed):
    rnd = random.Random(seed)
    store = build_store(rnd)
    try:
        for _ in range(5):
            args = random_args(rnd)
            got = store.recall_memories(
                query_text=args["text"],
                query_embedding=args["emb"],
                domain=args["domain"],
                directory=args["directory"],
                agent_topic=args["agent_topic"],
                min_heat=args["min_heat"],
                max_results=args["max_results"],
                weights=args["weights"],
                trusted_origins=("user",),
                untrusted_factor=args["untrusted_factor"],
            )
            assert [(r["memory_id"], r["score"]) for r in got] == reference(
                store, args
            ), args
    finally:
        store.close()


def _members(store: SqliteMemoryStore, groups: list) -> dict[int, set[int]]:
    """Ids of each group, by its own predicate."""
    return {
        g.signal: {
            r["id"]
            for r in store._conn.execute(
                f"SELECT m.id AS id FROM memories m WHERE {g.where}", g.params
            ).fetchall()
        }
        for g in groups
    }


def _check_pair_counts(store, g, members) -> None:
    """Every class count of every counted pair of ``g`` against a naive count."""
    from itertools import product

    from mcp_server.infrastructure.sqlite_store_recall_groups import class_count

    meta = store._conn.execute(
        "SELECT id, capture_origin, agent_context FROM memories"
    ).fetchall()
    for origin, agent, counts in g.pairs:
        if counts is None:  # single group: pairs listed, not counted
            continue
        rows = [
            r["id"]
            for r in meta
            if r["id"] in members[g.signal]
            and (r["capture_origin"], r["agent_context"]) == (origin, agent)
        ]
        for flags in product((False, True), repeat=len(g.others)):
            inside = {s for s, f in zip(g.others, flags, strict=True) if f}
            outside = set(g.others) - inside
            naive = sum(
                all(mid in members[s] for s in inside)
                and not any(mid in members[s] for s in outside)
                for mid in rows
            )
            assert class_count(g, counts, inside, outside) == naive


@pytest.mark.parametrize("seed", _SEEDS)
def test_pair_class_counts_match_a_naive_count(seed):
    """Every class count the fill derives from a group's count pass (by
    inclusion-exclusion) equals counting that class's rows of the pair."""
    from mcp_server.infrastructure.sqlite_store_recall_groups import finalize_groups

    rnd = random.Random(seed)
    store = build_store(rnd)
    try:
        args = random_args(rnd) | {"weights": dict.fromkeys(_KEYS, 1.0)}
        filters = (args["min_heat"], args["domain"], args["directory"])
        _, pending = store._contributions(
            args["text"], args["emb"], args["weights"], (_K, 10), filters
        )
        groups = finalize_groups(store._conn, pending)
        members = _members(store, groups)
        for g in (g for g in groups if g.index):
            _check_pair_counts(store, g, members)
    finally:
        store.close()
