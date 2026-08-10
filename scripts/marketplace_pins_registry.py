"""Public MCP registry cross-check for the marketplace pin-staleness gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once this module was added). The public MCP registry
(registry.modelcontextprotocol.io) is a THIRD version surface — independent
of the marketplace pin and PyPI — that server.json's own "name" field
names an entry for. Measured 2026-08-10: io.github.cdeust/hypermnesia-mcp
was published at 4.17.1 while the tag/server.json/PyPI were already at
4.17.2, invisible until queried directly (same failure shape as #179 and
PIN_VERSION_UNPUBLISHED — a mandatory per-release step that lived only in
prose, with nothing committed to run it or verify it happened).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# See marketplace_pins_semver.py's identical bootstrap comment.
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from marketplace_pins_http import HTTP_NOT_FOUND, API_TIMEOUT_S, api_headers  # noqa: E402

REGISTRY_API = "https://registry.modelcontextprotocol.io/v0/servers"

# Same contract as PENDING_PINS (marketplace_pins_github.py): an entry
# here degrades a real REGISTRY_VERSION_STALE finding to a named NOTICE
# while a committed, tracked fix is in flight — never a placeholder,
# never silent.
#
# One entry, not empty: the automated publish job
# (.github/workflows/release.yml::publish-mcp-registry, added in the same
# change as this check) only runs on a `v*` tag push. Merging this PR does
# not push a new tag, so the registry stays at 4.17.1 — a real, currently
# true gap, not a hypothetical one — until the next release tag runs that
# job. Publishing the missing 4.17.2 entry out of band requires a
# credential this agent does not hold (`mcp-publisher login` needs either
# an interactive GitHub OAuth browser flow or a personal access token) and
# was correctly refused when attempted; a maintainer with real
# credentials, or the next tagged release, closes this. Remove this entry
# once the registry serves >= the repo's authoritative version.
PENDING_REGISTRY: dict[str, str] = {
    "io.github.cdeust/hypermnesia-mcp": (
        "release.yml::publish-mcp-registry (this PR) resolves it on the next "
        "v* tag push; no CI credential exists to publish it sooner"
    ),
}


def list_registry_versions(search_term: str) -> list[tuple[str, str, bool]] | None:
    """[(name, version, is_latest), ...] for every registry entry matching
    `search_term`; None when the registry has nothing for it.

    The registry API has no exact-name lookup (verified 2026-08-10: a
    `name=` query parameter is silently ignored, not a filter), so this
    fetches by `search=` and the caller filters to the exact name it wants.
    """
    url = f"{REGISTRY_API}?search={urllib.parse.quote(search_term)}"
    req = urllib.request.Request(url, headers=api_headers())
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == HTTP_NOT_FOUND:
            return None
        raise
    out = []
    for entry in data.get("servers", []):
        srv = entry.get("server", {})
        meta = entry.get("_meta", {}).get(
            "io.modelcontextprotocol.registry/official", {}
        )
        out.append(
            (srv.get("name", ""), srv.get("version", ""), bool(meta.get("isLatest")))
        )
    return out


def _resolve_latest_registry_version(registry_name: str, list_versions):
    """Fetch + narrow to the single 'latest' entry for `registry_name`.

    Returns `(early_result, latest_version)` — exactly one is None.
    `early_result` is a ready (failure, notice) pair for every terminal
    case (network failure, nothing found, no 'latest' flag). Split out of
    `check_registry_version` to keep it under the §4.2 method-size cap.
    """
    try:
        entries = list_versions(registry_name.rsplit("/", 1)[-1])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        notice = (
            f"NOTICE: registry: network degraded ({e.__class__.__name__}); "
            f"{registry_name} not verified this run"
        )
        return (None, notice), None
    if entries is None:
        return (
            None,
            f"NOTICE: registry: {registry_name} not found; not comparable",
        ), None
    latest = [v for n, v, is_latest in entries if n == registry_name and is_latest]
    if not latest:
        notice = (
            f"NOTICE: registry: no 'latest' entry for {registry_name}; not comparable"
        )
        return (None, notice), None
    return None, latest[0]


def check_registry_version(
    registry_name: str,
    authoritative_version: str,
    list_versions=list_registry_versions,
    pending: dict[str, str] | None = None,
):
    """Returns (failure, notice) — exactly one is non-None or both None.

    Exact-equality, not "behind": a registry entry ahead of the repo (a
    republish of a version this repo never tagged) is just as much a lie
    to whoever reads the registry as one that lags.
    """
    if pending is None:
        pending = PENDING_REGISTRY
    early_result, registry_version = _resolve_latest_registry_version(
        registry_name, list_versions
    )
    if registry_version is None:
        return early_result
    if registry_version == authoritative_version:
        return None, None
    if registry_name in pending:
        return (
            None,
            f"NOTICE: registry: {registry_name} serves {registry_version}, "
            f"repo is {authoritative_version} — PENDING: {pending[registry_name]}",
        )
    return (
        f"REGISTRY_VERSION_STALE: {registry_name}: MCP registry serves "
        f"{registry_version} but this repo's authoritative version is "
        f"{authoritative_version}",
        None,
    )


def check_registry_surface(root: Path, primary_pin: str):
    """Cross-check server.json's own registry `name` against what the
    public MCP registry actually serves. Returns (failures, notices).
    Absent server.json or a missing `name` field is not a failure — not
    every repo on this marketplace publishes to the MCP registry.
    """
    server_json = root / "server.json"
    if not server_json.is_file():
        return [], []
    registry_name = json.loads(server_json.read_text()).get("name", "")
    if not registry_name:
        return [], []
    failure, notice = check_registry_version(registry_name, primary_pin)
    return ([failure] if failure else []), ([notice] if notice else [])
