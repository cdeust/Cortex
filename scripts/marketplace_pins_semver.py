"""Semver parsing + local git-tag helpers for the marketplace pin gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Offline, reads
git only — the PIN_BEHIND_TAG detection path (AP #67) depends on this
staying dependency-free of the network-facing modules.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Bare sibling import (not a package-relative one): this file is loaded
# both as a plain script-directory module (`python3 scripts/check_...py`,
# where Python puts scripts/ on sys.path[0] automatically) and, in tests,
# via `importlib.util.spec_from_file_location` from a different cwd — same
# idiom as craftsmanship_rules.py's sibling-import bootstrap.
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from marketplace_pins_http import API_TIMEOUT_S  # noqa: E402


def parse_semver(tag: str) -> tuple[int, ...] | None:
    """'v2.34.0' / '2.34.0' -> (2, 34, 0); None when not semver."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def local_semver_tags(
    root: Path, run=subprocess.run
) -> list[tuple[tuple[int, ...], str]]:
    """Every (parsed_version, raw_tag) pair in this repo; [] on no tags/not a repo."""
    proc = run(
        ["git", "-C", str(root), "tag", "--list"],
        capture_output=True,
        text=True,
        timeout=API_TIMEOUT_S,
    )
    if proc.returncode != 0:
        return []
    return [(v, t) for t in proc.stdout.split() if (v := parse_semver(t))]


def latest_local_tag(root: Path, run=subprocess.run) -> str | None:
    """Highest semver tag in this repo, or None (no tags / not a repo)."""
    parsed = local_semver_tags(root, run)
    return max(parsed)[1] if parsed else None


def tags_between(root: Path, pin: tuple, latest: tuple, run=subprocess.run) -> int:
    parsed = local_semver_tags(root, run)
    return sum(1 for v, _ in parsed if pin < v <= latest)
