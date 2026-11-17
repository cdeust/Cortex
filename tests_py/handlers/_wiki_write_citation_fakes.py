"""Fidelity fakes of wiki_write's citation collaborators (store, pages, citations).

Split out of ``test_wiki_write_citations.py`` (300-line cap). Each fake
reproduces the DB-level contract of what it replaces; a breach of the
handler's own contract (lookup inside the unit, write off the request
connection) is recorded on a shared ``_Violations`` list that the
``wired_pg`` fixture asserts empty after each test.

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
        """The page row and its citations commit as one unit (issue #715)."""
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
        self._next_id = 1
        self.raise_on_upsert = False
        self.request_conn: _FakeConn | None = None
        self.violations = violations

    def upsert(self, conn, page_row: dict) -> tuple[int, bool]:
        self.violations.check(
            conn is self.request_conn, "page row written off the request unit"
        )
        if self.raise_on_upsert:
            raise RuntimeError("PG unreachable")
        rel_path = page_row["rel_path"]
        if rel_path in self.by_path:
            return self.by_path[rel_path], False
        pid = self._next_id
        self._next_id += 1
        self.by_path[rel_path] = pid
        return pid, True


class _FakeCitations:
    """Reproduces the unqualified ON CONFLICT DO NOTHING dedup: a row is
    rejected if it matches EITHER partial unique index."""

    def __init__(self, violations: _Violations) -> None:
        self.rows: list[tuple[int, str, str, int | None]] = []
        self._next_id = 1
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
