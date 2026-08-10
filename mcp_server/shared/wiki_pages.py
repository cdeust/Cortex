"""Wiki page public API — parsing, templates, and index building.

Design intent: pages are *authored* content, not derived views. Templates
provide sensible sections; the body is whatever the caller passes in.

This module is the composed public entry point for wiki page handling. The
implementation is split across cohesive collaborators:

  * ``wiki_frontmatter`` — ``PageDocument``, ``parse_page``, ``render_page``
    (YAML-ish frontmatter parsing/rendering).
  * ``wiki_page_builders`` — ``build_adr``, ``build_spec``, ``build_note``,
    ``build_file_doc``, ``build_lesson``, ``build_convention``,
    ``build_reference``, and their shared maturity/sources helpers.
  * ``wiki_index`` — ``build_index`` (INDEX.md generation).

Every name importable from this module before the split remains importable
from here — this is the module's public contract, not a compat shim.
"""

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
