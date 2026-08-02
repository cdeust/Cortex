"""Contract test for the plugin MCP server config — the plugin↔Claude-Code interface.

Verifies the inline `mcpServers` object in `.claude-plugin/plugin.json`
against the documented Claude Code plugin contract.
Source: https://code.claude.com/docs/en/plugins-reference,
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

History of this contract:

Discord 2026-05-09: prior config used a Python `-c` one-liner that
read ~/.claude/plugins/installed_plugins.json and execvp'd into the
launcher. Failure modes were silent because `python3 -c` swallowed stack
traces. The fix routes through the documented substitution mechanism.

2026-06-12: the config moved from a repo-root `.mcp.json` (referenced by
plugin.json as "./.mcp.json") to an inline object in plugin.json. Reason:
Claude Code ALSO interprets a repo-root `.mcp.json` as PROJECT-scoped MCP
config when the plugin source repo itself is opened as a working
directory. In project scope `${CLAUDE_PLUGIN_ROOT}` is never substituted
(it is plugin-scope only), so the spawn ran
`python3 '<repo>/${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py'` → ENOENT →
"MCP error -32000: Connection closed" on every session in this repo,
shadowing the healthy plugin-scoped server. Inline plugin.json
`mcpServers` is documented and is invisible to project-scope discovery.

This test guards against regression to either failure mode: the inline
`-c` script (substitutability violation: it imposed a STRONGER
precondition than the contract — a specific marketplace key in
installed_plugins.json) and the reintroduction of a repo-root
`.mcp.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
CLAUDE_AGENT_DIR = REPO_ROOT / "claude-agents"


@pytest.fixture(scope="module")
def mcp_config() -> dict:
    manifest = json.loads(PLUGIN_JSON.read_text())
    return manifest["mcpServers"]


def test_mcp_servers_inline_object(mcp_config: dict) -> None:
    """`mcpServers` must be an inline object, not a path string.

    A path string ("./.mcp.json") requires a repo-root `.mcp.json`,
    which Claude Code double-interprets as project-scoped config when
    the plugin source repo is the working directory (see module
    docstring, 2026-06-12).
    """
    assert isinstance(mcp_config, dict), (
        f"mcpServers must be an inline object, got: {type(mcp_config).__name__}"
    )
    assert "cortex" in mcp_config


def test_no_repo_root_mcp_json() -> None:
    """A repo-root `.mcp.json` must not exist.

    Claude Code picks it up as PROJECT-scoped MCP config in this repo,
    where ${CLAUDE_PLUGIN_ROOT} is never substituted — the spawn fails
    with -32000 and shadows the healthy plugin-scoped server.
    """
    assert not (REPO_ROOT / ".mcp.json").exists(), (
        "Repo-root .mcp.json reintroduced — it double-registers as "
        "project-scoped config with unsubstituted ${CLAUDE_PLUGIN_ROOT}. "
        "Keep the MCP server config inline in .claude-plugin/plugin.json."
    )


def test_no_inline_python_c_wrapper(mcp_config: dict) -> None:
    """The `-c` wrapper is forbidden — it swallows launcher errors.

    Substitutability violation: the wrapper required a specific key in
    installed_plugins.json. Manual installs and --plugin-dir runs broke
    silently because python3 -c discarded the traceback.
    """
    args = mcp_config["cortex"]["args"]
    assert "-c" not in args, (
        "Detected `-c` inline script in mcpServers args. This swallows "
        "launcher errors and breaks --plugin-dir / manual-install. "
        "Use ${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py instead."
    )


def test_args_use_claude_plugin_root_substitution(mcp_config: dict) -> None:
    """args[] must reference ${CLAUDE_PLUGIN_ROOT} per the documented contract.

    Per Claude Code plugin reference, MCP server `args[]` substrings of
    the form ${CLAUDE_PLUGIN_ROOT} are substituted inline before the
    process is spawned.
    """
    args = mcp_config["cortex"]["args"]
    joined = " ".join(args)
    assert "${CLAUDE_PLUGIN_ROOT}" in joined, (
        f"args[] must reference ${{CLAUDE_PLUGIN_ROOT}} for plugin path "
        f"resolution. Got: {args}"
    )


def test_launcher_path_referenced(mcp_config: dict) -> None:
    """The args must point at scripts/launcher.py with the mcp_server target."""
    args = mcp_config["cortex"]["args"]
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
    cmd = mcp_config["cortex"]["command"]
    assert cmd in ("python3", "python"), f"Expected python3 (or python), got: {cmd!r}"


def test_claude_only_agent_uses_custom_component_path() -> None:
    """Keep Claude's agent metadata out of Gemini's automatic agents/ scan.

    Claude accepts comma-delimited tool names and the ``haiku`` model alias;
    Gemini requires a YAML array and Gemini model identifier. The agent is a
    Claude plugin enhancement, not part of the host-neutral MCP contract, so
    the Claude manifest points to a custom directory instead of weakening or
    duplicating its configuration for other hosts.
    """
    manifest = json.loads(PLUGIN_JSON.read_text())
    assert manifest["agents"] == ["./claude-agents/cortex-wiki-groomer.md"]
    assert (CLAUDE_AGENT_DIR / "cortex-wiki-groomer.md").is_file()
    assert not any((REPO_ROOT / "agents").glob("*.md"))
