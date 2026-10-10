"""Tests for ingest_findings_writers — mocked cursor (unit tier, mirrors
test_wiki_page_sources.py's pattern: no live Postgres required here; the
live integration proof against a real throwaway database is reported
separately in the task output)."""

from __future__ import annotations

from unittest.mock import MagicMock


from mcp_server.handlers.ingest_findings_artifacts import FindingRecord, Receipt
from mcp_server.handlers.ingest_findings_writers import (
    find_existing_memory,
    write_finding,
    write_finding_memory,
    write_finding_page,
    write_receipt_memos,
)


class _FakeStore:
    def __init__(self, existing_by_tag: dict[str, list[dict]] | None = None):
        self.memories: list[dict] = []
        self._next = 9000
        self._existing_by_tag = existing_by_tag or {}

    def insert_memory(self, data: dict) -> int:
        mid = self._next
        self._next += 1
        data = {**data, "id": mid}
        self.memories.append(data)
        return mid

    def get_memories_by_tag(
        self, tag: str, limit: int = 20, heads_only: bool = True
    ) -> list[dict]:
        return self._existing_by_tag.get(tag, [])


def _verified_finding(**overrides) -> FindingRecord:
    base = dict(
        run_id="run1",
        finding_id="f1",
        verified=True,
        title="Symbol X leaks memory",
        description="Root cause: unbounded growth in cache Y.",
        refined_rel_path="findings/f1/stage-1.refined.json",
        file_paths=["src/foo.rs"],
        receipts=[
            Receipt(
                stage="stage-2",
                rel_path="stage-2.verified.json",
                digest="abc123",
                verdict="verified",
                raw={},
                transcript_digest="cafef00d",
            )
        ],
        source_path=None,
    )
    base.update(overrides)
    return FindingRecord(**base)


def _mock_conn(*, memo_exists: bool = False, page_id: int = 42) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (1,) if memo_exists else None
    return conn


class TestFindExistingMemory:
    def test_returns_none_when_no_prior_memory(self):
        store = _FakeStore()
        assert find_existing_memory(store, "run1", "f1") is None

    def test_returns_id_when_tag_present(self):
        tag = "ap-finding:run1:f1"
        store = _FakeStore(
            existing_by_tag={tag: [{"id": 777, "tags": ["finding", tag]}]}
        )
        assert find_existing_memory(store, "run1", "f1") == 777


class TestWriteFindingMemory:
    def test_verified_finding_gets_verified_tags_and_high_confidence(self):
        store = _FakeStore()
        finding = _verified_finding()
        mem_id, created = write_finding_memory(store, finding)
        assert created is True
        record = store.memories[0]
        assert "verified" in record["tags"]
        assert "finding" in record["tags"]
        assert record["confidence"] > 0.8
        assert record["is_protected"] is True

    def test_hypothesis_finding_gets_low_confidence_no_protection(self):
        store = _FakeStore()
        finding = _verified_finding(verified=False, receipts=[])
        _, created = write_finding_memory(store, finding)
        assert created is True
        record = store.memories[0]
        assert "hypothesis" in record["tags"]
        assert "verified" not in record["tags"]
        assert record["confidence"] < 0.5
        assert record["is_protected"] is False

    def test_reingesting_same_finding_does_not_duplicate(self):
        tag = "ap-finding:run1:f1"
        store = _FakeStore(
            existing_by_tag={tag: [{"id": 555, "tags": ["finding", tag]}]}
        )
        finding = _verified_finding()
        mem_id, created = write_finding_memory(store, finding)
        assert created is False
        assert mem_id == 555
        assert store.memories == []  # no new row inserted


class TestWriteReceiptMemos:
    def test_inserts_one_memo_per_new_receipt(self, monkeypatch):
        import mcp_server.handlers.ingest_findings_writers as w

        inserted = []

        def _fake_insert_memo(conn, **kwargs):
            inserted.append(kwargs)
            return 1

        monkeypatch.setattr(w, "insert_memo", _fake_insert_memo)
        conn = _mock_conn(memo_exists=False)
        finding = _verified_finding()

        count = write_receipt_memos(conn, finding, page_id=42)

        assert count == 1
        assert inserted[0]["inputs"]["run_id"] == "run1"
        assert inserted[0]["inputs"]["finding_id"] == "f1"
        assert inserted[0]["inputs"]["stage"] == "stage-2"
        assert inserted[0]["inputs"]["digest"] == "abc123"
        assert inserted[0]["inputs"]["transcript_digest"] == "cafef00d"
        assert inserted[0]["author"] == "ap-pipeline"

    def test_transcript_digest_absent_from_inputs_when_ap_omits_it(self, monkeypatch):
        import mcp_server.handlers.ingest_findings_writers as w

        inserted = []
        monkeypatch.setattr(
            w, "insert_memo", lambda conn, **kw: inserted.append(kw) or 1
        )
        conn = _mock_conn(memo_exists=False)
        finding = _verified_finding(
            receipts=[
                Receipt(
                    stage="stage-2",
                    rel_path="stage-2.verified.json",
                    digest="abc123",
                    verdict="verified",
                    raw={},
                    transcript_digest=None,
                )
            ]
        )

        write_receipt_memos(conn, finding, page_id=42)

        assert "transcript_digest" not in inserted[0]["inputs"]

    def test_skips_receipt_already_recorded(self, monkeypatch):
        import mcp_server.handlers.ingest_findings_writers as w

        called = []
        monkeypatch.setattr(w, "insert_memo", lambda conn, **kw: called.append(kw))
        conn = _mock_conn(memo_exists=True)
        finding = _verified_finding()

        count = write_receipt_memos(conn, finding, page_id=42)

        assert count == 0
        assert called == []


