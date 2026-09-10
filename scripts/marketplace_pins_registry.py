"""Public MCP registry cross-check for the marketplace pin-staleness gate.

source: ADR-0756"""

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

# source: ADR-0756
PENDING_REGISTRY: dict[str, str] = {
    "io.github.cdeust/hypermnesia-mcp": (
        "release.yml::publish-mcp-registry (this PR) resolves it on the next "
        "v* tag push; no CI credential exists to publish it sooner"
    ),
}


def list_registry_versions(search_term: str) -> list[tuple[str, str, bool]] | None:
    """[(name, version, is_latest), ...] for every registry entry matching
        `search_term`; None when the registry has nothing for it.

    source: ADR-0756"""
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


# source: ADR-0756
SERVER_JSON_DESCRIPTION_MIN_LENGTH = 1
SERVER_JSON_DESCRIPTION_MAX_LENGTH = 100


def check_server_json_schema(root: Path) -> list[str]:
    """Offline, schema-derived validity checks on server.json's own fields
        — distinct from check_registry_version's cross-repo VERSION check.
        Catches the class of defect that produces a 422 at publish time (schema
        violation), which a version-only comparison cannot see: a server.json
        can have the exactly-correct version and still be unpublishable.

    source: ADR-0756"""
    server_json = root / "server.json"
    if not server_json.is_file():
        return []
    description = json.loads(server_json.read_text()).get("description", "")
    length = len(description)
    if length > SERVER_JSON_DESCRIPTION_MAX_LENGTH:
        return [
            f"SERVER_JSON_DESCRIPTION_TOO_LONG: server.json description is "
            f"{length} chars; the MCP registry schema caps it at "
            f"{SERVER_JSON_DESCRIPTION_MAX_LENGTH} — a tag cut from this "
            f"tree cannot be published (422) and there is no way to publish "
            f"an already-tagged violation after the fact, only a new tag"
        ]
    if length < SERVER_JSON_DESCRIPTION_MIN_LENGTH:
        return [
            f"SERVER_JSON_DESCRIPTION_TOO_SHORT: server.json description is "
            f"empty; the MCP registry schema requires at least "
            f"{SERVER_JSON_DESCRIPTION_MIN_LENGTH} char"
        ]
    return []


def check_registry_surface(root: Path, primary_pin: str):
    """Cross-check server.json's own registry `name` against what the
        public MCP registry actually serves, AND server.json's own schema
        validity (description length).

    source: ADR-0756"""
    server_json = root / "server.json"
    if not server_json.is_file():
        return [], []
    schema_failures = check_server_json_schema(root)
    registry_name = json.loads(server_json.read_text()).get("name", "")
    if not registry_name:
        return schema_failures, []
    failure, notice = check_registry_version(registry_name, primary_pin)
    version_failures = [failure] if failure else []
    return schema_failures + version_failures, ([notice] if notice else [])
