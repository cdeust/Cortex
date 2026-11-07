"""Centralized path constants for all filesystem locations.

All paths are absolute, derived from the Claude configuration root plus
constants. No I/O operations — only path construction.

Unset (the default for every production install), behavior is unchanged:
the root stays ``~/.claude``.

source: ADR-0514"""

from __future__ import annotations

import os
from pathlib import Path

_CLAUDE_DIR_OVERRIDE = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()

CLAUDE_DIR = (
    Path(_CLAUDE_DIR_OVERRIDE).expanduser()
    if _CLAUDE_DIR_OVERRIDE
    else Path.home() / ".claude"
)
# Claude Code writes its session transcripts under its configuration directory,
# ``$CLAUDE_CONFIG_DIR`` when set, else ``~/.claude`` (the same resolution as
# scripts/init_plugin.py ``data_dir``). ``CORTEX_CLAUDE_DIR`` still wins: it is
# the isolation seam that binds a test or sandboxed run to one throwaway tree.
# Only the transcript root follows the host variable; Cortex's own data stays
# under ``CLAUDE_DIR`` so setting it never relocates an existing store.
# source: issue #710 ("The profile code ignores the host's config-directory
# variable when locating transcripts.")
_HOST_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
CLAUDE_PROJECTS_DIR = (
    Path(_HOST_CONFIG_DIR).expanduser()
    if _HOST_CONFIG_DIR and not _CLAUDE_DIR_OVERRIDE
    else CLAUDE_DIR
) / "projects"
METHODOLOGY_DIR = CLAUDE_DIR / "methodology"
PROFILES_PATH = METHODOLOGY_DIR / "profiles.json"
SESSION_LOG_PATH = METHODOLOGY_DIR / "session-log.json"
BRAIN_INDEX_PATH = CLAUDE_DIR / "brain-index.json"
MCP_CONNECTIONS_PATH = METHODOLOGY_DIR / "mcp-connections.json"
WIKI_ROOT = METHODOLOGY_DIR / "wiki"
