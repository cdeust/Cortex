"""The single composition-root wiring entry point for core/'s injection
seams (issue #560: core/ may not import os/pathlib or perform I/O).

Every core/ seam needs its real implementation wired before any core
function using it runs — wire_composition_root() wires all of them in
one place, idempotently. Every real entry point calls it exactly once:
mcp_server/__main__.py, scripts/launcher.py (the plugin-installed
server AND every hook route through it, ADR-0742), every hook script's
own ``if __name__ == "__main__":`` block (covers session_start.py's
documented fallback to a bare ``python -m mcp_server.hooks.X`` when
launcher.py is not found on disk), the test session
(tests_py/_composition_root_wiring.py), and every benchmark/script that
reaches core directly.

This module sits at the top level next to __main__.py and doctor.py, not
inside core/ or infrastructure/ — it may import both freely, which is
exactly the composition-root's job.

The wiki-root default (``WIKI_ROOT``) is the SAME real value in every
context, production or test: conftest.py redirects ``CORTEX_CLAUDE_DIR``
to an isolated throwaway directory before any mcp_server import, so
``WIKI_ROOT`` resolves under that directory during tests (no ``_schema/``
folder there, so behavior matches the historical "no override" default)
without a separate test-only code path.

source: issue #560
"""

from __future__ import annotations

from mcp_server.core.wiki_axis_registry import (
    configure_default_wiki_root,
    configure_schema_file_reader,
)
from mcp_server.core.wiki_coverage import configure_wiki_coverage_filesystem
from mcp_server.core.wiki_coverage_dashboard import configure_dashboard_filesystem
from mcp_server.core.wiki_drift import configure_wiki_drift_filesystem
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_axis_fs import read_schema_files
from mcp_server.infrastructure.wiki_coverage_fs import (
    domain_kind_membership,
    markdown_file_sizes,
    stat_page,
    walk_markdown_contents,
    walk_source_files,
)
from mcp_server.infrastructure.wiki_dashboard_fs import (
    count_curation_gaps_under,
    domain_dirs_under,
    kind_page_counts,
    wiki_root_is_dir,
    write_dashboard_pages,
)
from mcp_server.infrastructure.wiki_drift_fs import (
    iter_wiki_markdown_pages,
    read_wiki_page,
    source_file_exists_under,
    wiki_page_mtime,
)

_WIRED = False


def wire_composition_root() -> None:
    """Wire every core/ injection seam to its real implementation.

    Precondition: none.
    Postcondition: every seam this module knows about is configured;
    idempotent — a second call is a no-op, so every entry point can call
    this unconditionally without coordinating with any other caller.

    source: issue #560"""
    global _WIRED
    if _WIRED:
        return
    configure_default_wiki_root(lambda: str(WIKI_ROOT))
    configure_schema_file_reader(read_schema_files)
    configure_wiki_coverage_filesystem(
        stat_page=stat_page,
        markdown_file_sizes=markdown_file_sizes,
        domain_kind_membership=domain_kind_membership,
        walk_source_files=walk_source_files,
        walk_markdown_contents=walk_markdown_contents,
    )
    configure_wiki_drift_filesystem(
        read_page=read_wiki_page,
        page_mtime=wiki_page_mtime,
        file_exists_under=source_file_exists_under,
        iter_pages=iter_wiki_markdown_pages,
    )
    configure_dashboard_filesystem(
        count_curation_gaps=count_curation_gaps_under,
        kind_page_counts=kind_page_counts,
        domain_dirs_under=domain_dirs_under,
        wiki_root_is_dir=wiki_root_is_dir,
        write_dashboard_pages=write_dashboard_pages,
    )
    _WIRED = True
