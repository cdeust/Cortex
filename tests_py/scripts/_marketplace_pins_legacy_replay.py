"""Frozen, verbatim copies of pre-fix check_marketplace_pins.py logic
(git blame: pre-e0661ad9), kept ONLY so the incident-replay tests in
test_check_marketplace_pins.py can prove the historical defect existed —
by executing the actual old code against the actual historical inputs —
rather than merely asserting it in prose. Split into its own file (issue:
test_check_marketplace_pins.py crossed the 300-line §4.1 cap once this
coverage was added).

Never call these outside a test, and never "fix" them — the whole point
is that they reproduce the bug.
"""

from __future__ import annotations

import json
import urllib.error
from typing import NamedTuple

from tests_py.scripts._marketplace_pins_test_loader import gate


class LegacyGithubFetchers(NamedTuple):
    """Bundles the two pre-fix `check_github_pin` injection points (§4.4:
    a 5th positional parameter on the function below would be a hard-rule
    violation even for a frozen historical copy — this is the parameter-
    object fix coding-standards.md §4.4 itself prescribes, not a
    behavioral change from the original).
    """

    fetch: object
    count: object


def pre_fix_check_github_pin(
    name: str, repo: str, pin: str, fetchers: LegacyGithubFetchers
):
    """Frozen, verbatim copy of `check_github_pin` as it existed BEFORE this
    change: only ever compared the pin to the *latest* known tag
    (`pinned < latest`), never checked whether a release matching the pin
    existed at all — the defect PIN_VERSION_UNPUBLISHED closes.
    """
    try:
        tag = fetchers.fetch(repo)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return (
            None,
            f"NOTICE: {name}: network degraded ({e.__class__.__name__}); "
            f"pin not verified this run",
        )
    if tag is None:
        return (
            None,
            f"NOTICE: {name}: {repo} has no published releases; pin not comparable",
        )
    latest, pinned = gate.parse_semver(tag), gate.parse_semver(pin)
    if latest is None or pinned is None:
        return f"UNPARSEABLE: {name}: pin={pin!r} latest={tag!r}", None
    if pinned < latest:
        n = fetchers.count(repo, pinned, latest)
        behind = f"{n} release(s)" if n is not None else "release(s)"
        return (
            f"PIN_BEHIND_RELEASE: {name}: pins {pin}, {repo} latest is {tag} "
            f"({behind} never delivered)",
            None,
        )
    return None, None


def pre_fix_check_self_pin(name: str, source: str, pin: str, root):
    """Frozen, verbatim copy of `check_self_pin` as it existed BEFORE this
    change — same rationale as `pre_fix_check_github_pin` above.

    The original referenced module-level `FROZEN_PINS` directly (a global,
    not a parameter — its real 4-parameter signature is reproduced exactly
    here); this frozen copy inlines an empty set since every caller uses a
    `name` that was never in FROZEN_PINS, so the branch's outcome is
    identical without needing a 5th parameter to inject one.
    """
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
    if name in frozenset():  # stands in for the real FROZEN_PINS global
        return failures
    tag = gate.latest_local_tag(root)
    pinned = gate.parse_semver(pin)
    if tag and pinned and (latest := gate.parse_semver(tag)) and pinned < latest:
        n = gate.tags_between(root, pinned, latest)
        failures.append(
            f"PIN_BEHIND_TAG: {name}: pins {pin} but this repo's latest tag is {tag} "
            f"({n} release(s) never delivered to installs)"
        )
    return failures
