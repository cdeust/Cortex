"""Knowledge graph entity extraction — typed entity/relationship detection from content.

Extracts entities (functions, dependencies, errors, decisions, technologies)
and typed relationships (imports, calls, resolved_by, decided_to_use, co_occurrence)
from memory content using regex-based heuristics. No LLM needed.

Pure business logic — no I/O. Storage is handled by the caller.

Clean architecture split: core = extraction logic, infrastructure = persistence.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Valid relationship types
VALID_REL_TYPES = frozenset(
    {
        "co_occurrence",
        "imports",
        "calls",
        "debugged_with",
        "decided_to_use",
        "caused_by",
        "resolved_by",
        "preceded_by",
        "derived_from",
    }
)

# Entity types
ENTITY_TYPES = frozenset(
    {
        "function",
        "dependency",
        "error",
        "decision",
        "technology",
        "file",
        "variable",
    }
)

# ── Extraction patterns ──────────────────────────────────────────────────

_IMPORT_FULL_RE = re.compile(r"(?:^|\n)\s*import\s+([\w.]+)")
_FROM_IMPORT_RE = re.compile(r"(?:^|\n)\s*from\s+([\w.]+)\s+import\s+([\w, ]+)")
_DEF_RE = re.compile(r"\bdef\s+(\w+)\s*\(")
_CLASS_RE = re.compile(r"\bclass\s+(\w+)")
_CALL_RE = re.compile(r"\b(\w+)\s*\(")
_ERROR_FIX_RE = re.compile(
    r"(?:fix(?:ed)?|resolv(?:ed|e|ing)|solved?)\s+(?:the\s+)?(\w*(?:Error|Exception|error|bug|issue))",
    re.IGNORECASE,
)
_DECIDED_RE = re.compile(
    r"decided\s+to\s+use\s+(\w+(?:\s+\w+){0,2})\s+instead\s+of\s+(\w+(?:\s+\w+){0,2})",
    re.IGNORECASE,
)
_FILE_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w@.-]+/)+[\w@.-]+\.\w+")
_CAMELCASE_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:[A-Z][a-zA-Z]+)+\b")


def _extract_import_entities(content: str) -> list[tuple[str, str, str]]:
    """Extract dependency and function entities from import statements."""
    results: list[tuple[str, str, str]] = []
    for m in _FROM_IMPORT_RE.finditer(content):
        module = m.group(1)
        names = [n.strip() for n in m.group(2).split(",")]
        results.append((module, "dependency", ""))
        for name in names:
            if name and len(name) > 1:
                results.append((name, "function", "imports"))

    for m in _IMPORT_FULL_RE.finditer(content):
        results.append((m.group(1), "dependency", ""))
    return results


def _extract_definition_entities(
    content: str,
) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Extract function and class definition entities. Returns (entities, defined_func_names)."""
    results: list[tuple[str, str, str]] = []
    defined_funcs: set[str] = set()

    for m in _DEF_RE.finditer(content):
        fname = m.group(1)
        if fname.startswith("_") and len(fname) < 3:
            continue
        defined_funcs.add(fname)
        results.append((fname, "function", ""))

    for m in _CLASS_RE.finditer(content):
        results.append((m.group(1), "technology", ""))

    return results, defined_funcs


def _extract_pattern_entities(
    content: str, defined_funcs: set[str]
) -> list[tuple[str, str, str]]:
    """Extract error-fix, decision, file path, and CamelCase entities."""
    results: list[tuple[str, str, str]] = []

    for m in _ERROR_FIX_RE.finditer(content):
        results.append((m.group(1), "error", "resolved_by"))

    for m in _DECIDED_RE.finditer(content):
        results.append((m.group(1).strip(), "decision", "decided_to_use"))
        results.append((m.group(2).strip(), "decision", "decided_to_use"))

    for m in _FILE_PATH_RE.finditer(content):
        results.append((m.group(0), "file", ""))

    for m in _CAMELCASE_RE.finditer(content):
        name = m.group(0)
        if name not in defined_funcs and len(name) > 2:
            results.append((name, "technology", ""))

    return results


