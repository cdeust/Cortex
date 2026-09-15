"""The single composition-root wiring entry point for core/'s injection
seams (issue #560: core/ may not import os/pathlib or perform I/O).

Every core/ seam needs its real implementation wired before any core
function using it runs. wire_composition_root() wires all of them in one
place, idempotently, and every real process entry point calls it once:
mcp_server/__main__.py, scripts/launcher.py, every hook script's own
``if __name__ == "__main__":`` block, the test session
(tests_py/_composition_root_wiring.py), and every benchmark or script
that reaches core directly.

Why it lives in hooks/: the wiring must import both core/ and
infrastructure/, and hook processes must be able to import it. The layer
table (docs/module-inventory.md § Dependency Rules) lets hooks/ import
core and infrastructure but not handlers/ or a top-level module, so
hooks/ is the one layer every entry point can reach that may do this job.

The wiki-root default (``WIKI_ROOT``) is the same real value in every
context: conftest.py redirects ``CORTEX_CLAUDE_DIR`` to a throwaway
directory before any mcp_server import, so tests need no separate path.

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
