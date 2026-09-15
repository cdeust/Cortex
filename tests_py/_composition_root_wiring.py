"""Test-session composition-root wiring for core/'s injection seams that
production wires in mcp_server/__main__.py (issue #560: core/ may not
import os/pathlib). Kept out of conftest.py to stay under its own 300-line
cap (coding-standards.md §4).
"""

from __future__ import annotations

from mcp_server.core.wiki_axis_registry import configure_schema_file_reader
from mcp_server.core.wiki_coverage import configure_wiki_coverage_filesystem
from mcp_server.core.wiki_coverage_dashboard import configure_dashboard_filesystem
from mcp_server.core.wiki_drift import configure_wiki_drift_filesystem
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
