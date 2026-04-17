"""Helpers for backfill_memories -- file discovery, hashing, and concept linking.

Extracted from backfill_memories.py to keep both files under 300 lines.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Age-decayed initial heat (Fix 1: issue #14 P1) ───────────────────────
#
# Pre-v3.12.2, every memory entered the store at heat=1.0, including backfills
# of historical conversations. A 300+ session bulk import therefore produced
# a sharp peak at heat ≈ 0.94-1.0 (after surprise boost + decay), which
# Turrigiano multiplicative scaling (order-preserving by construction —
# Tetzlaff et al. 2011 Eq. 3) cannot flatten into the target distribution.
# User-visible symptom: recall pinned to the import cohort for 24+h.
#
# Fix: compute the initial heat of a backfilled memory from the age of the
# source session via an Ebbinghaus-style exponential decay. A floor of 0.3
# preserves semantic retrievability — old memories still surface via WRRF
# when query intent matches, they just don't dominate purely on heat.
#
# source: Ebbinghaus, H. (1885). "Über das Gedächtnis." r(t) = exp(-t/S)
# source: half-life tuned to the Cortex 30-day consolidation window
#         (core/cascade.py, ADR-013 thermodynamic memory model)
_DEFAULT_HALF_LIFE_DAYS = 30.0
_DEFAULT_HEAT_FLOOR = 0.3
_LN2 = math.log(2)


def age_decayed_heat(
    age_days: float,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
    floor: float = _DEFAULT_HEAT_FLOOR,
) -> float:
    """Initial heat for a historical memory, decayed from its content age.

    Pre: age_days is a float; negative values are clamped to 0.
    Post: returns a value in [floor, 1.0]. Monotone non-increasing in
    age_days. h(0)=1.0; h→floor as age_days→infinity.

    Curve: h(t) = floor + (1 - floor) · exp(-t · ln(2) / half_life_days)

    Reference points (floor=0.3, half_life=30d):
        age=0   → 1.000
        age=7   → 0.879
        age=30  → 0.650
        age=90  → 0.388
        age=180 → 0.311
        age=365 → 0.301

    Source: Ebbinghaus (1885); half-life tuned to Cortex 30-day window.
    """
    clamped_age = max(0.0, float(age_days))
    decay = math.exp(-clamped_age * _LN2 / half_life_days)
    return floor + (1.0 - floor) * decay


def compute_age_days(timestamp: str | None, now: datetime | None = None) -> float:
    """Age in days between an ISO-8601 timestamp and `now` (default: utcnow).

    Pre: timestamp is an ISO-8601 string or None/empty.
    Post: returns age in days (≥ 0). Returns 0.0 on missing, unparseable,
    or future-dated input (safe fallback: callers then get h(0)=1.0,
    matching legacy behaviour).
    """
    if not timestamp:
        return 0.0
    try:
        ts = timestamp.strip()
        # datetime.fromisoformat pre-3.11 does not accept a trailing 'Z'.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0
    reference = now if now is not None else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta = reference - parsed
    return max(0.0, delta.total_seconds() / 86400.0)


# Core concept keywords for entity linking
_CORE_CONCEPTS = {
    "predictive_coding": [
        "predictive coding",
        "write gate",
        "novelty score",
        "embedding novelty",
    ],
    "hopfield": ["hopfield", "modern hopfield", "pattern matrix"],
    "hdc": ["hyperdimensional", "hdc", "bind bundle permute", "bipolar vector"],
    "successor_representation": [
        "successor representation",
        "co-access",
        "sr graph",
        "sr score",
    ],
    "thermodynamics": ["heat decay", "thermodynamic", "cold threshold", "heat score"],
    "consolidation": [
        "cls consolidation",
        "episodic to semantic",
        "memify",
        "sleep compute",
    ],
    "fractal_hierarchy": [
        "fractal hierarchy",
        "recall hierarchical",
        "drill down",
        "cluster",
    ],
    "knowledge_graph": [
        "entity relationship",
        "causal chain",
        "knowledge graph",
        "entity extraction",
    ],
}


# -- Backfill log --


def ensure_backfill_log(store: MemoryStore) -> None:
    """Create the backfill_log table if it doesn't exist.

    Phase 5: runs on the batch pool (bootstrap work for a batch job).
    """
    with store.acquire_batch() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS backfill_log (
                id SERIAL PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                memories_imported INTEGER DEFAULT 0,
                processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )


def file_hash(path: Path) -> str:
    """Compute a fast hash of the first 64 KB of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def is_already_backfilled(store: MemoryStore, path: Path, current_hash: str) -> bool:
    """Check whether a file has already been backfilled with this hash.

    Phase 5: batch pool (part of a backfill job).
    """
    with store.acquire_batch() as conn:
        row = conn.execute(
            "SELECT file_hash FROM backfill_log WHERE file_path = %s",
            (str(path),),
        ).fetchone()
    if row is None:
        return False
    return row["file_hash"] == current_hash


def mark_backfilled(store: MemoryStore, path: Path, fhash: str, count: int) -> None:
    """Record that a file has been backfilled.

    Phase 5: batch pool.
    """
    with store.acquire_batch() as conn:
        conn.execute(
            """INSERT INTO backfill_log (file_path, file_hash, memories_imported, processed_at)
               VALUES (%s, %s, %s, NOW())
               ON CONFLICT(file_path) DO UPDATE SET
                 file_hash = EXCLUDED.file_hash,
                 memories_imported = EXCLUDED.memories_imported,
                 processed_at = NOW()
            """,
            (str(path), fhash, count),
        )


# -- File discovery --


def discover_files(project_filter: str, max_files: int) -> list[tuple[Path, str]]:
    """Return (path, project_slug) pairs for JSONL session files."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return []

    results: list[tuple[Path, str]] = []
    limit = max_files * 3  # over-fetch, filter later

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        slug = project_dir.name
        if project_filter and project_filter not in slug:
            continue
        for jsonl_file in sorted(project_dir.glob("*.jsonl"), reverse=True):
            results.append((jsonl_file, slug))
            if len(results) >= limit:
                break

    return results[:limit]


def slug_to_domain(slug: str) -> str:
    """Convert a project slug like '-Users-you-project-name' to a domain hint."""
    parts = [p for p in slug.split("-") if p and len(p) > 2]
    return parts[-1] if parts else slug[:20]


# -- Concept linking --


def find_concepts(content: str) -> list[str]:
    """Return core concept keys that appear in the content."""
    lower = content.lower()
    return [
        key
        for key, keywords in _CORE_CONCEPTS.items()
        if any(kw in lower for kw in keywords)
    ]


def _upsert_concept_entity(store: MemoryStore, concept: str) -> int | None:
    """Find or create an entity for a core concept. Returns entity_id."""
    entity_name = f"cortex:{concept}"
    existing = store.get_entity_by_name(entity_name)
    if existing:
        return existing["id"]
    try:
        return store.insert_entity(
            {
                "name": entity_name,
                "type": "concept",
                "domain": "cortex",
                "heat": 0.8,
            }
        )
    except Exception:
        return None


def link_concepts(store: MemoryStore, memory_id: int, concepts: list[str]) -> int:
    """Create entity relationships linking a memory to core concepts."""
    linked = 0
    for concept in concepts:
        entity_id = _upsert_concept_entity(store, concept)
        if entity_id is None:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": memory_id,
                    "target_entity_id": entity_id,
                    "relationship_type": "mentions_concept",
                    "weight": 0.8,
                    "confidence": 0.7,
                }
            )
            linked += 1
        except Exception:
            pass
    return linked
