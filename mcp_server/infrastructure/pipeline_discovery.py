"""Discover the ai-automatised-pipeline MCP server and wire it into
Cortex's mcp-connections.json automatically.

Runs on SessionStart so users who have the pipeline installed get the
``codebase`` MCP server wired up without manual config editing. The
discovery mirrors ``cortex-doctor``'s optional-capability probe:

  1. Binaries on PATH: ``cortex-pipeline``, ``automatised-pipeline``,
     ``ai-automatised-pipeline``, ``ai-architect-mcp``.
  2. Sibling git checkout at ``../anthropic/ai-automatised-pipeline``
     with a built Cargo release binary at
     ``target/release/ai-architect-mcp``.
  3. Otherwise: no change to mcp-connections.json.

If the file already exists AND already has a ``codebase`` server entry,
we leave it alone — users who customized their config keep their
customization. We only write when the config is missing entirely OR
the ``codebase`` key is absent.

Source: user directive "detected and guided, not all users will have a
use of it". Pipeline is optional.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json, write_json

logger = logging.getLogger(__name__)

# Binary name candidates on PATH, cheapest check first.
_BINARY_CANDIDATES = (
    "cortex-pipeline",
    "automatised-pipeline",
    "ai-automatised-pipeline",
    "ai-architect-mcp",
)

# Common source-checkout locations. Relative to each user's working dir
# (the MCP server runs in the user's project root, so `..` is their
# parent directory — a common monorepo sibling layout).
_SOURCE_DIRS = (
    "../anthropic/ai-automatised-pipeline",
    "../../anthropic/ai-automatised-pipeline",
    "../ai-automatised-pipeline",
)

_BUILT_RELATIVE = ("target/release/ai-architect-mcp",)

# ── Install paths (shared with pipeline_installer) ──────────────────────

# Where the silent installer clones and builds the upstream source.
# Living next to other methodology artefacts means cleanup is one rm -rf.
_INSTALL_SRC_DIR = (
    Path.home() / ".claude" / "methodology" / "src" / "automatised-pipeline"
)
_INSTALL_BIN_DIR = Path.home() / ".claude" / "methodology" / "bin"
_INSTALL_SYMLINK = _INSTALL_BIN_DIR / "mcp-server"


def discover_pipeline_command() -> Optional[list[str]]:
    """Return [command, *args] for the pipeline MCP server, or None.

    None means "no pipeline found" — callers should leave the mcp
    config alone and let ingest_codebase fail with the standard
    McpConnectionError when invoked (ingestion is explicitly opt-in).
    """
    # Auto-installed location — preferred when present.
    if _INSTALL_SYMLINK.exists() and os.access(_INSTALL_SYMLINK, os.X_OK):
        return [str(_INSTALL_SYMLINK)]

    for name in _BINARY_CANDIDATES:
        path = shutil.which(name)
        if path:
            return [path]

    for source in _SOURCE_DIRS:
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            continue
        for rel in _BUILT_RELATIVE:
            built = root / rel
            if built.is_file() and built.stat().st_mode & 0o111:
                return [str(built)]

    return None


def ensure_pipeline_connection() -> dict:
    """Write the ``codebase`` entry into mcp-connections.json when absent.

    Returns a small audit dict describing what happened:
      action: "wrote_config" | "added_codebase" | "already_configured"
              | "no_pipeline_found"
      path:   path to the config file (always)
      binary: resolved pipeline binary path (when discovered)

    Idempotent. Safe to call every SessionStart.
    """
    path = Path(MCP_CONNECTIONS_PATH)
    command = discover_pipeline_command()
    existing = read_json(path) or {}

    existing_codebase = existing.get("servers", {}).get("codebase")
    if existing_codebase:
        configured_cmd = existing_codebase.get("command") or ""
        # Validate that the configured binary still exists. A user
        # may have rm-rf'd the install dir, deleted the symlink, or
        # moved the source repo. Stale entries silently break ingest;
        # purge them so the install path can re-run.
        if (
            configured_cmd
            and Path(configured_cmd).exists()
            and os.access(configured_cmd, os.X_OK)
        ):
            return {
                "action": "already_configured",
                "path": str(path),
                "binary": configured_cmd,
            }
        # Stale entry: drop it so the discovery+install path runs.
        # Other server entries (if any) are preserved.
        servers = dict(existing.get("servers") or {})
        servers.pop("codebase", None)
        existing = {**existing, "servers": servers}
        try:
            write_json(path, existing)
        except Exception as exc:
            logger.warning(
                "Failed to purge stale codebase entry from %s: %s", path, exc
            )

    # Auto-install path. If discovery fails, attempt a silent
    # git-clone + cargo build (and rustup bootstrap if cargo missing)
    # before giving up. Lazy import to avoid a module-load cycle —
    # pipeline_installer imports from this module.
    if command is None:
        from mcp_server.infrastructure.pipeline_installer import install_pipeline

        install_result = install_pipeline()
        if install_result.get("action") == "installed":
            command = discover_pipeline_command()

    if command is None:
        return {"action": "no_pipeline_found", "path": str(path)}

    # Merge into existing config (preserving other servers) or create fresh.
    config = dict(existing)
    servers = dict(config.get("servers") or {})
    servers["codebase"] = {
        "command": command[0],
        "args": command[1:],
        "env": {},
        # 0 = no per-call timeout; fresh-codebase indexing of large
        # trees can legitimately exceed any fixed bound. Liveness is
        # governed by the child process and explicit cancellation.
        "callTimeoutMs": 0,
    }
    config["servers"] = servers
    config.setdefault(
        "_comment",
        "Auto-generated by Cortex pipeline_discovery. Customize freely — "
        "Cortex only adds missing server entries, never overwrites.",
    )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, config)
    except Exception as exc:
        logger.warning("Failed to write %s: %s", path, exc)
        return {
            "action": "write_failed",
            "path": str(path),
            "binary": command[0],
            "error": str(exc),
        }

    return {
        "action": "wrote_config" if not existing else "added_codebase",
        "path": str(path),
        "binary": command[0],
    }
