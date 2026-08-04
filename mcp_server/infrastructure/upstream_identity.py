"""Canonical identity of the upstream codebase-intelligence MCP server.

The producer was renamed twice — ``automatised-pipeline`` ->
``ai-architect-codebase`` -> ``ai-architect-mcp-codebase`` (canonical since
v0.9.0, 2026-08-04). Cortex resolves that server three different ways (release
asset, marketplace install, PATH lookup) and validates the resolved command
against a security allowlist, so the producer's names were hardcoded in five
modules. When the producer renamed its binary once before, only some of those
copies were updated; the pool allowlist was missed and every ingest failed with
"Command not in allowed list" (CHANGELOG 3.14.11). One copy per module is what
made that recurrence possible, so the names live here and nowhere else.

The producer publishes ``mcp-contract.json`` as the machine source of truth.
The values below mirror it and are verified against it in CI
(.github/workflows/upstream-identity.yml), pinned to a commit SHA rather than a
tag because the producer's README is explicit that tags can be moved:
https://raw.githubusercontent.com/cdeust/ai-architect-mcp-codebase/37728cc5747cebe39ea9d4011b7424de90f0a57b/mcp-contract.json

Legacy names are kept as *fallbacks*, never as the primary: installs predating
v0.9.0 still carry the old marketplace key on disk, and the producer still
ships an ``automatised-pipeline`` ``[[bin]]`` alias. That alias is explicitly
labelled "Compatibility alias only" upstream, so it is a bridge, not a contract.
"""

from __future__ import annotations

from pathlib import Path

# --- canonical (mcp-contract.json) -----------------------------------------
CANONICAL_REPO = "cdeust/ai-architect-mcp-codebase"
CANONICAL_PLUGIN = "ai-architect-mcp-codebase"
CANONICAL_MARKETPLACE = f"{CANONICAL_PLUGIN}-marketplace"
CANONICAL_PLUGIN_KEY = f"{CANONICAL_PLUGIN}@{CANONICAL_MARKETPLACE}"
CANONICAL_BINARY = "ai-architect-mcp-codebase"

# --- legacy, resolvable but never preferred --------------------------------
# Ordered oldest-last so the canonical name always wins a lookup.
LEGACY_PLUGIN_KEYS = ("automatised-pipeline@automatised-pipeline-marketplace",)
LEGACY_BINARIES = ("automatised-pipeline",)

PLUGIN_KEYS = (CANONICAL_PLUGIN_KEY, *LEGACY_PLUGIN_KEYS)
# Each plugin key's install ships its binary under target/release/<name>; the
# key and the binary renamed together, so they are paired rather than crossed.
PLUGIN_KEY_BINARIES = (
    (CANONICAL_PLUGIN_KEY, CANONICAL_BINARY),
    *((key, LEGACY_BINARIES[0]) for key in LEGACY_PLUGIN_KEYS),
)
BINARY_NAMES = (CANONICAL_BINARY, *LEGACY_BINARIES)

# Commands the upstream bridge may spawn. mcp_client validates a resolved
# command against this set by basename; omitting the canonical name here turns
# a correct resolution into "Command not in allowed list", which is exactly how
# the 3.14.11 regression presented.
ALLOWED_UPSTREAM_COMMANDS = frozenset(BINARY_NAMES)

RELEASES_LATEST_URL = f"https://api.github.com/repos/{CANONICAL_REPO}/releases/latest"
REPOSITORY_URL = f"https://github.com/{CANONICAL_REPO}"


def release_asset_name(os_tag: str, arch_tag: str) -> str:
    """Release tarball published by the producer for a platform."""
    return f"{CANONICAL_BINARY}-{os_tag}-{arch_tag}.tar.gz"


def built_binary_relatives() -> tuple[str, ...]:
    """target/release paths to try, canonical first, .exe first on NT.

    source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.5 — Windows builds emit
    an .exe; the extension-less name is the Linux/macOS artifact.
    """
    out: list[str] = []
    for name in BINARY_NAMES:
        out.append(str(Path("target") / "release" / f"{name}.exe"))
        out.append(str(Path("target") / "release" / name))
    return tuple(out)
