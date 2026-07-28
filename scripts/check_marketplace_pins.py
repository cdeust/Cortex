#!/usr/bin/env python3
"""Marketplace pin-staleness gate. CANONICAL COPY: cdeust/Cortex.

A byte-identical copy lives in cdeust/automatised-pipeline (its CI diffs
against this file weekly and fails on drift), so the gate is ONE artifact
guarding both repos — never two copies that diverge into a no-op.

Releasing does not ship: delivery is gated by pins in
``.claude-plugin/marketplace.json``. Six zetetic-team-subagents releases and
two cortex-viz releases were withheld silently (Cortex #179); AP's own
manifests sat a three-way split with its tag (AP #67). Failure classes:

  PIN_BEHIND_TAG       local-source pin < this repo's latest semver git tag.
                       Offline, reads git only — detects the #67 incident
                       even when every manifest agrees (they were BOTH stale).
  PIN_BEHIND_RELEASE   github-source pin < that repo's latest release.
  SELF_PIN_MISMATCH    local-source pin != the plugin's own plugin.json.
  SERVER_JSON_SPLIT    root server.json version != the primary local pin
                       (the unguarded third leg of AP's three-way split).

Network failures DEGRADE TO SILENCE (NOTICE + exit 0): a gate that reddens
every PR during a GitHub outage gets disabled, and then the six-release gap
recurs with the gate nominally in place. The offline path is tested.

Frozen pins: deliberately never-advancing pins (deprecation shims) are
listed in FROZEN_PINS with a reason — audited allowlist, not silence.

Exit codes: 0 current (or degraded, with NOTICE), 1 stale pin(s), 2 error.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MARKETPLACE = (
    Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
)
API_TIMEOUT_S = 15  # source: GitHub API p99 well below; matches prior gate rev
# source: audited 2026-07-25 (Cortex PR #182 review clause 5) — the `cortex`
# deprecation shim announces the hypermnesia-mcp rename and is frozen at the
# rename release by design; advancing it would defeat its purpose.
FROZEN_PINS = {"cortex": "deprecation shim, frozen at the 4.15.0 rename release"}


def parse_semver(tag: str) -> tuple[int, ...] | None:
    """'v2.34.0' / '2.34.0' -> (2, 34, 0); None when not semver."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def latest_local_tag(root: Path, run=subprocess.run) -> str | None:
    """Highest semver tag in this repo, or None (no tags / not a repo)."""
    proc = run(
        ["git", "-C", str(root), "tag", "--list"],
        capture_output=True,
        text=True,
        timeout=API_TIMEOUT_S,
    )
    if proc.returncode != 0:
        return None
    parsed = [(v, t) for t in proc.stdout.split() if (v := parse_semver(t))]
    return max(parsed)[1] if parsed else None


def tags_between(root: Path, pin: tuple, latest: tuple, run=subprocess.run) -> int:
    proc = run(
        ["git", "-C", str(root), "tag", "--list"],
        capture_output=True,
        text=True,
        timeout=API_TIMEOUT_S,
    )
    if proc.returncode != 0:
        return 0
    return sum(
        1 for t in proc.stdout.split() if (v := parse_semver(t)) and pin < v <= latest
    )


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "pin-gate"}
    if token := os.environ.get("GITHUB_TOKEN", ""):
        headers["Authorization"] = f"Bearer {token}"
    return headers


# source: RFC 9110 §15.5.5 — HTTP 404 Not Found
_HTTP_NOT_FOUND = 404


def latest_release_tag(repo: str) -> str | None:
    """Latest release tag; None when the repo has no releases (404)."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest", headers=_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            return json.load(resp).get("tag_name")
    except urllib.error.HTTPError as e:
        if e.code == _HTTP_NOT_FOUND:
            return None
        raise


def releases_between(repo: str, pin: tuple, latest: tuple) -> int | None:
    """Count releases with pin < tag <= latest; None when not determinable."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=100", headers=_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            releases = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return sum(
        1
        for r in releases
        if (v := parse_semver(r.get("tag_name", ""))) and pin < v <= latest
    )


def check_github_pin(
    name: str, repo: str, pin: str, fetch=latest_release_tag, count=releases_between
):
    """Returns (failure, notice) — exactly one is non-None or both None."""
    try:
        tag = fetch(repo)
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
    latest, pinned = parse_semver(tag), parse_semver(pin)
    if latest is None or pinned is None:
        return f"UNPARSEABLE: {name}: pin={pin!r} latest={tag!r}", None
    if pinned < latest:
        n = count(repo, pinned, latest)
        behind = f"{n} release(s)" if n is not None else "release(s)"
        return (
            f"PIN_BEHIND_RELEASE: {name}: pins {pin}, {repo} latest is {tag} "
            f"({behind} never delivered)",
            None,
        )
    return None, None


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
    tag = latest_local_tag(root)
    pinned = parse_semver(pin)
    if tag and pinned and (latest := parse_semver(tag)) and pinned < latest:
        n = tags_between(root, pinned, latest)
        failures.append(
            f"PIN_BEHIND_TAG: {name}: pins {pin} but this repo's latest tag is {tag} "
            f"({n} release(s) never delivered to installs)"
        )
    return failures


def check_server_json(root: Path, primary_pin: str) -> str | None:
    server = root / "server.json"
    if not server.is_file():
        return None
    version = json.loads(server.read_text()).get("version", "")
    if version and version != primary_pin:
        return (
            f"SERVER_JSON_SPLIT: server.json says {version} "
            f"but the primary marketplace pin is {primary_pin}"
        )
    return None


def main() -> int:
    if not MARKETPLACE.is_file():
        print(f"ERROR: {MARKETPLACE} not found", file=sys.stderr)
        return 2
    root = MARKETPLACE.parent.parent
    data = json.loads(MARKETPLACE.read_text())
    failures: list[str] = []
    notices: list[str] = []
    primary_pin = ""
    for plugin in data.get("plugins", []):
        name, pin, source = (
            plugin.get("name", "?"),
            plugin.get("version", ""),
            plugin.get("source"),
        )
        if not pin:
            continue
        if isinstance(source, dict) and source.get("source") == "github":
            failure, notice = check_github_pin(name, source["repo"], pin)
            if failure:
                failures.append(failure)
            if notice:
                notices.append(notice)
        elif isinstance(source, str):
            failures.extend(check_self_pin(name, source, pin, root))
            if source.strip("/") in ("", "."):
                primary_pin = pin
    if primary_pin and (split := check_server_json(root, primary_pin)):
        failures.append(split)
    for line in notices:
        print(line)
    for line in failures:
        print(line)
    if failures:
        print(
            f"\n{len(failures)} stale pin(s). A release is not shipped until "
            f"its pin moves — bump .claude-plugin/marketplace.json "
            f"(and server.json)."
        )
        return 1
    print(
        "All marketplace pins current."
        + (" (network-degraded checks noticed above)" if notices else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
