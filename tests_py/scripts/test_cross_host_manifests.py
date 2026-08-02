"""Static contracts shared by the Gemini, Codex, and MCP registry surfaces."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text())


def test_gemini_extension_launches_the_published_stdio_entrypoint() -> None:
    server = _json("gemini-extension.json")["mcpServers"]["cortex"]
    assert server == {
        "command": "uvx",
        "args": ["--from", "hypermnesia-mcp[sqlite]", "hypermnesia-mcp"],
    }


def test_cross_host_manifest_versions_match_the_release() -> None:
    expected = _json("package.json")["version"]
    assert _json("gemini-extension.json")["version"] == expected
    assert _json("server.json")["version"] == expected
    assert _json("manifest.json")["version"] == expected
    assert _json(".claude-plugin/plugin.json")["version"] == expected
