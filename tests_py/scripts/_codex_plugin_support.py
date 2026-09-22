"""Shared paths and manifest-reading helpers for the Codex plugin contracts.

`test_codex_plugin_contract.py` and `test_codex_plugin_hooks_contract.py`
both read the same manifests and both need to find which hook module a
command dispatches to. That scan was written three times across the two
files while they were being split apart; it lives here once instead.

Follows the `_craftsmanship_support.py` precedent in this package: a real
module import, not a per-file `spec_from_file_location`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from mcp_server.hooks.entry import HOOK_MODULES

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin/plugin.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"
HOOKS_REF = "./hooks/hooks.json"
HOOKS_PATH = PLUGIN_ROOT / "hooks/hooks.json"
CLAUDE_PLUGIN_PATH = REPO_ROOT / ".claude-plugin/plugin.json"

# The console script mcp_server/hooks/entry.py backs (pyproject.toml). A Codex
# plugin ships only its own directory, so it can call neither this repository
# nor scripts/launcher.py.
HOOK_CONSOLE_SCRIPT = "hypermnesia-mcp-hook"
# How each host's manifest spells the module at the end of a hook command.
CODEX_SUFFIX = HOOK_CONSOLE_SCRIPT + " {module}'"
CLAUDE_SUFFIX = "mcp_server.hooks.{module}'"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def codex_hooks() -> dict:
    return read_json(HOOKS_PATH)["hooks"]


def claude_hooks() -> dict:
    return read_json(CLAUDE_PLUGIN_PATH)["hooks"]


def every_hook(hooks: dict) -> Iterator[tuple[str, dict, dict]]:
    """(event, entry, hook) for every command a hooks manifest declares."""
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry["hooks"]:
                yield event, entry, hook


def hook_index(hooks: dict, suffix: str) -> dict[str, tuple[str, dict, dict]]:
    """Allowlisted module -> (event, entry, hook) that dispatches to it.

    `suffix` is a `{module}` template because the two hosts spell the tail of
    the command differently. Modules outside HOOK_MODULES are ignored, so the
    result never claims a dispatch the console script would refuse.
    """
    return {
        module: (event, entry, hook)
        for event, entry, hook in every_hook(hooks)
        for module in HOOK_MODULES
        if hook["command"].endswith(suffix.format(module=module))
    }
