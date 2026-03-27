"""Memory decomposition: structure-aware chunking with entity enrichment.

Inspired by the ai-architect artifact chunking strategy: split at natural
structural boundaries (speaker turns for conversations, headings for
markdown), not arbitrary character limits. Each chunk carries extracted
entities for graph-based retrieval.

Chunking strategies:
  1. Conversation content: group by speaker turn pairs (2-3 exchanges)
  2. Markdown content: split at ## heading boundaries
  3. Short content (< threshold): pass through unchanged

Pure business logic — no I/O.
"""

from __future__ import annotations

import re

# ── Entity extraction patterns (conversational content) ──────────────────

_PERSON_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*)\b")

_QUOTED_RE = re.compile(r'"([^"]{3,60})"' r"|\u201c([^\u201d]{3,60})\u201d")

_PREFERENCE_RE = re.compile(
    r"\b(prefer|love|enjoy|like|hate|dislike|favorite|"
    r"fan of|into|passionate about|interested in)\b",
    re.IGNORECASE,
)

_ACTIVITY_RE = re.compile(
    r"\b(went to|visited|attended|started|began|joined|"
    r"signed up|enrolled|bought|purchased|got|received|"
    r"adopted|moved to|traveled to|came back from)\b",
    re.IGNORECASE,
)

_DECISION_RE = re.compile(
    r"\b(decided|chose|plan to|going to|will|want to|"
    r"thinking about|considering|from now on|always|never)\b",
    re.IGNORECASE,
)

# Stopwords for person name filtering
_COMMON_WORDS = frozenset(
    {
        "Date",
        "The",
        "This",
        "That",
        "These",
        "Those",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "How",
        "Why",
        "Yes",
        "Hey",
        "Hello",
        "Sure",
        "Really",
        "Beautiful",
        "Awesome",
        "Amazing",
        "Wow",
        "Nice",
        "Cool",
        "Right",
        "Actually",
        "Honestly",
        "Absolutely",
        "Definitely",
        "Sounds",
        "Congrats",
        "Congratulations",
        "Sorry",
        "Speaker",
        "Thanks",
        "Thank",
        "Good",
        "Great",
        "Well",
        "Also",
        "But",
        "And",
        "For",
        "Not",
        "Can",
        "Did",
        "Does",
        "Has",
        "Have",
        "Had",
        "Was",
        "Were",
        "Are",
        "Been",
        "Being",
        "May",
        "June",
        "July",
        "August",
        "March",
        "April",
        "January",
        "February",
        "September",
        "October",
        "November",
        "December",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
)


# ── Structural boundary detection ────────────────────────────────────────

_SPEAKER_LINE_RE = re.compile(r"^\[([^\]]+)\]:\s*", re.MULTILINE)
_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
_DATE_PREFIX_RE = re.compile(r"^(\[Date:[^\]]*\])\s*\n?")


# ── Entity extraction ────────────────────────────────────────────────────


def extract_conversational_entities(content: str) -> dict:
    """Extract named entities from conversational content."""
    persons = []
    seen: set[str] = set()
    for m in _PERSON_RE.finditer(content):
        name = m.group(1)
        if name not in _COMMON_WORDS and len(name) > 2 and name not in seen:
            seen.add(name)
            persons.append(name)

    quoted = []
    for m in _QUOTED_RE.finditer(content):
        term = m.group(1) or m.group(2)
        if term:
            quoted.append(term.strip())

    return {
        "persons": persons[:20],
        "quoted_terms": quoted[:10],
        "has_preference": bool(_PREFERENCE_RE.search(content)),
        "has_activity": bool(_ACTIVITY_RE.search(content)),
        "has_decision": bool(_DECISION_RE.search(content)),
    }


def build_entity_summary(entities: dict) -> str:
    """Build a compact entity summary string for embedding enrichment."""
    parts = []
    if entities.get("persons"):
        parts.append("People: " + ", ".join(entities["persons"][:5]))
    if entities.get("quoted_terms"):
        parts.append("Topics: " + ", ".join(entities["quoted_terms"][:3]))
    tags = []
    if entities.get("has_preference"):
        tags.append("preference")
    if entities.get("has_activity"):
        tags.append("activity")
    if entities.get("has_decision"):
        tags.append("decision")
    if tags:
        parts.append("Type: " + ", ".join(tags))
    return " | ".join(parts)


# ── Structure-aware decomposition ────────────────────────────────────────


def decompose_memory(
    content: str,
    turns_per_chunk: int = 4,
    min_chunk_chars: int = 100,
) -> list[dict]:
    """Decompose memory content at natural structural boundaries.

    Strategy selection:
      - Conversation content (has [Speaker]: lines): group by turn pairs
      - Markdown content (has ## headings): split at heading boundaries
      - Other/short content: return as single chunk

    Each chunk gets entity extraction for retrieval enrichment.

    Args:
        content: Memory content to decompose.
        turns_per_chunk: Number of speaker turns per conversation chunk.
        min_chunk_chars: Minimum chars for a chunk to be kept.

    Returns:
        List of {content, entities} dicts.
    """
    content = content.strip()
    if not content:
        return []

    # Extract date prefix — will be prepended to every chunk
    date_prefix = ""
    date_match = _DATE_PREFIX_RE.match(content)
    if date_match:
        date_prefix = date_match.group(1) + "\n"
        content = content[date_match.end() :]

    # Detect content type and dispatch
    has_speakers = bool(_SPEAKER_LINE_RE.search(content))
    has_headings = bool(_HEADING_RE.search(content))

    if has_speakers:
        chunks = _chunk_by_turns(content, date_prefix, turns_per_chunk, min_chunk_chars)
    elif has_headings:
        chunks = _chunk_by_headings(content, date_prefix, min_chunk_chars)
    else:
        # No structural boundaries — return as single chunk
        full = date_prefix + content if date_prefix else content
        return [{"content": full, "entities": extract_conversational_entities(full)}]

    if not chunks:
        full = date_prefix + content if date_prefix else content
        return [{"content": full, "entities": extract_conversational_entities(full)}]

    return [
        {"content": c, "entities": extract_conversational_entities(c)} for c in chunks
    ]


def _chunk_by_turns(
    content: str,
    date_prefix: str,
    turns_per_chunk: int,
    min_chunk_chars: int,
) -> list[str]:
    """Split conversation at speaker turn boundaries.

    Groups N consecutive turns into each chunk. Every chunk gets the
    date prefix for temporal context.
    """
    # Split into individual turns
    turns: list[str] = []
    current = ""
    for line in content.split("\n"):
        if _SPEAKER_LINE_RE.match(line) and current.strip():
            turns.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        turns.append(current.strip())

    if len(turns) <= turns_per_chunk:
        # Too few turns to split — return as single chunk
        return []

    # Group turns into chunks
    chunks: list[str] = []
    for i in range(0, len(turns), turns_per_chunk):
        group = turns[i : i + turns_per_chunk]
        chunk_text = date_prefix + "\n".join(group)
        if len(chunk_text) >= min_chunk_chars:
            chunks.append(chunk_text)

    return chunks


def _chunk_by_headings(
    content: str,
    date_prefix: str,
    min_chunk_chars: int,
) -> list[str]:
    """Split markdown at ## heading boundaries."""
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        chunk_text = date_prefix + section if date_prefix else section
        if len(chunk_text) >= min_chunk_chars:
            chunks.append(chunk_text)
    return chunks
