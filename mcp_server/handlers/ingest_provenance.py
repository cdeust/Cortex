"""Ingestion provenance (ADR-0052 sec 2, INC5.2).

Two Cortex handlers write the same PostgreSQL rows from two different
engines: ``ingest_codebase`` (primary — pulls the automatised-pipeline (AP)
graph via APBridge/mcp_client_pool) and ``codebase_analyze`` (explicit
fallback — native in-process tree-sitter AST, used only when AP is
unreachable). ADR-0052 sec 2 requires that:

1. every memory either path writes carries a provenance tag (``src:ap`` or
   ``src:native``), plus the AP binary version when ``src:ap`` applies;
2. ``codebase_analyze`` states explicitly whether it is running as the
   documented AP-unreachable fallback, or in violation of the documented
   precedence (AP is reachable but native ran anyway) — never silently;
3. ``ingest_codebase`` checks version parity between its two Cortex->AP
   client paths (``APBridge`` resolution vs the ``mcp_client_pool``
   ``mcp-connections.json`` "codebase" server) and surfaces divergence
   (iface angle-mort 5: a live skew was observed between a 0.4.0 symlinked
   binary and a manifest-declared 0.6.0 plugin).

This module is the single place both ingestion handlers get their
provenance tags and the parity check from — no writer computes a tag
string inline. Infrastructure I/O (APBridge, mcp_client_pool) is reached
the same way ``ingest_helpers.py`` already does from the handlers layer.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

from mcp_server.handlers.ingest_helpers import call_upstream, normalise_mcp_payload
from mcp_server.infrastructure.ap_bridge import APBridge

logger = logging.getLogger(__name__)

# ── Provenance tags (ADR-0052 sec 2, requirement 1) ─────────────────────────

SRC_AP_TAG = "src:ap"
SRC_NATIVE_TAG = "src:native"
_AP_VERSION_TAG_PREFIX = "src:ap-version:"

# ── Fallback-precedence tags (ADR-0052 sec 2, requirement 2) ────────────────

FALLBACK_LEGITIMATE_TAG = "src:native-fallback"
FALLBACK_PRECEDENCE_VIOLATION_TAG = "src:native-precedence-violation"

_UPSTREAM_SERVER = "codebase"

__all__ = [
    "SRC_AP_TAG",
    "SRC_NATIVE_TAG",
    "FALLBACK_LEGITIMATE_TAG",
    "FALLBACK_PRECEDENCE_VIOLATION_TAG",
    "ap_version_tag",
    "ap_provenance_tags",
    "native_provenance_tags",
    "native_fallback_status",
    "fetch_ap_version_via_bridge",
    "fetch_ap_version_via_pool",
    "VersionParity",
    "check_version_parity",
]


def ap_version_tag(version: str) -> str:
    """Canonical tag encoding the AP binary version that produced a memory."""
    return f"{_AP_VERSION_TAG_PREFIX}{version}"


def ap_provenance_tags(version: str | None) -> list[str]:
    """Provenance tags for a memory written via the AP (``ingest_codebase``) path.

    Precondition:  none.
    Postcondition: always includes SRC_AP_TAG; includes the version tag only
                   when a version string was actually resolved — an
                   unresolved version is reported as absent, never guessed
                   (zetetic: no speculative backfill, ADR-0052 risk 5).
    """
    tags = [SRC_AP_TAG]
    if version:
        tags.append(ap_version_tag(version))
    return tags


def native_provenance_tags() -> list[str]:
    """Provenance tag for a memory written via the native (``codebase_analyze``) path."""
    return [SRC_NATIVE_TAG]


def native_fallback_status() -> tuple[str, str | None]:
    """Whether ``codebase_analyze`` is running as the documented fallback.

    Precondition:  none — uses only the static reachability check already
                   used to gate ``ingest_codebase``'s tool registration
                   (``upstream_availability.codebase_upstream_available``),
                   so this never adds a live AP round-trip to the native
                   path (whose whole point is not depending on AP).
    Postcondition: returns ``(tag, warning)``. ``tag`` is
                   FALLBACK_LEGITIMATE_TAG when AP is NOT reachable (the
                   documented case, ADR-0052 sec 2) or
                   FALLBACK_PRECEDENCE_VIOLATION_TAG when AP IS reachable
                   (native ran anyway — a precedence violation). ``warning``
                   is None for the legitimate case, a human-readable
                   message for the violation case (the caller logs it —
                   this function never logs itself, keeping it a pure
                   decision).
    """
    from mcp_server.infrastructure.upstream_availability import (
        codebase_upstream_available,
    )

    if codebase_upstream_available():
        return (
            FALLBACK_PRECEDENCE_VIOLATION_TAG,
            "codebase_analyze (native) ran while the automatised-pipeline "
            "upstream is reachable. ingest_codebase is the primary "
            "ingestion path and codebase_analyze is its explicit fallback "
            "for when AP is unreachable only (ADR-0052 sec 2) — this run "
            "violates that precedence.",
        )
    return (FALLBACK_LEGITIMATE_TAG, None)


def _extract_version(payload: Any) -> str | None:
    result = normalise_mcp_payload(payload)
    if isinstance(result, dict):
        version = result.get("version")
        if isinstance(version, str) and version:
            return version
    return None


async def fetch_ap_version_via_bridge() -> str | None:
    """AP version as resolved by the ``APBridge`` client path (ap_bridge.py).

    Postcondition: returns the version string on success, None on any
    failure (AP disabled, unreachable, malformed reply) — never raises.
    """
    bridge = APBridge()
    try:
        payload = await bridge.health_check()
    except Exception as exc:  # noqa: BLE001 — defensive bridge boundary; failure is logged, returns None  # pragma: no cover
        logger.debug("ap version (bridge path) unavailable: %s", exc)
        return None
    finally:
        await bridge.close()
    return _extract_version(payload)


async def fetch_ap_version_via_pool() -> str | None:
    """AP version as resolved by the ``mcp_client_pool`` client path
    (``mcp-connections.json`` "codebase" server entry).

    Postcondition: returns the version string on success, None on any
    failure — never raises.
    """
    try:
        payload = await call_upstream(_UPSTREAM_SERVER, "health_check", {})
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("ap version (pool path) unavailable: %s", exc)
        return None
    return _extract_version(payload)


@dataclasses.dataclass(frozen=True)
class VersionParity:
    """Result of comparing AP versions across the two Cortex->AP client paths."""

    bridge_version: str | None
    pool_version: str | None
    status: str  # "match" | "mismatch" | "unknown"
    warning: str | None


def _parity_from_versions(
    bridge_version: str | None, pool_version: str | None
) -> VersionParity:
    if bridge_version is None or pool_version is None:
        return VersionParity(
            bridge_version,
            pool_version,
            "unknown",
            "AP client-path version parity could not be checked: "
            f"APBridge={bridge_version or '<unreachable>'}, "
            f"mcp_client_pool={pool_version or '<unreachable>'}.",
        )
    if bridge_version == pool_version:
        return VersionParity(bridge_version, pool_version, "match", None)
    return VersionParity(
        bridge_version,
        pool_version,
        "mismatch",
        "AP client-path version skew: APBridge resolves "
        f"{bridge_version!r}, mcp_client_pool resolves {pool_version!r}. "
        "The two Cortex->AP client paths (ap_bridge.py resolution vs "
        "mcp-connections.json) point at different AP binaries — see "
        "ADR-0052 sec 2 (iface angle-mort 5).",
    )


async def check_version_parity() -> VersionParity:
    """Compare AP versions across the two Cortex->AP client paths.

    Precondition:  none — safe to call whether or not AP is reachable via
                   either path.
    Postcondition: never raises. ``status`` is "unknown" (not "mismatch")
                   when either path fails to resolve a version, so a
                   partial failure never reads as a false skew. A genuine
                   "mismatch" is logged as a warning here (single log
                   site for this signal); callers additionally surface the
                   dataclass in their own response for external
                   verifiability (D5 acceptance criterion — log + response
                   field, not log-only).
    """
    bridge_version, pool_version = await asyncio.gather(
        fetch_ap_version_via_bridge(), fetch_ap_version_via_pool()
    )
    result = _parity_from_versions(bridge_version, pool_version)
    if result.status == "mismatch":
        logger.warning(result.warning)
    return result
