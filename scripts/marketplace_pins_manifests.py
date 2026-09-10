"""Root-manifest version-split checks for the marketplace pin gate.

source: ADR-0755"""

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

    source: ADR-0755"""
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
