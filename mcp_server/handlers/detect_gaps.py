"""Handler: detect_gaps — identify missing connections and knowledge gaps.

Surfaces blind spots in the memory store, across four axes:
  1. Isolated entities (referenced in memories but have no relationships)
  2. Domains with sparse entity coverage vs. the global average
  3. Temporal drift (domains whose most-recently-accessed memory is old)
  4. Cognitive blind spots (per-domain category/tool/pattern gaps from
     the profile-based blindspot_detector)

Combines structural gap detection with cognitive blindspot analysis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp_server.core.blindspot_detector import detect_blind_spots
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.observability import silent_failure

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Detect gaps",
    "annotations": READ_ONLY,
    "description": (
        "Surface knowledge gaps across four axes: isolated entities "
        "(referenced in memories but with zero relationships, cap 10), "
        "sparse domains (entity count under 50% of the cross-domain "
        "average, cap 5), temporal drift (domains whose most-recently-"
        "accessed memory — sampled from up to 10 per domain — exceeds "
        "`stale_threshold_days`, cap 5), and cognitive blind spots (per-"
        "domain category/tool/pattern gaps from the profile-based "
        "blindspot detector, capped to the first 5 domains and 3 spots "
        "each). Does not detect duplicates, contradictions, or "
        "domainless/sourceless memories. Use this "
        "when planning research priorities or auditing coverage. Distinct "
        "from `assess_coverage` (numeric coverage SCORE 0-100 per axis, no "
        "specific gap list), and `memory_stats` (population counts only, "
        "no gap interpretation). Read-only. Latency ~500ms-2s depending on "
        "store size. Returns {total_gaps, gaps: [{gap_type, ...}], "
        "by_type: {gap_type: count}, domain_filter}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Focus gap analysis on a specific domain. Omit for a global "
                    "scan across all domains."
                ),
                "examples": ["cortex", "auth-service"],
            },
            "include_entity_gaps": {
                "type": "boolean",
                "description": (
                    "Include isolated-entity analysis: entities referenced in "
                    "memories but with no outgoing/incoming relationships."
                ),
                "default": True,
            },
            "include_domain_gaps": {
                "type": "boolean",
                "description": (
                    "Include cross-domain coverage analysis: domains whose "
                    "memory count or category coverage falls below the global average."
                ),
                "default": True,
            },
            "include_temporal_gaps": {
                "type": "boolean",
                "description": (
                    "Include temporal drift detection: domains whose most "
                    "recent memory is older than 'stale_threshold_days'."
                ),
                "default": True,
            },
            "stale_threshold_days": {
                "type": "integer",
                "description": (
                    "Days since last access for a domain to count as temporally "
                    "drifted. Lower = stricter freshness requirement."
                ),
                "default": 30,
                "minimum": 1,
                "maximum": 365,
                "examples": [7, 30, 90],
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Gap detectors ─────────────────────────────────────────────────────────


def _entity_gaps(store: MemoryStore) -> list[dict[str, Any]]:
    """Find entities that are referenced but have no relationships."""
    isolated = store.get_isolated_entities(limit=20)
    return [
        {
            "entity_id": e["id"],
            "entity_name": e["name"],
            "entity_type": e["type"],
            "domain": e.get("domain", ""),
            "relationship_count": e.get("relationship_count", 0),
            "heat": round(e.get("heat", 0), 4),
            "gap_type": "isolated_entity",
        }
        for e in isolated
        if e.get("relationship_count", 0) == 0
    ][:10]


def _domain_coverage_gaps(store: MemoryStore) -> list[dict[str, Any]]:
    """Find domains with fewer memories than the global average."""
    counts = store.count_memories()
    total = counts.get("total", 0)
    if not total:
        return []

    domain_counts = store.get_domain_entity_counts()
    if not domain_counts:
        return []

    avg = sum(d["count"] for d in domain_counts) / len(domain_counts)
    gaps = []
    for d in domain_counts:
        if d["count"] < avg * 0.5 and d.get("domain"):  # Below 50% of average
            gaps.append(
                {
                    "domain": d["domain"],
                    "entity_count": d["count"],
                    "avg_entity_count": round(avg, 1),
                    "coverage_ratio": round(d["count"] / avg, 3),
                    "gap_type": "sparse_domain",
                }
            )
    return sorted(gaps, key=lambda x: x["coverage_ratio"])[:5]


def _temporal_gaps(store: MemoryStore, stale_days: int) -> list[dict[str, Any]]:
    """Find domains whose memories haven't been accessed recently."""
    stale_threshold = stale_days * 86400.0  # seconds
    now = datetime.now(timezone.utc).timestamp()

    gaps = []
    domain_counts = store.get_domain_entity_counts()
    for d in domain_counts:
        domain = d.get("domain", "")
        if not domain:
            continue
        mems = store.get_memories_for_domain(domain, min_heat=0.0, limit=10)
        if not mems:
            continue
        latest_access = max(
            (m.get("last_accessed", "") for m in mems),
            default="",
        )
        if not latest_access:
            continue
        try:
            dt = datetime.fromisoformat(latest_access)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_seconds = now - dt.timestamp()
            if age_seconds > stale_threshold:
                days_old = int(age_seconds / 86400)
                gaps.append(
                    {
                        "domain": domain,
                        "days_since_access": days_old,
                        "memory_count": len(mems),
                        "gap_type": "temporal_drift",
                    }
                )
        except (ValueError, TypeError):
            pass

    return sorted(gaps, key=lambda x: x["days_since_access"], reverse=True)[:5]


def _cognitive_style_gaps(domain: str | None) -> list[dict[str, Any]]:
    """Use existing blindspot_detector to find category/tool/pattern gaps."""
    try:
        profiles = load_profiles()
        domains = profiles.get("domains", {})
        sessions = profiles.get("sessions", [])
        if not domains:
            return []

        target_domain_ids = (
            [domain] if domain and domain in domains else list(domains.keys())
        )
        gaps = []
        for dom_id in target_domain_ids[:5]:  # Cap to avoid long runs
            blind_spots = detect_blind_spots(
                domain_id=dom_id,
                domain_conversations=sessions,
                all_conversations=sessions,
                profiles=profiles,
            )
            for spot in blind_spots[:3]:
                spot["domain"] = dom_id
                spot["gap_type"] = "cognitive_blind_spot"
                gaps.append(spot)
        return gaps[:10]
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("detect_gaps.blind_spots", exc)
        return []


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect knowledge gaps in the memory store."""
    args = args or {}
    domain = args.get("domain", "")
    include_entity = args.get("include_entity_gaps", True)
    include_domain = args.get("include_domain_gaps", True)
    include_temporal = args.get("include_temporal_gaps", True)
    stale_days = int(args.get("stale_threshold_days", 30))

    store = _get_store()

    all_gaps: list[dict[str, Any]] = []

    if include_entity:
        all_gaps.extend(_entity_gaps(store))

    if include_domain:
        all_gaps.extend(_domain_coverage_gaps(store))

    if include_temporal:
        all_gaps.extend(_temporal_gaps(store, stale_days))

    # Cognitive style gaps from profile-based blindspot detector
    cognitive_gaps = _cognitive_style_gaps(domain or None)
    all_gaps.extend(cognitive_gaps)

    # Group by type for easier consumption
    by_type: dict[str, list] = {}
    for gap in all_gaps:
        gtype = gap.get("gap_type", "unknown")
        by_type.setdefault(gtype, []).append(gap)

    return {
        "total_gaps": len(all_gaps),
        "gaps": all_gaps,
        "by_type": {k: len(v) for k, v in by_type.items()},
        "domain_filter": domain or "global",
    }
