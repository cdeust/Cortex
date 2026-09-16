"""The advertised tool surface is read from the registries, not restated.

`scripts/verify_mcp_hosts.py` carried its own literal floor of 52 while the
surface moved to 54 (ADR-1066), and nothing noticed until the count reached
57 and broke that script's ceiling in CI (issue #597).

source: ADR-1077
"""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer

from mcp_server.__main__ import register_all
from mcp_server.tool_surface import UPSTREAM_TOOL_NAMES, standalone_tool_names


def _live(*, codebase: bool, prd: bool) -> set[str]:
    server = MCPServer(name="surface-test", version="0.0.0")
    register_all(server, codebase=codebase, prd=prd)
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_the_derived_surface_is_what_registers() -> None:
    assert standalone_tool_names() == _live(codebase=False, prd=False)


def test_the_upstream_names_are_exactly_the_gated_ones() -> None:
    gated = _live(codebase=True, prd=True) - _live(codebase=False, prd=False)

    assert gated == set(UPSTREAM_TOOL_NAMES)


def test_the_host_contract_bounds_follow_the_surface() -> None:
    from scripts.verify_mcp_hosts import full_tool_bounds

    minimum, maximum = full_tool_bounds()

    assert minimum == len(standalone_tool_names())
    assert maximum == minimum + len(UPSTREAM_TOOL_NAMES)


def test_the_docker_smoke_floor_follows_the_surface() -> None:
    """The last bare literal: a shell default nothing tied to the registries."""
    import pathlib
    import re

    script = pathlib.Path("scripts/docker_smoke.sh").read_text(encoding="utf-8")
    match = re.search(r'MIN_TOOL_COUNT="\$\{CORTEX_SMOKE_MIN_TOOLS:-(\d+)\}"', script)

    assert match, "docker_smoke.sh no longer declares MIN_TOOL_COUNT as expected"
    assert int(match.group(1)) == len(standalone_tool_names())


def test_the_verifier_imports_without_the_mcp_sdk() -> None:
    """The mcp-host-config CI job installs the host CLIs, not the SDK.

    Importing `mcp_server.tool_surface` at module scope pulled the SDK
    through the registries and broke that job (issue #597).
    """
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent("""
        import sys
        class Blocker:
            def find_module(self, name, path=None):
                blocked = name == "mcp" or name.startswith("mcp.")
                return self if blocked else None
            def load_module(self, name):
                raise ImportError(name)
        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, ".")
        import importlib
        importlib.import_module("scripts.verify_mcp_hosts")
        print("imported")
    """)

    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout
