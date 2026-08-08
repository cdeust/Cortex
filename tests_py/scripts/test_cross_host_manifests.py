"""Static contracts shared by the Gemini, Codex, and MCP registry surfaces."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

# Version-site cross-file agreement is scripts/check_version_surfaces.py's
# job (it is the single source of truth for every one of the 14 sites, not
# just the 5 this file used to hand-maintain its own list of) — imported
# rather than re-asserted here, so this file has one fewer place a new
# version site could be added and forgotten.
_spec = importlib.util.spec_from_file_location(
    "scripts.check_version_surfaces",
    REPO_ROOT / "scripts" / "check_version_surfaces.py",
)
_version_surfaces = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_version_surfaces)


def _json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text())


def test_gemini_extension_launches_the_published_stdio_entrypoint() -> None:
    server = _json("gemini-extension.json")["mcpServers"]["cortex"]
    assert server == {
        "command": "uvx",
        "args": ["--from", "hypermnesia-mcp[sqlite]", "hypermnesia-mcp"],
    }


def test_cross_host_manifest_versions_match_the_release() -> None:
    assert _version_surfaces.check_version_surfaces(_version_surfaces.read) == []
