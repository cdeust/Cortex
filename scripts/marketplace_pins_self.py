"""Local-source (self-hosted-in-this-repo) pin checks for the marketplace gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Covers pins
shaped ``{"source": "./some/path", "version": ...}`` — a plugin whose code
lives in this repo, checked against this repo's own ``plugin.json`` and
git tags rather than a remote GitHub API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# See marketplace_pins_semver.py's identical bootstrap comment.
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from marketplace_pins_semver import local_semver_tags, parse_semver, tags_between  # noqa: E402

# source: audited 2026-07-25 (Cortex PR #182 review clause 5) and 2026-08-04
# (Cortex PR #351 Opus review) — each legacy identity is a notice-only shim
# frozen at its rename release; advancing one would hide the migration boundary.
FROZEN_PINS = {
    "cortex": "deprecation shim, frozen at the 4.15.0 rename release",
    "cortex-viz": "deprecation shim, frozen at the 2.8.0 pre-rename release",
}


def check_self_pin(name: str, source: str, pin: str, root: Path) -> list[str]:
    failures: list[str] = []
    plugin_json = root / source / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        plugin_json = root / source / "plugin.json"
    if plugin_json.is_file():
        actual = json.loads(plugin_json.read_text()).get("version", "")
        if actual and actual != pin:
            failures.append(
                f"SELF_PIN_MISMATCH: {name}: pins {pin} "
                f"but {plugin_json.relative_to(root)} says {actual}"
            )
    if name in FROZEN_PINS:
        # frozen: manifest coherence still checked, tag advance is by-design
        return failures
    parsed_tags = local_semver_tags(root)
    pinned = parse_semver(pin)
    if not parsed_tags or pinned is None:
        # no tags to compare against, or an unparseable pin: nothing to say
        return failures
    published = {v for v, _ in parsed_tags}
    latest_v, latest_tag = max(parsed_tags)
    if pinned not in published:
        failures.append(
            f"PIN_VERSION_UNPUBLISHED: {name}: pins {pin} but this repo has no "
            f"matching tag (latest tag is {latest_tag})"
        )
        return failures
    if pinned < latest_v:
        n = tags_between(root, pinned, latest_v)
        failures.append(
            f"PIN_BEHIND_TAG: {name}: pins {pin} but this repo's latest tag is "
            f"{latest_tag} ({n} release(s) never delivered to installs)"
        )
    return failures