class TestWriteFindingPageSourceAnchoring:
    def _patch_infra(self, monkeypatch, *, page_id: int = 42):
        import mcp_server.handlers.ingest_findings_writers as w

        calls = []
        monkeypatch.setattr(w, "write_page", lambda *a, **k: None)
        monkeypatch.setattr(w, "upsert_page", lambda conn, row: (page_id, True))
        monkeypatch.setattr(
            w,
            "upsert_page_sources",
            lambda conn, pid, entries, **kw: (
                calls.append((pid, tuple(entries), kw)) or len(entries)
            ),
        )
        return calls

    def test_anchors_both_link_kinds_when_source_path_present(self, monkeypatch):
        calls = self._patch_infra(monkeypatch)
        finding = _verified_finding(
            file_paths=["src/foo.rs"], source_path="/abs/report.json"
        )

        write_finding_page(_mock_conn(), finding, memory_id=1)

        kinds = {kw["link_kind"]: (pid, entries) for pid, entries, kw in calls}
        assert kinds["finding"] == (42, ("src/foo.rs",))
        assert kinds["extracted_from"] == (42, ("/abs/report.json",))
        for _pid, _entries, kw in calls:
            assert kw["source"] == "ap-pipeline"

    def test_no_extracted_from_call_when_source_path_absent(self, monkeypatch):
        calls = self._patch_infra(monkeypatch)
        finding = _verified_finding(file_paths=["src/foo.rs"], source_path=None)

        write_finding_page(_mock_conn(), finding, memory_id=1)

        kinds = [kw["link_kind"] for _pid, _entries, kw in calls]
        assert kinds == ["finding"]

    def test_reingesting_same_finding_reissues_same_anchoring_idempotently(
        self, monkeypatch
    ):
        calls = self._patch_infra(monkeypatch)
        finding = _verified_finding(
            file_paths=["src/foo.rs"], source_path="/abs/report.json"
        )

        write_finding_page(_mock_conn(), finding, memory_id=1)
        write_finding_page(_mock_conn(), finding, memory_id=1)

        # Same two (link_kind, entries) pairs both times -- delete+insert
        # semantics in the real upsert_page_sources make a second call
        # with identical arguments a no-op on row count.
        first_pass = [(pid, entries, kw["link_kind"]) for pid, entries, kw in calls[:2]]
        second_pass = [
            (pid, entries, kw["link_kind"]) for pid, entries, kw in calls[2:]
        ]
        assert first_pass == second_pass


class TestWriteFinding:
    def test_hypothesis_finding_skips_page_and_memos(self, monkeypatch):
        import mcp_server.handlers.ingest_findings_writers as w

        page_calls = []
        monkeypatch.setattr(
            w, "write_finding_page", lambda *a, **k: page_calls.append(a) or 1
        )
        store = _FakeStore()
        conn = _mock_conn()
        finding = _verified_finding(verified=False, receipts=[])

        result = write_finding(store, conn, finding)

        assert result["verified"] is False
        assert result["page_id"] is None
        assert result["memos_written"] == 0
        assert page_calls == []

    def test_verified_finding_writes_memory_page_and_memos(self, monkeypatch):
        import mcp_server.handlers.ingest_findings_writers as w

        monkeypatch.setattr(w, "write_finding_page", lambda conn, finding, mem_id: 42)
        monkeypatch.setattr(w, "write_receipt_memos", lambda conn, finding, page_id: 1)
        store = _FakeStore()
        conn = _mock_conn()
        finding = _verified_finding()

        result = write_finding(store, conn, finding)

        assert result["verified"] is True
        assert result["page_id"] == 42
        assert result["memos_written"] == 1
        assert result["memory_created"] is True
