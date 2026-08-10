"""GitHub-source pin checks for the marketplace pin-staleness gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added). Covers pins
shaped ``{"source": "github", "repo": ..., "version": ..., "sha": ...}``:
does a release matching the pinned version exist at all
(PIN_VERSION_UNPUBLISHED), is it the latest one (PIN_BEHIND_RELEASE), and
is the optional pinned ``sha`` reachable from the repo's default branch
(PIN_SHA_UNREACHABLE). See check_marketplace_pins.py's module docstring
for the full failure-class catalogue and the incidents each one closes.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# See marketplace_pins_semver.py's identical bootstrap comment.
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from marketplace_pins_http import HTTP_NOT_FOUND, API_TIMEOUT_S, api_headers  # noqa: E402
from marketplace_pins_semver import parse_semver  # noqa: E402

# Same contract as PENDING_REGISTRY (marketplace_pins_registry.py): an
# entry here degrades a real PIN_VERSION_UNPUBLISHED finding to a named
# NOTICE while a committed, tracked fix is in flight — never a
# placeholder, never silent. Empty here because the one entry this gate
# needed (cdeust/cortex-viz#130) resolved within the same change that
# introduced the mechanism — merged, tagged v3.1.0, published to PyPI,
# verified 2026-08-10.
PENDING_PINS: dict[str, str] = {}


def list_release_tags(repo: str) -> list[str] | None:
    """Raw tag_name of every published release (<=100); None if repo has none (404).

    The full list, not just "latest": PIN_VERSION_UNPUBLISHED needs to test
    set-membership (does a tag matching the pin exist AT ALL), which a
    latest-only fetch cannot answer — a pin can be simultaneously "not the
    latest" AND "not published either", and only the full list tells them
    apart from "published but superseded".
    """
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=100",
        headers=api_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            releases = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == HTTP_NOT_FOUND:
            return None
        raise
    return [r.get("tag_name", "") for r in releases]


# source: GitHub REST "Compare two commits" — `status` is exactly one of
# ahead / behind / identical / diverged.
# https://docs.github.com/rest/commits/commits#compare-two-commits
#
# compare/BASE...HEAD describes HEAD relative to BASE. With BASE = the default
# branch, `identical` means the pin IS the branch tip and `behind` means it is
# an ancestor of it — both reachable. `ahead` and `diverged` mean the pin
# carries commits the branch does not: an unmerged PR head, which stops being
# reachable the moment that PR is squash-merged.
REACHABLE_FROM_DEFAULT = frozenset({"identical", "behind"})
SHA_DISPLAY_LEN = 12  # source: git's default core.abbrev floor for readable logs


def default_branch(repo: str) -> str | None:
    """Repo's default branch; None when the repo does not resolve (404)."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}", headers=api_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            return json.load(resp).get("default_branch")
    except urllib.error.HTTPError as e:
        if e.code == HTTP_NOT_FOUND:
            return None
        raise


def compare_status(repo: str, base: str, head: str) -> str | None:
    """Comparison status of head vs base; None when head does not resolve."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/compare/{base}...{head}",
        headers=api_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            return json.load(resp).get("status")
    except urllib.error.HTTPError as e:
        if e.code == HTTP_NOT_FOUND:
            return None
        raise


def check_pin_sha(
    name: str, repo: str, sha: str, branch=default_branch, compare=compare_status
):
    """Returns (failure, notice) — exactly one is non-None, or both are None."""
    try:
        base = branch(repo)
        if base is None:
            return (
                None,
                f"NOTICE: {name}: {repo} does not resolve; "
                f"pinned sha not verified this run",
            )
        status = compare(repo, base, sha)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return (
            None,
            f"NOTICE: {name}: network degraded ({e.__class__.__name__}); "
            f"pinned sha not verified this run",
        )
    short = sha[:SHA_DISPLAY_LEN]
    if status is None:
        return (
            f"PIN_SHA_UNREACHABLE: {name}: {repo} does not resolve commit {short} "
            f"(absent from the repository)",
            None,
        )
    if status not in REACHABLE_FROM_DEFAULT:
        return (
            f"PIN_SHA_UNREACHABLE: {name}: {repo}@{short} is '{status}' of "
            f"{base} — the pin targets a commit outside the default branch "
            f"(an unmerged PR head stops resolving once that PR is squashed)",
            None,
        )
    return None, None


def _check_unpublished_github_pin(
    name: str, repo: str, pin: str, latest_tag: str, pending: dict[str, str]
):
    """The PIN_VERSION_UNPUBLISHED branch of `check_github_pin`, split out to
    keep the caller under the §4.2 method-size cap. `pending` degrades this
    to a named NOTICE for a release genuinely in flight — never silence.
    """
    if name in pending:
        return (
            None,
            f"NOTICE: {name}: pins {pin}, no matching {repo} release yet "
            f"— PENDING: {pending[name]}",
        )
    return (
        f"PIN_VERSION_UNPUBLISHED: {name}: pins {pin} but {repo} has no "
        f"matching release (latest published is {latest_tag})",
        None,
    )


def _fetch_github_versions(name: str, repo: str, pin: str, list_tags):
    """Resolve `repo`'s releases into (parsed pin, [(version, raw_tag), ...]).

    Returns `(early_result, resolved)` — exactly one is None. `early_result`
    is a ready-to-return (failure, notice) pair for every terminal case that
    doesn't need the pin/latest comparison (network failure, no releases,
    nothing parses). Split out of `check_github_pin` to keep it under the
    §4.2 method-size cap.
    """
    try:
        tags = list_tags(repo)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        notice = (
            f"NOTICE: {name}: network degraded ({e.__class__.__name__}); "
            f"pin not verified this run"
        )
        return (None, notice), None
    if tags is None:
        notice = f"NOTICE: {name}: {repo} has no published releases; pin not comparable"
        return (None, notice), None
    pinned = parse_semver(pin)
    versions = [(v, t) for t in tags if (v := parse_semver(t))]
    if pinned is None:
        return (f"UNPARSEABLE: {name}: pin={pin!r}", None), None
    if not versions:
        latest_raw = tags[0] if tags else None
        return (f"UNPARSEABLE: {name}: pin={pin!r} latest={latest_raw!r}", None), None
    return None, (pinned, versions)


def check_github_pin(
    name: str,
    repo: str,
    pin: str,
    list_tags=list_release_tags,
    pending: dict[str, str] | None = None,
):
    """Returns (failure, notice) — exactly one is non-None or both None.

    Checks TWO independent properties, in order: (1) does a release matching
    the pin exist at all (PIN_VERSION_UNPUBLISHED if not), and only if it
    does, (2) is it the latest one (PIN_BEHIND_RELEASE if not).
    """
    if pending is None:
        pending = PENDING_PINS
    early_result, resolved = _fetch_github_versions(name, repo, pin, list_tags)
    if resolved is None:
        return early_result
    pinned, versions = resolved
    published = {v for v, _ in versions}
    latest_v, latest_tag = max(versions)
    if pinned not in published:
        return _check_unpublished_github_pin(name, repo, pin, latest_tag, pending)
    if pinned < latest_v:
        n = sum(1 for v, _ in versions if pinned < v <= latest_v)
        return (
            f"PIN_BEHIND_RELEASE: {name}: pins {pin}, {repo} latest is {latest_tag} "
            f"({n} release(s) never delivered)",
            None,
        )
    return None, None
