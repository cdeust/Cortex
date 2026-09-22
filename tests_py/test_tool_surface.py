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
    """The mcp-host-config CI job installs the host CLIs, not the SDK.

    Importing `mcp_server.tool_surface` at module scope pulled the SDK
    through the registries and broke that job (issue #597).
    """
    result = subprocess.run(
        [sys.executable, "-c", _SDK_FREE_IMPORT_PROBE], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_the_sdk_less_job_never_binds_a_release_to_this_checkouts_bounds() -> None:
    """Importability is not enough: a full-profile case in the SDK-less job
    still *calls* `full_tool_bounds()` and dies on the same missing SDK.

    Codex stopped shipping a lean profile (PR #620), so mcp-host-config's
    codex-cli case had to move to `--profiles full`, and it broke that way.
    `--published-surface` is what keeps the call unreachable there, and it is
    correct beyond the SDK: that command resolves a released artifact whose
    surface is its own release's, not this checkout's (ADR-1077, revision
    2026-09-22).
    """
    import pathlib
    import re

    workflow = pathlib.Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  mcp-host-config:\n", 1)
    assert len(job) == 2, "the mcp-host-config job is no longer declared as expected"
    # Up to the next top-level job key.
    body = re.split(r"\n  [a-z][a-z-]*:\n", job[1], maxsplit=1)[0]

    # Per invocation, not over the whole job: a second --profiles full case
    # added later that legitimately needs no flag would otherwise satisfy a
    # job-wide substring check on behalf of the one that does need it.
    invocations = [
        # From the script name to the `--` that ends the flags.
        match.group(0)
        for match in re.finditer(
            r"verify_mcp_hosts\.py(?:[^\n]*\\\n)*[^\n]*", body, flags=re.MULTILINE
        )
    ]
    assert invocations, (
        "the job no longer drives the verifier; drop this test or re-point it"
    )
    for invocation in invocations:
        if "--profiles full" in invocation:
            assert "--published-surface" in invocation, (
                "this full-profile case in the SDK-less job must pass "
                "--published-surface, or it calls full_tool_bounds() and dies "
                f"on ModuleNotFoundError: No module named 'mcp':\n{invocation}"
            )
