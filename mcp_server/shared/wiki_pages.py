"""Wiki page public API — parsing, templates, and index building.

source: ADR-0684"""

from __future__ import annotations

from mcp_server.shared.wiki_frontmatter import (
    PageDocument,
    parse_page,
    render_page,
)
from mcp_server.shared.wiki_index import build_index
from mcp_server.shared.wiki_page_builders import (
    ADR_STATUSES,
    build_adr,
    build_convention,
    build_file_doc,
    build_lesson,
    build_note,
    build_reference,
    build_spec,
    maturity_label,
)

__all__ = [
    "ADR_STATUSES",
    "PageDocument",
    "build_adr",
    "build_convention",
    "build_file_doc",
    "build_index",
    "build_lesson",
    "build_note",
    "build_reference",
    "build_spec",
    "maturity_label",
    "parse_page",
    "render_page",
]
