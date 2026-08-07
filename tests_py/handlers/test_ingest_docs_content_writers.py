"""Unit tests for ingest_docs_content_writers (INC5.3/D6) — fake store,
no live Postgres required (mirrors test_ingest_findings_writers.py's
pattern)."""

from __future__ import annotations

from pathlib import Path

from mcp_server.handlers.ingest_docs_content_writers import (
    MAX_DOC_BYTES,
    doc_content_hash,
    doc_hash_tag,
    doc_tag,
    existing_content_hash,
    find_existing_doc_memory,
    read_doc_content,
    write_doc_memory,
    write_doc_reference_edge,
)


class _FakeStore:
    def __init__(
        self,
        existing_by_tag: dict[str, list[dict]] | None = None,
        entities_by_name: dict[str, dict] | None = None,
    ):
        self.memories: list[dict] = []
        self.relationships: list[dict] = []
        self.supersede_calls: list[tuple[dict, int]] = []
        self._next = 9000
        self._existing_by_tag = existing_by_tag or {}
        self._entities_by_name = entities_by_name or {}

    def insert_memory(self, data: dict) -> int:
        mid = self._next
        self._next += 1
        self.memories.append({**data, "id": mid})
        return mid

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict]:
        return self._existing_by_tag.get(tag, [])

    def get_entity_by_name(self, name: str) -> dict | None:
        return self._entities_by_name.get(name)

    def insert_relationship(self, data: dict) -> int:
        self.relationships.append(data)
        return len(self.relationships)

    def supersede_atomic(self, data: dict, target_id: int) -> tuple[int, int]:
        self.supersede_calls.append((data, target_id))
        new_id = self.insert_memory(data)
        return new_id, target_id


class _NoSupersedeStore(_FakeStore):
    """A store whose supersede_atomic bounded-rebase exhausted — mirrors
    supersede_atomic's own documented (None, last_head_id) contention
    return, exercised without needing real concurrency."""

    def supersede_atomic(self, data: dict, target_id: int) -> tuple[None, int]:
        return None, target_id


class TestDocTag:
    def test_deterministic_and_scoped_to_domain_and_path(self):
        assert doc_tag("code:proj", "docs/a.md") == "ap-doc:code:proj:docs/a.md"
        assert doc_tag("code:proj", "docs/a.md") != doc_tag("code:other", "docs/a.md")


class TestFindExistingDocMemory:
    def test_returns_none_when_no_prior_memory(self):
        store = _FakeStore()
        assert find_existing_doc_memory(store, "code:proj", "README.md") is None

    def test_returns_record_when_tag_present(self):
        tag = doc_tag("code:proj", "README.md")
        store = _FakeStore(existing_by_tag={tag: [{"id": 42, "tags": ["doc", tag]}]})
        found = find_existing_doc_memory(store, "code:proj", "README.md")
        assert found is not None
        assert found["id"] == 42

    def test_degrades_to_none_when_store_lacks_tag_query(self):
        class _NoTagStore:
            pass

        assert find_existing_doc_memory(_NoTagStore(), "code:proj", "README.md") is None

    def test_superseded_row_is_skipped_head_is_returned(self):
        """A tag lands on every row in a supersession chain (issue #381) —
        the OLD, superseded row must never be picked over its live head,
        or a re-ingest would keep comparing against a retracted snapshot."""
        tag = doc_tag("code:proj", "README.md")
        store = _FakeStore(
            existing_by_tag={
                tag: [
                    {"id": 99, "tags": ["doc", tag], "superseded_by_id": None},
                    {"id": 42, "tags": ["doc", tag], "superseded_by_id": 99},
                ]
            }
        )
        found = find_existing_doc_memory(store, "code:proj", "README.md")
        assert found is not None
        assert found["id"] == 99


