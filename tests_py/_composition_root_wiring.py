"""Test-session composition-root wiring for core/'s injection seams that
production wires via mcp_server.hooks.wiring.wire_composition_root
(issue #560: core/ may not import os/pathlib). Kept out of conftest.py to
stay under its own 300-line cap (coding-standards.md §4).

Same function as production: WIKI_ROOT resolves under the isolated
$CORTEX_CLAUDE_DIR conftest.py already redirects before any mcp_server
import, so the test session sees the real resolution path with an empty
(no ``_schema/`` folder) directory -- behaviorally identical to the
historical "no override" default, without a separate test-only seam.
"""

from __future__ import annotations

from mcp_server.hooks.wiring import wire_composition_root

wire_composition_root()
