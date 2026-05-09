"""Contract test for .mcp.json — the plugin↔Claude-Code interface.

Verifies the `.mcp.json` shape against the documented Claude Code plugin
contract. Source: https://code.claude.com/docs/en/plugins-reference,
section "Environment variables":

  > ${CLAUDE_PLUGIN_ROOT}: ... Both are substituted inline anywhere they
  > appear in skill content, agent content, hook commands, monitor
  > commands, and MCP or LSP server configs.

And the canonical example in the same reference:

  "plugin-database": {
    "command": "${CLAUDE_PLUGIN_ROOT}/servers/db-server",
    "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"],
    "env": { "DB_PATH": "${CLAUDE_PLUGIN_ROOT}/data" }
  }

Discord 2026-05-09: prior `.mcp.json` used a Python `-c` one-liner that
read ~/.claude/plugins/installed_plugins.json and execvp'd into the
launcher. Failure modes were silent because `python3 -c` swallowed stack
traces. The fix routes through the documented substitution mechanism.

This test guards against regression to the inline `-c` script (the
substitutability violation: the inline script imposed a STRONGER
precondition than the contract — it required a specific marketplace
key in installed_plugins.json, rejecting --plugin-dir / --plugin-url /
manual-install scenarios that the documented contract supports).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_JSON = REPO_ROOT / ".mcp.json"


@pytest.fixture(scope="module")
def mcp_config() -> dict:
    return json.loads(MCP_JSON.read_text())


def test_mcp_json_exists(mcp_config: dict) -> None:
    assert "mcpServers" in mcp_config
    assert "cortex" in mcp_config["mcpServers"]


def test_no_inline_python_c_wrapper(mcp_config: dict) -> None:
    """The `-c` wrapper is forbidden — it swallows launcher errors.

    Substitutability violation: the wrapper required a specific key in
    installed_plugins.json. Manual installs and --plugin-dir runs broke
    silently because python3 -c discarded the traceback.
    """
    args = mcp_config["mcpServers"]["cortex"]["args"]
    assert "-c" not in args, (
        "Detected `-c` inline script in .mcp.json args. This swallows "
        "launcher errors and breaks --plugin-dir / manual-install. "
        "Use ${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py instead."
    )


def test_args_use_claude_plugin_root_substitution(mcp_config: dict) -> None:
    """args[] must reference ${CLAUDE_PLUGIN_ROOT} per the documented contract.

    Per Claude Code plugin reference, MCP server `args[]` substrings of
    the form ${CLAUDE_PLUGIN_ROOT} are substituted inline before the
    process is spawned.
    """
    args = mcp_config["mcpServers"]["cortex"]["args"]
    joined = " ".join(args)
    assert "${CLAUDE_PLUGIN_ROOT}" in joined, (
        f"args[] must reference ${{CLAUDE_PLUGIN_ROOT}} for plugin path "
        f"resolution. Got: {args}"
    )


def test_launcher_path_referenced(mcp_config: dict) -> None:
    """The args must point at scripts/launcher.py with the mcp_server target."""
    args = mcp_config["mcpServers"]["cortex"]["args"]
    assert any("scripts/launcher.py" in a for a in args), (
        f"Expected scripts/launcher.py in args, got: {args}"
    )
    assert "mcp_server" in args, (
        f"Expected 'mcp_server' module target in args, got: {args}"
    )


def test_referenced_launcher_exists() -> None:
    """The substituted target must exist on disk so the spawn won't fail.

    This is the Liskov post-condition: after Claude Code substitutes
    ${CLAUDE_PLUGIN_ROOT}, the resulting absolute path must resolve to
    a real file. We verify by resolving against the repo root (which is
    what CLAUDE_PLUGIN_ROOT will be when this plugin is loaded).
    """
    launcher = REPO_ROOT / "scripts" / "launcher.py"
    assert launcher.is_file(), f"Launcher not found at {launcher}"


def test_command_is_python3(mcp_config: dict) -> None:
    """`command` must be a python interpreter; the contract requires the
    spawned process to be able to execute the launcher.py script.
    """
    cmd = mcp_config["mcpServers"]["cortex"]["command"]
    assert cmd in ("python3", "python"), f"Expected python3 (or python), got: {cmd!r}"