def _deduplicate_entities(results: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """Deduplicate entity tuples preserving insertion order."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for name, etype, rel_ctx in results:
        key = (name, etype, rel_ctx)
        if key not in seen:
            seen.add(key)
            unique.append(
                {
                    "name": name,
                    "type": etype,
                    "relationship_context": rel_ctx,
                }
            )
    return unique


def extract_entities(content: str) -> list[dict[str, str]]:
    """Extract typed entities from content.

    Returns list of {name, type, relationship_context} dicts.
    relationship_context is empty string unless the entity implies a relationship.
    """
    results: list[tuple[str, str, str]] = []
    results.extend(_extract_import_entities(content))
    defn_entities, defined_funcs = _extract_definition_entities(content)
    results.extend(defn_entities)
    results.extend(_extract_pattern_entities(content, defined_funcs))
    return _deduplicate_entities(results)


def _find_entity_positions(
    entity_names: list[str],
    content_lower: str,
) -> list[tuple[str, list[int]]]:
    """Find all character positions for each entity name in content."""
    positions: dict[str, list[int]] = defaultdict(list)
    for name in entity_names:
        name_lower = name.lower()
        start = 0
        while True:
            idx = content_lower.find(name_lower, start)
            if idx == -1:
                break
            positions[name].append(idx)
            start = idx + 1
    return [(n, ps) for n, ps in positions.items() if ps]


def _min_pair_distance(pos_a: list[int], pos_b: list[int]) -> float:
    """Compute minimum distance between two sets of positions."""
    min_dist = float("inf")
    for pa in pos_a:
        for pb in pos_b:
            dist = abs(pa - pb)
            if dist < min_dist:
                min_dist = dist
    return min_dist


def detect_co_occurrences(
    entity_names: list[str],
    content: str,
    window_chars: int = 500,
) -> list[tuple[str, str, float]]:
    """Detect co-occurring entities within a character window.

    Returns (entity_a, entity_b, proximity_score) triples.
    Proximity score is inversely proportional to distance.
    """
    names_with_pos = _find_entity_positions(entity_names, content.lower())

    results: list[tuple[str, str, float]] = []
    for i, (name_a, pos_a) in enumerate(names_with_pos):
        for name_b, pos_b in names_with_pos[i + 1 :]:
            min_dist = _min_pair_distance(pos_a, pos_b)
            if min_dist <= window_chars:
                proximity = 1.0 - (min_dist / window_chars)
                results.append((name_a, name_b, round(proximity, 4)))

    return results


def _group_entities_by_context(
    entities: list[dict[str, str]],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Group entities into importers, dependencies, resolved, and decisions."""
    importers: list[str] = []
    dependencies: list[str] = []
    resolved: list[str] = []
    decisions: list[str] = []

    for e in entities:
        ctx = e.get("relationship_context", "")
        if ctx == "imports":
            importers.append(e["name"])
        elif e["type"] == "dependency":
            dependencies.append(e["name"])
        elif ctx == "resolved_by":
            resolved.append(e["name"])
        elif ctx == "decided_to_use":
            decisions.append(e["name"])

    return importers, dependencies, resolved, decisions


def infer_relationships(
    entities: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Infer typed relationships between extracted entities.

    Uses relationship_context from extraction to create edges.
    """
    importers, dependencies, resolved, decisions = _group_entities_by_context(entities)
    relationships: list[dict[str, str]] = []

    for imp in importers:
        for dep in dependencies:
            relationships.append(
                {
                    "source": dep,
                    "target": imp,
                    "type": "imports",
                }
            )

    for err in resolved:
        relationships.append(
            {
                "source": err,
                "target": "",
                "type": "resolved_by",
            }
        )

    if len(decisions) >= 2:
        relationships.append(
            {
                "source": decisions[0],
                "target": decisions[1],
                "type": "decided_to_use",
            }
        )

    return relationships
