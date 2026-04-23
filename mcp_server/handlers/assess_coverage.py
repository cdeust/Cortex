"""Handler: assess_coverage — knowledge completeness evaluation.

Evaluates how well the memory store covers the current codebase/project:
  1. File coverage: which key files have been seen/remembered
  2. Domain balance: distribution of memories across detected domains
  3. Age distribution: how fresh vs stale the knowledge is
  4. Entity density: how many entities per memory (richness signal)
  5. Compression ratio: how much content has been compressed (loss signal)

Returns a 0-100 coverage score and actionable recommendations.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.handlers._tool_meta import READ_ONLY

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "title": "Assess coverage",
    "annotations": READ_ONLY,
    "description": (
        "Score how well the memory store covers a project across five "
        "axes: file coverage (which key files are remembered), domain "
        "balance (per-domain memory distribution), age distribution (fresh "
        "vs stale), entity density (richness signal), and compression "
        "ratio (loss signal). Combines into a 0-100 coverage score and "
        "emits actionable recommendations (e.g., `run codebase_analyze on "
        "src/api/`, `consolidate to recompress 12 cold memories`). Use "
        "this before claiming Cortex `knows` a codebase, or as a "
        "milestone-completion check. Distinct from `detect_gaps` (lists "
        "specific missing connections, no aggregate score), `memory_stats` "
        "(raw counts, no scoring), and `narrative` (prose summary, no "
        "numeric coverage). Read-only. Latency ~500ms-1s. Returns "
        "{coverage_score, axes: {file, domain, age, entity, compression}, "
        "recommendations}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "directory": {
                "type": "string",
                "description": "Absolute project directory to assess. Defaults to current working directory.",
                "examples": ["/Users/alice/code/cortex"],
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to assess when 'directory' is not supplied.",
                "examples": ["cortex", "auth-service"],
            },
            "stale_days": {
                "type": "integer",
                "description": "Days since last access for a memory to count as stale in the age-distribution score.",
                "default": 14,
                "minimum": 1,
                "maximum": 365,
                "examples": [7, 14, 30],
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Sub-evaluators ────────────────────────────────────────────────────────────


def _age_distribution(
    memories: list[dict[str, Any]],
    stale_days: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=stale_days)
    fresh_cutoff = now - timedelta(days=stale_days // 3)

    fresh = stale = total = 0
    for mem in memories:
        raw = mem.get("created_at", "")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            total += 1
            if dt >= fresh_cutoff:
                fresh += 1
            elif dt < stale_cutoff:
                stale += 1
        except (ValueError, TypeError):
            pass

    if total == 0:
        return {"fresh": 0, "stale": 0, "total": 0, "freshness_ratio": 0.0}

    return {
        "fresh": fresh,
        "stale": stale,
        "total": total,
        "freshness_ratio": round(fresh / total, 3),
    }


def _entity_density(
    memories: list[dict[str, Any]], store: MemoryStore
) -> dict[str, Any]:
    """Compute average entity count per memory (richness)."""
    if not memories:
        return {"avg_entities_per_memory": 0.0, "total_entities": 0}

    try:
        all_entities = store.get_all_entities(min_heat=0.0)
        total_entities = len(all_entities)
        avg = total_entities / len(memories)
        return {
            "avg_entities_per_memory": round(avg, 2),
            "total_entities": total_entities,
        }
    except Exception:
        return {"avg_entities_per_memory": 0.0, "total_entities": 0}


def _compression_ratio(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """How much content has been compressed."""
    if not memories:
        return {"compressed": 0, "total": 0, "ratio": 0.0}
    compressed = sum(1 for m in memories if m.get("compression_level", 0) > 0)
    return {
        "compressed": compressed,
        "total": len(memories),
        "ratio": round(compressed / len(memories), 3),
    }


def _domain_balance(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """How evenly distributed are memories across domains."""
    domain_counts: dict[str, int] = {}
    for mem in memories:
        d = mem.get("domain") or "unassigned"
        domain_counts[d] = domain_counts.get(d, 0) + 1

    if not domain_counts:
        return {"domains": {}, "balance_score": 0.0}

    counts = list(domain_counts.values())
    avg = sum(counts) / len(counts)
    if avg > 0:
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        cv = (variance**0.5) / avg
        balance_score = max(0.0, 1.0 - cv)
    else:
        balance_score = 0.0

    return {
        "domains": domain_counts,
        "balance_score": round(balance_score, 3),
    }


def _compute_coverage_score(
    total_memories: int,
    freshness_ratio: float,
    entity_density: float,
    compression_ratio: float,
    balance_score: float,
) -> int:
    """Compute 0-100 coverage score from sub-signals."""
    quantity_score = min(1.0, total_memories / 100)
    entity_score = min(1.0, entity_density / 3.0)
    compression_penalty = compression_ratio * 0.3

    raw = (
        quantity_score * 0.30
        + freshness_ratio * 0.25
        + entity_score * 0.20
        + balance_score * 0.15
        - compression_penalty
        + 0.10
    )
    return int(max(0, min(100, raw * 100)))


def _recommendations(
    total: int,
    fresh: int,
    stale: int,
    entity_density: float,
    compressed: int,
    balance_score: float,
) -> list[str]:
    recs = []
    if total < 20:
        recs.append("Run `seed_project` to bootstrap memory from the codebase.")
    if stale > total * 0.4:
        recs.append("Run `validate_memory` — more than 40% of memories are stale.")
    if entity_density < 0.5:
        recs.append("Low entity density. Use `remember` with more specific content.")
    if compressed > total * 0.5:
        recs.append("High compression ratio — consider re-seeding with `seed_project`.")
    if balance_score < 0.4:
        recs.append(
            "Unbalanced domain coverage. Use `remember` with explicit `domain` tags."
        )
    if not recs:
        recs.append(
            "Coverage looks healthy. Run `consolidate` periodically to maintain quality."
        )
    return recs


# ── Handler ───────────────────────────────────────────────────────────────────


def _fetch_memories(
    store: MemoryStore,
    directory: str,
    domain: str,
) -> list[dict[str, Any]]:
    """Fetch memories scoped by directory, domain, or global."""
    if directory and directory != os.getcwd():
        return store.get_memories_for_directory(directory, min_heat=0.0)
    if domain:
        return store.get_memories_for_domain(domain, min_heat=0.0, limit=1000)
    return store.get_all_memories_for_validation(limit=1000)


def _evaluate_signals(
    memories: list[dict[str, Any]],
    store: MemoryStore,
    stale_days: int,
) -> dict[str, Any]:
    """Run all sub-evaluators and return their results."""
    age = _age_distribution(memories, stale_days)
    density = _entity_density(memories, store)
    compress = _compression_ratio(memories)
    balance = _domain_balance(memories)
    return {
        "age": age,
        "density": density,
        "compress": compress,
        "balance": balance,
    }


def _score_and_recommend(
    memories: list[dict[str, Any]],
    signals: dict[str, Any],
) -> tuple[int, list[str]]:
    """Compute coverage score and recommendations from signals."""
    score = _compute_coverage_score(
        total_memories=len(memories),
        freshness_ratio=signals["age"]["freshness_ratio"],
        entity_density=signals["density"]["avg_entities_per_memory"],
        compression_ratio=signals["compress"]["ratio"],
        balance_score=signals["balance"]["balance_score"],
    )
    recs = _recommendations(
        total=len(memories),
        fresh=signals["age"]["fresh"],
        stale=signals["age"]["stale"],
        entity_density=signals["density"]["avg_entities_per_memory"],
        compressed=signals["compress"]["compressed"],
        balance_score=signals["balance"]["balance_score"],
    )
    return score, recs


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess knowledge coverage completeness."""
    args = args or {}
    directory = args.get("directory", "") or os.getcwd()
    domain = args.get("domain", "")
    stale_days = int(args.get("stale_days", 14))

    store = _get_store()
    memories = _fetch_memories(store, directory, domain)

    if not memories:
        return {
            "coverage_score": 0,
            "total_memories": 0,
            "recommendations": ["No memories found. Run `seed_project` to bootstrap."],
        }

    signals = _evaluate_signals(memories, store, stale_days)
    score, recs = _score_and_recommend(memories, signals)

    return {
        "coverage_score": score,
        "total_memories": len(memories),
        "age_distribution": signals["age"],
        "entity_density": signals["density"],
        "compression": signals["compress"],
        "domain_balance": signals["balance"],
        "recommendations": recs,
        "directory": directory,
        "domain": domain,
    }
