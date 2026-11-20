"""The response of a governed wiki write, field by field.

``write_governed_page`` reports the page it wrote and what its citation step
recorded; ``write_page`` writes ``mode`` ``create`` when none is given. Pinned
on the fidelity fakes of ``test_wiki_write_citations.py``.

source: ADR-0475; issue #715 (mutation gate of the retraction-frontier change)
"""

from __future__ import annotations

from mcp_server.handlers import wiki_write
from tests_py.handlers import test_wiki_write_citations as base

_run = base._run
# the fixtures of the base module, under the names the tests below request
tmp_wiki = base.tmp_wiki
wired_pg = base.wired_pg


def test_a_write_reports_its_page_and_creates_by_default(tmp_wiki, wired_pg) -> None:
    content = "# A\n\nBody.\n"
    out = _run(wiki_write.write_governed_page(tmp_wiki, "reference/a.md", content))
    assert out == {
        "path": "reference/a.md",
        "mode": "create",
        "created": True,
        "bytes_written": len(content.encode("utf-8")),
        "root": str(tmp_wiki),
        "citations_written": 0,
    }
