"""Canonical identity of the upstream codebase-intelligence MCP server.

source: ADR-0622"""

from __future__ import annotations

from pathlib import Path

# source: ADR-0622
CANONICAL_REPO = "cdeust/ai-architect-mcp-codebase"
CANONICAL_PLUGIN = "ai-architect-mcp-codebase"
CANONICAL_MARKETPLACE = f"{CANONICAL_PLUGIN}-marketplace"
CANONICAL_PLUGIN_KEY = f"{CANONICAL_PLUGIN}@{CANONICAL_MARKETPLACE}"
CANONICAL_BINARY = "ai-architect-mcp-codebase"

# source: ADR-0622
LEGACY_PLUGIN_KEYS = ("automatised-pipeline@automatised-pipeline-marketplace",)
LEGACY_BINARIES = ("automatised-pipeline",)

PLUGIN_KEYS = (CANONICAL_PLUGIN_KEY, *LEGACY_PLUGIN_KEYS)
# source: ADR-0622
PLUGIN_KEY_BINARIES = (
    (CANONICAL_PLUGIN_KEY, CANONICAL_BINARY),
    *((key, LEGACY_BINARIES[0]) for key in LEGACY_PLUGIN_KEYS),
)
BINARY_NAMES = (CANONICAL_BINARY, *LEGACY_BINARIES)

# source: ADR-0622
ALLOWED_UPSTREAM_COMMANDS = frozenset(BINARY_NAMES)

RELEASES_LATEST_URL = f"https://api.github.com/repos/{CANONICAL_REPO}/releases/latest"
REPOSITORY_URL = f"https://github.com/{CANONICAL_REPO}"


def release_asset_name(os_tag: str, arch_tag: str) -> str:
    """Release tarball published by the producer for a platform."""
    return f"{CANONICAL_BINARY}-{os_tag}-{arch_tag}.tar.gz"


def built_binary_relatives() -> tuple[str, ...]:
    """target/release paths to try, canonical first, .exe first on NT.

    source: ADR-0622"""
    out: list[str] = []
    for name in BINARY_NAMES:
        out.append(str(Path("target") / "release" / f"{name}.exe"))
        out.append(str(Path("target") / "release" / name))
    return tuple(out)
