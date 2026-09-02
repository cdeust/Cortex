"""Unit tests for the change-remediation orchestrator (#110).

DB-free: a fake store records mark_memory_stale calls, a fake callback records
the paths handed to re-ingestion. Verifies the code-derived→reingest /
hand-authored→flag-stale split, path dedup, and the no-op case.
"""

from __future__ import annotations

from mcp_server.handlers.consolidation.change_remediation_pass import (
    remediate_impacted,
)


class _FakeStore:
    def __init__(self) -> None:
        self.marked: list[tuple[int, bool]] = []

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self.marked.append((memory_id, stale))


def _recorder():
    calls: list[list[str]] = []
    return calls, lambda paths: calls.append(paths)


def test_splits_reingest_and_flag_stale() -> None:
    impacted = [
        {"id": 1, "agent_context": "codebase", "changed_refs": ["src/a.py"]},
        {
            "id": 2,
            "agent_context": "",
            "tags": ["decision"],
            "changed_refs": ["src/a.py"],
        },
    ]
    store = _FakeStore()
    calls, reingest = _recorder()

    counts = remediate_impacted(impacted, store, reingest)

    assert counts == {"reingest_memories": 1, "flagged_stale": 1, "reingest_paths": 1}
    assert calls == [["src/a.py"]]  # only the code-derived memory's ref
    assert store.marked == [(2, True)]  # only the hand-authored memory flagged


def test_dedups_reingest_paths_across_memories() -> None:
    impacted = [
        {
            "id": 1,
            "agent_context": "codebase",
            "changed_refs": ["src/a.py", "src/b.py"],
        },
        {"id": 2, "agent_context": "codebase", "changed_refs": ["src/b.py"]},
    ]
    store = _FakeStore()
    calls, reingest = _recorder()

    counts = remediate_impacted(impacted, store, reingest)

    assert counts["reingest_memories"] == 2
    assert calls == [["src/a.py", "src/b.py"]]  # sorted + deduped
    assert store.marked == []


def test_empty_impacted_is_noop() -> None:
    store = _FakeStore()
    calls, reingest = _recorder()
    counts = remediate_impacted([], store, reingest)
    assert counts == {"reingest_memories": 0, "flagged_stale": 0, "reingest_paths": 0}
    assert calls == []
    assert store.marked == []
