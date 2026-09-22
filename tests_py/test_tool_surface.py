"""The advertised tool surface is read from the registries, not restated.

`scripts/verify_mcp_hosts.py` carried its own literal floor of 52 while the
surface moved to 54 (ADR-1066), and nothing noticed until the count reached
57 and broke that script's ceiling in CI (issue #597).

source: ADR-1077
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap

import pytest

from mcp.server.mcpserver import MCPServer

from mcp_server.__main__ import register_all
from mcp_server.tool_surface import UPSTREAM_TOOL_NAMES, standalone_tool_names


# find_spec, not the pre-PEP 451 find_module/load_module pair: CPython
# ignores a finder that lacks find_spec, so a blocker written the old way
# blocks nothing and the test passes against the very commit that broke
# CI. Measured on 3.12 before this was corrected (#599 review).
_SDK_FREE_IMPORT_PROBE = textwrap.dedent("""
        import importlib
        import sys

        class Blocker:
            def find_spec(self, name, path=None, target=None):
                if name == "mcp" or name.startswith("mcp."):
                    raise ImportError(name)
                return None

        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, ".")
        try:
            import mcp  # the blocker must actually block
        except ImportError:
            pass
        else:
            raise AssertionError("the probe's blocker did not block the SDK")
        importlib.import_module("scripts.verify_mcp_hosts")
        print("imported")
    """)


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
    """The verifier can bootstrap before artifact dependencies are installed.

    Importing registries at module scope previously broke this boundary
    (issue #597); full candidate verification loads them only when needed.
    """
    result = subprocess.run(
        [sys.executable, "-c", _SDK_FREE_IMPORT_PROBE], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_candidate_job_installs_dependencies_and_checks_its_full_surface() -> None:
    """The candidate wheel supplies the SDK; exact checkout bounds must run."""
    import pathlib
    import re

    workflow = pathlib.Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  mcp-host-config:\n", 1)
    assert len(job) == 2
    body = re.split(r"\n  [a-z][a-z-]*:\n", job[1], maxsplit=1)[0]
    commands = body.replace("\\\n", " ")
    invocations = re.findall(
        r"uv run[^\n]*scripts/verify_mcp_hosts\.py[^\n]*", commands
    )
    assert invocations, "candidate verification must install its wheel dependencies"
    assert 'uv build --wheel --out-dir "$RUNNER_TEMP/cortex-codex-wheel"' in body
    for invocation in invocations:
        assert '--no-project --with "$candidate_wheel" -- env' in invocation
        assert 'UV_FIND_LINKS="$RUNNER_TEMP/cortex-codex-wheel"' in invocation
        assert "--profiles full" in invocation
        assert "--published-surface" not in invocation, (
            "candidate bounds cannot be bypassed"
        )
        assert "--artifact-surface" not in invocation, (
            "candidate bounds cannot be bypassed"
        )


def test_candidate_verifier_rejects_lean_only_discovery(tmp_path) -> None:
    """A candidate claiming full must fail when only the lean tools survive."""
    from mcp_server.tool_profiles import LEAN_TOOL_NAMES
    from scripts.mcp_host_client import ContractCase, ContractError
    from scripts.verify_mcp_hosts import _verify_tool_surface

    case = ContractCase("codex-cli", "full", (), tmp_path, 180, False, "auto")
    responses = {2: {"result": {"tools": [{"name": n} for n in LEAN_TOOL_NAMES]}}}
    with pytest.raises(ContractError, match="discovered .* full tools; expected"):
        _verify_tool_surface(case, responses, published=False)
    responses[2]["result"]["tools"] = [{"name": n} for n in standalone_tool_names()]
    assert _verify_tool_surface(case, responses, published=False) == len(
        standalone_tool_names()
    )
