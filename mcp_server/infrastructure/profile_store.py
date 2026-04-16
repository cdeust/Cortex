"""Persistence layer for methodology profiles.

D5 fix (Phase 1 fragility sweep): profiles are now split into one JSON file
per domain under ``~/.claude/methodology/domains/<domain-id>.json``, with a
top-level ``~/.claude/methodology/index.json`` listing domain ids + the
small globals (version, updatedAt, globalStyle).

Before this change every ``record_session_end`` fully read and fully
rewrote a single ``profiles.json`` containing every domain's full profile.
Per Thompson's audit: at 1000 domains that's ~10 MB of write amplification
per session end — unacceptable as the system scales.

Public API:
    load_profiles()            - unified v2 dict (backwards compatible)
    save_profiles(profiles)    - splits into per-domain files + index
    load_profile(domain_id)    - lazy single-domain load
    save_profile(domain_id, p) - targeted write — ONLY touches one file

Migration: on first call after upgrade, if a legacy single-file
``profiles.json`` exists, it is split into per-domain files and the
legacy file is renamed to ``profiles.json.v1_backup``.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.config import METHODOLOGY_DIR, PROFILES_PATH
from mcp_server.infrastructure.file_io import ensure_dir, read_json, write_json

# Per-domain split layout. Sibling files rather than nested so index.json
# can act as the cheap "list all domains" read without touching any
# per-domain file. See ADR-0045 §R2 (bounded I/O per operation).
DOMAINS_DIR = METHODOLOGY_DIR / "domains"
INDEX_PATH = METHODOLOGY_DIR / "index.json"
LEGACY_BACKUP_PATH = Path(str(PROFILES_PATH) + ".v1_backup")


def empty_profiles() -> dict:
    return {"version": 2, "updatedAt": None, "globalStyle": None, "domains": {}}


def _empty_index() -> dict:
    """Index shape: globals + sorted list of domain ids."""
    return {
        "version": 2,
        "updatedAt": None,
        "globalStyle": None,
        "domain_ids": [],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _domain_path(domain_id: str) -> Path:
    """Per-domain file path. ``domain_id`` is used verbatim — callers upstream
    are responsible for producing safe identifiers (see
    ``shared/project_ids.py``). We still guard against path traversal here
    defensively.
    """
    if "/" in domain_id or ".." in domain_id or "\x00" in domain_id:
        raise ValueError(f"unsafe domain_id: {domain_id!r}")
    return DOMAINS_DIR / f"{domain_id}.json"


def _migrate_legacy_if_present() -> bool:
    """If a legacy single-file profiles.json exists, split it.

    Returns True if a migration happened (caller may want to log). Safe to
    call repeatedly — it's a no-op once the legacy file has been renamed.
    """
    if not PROFILES_PATH.exists():
        return False
    legacy = read_json(PROFILES_PATH)
    if not isinstance(legacy, dict):
        return False
    domains = legacy.get("domains") or {}
    if not isinstance(domains, dict):
        return False

    # Write each domain to its own file and build an index. This is one
    # bounded bulk operation per upgrade; subsequent session ends only
    # touch a single per-domain file.
    ensure_dir(DOMAINS_DIR)
    for domain_id, profile in domains.items():
        if isinstance(domain_id, str) and isinstance(profile, dict):
            try:
                write_json(_domain_path(domain_id), profile)
            except ValueError:
                # Skip ids that fail the safety guard — they will surface
                # at ``load_profile`` time if something depends on them.
                continue

    index = {
        "version": legacy.get("version", 2),
        "updatedAt": legacy.get("updatedAt"),
        "globalStyle": legacy.get("globalStyle"),
        "domain_ids": sorted(
            d for d in domains if isinstance(d, str) and "/" not in d
        ),
    }
    write_json(INDEX_PATH, index)
    shutil.move(str(PROFILES_PATH), str(LEGACY_BACKUP_PATH))
    return True


def _ensure_index() -> dict:
    """Return the on-disk index, triggering legacy migration if needed."""
    _migrate_legacy_if_present()
    idx = read_json(INDEX_PATH)
    if not isinstance(idx, dict):
        return _empty_index()
    idx.setdefault("version", 2)
    idx.setdefault("domain_ids", [])
    return idx


def load_profile(domain_id: str) -> dict | None:
    """Lazy single-domain load — O(1) file reads, never touches other domains.

    Preconditions:
        - ``domain_id`` is the canonical domain identifier.

    Postconditions:
        - Returns the domain profile dict if the file exists.
        - Returns None if the domain is unknown.
        - Triggers the legacy migration on first access if needed.
    """
    _ensure_index()
    try:
        path = _domain_path(domain_id)
    except ValueError:
        return None
    return read_json(path)


def load_profiles() -> dict:
    """Load all profiles, reassembled into the legacy v2 dict shape.

    Backwards-compatible: callers that expect ``profiles["domains"][id]``
    keep working. Internally: O(D) reads where D is the number of domains,
    once per call. Most handlers only need a single domain and should
    migrate to ``load_profile(domain_id)`` over time.
    """
    idx = _ensure_index()
    domains: dict = {}
    for domain_id in idx.get("domain_ids", []):
        profile = load_profile(domain_id)
        if profile is not None:
            domains[domain_id] = profile

    return {
        "version": idx.get("version", 2),
        "updatedAt": idx.get("updatedAt"),
        "globalStyle": idx.get("globalStyle"),
        "domains": domains,
    }


def save_profile(domain_id: str, profile: dict) -> None:
    """Save a single domain's profile — does NOT touch other domains' files.

    Postconditions:
        - ``<domains_dir>/<domain_id>.json`` is rewritten atomically via
          ``write_json``.
        - ``index.json`` is updated only if ``domain_id`` is new.
        - ``index.json.updatedAt`` is refreshed.
        - Mtime of OTHER per-domain files is unchanged — this is the key
          invariant that makes the split worthwhile.

    Preconditions:
        - ``domain_id`` is non-empty and contains no path-separator chars.
        - ``profile`` is a serialisable dict.
    """
    ensure_dir(DOMAINS_DIR)
    write_json(_domain_path(domain_id), profile)

    idx = _ensure_index()
    domain_ids = list(idx.get("domain_ids", []))
    if domain_id not in domain_ids:
        domain_ids.append(domain_id)
        domain_ids.sort()
    idx["domain_ids"] = domain_ids
    idx["updatedAt"] = _now_iso()
    write_json(INDEX_PATH, idx)


def save_profiles(profiles: dict) -> None:
    """Save all profiles — splits into per-domain files + index.

    Backwards-compatible with the legacy whole-dict API. Iterates the
    ``domains`` dict and writes each to its own file. Callers that want
    per-domain write amplification should use ``save_profile`` directly.
    """
    ensure_dir(DOMAINS_DIR)
    profiles["updatedAt"] = _now_iso()

    domains = profiles.get("domains") or {}
    if not isinstance(domains, dict):
        domains = {}

    for domain_id, profile in domains.items():
        if not isinstance(domain_id, str) or not isinstance(profile, dict):
            continue
        try:
            write_json(_domain_path(domain_id), profile)
        except ValueError:
            continue

    index = {
        "version": profiles.get("version", 2),
        "updatedAt": profiles["updatedAt"],
        "globalStyle": profiles.get("globalStyle"),
        "domain_ids": sorted(
            d for d in domains if isinstance(d, str) and "/" not in d
        ),
    }
    write_json(INDEX_PATH, index)
