"""Discover the ai-automatised-pipeline MCP server and wire it into
Cortex's mcp-connections.json automatically.

Runs on SessionStart so users who have the pipeline installed get the
``codebase`` MCP server wired up without manual config editing. The
discovery mirrors ``cortex-doctor``'s optional-capability probe:

  1. Marketplace install (canonical): the AP plugin installed via
     ``claude plugin install`` — resolved from ``installed_plugins.json``
     the same way AP's own ``.mcp.json`` does. Always preferred so Cortex
     spawns the exact plugin the user installed (no symlink, no drift).
  2. Binaries on PATH: ``cortex-pipeline``, ``automatised-pipeline``,
     ``ai-automatised-pipeline``.
  3. Sibling git checkout at ``../anthropic/ai-automatised-pipeline``
     with a built Cargo release binary at
     ``target/release/automatised-pipeline``.
  4. Otherwise: no change to mcp-connections.json.

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
import sys
from pathlib import Path
from typing import Optional

from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json, write_json
from mcp_server.shared.platform import home_dir

logger = logging.getLogger(__name__)

# Binary name candidates on PATH, cheapest check first.
_BINARY_CANDIDATES = (
    "cortex-pipeline",
    "automatised-pipeline",
    "ai-automatised-pipeline",
)

# Common source-checkout locations. Relative to each user's working dir
# (the MCP server runs in the user's project root, so `..` is their
# parent directory — a common monorepo sibling layout).
_SOURCE_DIRS = (
    "../anthropic/ai-automatised-pipeline",
    "../../anthropic/ai-automatised-pipeline",
    "../ai-automatised-pipeline",
)

# Windows builds emit an .exe; list it first so it wins on NT. The
# extension-less name is the Linux/macOS artifact.
# source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.5
_BUILT_RELATIVE = (
    "target/release/automatised-pipeline.exe",
    "target/release/automatised-pipeline",
)

# ── Marketplace install (canonical) ─────────────────────────────────────

# The AP plugin installed via its marketplace. This is the SAME source AP's
# own .mcp.json resolves from: installed_plugins.json -> installPath ->
# target/release/automatised-pipeline. Preferring it means Cortex spawns the
# exact plugin the user installed — no self-built symlink, no version drift.
_INSTALLED_PLUGINS_PATH = home_dir() / ".claude" / "plugins" / "installed_plugins.json"
_AP_PLUGIN_KEY = "automatised-pipeline@automatised-pipeline-marketplace"
_AP_BINARY_RELATIVE = Path("target") / "release" / "automatised-pipeline"


def _marketplace_pipeline_binary() -> Optional[str]:
    """Resolve the AP binary from the marketplace install, or None.

    Mirrors AP's own ``.mcp.json``: read ``installed_plugins.json``, take the
    plugin's ``installPath``, and point at ``target/release/automatised-pipeline``.
    Returns None when AP isn't installed or its binary hasn't been
    materialised yet (``bin/ensure-binary.sh`` runs on AP's first launch).
    """
    try:
        data = read_json(_INSTALLED_PLUGINS_PATH) or {}
        entries = (data.get("plugins") or {}).get(_AP_PLUGIN_KEY) or []
        for entry in entries:
            install_path = entry.get("installPath")
            if not install_path:
                continue
            binary = Path(install_path) / _AP_BINARY_RELATIVE
            if binary.is_file() and os.access(binary, os.X_OK):
                return str(binary)
    except Exception as exc:  # noqa: BLE001 — plugin-registry probe; failure is logged, discovery reports not-installed
        logger.debug("AP plugin discovery failed (non-fatal): %s", exc)
        return None
    return None


# ── Install paths (shared with pipeline_installer) ──────────────────────

# Where the silent installer clones and builds the upstream source.
# Living next to other methodology artefacts means cleanup is one rm -rf.
_INSTALL_SRC_DIR = (
    home_dir() / ".claude" / "methodology" / "src" / "automatised-pipeline"
)
_INSTALL_BIN_DIR = home_dir() / ".claude" / "methodology" / "bin"
_INSTALL_SYMLINK = _INSTALL_BIN_DIR / "mcp-server"


def discover_pipeline_command() -> Optional[list[str]]:
    """Return [command, *args] for the pipeline MCP server, or None.

    None means "no pipeline found" — callers should leave the mcp
    config alone and let ingest_codebase fail with the standard
    McpConnectionError when invoked (ingestion is explicitly opt-in).

    Resolution order, canonical install first:
      1. Marketplace install (installed_plugins.json) — the plugin the
         user installed via ``claude plugin install``. Always preferred.
      2. Self-installed symlink / PATH / sibling source checkout —
         legacy fallbacks for users without the marketplace plugin.
    """
    # Canonical: the marketplace-installed AP plugin.
    marketplace = _marketplace_pipeline_binary()
    if marketplace:
        return [marketplace]

    # Legacy self-installed location.
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
            # NTFS doesn't store Unix exec bits — st_mode & 0o111 is always 0
            # on Windows, so the bit check would reject every valid binary.
            # source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.5
            if built.is_file() and (
                sys.platform == "win32" or built.stat().st_mode & 0o111
            ):
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
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.warning(
                "Failed to purge stale codebase entry from %s: %s", path, exc
            )

    # Auto-install path. If discovery fails, attempt a silent
    # git-clone + cargo build (and rustup bootstrap if cargo missing)
    # before giving up. Lazy import to avoid a module-load cycle —
    # pipeline_installer imports from this module.
    if command is None:
        from mcp_server.infrastructure.pipeline_installer import install_pipeline  # noqa: PLC0415 — import cycle with mcp_server.infrastructure.pipeline_installer; a top-level import fails at boot

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
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
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