class TestReadDocContent:
    def test_reads_utf8_content(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# Hello\n", encoding="utf-8")
        content = read_doc_content(tmp_path, "README.md")
        assert content == "# Hello\n"

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert read_doc_content(tmp_path, "nope.md") is None

    def test_oversized_file_is_skipped_not_read(self, tmp_path: Path):
        big = tmp_path / "big.md"
        big.write_bytes(b"x" * (MAX_DOC_BYTES + 1))
        assert read_doc_content(tmp_path, "big.md") is None

    def test_file_exactly_at_cap_is_read(self, tmp_path: Path):
        exact = tmp_path / "exact.md"
        exact.write_bytes(b"x" * MAX_DOC_BYTES)
        assert read_doc_content(tmp_path, "exact.md") is not None

    def test_undecodable_bytes_return_none_not_raise(self, tmp_path: Path):
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\xff\xfe\x00\x01\x02")
        assert read_doc_content(tmp_path, "bad.md") is None


class TestWriteDocMemory:
    def test_writes_content_tagged_doc_and_src_ap(self):
        store = _FakeStore()
        mem_id, written, superseded = write_doc_memory(
            store, "code:proj", "/repo", "docs/a.md", "distinctive phrase here"
        )
        assert written is True
        assert superseded is False
        record = store.memories[0]
        assert "doc" in record["tags"]
        assert "src:ap" in record["tags"]
        assert doc_tag("code:proj", "docs/a.md") in record["tags"]
        assert "distinctive phrase here" in record["content"]
        assert record["domain"] == "code:proj"
        assert record["directory_context"] == "/repo"
        assert record["is_protected"] is False

    def test_first_capture_stamps_provenance_hash_and_path_tags(self):
        """Issue #381: a fresh doc memory carries a decidable revision stamp
        (content hash) and a structured source-path tag, not just the
        free-text `[{rel_path}]` header."""
        store = _FakeStore()
        content = "distinctive phrase here"
        write_doc_memory(store, "code:proj", "/repo", "docs/a.md", content)
        record = store.memories[0]
        assert doc_hash_tag(doc_content_hash(content)) in record["tags"]
        assert "doc-path:docs/a.md" in record["tags"]

    def test_reingesting_unchanged_doc_is_a_no_op(self):
        content = "content"
        tag = doc_tag("code:proj", "docs/a.md")
        existing = {
            "id": 555,
            "tags": ["doc", tag, doc_hash_tag(doc_content_hash(content))],
            "superseded_by_id": None,
        }
        store = _FakeStore(existing_by_tag={tag: [existing]})
        mem_id, written, superseded = write_doc_memory(
            store, "code:proj", "/repo", "docs/a.md", content
        )
        assert written is False
        assert superseded is False
        assert mem_id == 555
        assert store.memories == []
        assert store.supersede_calls == []

    def test_reingesting_changed_doc_supersedes_the_stale_snapshot(self):
        """Root-cause fix (issue #381): the source file changed since
        capture -> the old snapshot's chain head is superseded, not left
        to be served indistinguishably from current content."""
        tag = doc_tag("code:proj", "docs/a.md")
        existing = {
            "id": 555,
            "tags": ["doc", tag, doc_hash_tag(doc_content_hash("old content"))],
            "superseded_by_id": None,
        }
        store = _FakeStore(existing_by_tag={tag: [existing]})
        mem_id, written, superseded = write_doc_memory(
            store, "code:proj", "/repo", "docs/a.md", "new content"
        )
        assert written is True
        assert superseded is True
        assert mem_id != 555
        assert len(store.supersede_calls) == 1
        assert store.supersede_calls[0][1] == 555
        new_record = store.memories[0]
        assert "new content" in new_record["content"]
        assert doc_hash_tag(doc_content_hash("new content")) in new_record["tags"]

    def test_legacy_untagged_doc_memory_is_treated_as_changed_once(self):
        """A doc memory written before #381 carries no doc-sha256 tag —
        it must be re-verified (superseded) exactly once, converting it
        into a provenance-stamped snapshot, rather than being trusted
        forever just because a row with the dedup tag exists."""
        tag = doc_tag("code:proj", "docs/a.md")
        legacy = {"id": 555, "tags": ["doc", tag], "superseded_by_id": None}
        store = _FakeStore(existing_by_tag={tag: [legacy]})
        mem_id, written, superseded = write_doc_memory(
            store, "code:proj", "/repo", "docs/a.md", "content"
        )
        assert written is True
        assert superseded is True
        assert mem_id != 555

    def test_supersede_rebase_exhaustion_degrades_to_no_op(self):
        """supersede_atomic's own contract: (None, head_id) on bounded-rebase
        exhaustion under pathological contention. write_doc_memory must not
        raise or fabricate a memory id — it reports no write and lets the
        next ingest run retry from a fresh read."""
        tag = doc_tag("code:proj", "docs/a.md")
        existing = {
            "id": 555,
            "tags": ["doc", tag, doc_hash_tag(doc_content_hash("old"))],
            "superseded_by_id": None,
        }
        store = _NoSupersedeStore(existing_by_tag={tag: [existing]})
        mem_id, written, superseded = write_doc_memory(
            store, "code:proj", "/repo", "docs/a.md", "new"
        )
        assert written is False
        assert superseded is False
        assert mem_id == 555


class TestExistingContentHash:
    def test_extracts_hash_from_tag(self):
        h = doc_content_hash("some content")
        mem = {"tags": ["doc", doc_hash_tag(h)]}
        assert existing_content_hash(mem) == h

    def test_returns_none_when_tag_absent(self):
        assert existing_content_hash({"tags": ["doc"]}) is None
        assert existing_content_hash({}) is None


class TestWriteDocReferenceEdge:
    def test_writes_edge_when_both_endpoints_exist(self):
        store = _FakeStore(
            entities_by_name={
                "docs/a.md": {"id": 1},
                "docs/b.md": {"id": 2},
            }
        )
        written = write_doc_reference_edge(store, "docs/a.md", "docs/b.md")
        assert written is True
        assert store.relationships[0]["source_entity_id"] == 1
        assert store.relationships[0]["target_entity_id"] == 2
        assert store.relationships[0]["relationship_type"] == "references"

    def test_missing_endpoint_drops_edge_silently(self):
        store = _FakeStore(entities_by_name={"docs/a.md": {"id": 1}})
        written = write_doc_reference_edge(store, "docs/a.md", "docs/missing.md")
        assert written is False
        assert store.relationships == []
