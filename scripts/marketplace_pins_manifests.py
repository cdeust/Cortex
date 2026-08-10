"""Root-manifest version-split checks for the marketplace pin gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Checks that
every root-level manifest carrying its own copy of the version (server.json,
manifest.json) agrees with the primary local marketplace pin — the guard
AP #172 was missing when manifest.json alone went stale for two releases.
"""

from __future__ import annotations

import json
from pathlib import Path

# One row per file: adding a manifest never adds a branch to the check
# below, which is what let manifest.json go unguarded for two releases
# when the check was hardcoded to server.json alone (AP #172).
ROOT_VERSION_MANIFESTS: tuple[tuple[str, str, str], ...] = (
    ("server.json", "version", "SERVER_JSON_SPLIT"),
    ("manifest.json", "version", "MANIFEST_JSON_SPLIT"),
)


def check_root_manifests(root: Path, primary_pin: str) -> list[str]:
    """Flag every root manifest whose version disagrees with the primary pin.

    An absent file is not a failure and neither is a missing version key: the
    canonical repo has no manifest.json, ai-architect-mcp-codebase has both, and a
    gate that demanded every row exist everywhere would be a false positive in
    one repo or the other rather than a guard in both.
    """
    failures: list[str] = []
    for filename, key, failure_class in ROOT_VERSION_MANIFESTS:
        path = root / filename
        if not path.is_file():
            continue
        version = json.loads(path.read_text()).get(key, "")
        if version and version != primary_pin:
            failures.append(
                f"{failure_class}: {filename} says {version} "
                f"but the primary marketplace pin is {primary_pin}"
            )
    return failures
