#!/usr/bin/env python3
"""Cortex hook migration — removes legacy hooks from ~/.claude/settings.json.

Hooks are now managed via .claude-plugin/plugin.json (Anthropic best practice).
Claude Code injects ${CLAUDE_PLUGIN_ROOT} and ${CLAUDE_PLUGIN_DATA} automatically.

This script only cleans up old cortex-managed entries from settings.json.
Run it once after upgrading from <3.4 to remove stale hooks.

Usage:
    python3 scripts/install_hooks.py           # Clean up legacy hooks
    python3 scripts/install_hooks.py --check   # Check if legacy hooks exist
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_MARKER = "cortex-managed"


def _load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        return json.loads(_SETTINGS_PATH.read_text())
    return {}


def _save_settings(settings: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _remove_cortex_hooks(hooks: dict) -> tuple[dict, int]:
    """Remove all cortex-managed hook entries. Returns cleaned hooks and count removed."""
    cleaned = {}
    removed = 0
    for event, entries in hooks.items():
        kept = []
        for e in entries:
            if e.get("matcher") == _MARKER:
                removed += 1
                continue
            if any("mcp_server.hooks" in h.get("command", "") for h in e.get("hooks", [])):
                removed += 1
                continue
            kept.append(e)
        if kept:
            cleaned[event] = kept
    return cleaned, removed


def main() -> None:
    settings = _load_settings()
    existing_hooks = settings.get("hooks", {})

    if "--check" in sys.argv:
        _, count = _remove_cortex_hooks(existing_hooks)
        if count > 0:
            print(json.dumps({"legacy_hooks_found": count, "action": "run without --check to clean up"}))
        else:
            print(json.dumps({"legacy_hooks_found": 0, "status": "clean"}))
        return

    cleaned, removed = _remove_cortex_hooks(existing_hooks)

    if removed == 0:
        print(json.dumps({"status": "clean", "message": "No legacy hooks found"}))
        return

    settings["hooks"] = cleaned
    _save_settings(settings)
    print(json.dumps({
        "status": "migrated",
        "removed": removed,
        "message": "Hooks now managed by .claude-plugin/plugin.json"
    }))


if __name__ == "__main__":
    main()
