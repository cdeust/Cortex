"""Fidelity fakes of wiki_write's citation collaborators (store, pages, citations).

Split out of ``test_wiki_write_citations.py`` (300-line cap). The fakes
record a breach of the handler's own contract (lookup inside the unit,
write off the request connection) on a shared ``_Violations`` list that the
``wired_pg`` fixture asserts empty after each test. They do not reproduce
atomicity: ``_FakeConn.transaction()`` only yields, so a dropped
``with conn.transaction()`` is caught by the atomicity tests on the real
store (``test_wiki_write_citation_atomicity.py``), not here (PR #1085
review).

source: issue #715; PR #1083 and #1084 reviews
"""

from __future__ import annotations

from contextlib import contextmanager


class _Violations(list):
    """Contract breaches the fakes saw, asserted after each test.

    A fake that raised instead would have its error swallowed by the
    handler's ``except Exception`` and show only as ``citations_interrupted``
    (PR #1084 review); recording it lets the test name the breach.
    """

    def check(self, ok: bool, breach: str) -> None:
        if not ok:
            self.append(breach)


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    @contextmanager
    def transaction(self):
        """Only yields: the unit is entered, nothing is rolled back.

        Atomicity is proven on the real store
        (``test_wiki_write_citation_atomicity.py``), not by this fake.

        source: issue #715; PR #1085 and #1086 reviews
        """
        yield


class _FakeStore:
    """``_conn`` is the shared connection; the unit must never run on it."""

    def __init__(
        self, shared: _FakeConn, request: _FakeConn, violations: _Violations
    ) -> None:
        self._conn = shared
        self.violations = violations
        self.request_conn = request
        self.held = False
        self.memories: dict[int, dict] = {}

    @contextmanager
    def acquire_interactive(self):
        """The request-owned connection the citation unit runs on (PR #1083)."""
        self.held = True
        try:
            yield self.request_conn
        finally:
            self.held = False

    def get_memories_by_ids(self, memory_ids: list[int]) -> dict[int, dict]:
        # A lookup while the unit holds its connection borrows a second one.
        self.violations.check(
            not self.held, "memory lookup ran inside the citation unit"
        )
        return {m: self.memories[m] for m in memory_ids if m in self.memories}


class _FakePages:
    """rel_path -> page_id, auto-assigning ids like a real SERIAL PK."""

    def __init__(self, violations: _Violations) -> None:
        self.by_path: dict[str, int] = {}
        self.hashes: dict[str, str | None] = {}
        self._next_id = 1
        self.raise_on_upsert = False
        self.request_conn: _FakeConn | None = None
        self.violations = violations
        # page ids whose retractions a full write cleared, in call order
        self.cleared: list[int] = []
        # what page_retractions_frontier returns, and the frontier each clear got
        self.last_retraction = 0
        self.cleared_up_to: list[int] = []

    def upsert(self, conn, page_row: dict) -> tuple[int, bool]:
        self.violations.check(
            conn is self.request_conn, "page row written off the request unit"
        )
        if self.raise_on_upsert:
            raise RuntimeError("PG unreachable")
        rel_path = page_row["rel_path"]
        # was_modified is True when the recorded hash changes (ADR-0580)
        modified = self.hashes.get(rel_path) != page_row.get("body_hash")
        self.hashes[rel_path] = page_row.get("body_hash")
        if rel_path in self.by_path:
            return self.by_path[rel_path], modified
        pid = self._next_id
        self._next_id += 1
        self.by_path[rel_path] = pid
        return pid, True

    def retraction_frontier(self, conn) -> int:
        self.violations.check(
            conn is self.request_conn, "frontier read off a request connection"
        )
        return self.last_retraction

    def clear_retractions(self, conn, page_id: int, frontier: int) -> None:
        self.violations.check(
            conn is self.request_conn, "retractions cleared off the request unit"
        )
        self.cleared.append(page_id)
        self.cleared_up_to.append(frontier)


class _FakeCitations:
    """Reproduces the unqualified ON CONFLICT DO NOTHING dedup: a row is
    rejected if it matches EITHER partial unique index."""

    def __init__(self, violations: _Violations) -> None:
        self.rows: list[tuple[int, str, str, int | None]] = []
        self._next_id = 1
        # every insert_citation call, refused or not (review of PR #1113)
        self.attempts = 0
        self.request_conn: _FakeConn | None = None
        self.violations = violations

    def insert(
        self,
        conn,
        page_id: int,
        session_id: str = "",
        domain: str = "",
        memory_id: int | None = None,
    ) -> int | None:
        self.violations.check(
            conn is self.request_conn, "citation written off the request unit"
        )
        self.attempts += 1
        for existing in self.rows:
            if (
                session_id != ""
                and existing[0] == page_id
                and existing[1] == session_id
            ):
                return None
            if (
                memory_id is not None
                and existing[0] == page_id
                and existing[3] == memory_id
            ):
                return None
        cid = self._next_id
        self._next_id += 1
        self.rows.append((page_id, session_id, domain, memory_id))
        return cid

    def delete_memory_rows(self, conn, page_id: int, keep: list[int]) -> int:
        """``delete_page_memory_citations``: reads and ``keep`` stay."""
        self.violations.check(
            conn is self.request_conn, "citations deleted off the request unit"
        )
        kept = [r for r in self.rows if r[0] != page_id or r[3] is None or r[3] in keep]
        removed = len(self.rows) - len(kept)
        self.rows = kept
        return removed

    def memory_ids(self, conn, page_id: int) -> list[int]:
        """``list_page_cited_memory_ids``: distinct, first cited first."""
        self.violations.check(
            conn is self.request_conn, "citations read off the request unit"
        )
        named = [r[3] for r in self.rows if r[0] == page_id and r[3] is not None]
        return list(dict.fromkeys(named))
