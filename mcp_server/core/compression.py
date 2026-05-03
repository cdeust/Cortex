"""Rate-distortion memory compression — progressive fidelity degradation.

Memories degrade from full content -> gist -> tags as they age,
following information-theoretic optimal forgetting:
  Level 0 (recent): Full fidelity — complete content preserved
  Level 1 (medium): Gist — key sentences + code snippets + entities
  Level 2 (old):    Tag  — one-line summary + semantic tags

High importance/surprise memories resist compression (get more bits).
Protected and semantic-store memories are never compressed.

Pure business logic — no I/O. Storage/embedding operations handled by caller.

Based on Toth et al. (PLoS Comp Bio, 2020), MemFly (2025), Tishby (1999).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Patterns for scoring sentence information density
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_FILE_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w@.-]+/)+[\w@.-]+\.\w+")
_ERROR_RE = re.compile(r"\b\w*(?:Error|Exception|Traceback)\b")
_DECISION_RE = re.compile(
    r"\b(?:decided|chose|choosing|using|switched|migrated|replaced|selected|adopted)\b",
    re.IGNORECASE,
)
_NUMBER_VERSION_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
_CAMELCASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")


def _parse_ingested_at(memory: dict) -> datetime | None:
    """Parse ingest timestamp for cadence reasoning.

    Compression cadence asks "has this memory had time to be revisited
    in MY system" — that is elapsed time since ingest, NOT elapsed time
    since the original event. Backfilled / imported memories carry a
    backdated created_at (e.g. a 2023 conversation imported in 2026);
    using created_at would compress them on the first consolidation
    pass, before retrieval ever runs (see tasks/e1-v3-locomo-smoke-finding.md).

    Falls back to created_at for legacy rows that predate the
    ingested_at column (the schema migration in pg_schema.py backfills
    ingested_at = created_at in that case anyway, so the fallback only
    matters for in-memory dicts that never round-tripped through PG).
    """
    raw = memory.get("ingested_at") or memory.get("created_at", "")
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_resistance(memory: dict) -> float:
    """Compute compression resistance multiplier from memory attributes."""
    resistance = 1.0
    if memory.get("importance", 0.5) > 0.7:
        resistance *= 2.0
    if memory.get("surprise_score", 0.0) > 0.6:
        resistance *= 1.5
    if memory.get("confidence", 1.0) > 0.8:
        resistance *= 1.3
    if memory.get("access_count", 0) > 10:
        resistance *= 1.5
    return resistance


def get_compression_schedule(
    memory: dict,
    gist_age_hours: float = 168.0,
    tag_age_hours: float = 720.0,
) -> int:
    """Calculate target compression level based on age and importance.

    Returns:
        0 = full fidelity, 1 = gist, 2 = tag
    """
    if memory.get("is_protected", False):
        return 0
    if memory.get("store_type", "episodic") == "semantic":
        return 0

    ingested_at = _parse_ingested_at(memory)
    if ingested_at is None:
        return 0

    # Cadence is measured from ingest, not from the original event.
    # Source: tasks/e1-v3-locomo-smoke-finding.md.
    hours_elapsed = (datetime.now(timezone.utc) - ingested_at).total_seconds() / 3600.0
    resistance = _compute_resistance(memory)

    if hours_elapsed < gist_age_hours * resistance:
        return 0
    elif hours_elapsed < tag_age_hours * resistance:
        return 1
    else:
        return 2


def _select_gist_sentences(
    sentences: list[str],
    code_blocks: list[str],
    target_length: float,
) -> list[str]:
    """Score and select sentences for gist extraction."""
    scored: list[tuple[int, str, float]] = []
    for i, sent in enumerate(sentences):
        score = _score_sentence(sent)
        if i == 0:
            score += 10.0  # Primacy
        if i == len(sentences) - 1:
            score += 8.0  # Recency
        scored.append((i, sent, score))

    scored.sort(key=lambda x: x[2], reverse=True)

    selected: set[int] = {0, len(sentences) - 1}
    current_length = sum(len(cb) for cb in code_blocks)
    for idx, sent, _ in scored:
        if current_length >= target_length:
            break
        selected.add(idx)
        current_length += len(sent)

    return [sentences[i] for i in sorted(selected)]


def extract_gist(content: str, target_ratio: float = 0.3) -> str:
    """Extract gist from full content (compression level 1).

    Strategy:
      1. Preserve all code blocks verbatim
      2. Score sentences by information density
      3. Keep first + last sentences (primacy-recency effect)
      4. Target ~30% of original length
    """
    code_blocks = _CODE_BLOCK_RE.findall(content)
    text_without_code = _CODE_BLOCK_RE.sub("", content)

    sentences = _split_sentences(text_without_code)
    if not sentences:
        return "\n\n".join(code_blocks) if code_blocks else content

    if len(sentences) <= 3:
        parts = list(sentences)
        if code_blocks:
            parts.extend(code_blocks)
        return "\n".join(parts)

    target_length = max(len(content) * target_ratio, 50)
    gist_sentences = _select_gist_sentences(sentences, code_blocks, target_length)
    parts = gist_sentences
    if code_blocks:
        parts.extend(code_blocks)
    return "\n".join(parts)


def _extract_tag_entities(content: str, memory: dict) -> list[str]:
    """Collect entity names from content patterns and memory tags."""
    entities: set[str] = set()
    for m in _CAMELCASE_RE.finditer(content):
        entities.add(m.group(0))
    for m in _FILE_PATH_RE.finditer(content):
        entities.add(m.group(0))

    mem_tags = memory.get("tags", [])
    if isinstance(mem_tags, list):
        entities.update(t for t in mem_tags if isinstance(t, str))
    return sorted(entities)[:5]


def _format_created_date(memory: dict) -> str:
    """Extract a YYYY-MM-DD date string from memory's created_at."""
    created = memory.get("created_at", "")
    if not created:
        return "unknown"
    try:
        dt = datetime.fromisoformat(created)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return created[:10]


