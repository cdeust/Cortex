"""Contract tests for the additive, isolated Codex plugin package."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_PATH = REPO_ROOT / ".agents/plugins/marketplace.json"
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin/plugin.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_codex_plugin_is_confined_to_a_dedicated_subdirectory() -> None:
    """Never reintroduce the project-scoped MCP collision in Claude Code."""
    assert not (REPO_ROOT / ".mcp.json").exists()
    assert not (REPO_ROOT / ".codex-plugin").exists()
    assert PLUGIN_PATH.is_file()
    assert MCP_PATH.is_file()

    ignored = (REPO_ROOT / ".mcpbignore").read_text().splitlines()
    assert ".agents/" in ignored
    assert "plugins/hypermnesia-mcp-codex/" in ignored
    assert "plugins/cortex-deprecated/" in ignored


def test_codex_marketplace_resolves_only_the_dedicated_plugin() -> None:
    marketplace = _json(MARKETPLACE_PATH)
    assert marketplace["name"] == "cortex-codex-plugins"
    assert len(marketplace["plugins"]) == 1

    entry = marketplace["plugins"][0]
    assert entry == {
        "name": "hypermnesia-mcp-codex",
        "source": {
            "source": "local",
            "path": "./plugins/hypermnesia-mcp-codex",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Developer Tools",
    }
    source = (REPO_ROOT / entry["source"]["path"]).resolve()
    assert source == PLUGIN_ROOT.resolve()
    assert source.is_relative_to(REPO_ROOT.resolve())


def test_codex_plugin_is_mcp_only_and_uses_the_exact_lean_profile() -> None:
    plugin = _json(PLUGIN_PATH)
    server = _json(MCP_PATH)["mcpServers"]["cortex"]

    assert plugin["name"] == "hypermnesia-mcp-codex"
    assert plugin["mcpServers"] == "./.mcp.json"
    for unsupported in ("hooks", "skills", "apps", "agents", "postInstall"):
        assert unsupported not in plugin

    assert server == {
        "command": "uvx",
        "args": [
            "--from",
            "hypermnesia-mcp[sqlite]",
            "hypermnesia-mcp",
            "--profile",
            "lean",
        ],
        # Measured clean-cache startup on 2026-08-02: 110.46s. This bounded
        # ceiling leaves startup headroom without inventing a sleep or retry.
        "startup_timeout_sec": 180,
    }


def test_codex_package_does_not_weaken_the_primary_claude_plugin() -> None:
    claude = _json(REPO_ROOT / ".claude-plugin/plugin.json")
    claude_server = claude["mcpServers"]["cortex"]

    assert claude["name"] == "hypermnesia-mcp"
    assert claude["hooks"]
    assert claude["agents"] == ["./claude-agents/cortex-wiki-groomer.md"]
    assert claude_server["command"] == "python3"
    assert claude_server["args"] == [
        "${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py",
        "mcp_server",
    ]
    assert "--profile" not in claude_server["args"]
