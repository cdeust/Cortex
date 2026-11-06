"""ingest_document reports each embedded image it did not ingest (issue #732).

The parsers inventory every image with its reference and section; the handler
returns that inventory under ``attachments`` beside the ``images_skipped`` count,
so a caller sees which image of which section was left out instead of a bare
number.
"""

from __future__ import annotations

import json

import pytest

from mcp_server.handlers import ingest_document
from tests_py.handlers.test_ingest_document import (  # noqa: F401 (fixture)
    _make_docx,
    _para,
    wired,
)

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _drawing(rid: str) -> str:
    blip = f'<a:blip xmlns:a="{_A}" xmlns:r="{_R}" r:embed="{rid}"/>'
    return f"<w:p><w:r><w:drawing>{blip}</w:drawing></w:r></w:p>"


@pytest.mark.asyncio
async def test_image_skip_notice_surfaced(wired, tmp_path):  # noqa: F811
    body = _para("H", "Heading1") + _para("x") + "<w:p><w:r><w:drawing/></w:r></w:p>"
    p = _make_docx(tmp_path / "img.docx", body)
    out = await ingest_document.handler({"path": str(p)})
    assert out["images_skipped"] == 1
    assert any("image" in n for n in out["notices"])


@pytest.mark.asyncio
async def test_each_skipped_image_is_named_with_its_section(wired, tmp_path):  # noqa: F811
    body = (
        _para("Design", "Heading1")
        + _drawing("rId7")
        + _para("Rollout", "Heading1")
        + _para("y")
        + "<w:p><w:r><w:drawing/></w:r></w:p>"
    )
    p = _make_docx(tmp_path / "two.docx", body)
    out = await ingest_document.handler({"path": str(p)})
    assert out["images_skipped"] == 2
    assert out["section_headings"] == ["Design", "Rollout"]
    assert out["attachments"] == [
        {
            "ordinal": 1,
            "reference": "rId7",
            "section_index": 0,
            "state": "unsupported",
        },
        {
            "ordinal": 2,
            "reference": "",
            "section_index": 1,
            "state": "unsupported",
        },
    ]


@pytest.mark.asyncio
async def test_a_document_without_images_reports_none(wired, tmp_path):  # noqa: F811
    p = _make_docx(tmp_path / "plain.docx", _para("H", "Heading1") + _para("x"))
    out = await ingest_document.handler({"path": str(p)})
    assert (out["images_skipped"], out["attachments"]) == (0, [])


@pytest.mark.asyncio
async def test_a_long_heading_is_not_copied_once_per_image(wired, tmp_path):  # noqa: F811
    heading = "H" * 5000
    body = _para(heading, "Heading1") + "<w:p><w:r><w:drawing/></w:r></w:p>" * 50
    p = _make_docx(tmp_path / "many.docx", body)
    out = await ingest_document.handler({"path": str(p)})
    assert out["images_skipped"] == 50
    assert {a["section_index"] for a in out["attachments"]} == {0}
    assert heading not in json.dumps(out["attachments"])