def _truncate_tag_repr(
    summary: str, tag_part: str, date_str: str, entity_list: list[str]
) -> str:
    """Assemble and truncate tag representation to 200 chars."""
    tag_repr = f"{summary} | Tags: {tag_part} | Created: {date_str}"
    if len(tag_repr) > 200:
        available = 200 - len(f" | Tags: {tag_part} | Created: {date_str}")
        if available > 10:
            summary = summary[: available - 3] + "..."
        else:
            summary = summary[:30] + "..."
            tag_part = ", ".join(entity_list[:2]) if entity_list else "general"
        tag_repr = f"{summary} | Tags: {tag_part} | Created: {date_str}"
    if len(tag_repr) > 200:
        tag_repr = tag_repr[:197] + "..."
    return tag_repr


def generate_tag(content: str, memory: dict) -> str:
    """Generate tag representation (compression level 2).

    Format: "[summary] | Tags: [entities] | Created: [date]"
    Target: < 200 characters.
    """
    entity_list = _extract_tag_entities(content, memory)
    sentences = _split_sentences(content)
    summary = sentences[0] if sentences else content[:80]
    date_str = _format_created_date(memory)
    tag_part = ", ".join(entity_list) if entity_list else "general"
    return _truncate_tag_repr(summary, tag_part, date_str, entity_list)


# ── Internal helpers ─────────────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, filtering empty."""
    raw = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in raw if s.strip()]


def _score_sentence(sentence: str) -> float:
    """Score a sentence by information density."""
    score = 0.0
    if _FILE_PATH_RE.search(sentence):
        score += 3.0
    if _ERROR_RE.search(sentence):
        score += 4.0
    if _DECISION_RE.search(sentence):
        score += 3.0
    if _NUMBER_VERSION_RE.search(sentence):
        score += 2.0
    if _CAMELCASE_RE.search(sentence):
        score += 2.0
    if "`" in sentence:
        score += 2.0
    return score
