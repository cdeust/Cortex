#!/usr/bin/env python3
"""Install Cortex hooks into ~/.claude/settings.json at user level.

Resolves the plugin root path at install time so hooks work without
relying on ${CLAUDE_PLUGIN_ROOT} substitution. Idempotent — safe to
run multiple times.

Usage:
    python3 scripts/install_hooks.py [--plugin-root /path/to/cortex]
    python3 scripts/install_hooks.py --uninstall
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_MARKER = "cortex-managed"


def _resolve_plugin_root() -> str:
    """Determine the plugin root directory."""
    import os

    # Explicit argument
    for i, arg in enumerate(sys.argv):
        if arg == "--plugin-root" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]

    # Environment variable (set by Claude Code for plugin hooks)
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if env_root and Path(env_root).is_dir():
        return env_root

    # Fall back to this script's location
    return str(Path(__file__).resolve().parent.parent)


def _build_hooks(root: str) -> dict:
    """Build the hooks config with resolved paths."""
    db_export = (
        'export DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cortex}";'
    )
    py_export = f'export PYTHONPATH="{root}";'
    cd_cmd = f'cd "{root}" &&'

    def cmd(module: str) -> str:
        return f"{db_export} {py_export} {cd_cmd} python3 -m {module}"

    return {
        "SessionStart": [
            {
                "matcher": _MARKER,
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            f"{db_export} {py_export} "
                            f"python3 -c 'import psycopg' 2>/dev/null || "
                            f'python3 -m pip install -q "psycopg[binary]>=3.1" "pgvector>=0.3" '
                            f'"sentence-transformers>=2.2.0" "flashrank>=0.2.0" 2>/dev/null; '
                            f"{cd_cmd} python3 -m mcp_server.hooks.session_start"
                        ),
                    }
                ],
            }
        ],
        "UserPromptSubmit": [
            {
                "matcher": _MARKER,
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.auto_recall"),
                        "timeout": 3,
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": _MARKER,
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.post_tool_capture"),
                    },
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.preemptive_context"),
                        "timeout": 3,
                    },
                ],
            }
        ],
        "SessionEnd": [
            {
                "matcher": _MARKER,
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.session_lifecycle"),
                        "timeout": 10,
                    }
                ],
            }
        ],
        "Notification": [
            {
                "matcher": "compaction",
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.compaction_checkpoint"),
                    }
                ],
            }
        ],
        "SubagentStart": [
            {
                "matcher": _MARKER,
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd("mcp_server.hooks.agent_briefing"),
                        "timeout": 5,
                    }
                ],
            }
        ],
    }


def _load_settings() -> dict:
    """Load settings.json, creating it if missing."""
    if _SETTINGS_PATH.exists():
        return json.loads(_SETTINGS_PATH.read_text())
    return {}


def _save_settings(settings: dict) -> None:
    """Write settings.json."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _remove_cortex_hooks(hooks: dict) -> dict:
    """Remove all cortex-managed hook entries."""
    cleaned = {}
    for event, entries in hooks.items():
        kept = [e for e in entries if e.get("matcher") != _MARKER]
        # Also remove entries whose commands reference mcp_server.hooks
        kept = [
            e
            for e in kept
            if not any(
                "mcp_server.hooks" in h.get("command", "") for h in e.get("hooks", [])
            )
        ]
        if kept:
            cleaned[event] = kept
    return cleaned


def install() -> None:
    """Install Cortex hooks to user settings."""
    root = _resolve_plugin_root()
    if not Path(root).is_dir():
        print(f"Error: plugin root not found: {root}", file=sys.stderr)
        sys.exit(1)

    settings = _load_settings()
    existing_hooks = settings.get("hooks", {})

    # Remove any existing Cortex hooks first
    cleaned = _remove_cortex_hooks(existing_hooks)

    # Merge new hooks
    new_hooks = _build_hooks(root)
    for event, entries in new_hooks.items():
        if event not in cleaned:
            cleaned[event] = []
        cleaned[event].extend(entries)

    settings["hooks"] = cleaned
    _save_settings(settings)

    hook_count = sum(
        len(e.get("hooks", [])) for entries in new_hooks.values() for e in entries
    )
    print(
        json.dumps(
            {
                "status": "installed",
                "plugin_root": root,
                "hooks_registered": hook_count,
                "events": list(new_hooks.keys()),
            }
        )
    )


def uninstall() -> None:
    """Remove Cortex hooks from user settings."""
    settings = _load_settings()
    existing_hooks = settings.get("hooks", {})
    cleaned = _remove_cortex_hooks(existing_hooks)
    settings["hooks"] = cleaned
    _save_settings(settings)
    print(json.dumps({"status": "uninstalled"}))


def main() -> None:
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()


if __name__ == "__main__":
    main()
