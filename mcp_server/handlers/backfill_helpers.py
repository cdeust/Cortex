"""Helpers for backfill_memories -- file discovery, hashing, and concept linking.

source: ADR-0333"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mcp_server.infrastructure.handler_operations import (
    backfill_log_hash,
    record_backfill,
)
from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure
from mcp_server.shared.domain_mapping import resolve_domain
from mcp_server.core.gist_extraction import (
    extract_gist,
    format_artifact_pointer,
    needs_gist,
)
from mcp_server.infrastructure.artifact_store import store_artifact

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
    return store.call_batch(backfill_log_hash, str(path)) == current_hash


def mark_backfilled(store: MemoryStore, path: Path, fhash: str, count: int) -> None:
    """Record that a file has been backfilled.

    Phase 5: batch pool.
    """
    store.call_batch(record_backfill, str(path), fhash, count)


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
        # source: ADR-0333
        for jsonl_file in sorted(project_dir.rglob("*.jsonl"), reverse=True):
            parent = jsonl_file.parent
            accept = (
                parent == project_dir
                or parent.name == jsonl_file.stem
                or jsonl_file.name.startswith("agent-")
            )
            if not accept:
                continue
            results.append((jsonl_file, slug))
            if len(results) >= limit:
                break

    return results[:limit]


def slug_to_domain(slug: str) -> str:
    """Convert a project slug like '-Users-you-project-name' to a canonical domain.

    source: ADR-0333"""

    return resolve_domain(slug)


# -- Oversized-content gist gate (shared by import + backfill) --


def gist_oversized_content(content: str) -> str:
    """Gist + artifact-pointer an extracted item's content if it is oversized.

    source: ADR-0333"""

    if not needs_gist(content):
        return content
    try:
        path = store_artifact(content)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("backfill.artifact_store", exc)
        return content
    pointer = format_artifact_pointer(str(path), len(content))
    return f"{extract_gist(content)}\n\n{pointer}"


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
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("backfill.concept_entity_upsert", exc)
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
        except Exception as exc:  # noqa: BLE001 — per-link failure must not abort the batch
            silent_failure.note("backfill.concept_link", exc)
    return linked
