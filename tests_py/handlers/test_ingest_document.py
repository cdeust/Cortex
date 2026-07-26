"""Integration tests for the ingest_document handler (issue #192).

The pure parsers/normalizer are unit-tested elsewhere; here we drive the
composition root end-to-end against a fake store and a recording wiki-write
stub, exercising the read→parse→normalize→write wiring and every failure/
edge branch enumerated in the issue.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mcp_server.handlers import ingest_document
from mcp_server.handlers.ingest_document import _resolve_format

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class TestResolveFormat:
    def test_explicit_docx(self):
        assert _resolve_format(Path("x.txt"), "docx") == "docx"

    def test_explicit_confluence(self):
        assert _resolve_format(Path("x.txt"), "confluence") == "confluence-export"

    def test_auto_docx_by_extension(self):
        assert _resolve_format(Path("a.docx"), "auto") == "docx"

    @pytest.mark.parametrize("ext", [".xml", ".xhtml", ".html", ".htm"])
    def test_auto_confluence_by_extension(self, ext):
        assert _resolve_format(Path("a" + ext), "auto") == "confluence-export"

    def test_unknown_extension_returns_empty(self):
        assert _resolve_format(Path("a.txt"), "auto") == ""

    def test_extension_is_case_insensitive(self):
        assert _resolve_format(Path("A.DOCX"), "auto") == "docx"


class _FakeStore:
    def __init__(self):
        self.memories: list[dict] = []
        self._next = 1000
        self._by_tag: dict[str, list[dict]] = {}

    def insert_memory(self, data: dict) -> int:
        mid = self._next
        self._next += 1
        row = {**data, "id": mid}
        self.memories.append(row)
        for tag in data.get("tags", []):
            self._by_tag.setdefault(tag, []).append(row)
        return mid

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict]:
        return self._by_tag.get(tag, [])


class _RecordingWrite:
    def __init__(self):
        self.calls: list[tuple] = []

    async def __call__(
        self, root, rel_path, content, *, mode="create", tags=None, memory_ids=None
    ):
        self.calls.append((root, rel_path, content, mode, tags))
        return {"path": rel_path, "created": True, "bytes_written": len(content)}


@pytest.fixture
def wired(monkeypatch):
    store = _FakeStore()
    write = _RecordingWrite()
    monkeypatch.setattr(ingest_document, "_get_store", lambda: store)
    monkeypatch.setattr(ingest_document, "write_governed_page", write)
    return store, write


def _make_docx(path: Path, body: str) -> Path:
    xml = f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def _para(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


class TestDocxHappyPath:
    @pytest.mark.asyncio
    async def test_ingests_docx_end_to_end_exact_response(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(
            tmp_path / "spec.docx",
            _para("Spec", "Title") + _para("Intro", "Heading1") + _para("hello"),
        )
        out = await ingest_document.handler({"path": str(p)})
        # Exact key set — guards every response field name.
        assert set(out.keys()) == {
            "ingested",
            "idempotent_skip",
            "title",
            "source",
            "source_kind",
            "version",
            "wiki_path",
            "summary_memory_id",
            "section_count",
            "images_skipped",
            "notices",
        }
        assert out["ingested"] is True
        assert out["idempotent_skip"] is False
        assert out["title"] == "Spec"
        assert out["source"] == str(p)
        assert out["source_kind"] == "docx"
        assert out["wiki_path"] == "documents/spec.md"
        assert out["summary_memory_id"] == store.memories[0]["id"]
        assert out["section_count"] == 1
        assert out["images_skipped"] == 0
        assert out["notices"] == []
        assert len(out["version"]) == 16
        # The wiki write is invoked with the governed root, the slugged path,
        # replace mode, and provenance tags.
        from mcp_server.infrastructure.config import WIKI_ROOT

        assert len(write.calls) == 1
        root, rel, _content, mode, tags = write.calls[0]
        assert root == WIKI_ROOT
        assert rel == "documents/spec.md"
        assert mode == "replace"
        assert tags == ["document", "ingest", "docx"]
        # Every memory carries the source-kind provenance tag.
        assert "docx" in store.memories[0]["tags"]
        assert any("hello" in m["content"] for m in store.memories)

    @pytest.mark.asyncio
    async def test_written_memories_carry_domain_and_directory(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "d.docx", _para("H", "Heading1") + _para("body"))
        await ingest_document.handler({"path": str(p), "domain": "team"})
        assert store.memories[0]["domain"] == "team"
        assert store.memories[0]["directory_context"] == str(p.resolve().parent)

    @pytest.mark.asyncio
    async def test_default_domain_is_documents(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "d.docx", _para("H", "Heading1") + _para("body"))
        await ingest_document.handler({"path": str(p)})
        assert store.memories[0]["domain"] == "documents"

    @pytest.mark.asyncio
    async def test_title_override_reaches_parser(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "d.docx", _para("Real Heading", "Heading1"))
        out = await ingest_document.handler({"path": str(p), "title": "Custom Title"})
        assert out["title"] == "Custom Title"

    @pytest.mark.asyncio
    async def test_wiki_write_failure_sets_wiki_path_none_but_still_ingests(
        self, wired, tmp_path, caplog, monkeypatch
    ):
        store, _ = wired

        async def _failing_write(*a, **k):
            return {"error": "boom"}

        monkeypatch.setattr(ingest_document, "write_governed_page", _failing_write)
        p = _make_docx(tmp_path / "d.docx", _para("H", "Heading1") + _para("body"))
        out = await ingest_document.handler({"path": str(p)})
        assert out["ingested"] is True
        assert out["wiki_path"] is None
        # Memories are still written; the wiki failure is logged with the
        # failing page payload (exact message), not silently.
        assert store.memories
        msgs = [r.getMessage() for r in caplog.records]
        assert "ingest_document wiki write failed: {'error': 'boom'}" in msgs

    @pytest.mark.asyncio
    async def test_reingest_same_version_is_idempotent(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "a.docx", _para("A", "Heading1") + _para("body"))
        await ingest_document.handler({"path": str(p)})
        writes_after_first = len(write.calls)
        memories_after_first = len(store.memories)
        out = await ingest_document.handler({"path": str(p)})
        assert set(out.keys()) == {
            "ingested",
            "idempotent_skip",
            "reason",
            "summary_memory_id",
            "title",
            "version",
            "images_skipped",
            "notices",
        }
        assert out["ingested"] is True
        assert out["idempotent_skip"] is True
        assert out["reason"] == "already ingested at this version"
        # The skip response surfaces the ORIGINAL summary memory id, not None.
        assert out["summary_memory_id"] == store.memories[0]["id"]
        # No new wiki write, no new memory.
        assert len(write.calls) == writes_after_first
        assert len(store.memories) == memories_after_first


class TestConfluenceHappyPath:
    @pytest.mark.asyncio
    async def test_ingests_confluence_export(self, wired, tmp_path):
        store, write = wired
        p = tmp_path / "page.xml"
        p.write_text("<h1>Onboarding</h1><p>welcome&nbsp;aboard</p>", encoding="utf-8")
        out = await ingest_document.handler({"path": str(p)})
        assert out["ingested"] is True
        assert out["source_kind"] == "confluence-export"
        assert out["title"] == "Onboarding"

    @pytest.mark.asyncio
    async def test_confluence_title_override_reaches_parser(self, wired, tmp_path):
        store, write = wired
        p = tmp_path / "page.xml"
        p.write_text("<h1>Real Heading</h1><p>x</p>", encoding="utf-8")
        out = await ingest_document.handler({"path": str(p), "title": "Custom"})
        assert out["title"] == "Custom"


class TestImagesSkipped:
    @pytest.mark.asyncio
    async def test_image_skip_notice_surfaced(self, wired, tmp_path):
        store, write = wired
        body = (
            _para("H", "Heading1") + _para("x") + "<w:p><w:r><w:drawing/></w:r></w:p>"
        )
        p = _make_docx(tmp_path / "img.docx", body)
        out = await ingest_document.handler({"path": str(p)})
        assert out["images_skipped"] == 1
        assert any("image" in n for n in out["notices"])


class TestEmptyDocument:
    @pytest.mark.asyncio
    async def test_empty_docx_ingested_with_notice(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "empty.docx", "")
        out = await ingest_document.handler({"path": str(p)})
        assert out["ingested"] is True
        assert out["section_count"] == 0
        assert any("no extractable text" in n for n in out["notices"])


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_no_path_is_exact_error(self, wired):
        out = await ingest_document.handler({})
        assert out == {"ingested": False, "reason": "path is required"}

    @pytest.mark.asyncio
    async def test_unsupported_format_exact_reason(self, wired, tmp_path):
        p = tmp_path / "notes.txt"
        p.write_text("hi", encoding="utf-8")
        out = await ingest_document.handler({"path": str(p)})
        assert out == {
            "ingested": False,
            "reason": "unsupported document format for notes.txt "
            "(expected .docx or a Confluence .xml/.xhtml/.html export)",
        }

    @pytest.mark.asyncio
    async def test_malformed_zip_writes_nothing(self, wired, tmp_path):
        store, write = wired
        bad = tmp_path / "corrupt.docx"
        bad.write_bytes(b"not a zip at all")
        out = await ingest_document.handler({"path": str(bad)})
        assert out["ingested"] is False
        assert out["reason"] == "document_read_failed"
        assert set(out.keys()) == {"ingested", "reason", "error"}
        assert "cannot open docx" in out["error"]  # the real exception text
        # Loud failure, no partial write.
        assert write.calls == []
        assert store.memories == []

    @pytest.mark.asyncio
    async def test_malformed_xml_writes_nothing(self, wired, tmp_path):
        store, write = wired
        p = _make_docx(tmp_path / "bad.docx", "")
        # Overwrite the main part with malformed XML.
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", "<w:document><w:body><unclosed>")
        out = await ingest_document.handler({"path": str(p)})
        assert out["ingested"] is False
        assert out["reason"] == "document_parse_failed"
        assert set(out.keys()) == {"ingested", "reason", "error"}
        assert "malformed docx XML" in out["error"]
        assert write.calls == []
        assert store.memories == []

    @pytest.mark.asyncio
    async def test_explicit_format_override(self, wired, tmp_path):
        store, write = wired
        # A .txt file whose content is Confluence XHTML, forced via format.
        p = tmp_path / "page.txt"
        p.write_text("<h1>Forced</h1><p>body</p>", encoding="utf-8")
        out = await ingest_document.handler({"path": str(p), "format": "confluence"})
        assert out["ingested"] is True
        assert out["title"] == "Forced"
