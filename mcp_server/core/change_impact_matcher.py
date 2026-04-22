"""Phase 4 (ADR-0046) — match code-change impact sets to memories.

Given:
  * a set of impacted qualified names (from ``ap.detect_changes`` /
    ``ap.get_impact``),
  * a set of file paths touched by the commit,
  * an iterable of memory rows (``{memory_id, content, tags, ...}``),

return a deterministic list of ``(memory_id, matched_terms)`` pairs
identifying memories whose content mentions any impacted symbol or file.

Pure logic — no I/O. Case-insensitive substring match on the *content*
field plus tag intersection. The handler is responsible for deciding
what to do with the matches (heat bump, tag annotation, user report).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImpactMatch:
    """A single memory touched by a change-impact set."""

    memory_id: int | str
    matched_symbols: list[str]
    matched_files: list[str]
    match_count: int


def _tail_of_qualname(q: str) -> str:
    """Return the last identifier of a dotted qualname, e.g.
    ``foo.Bar.baz`` → ``baz``. Used to widen the match —- memories
    often mention ``baz()`` without its module prefix."""
    return q.rsplit(".", 1)[-1] if "." in q else q


def _basename(path: str) -> str:
    if not path:
        return ""
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def match_memories(
    *,
    impacted_symbols: list[str],
    impacted_files: list[str],
    memories: list[dict],
    id_key: str = "memory_id",
) -> list[ImpactMatch]:
    """Return a deterministic list of memories touched by the impact set.

    A memory matches if:
      * its ``content`` mentions any impacted symbol (or its tail name),
      * OR any impacted file path (or its basename),
      * OR its ``tags`` list intersects the impacted-file basenames.

    The match is case-insensitive. Results are ordered by descending
    match_count then ascending id so the output is stable across runs.
    """
    sym_terms = [(q, _tail_of_qualname(q)) for q in impacted_symbols if q]
    file_terms = [(p, _basename(p)) for p in impacted_files if p]

    out: list[ImpactMatch] = []
    for m in memories or []:
        mid = m.get(id_key) if id_key in m else m.get("id")
        if mid is None:
            continue
        content = (m.get("content") or "").lower()
        tags = {str(t).lower() for t in (m.get("tags") or [])}

        matched_symbols: list[str] = []
        for full, tail in sym_terms:
            if full.lower() in content or (tail and tail.lower() in content):
                matched_symbols.append(full)

        matched_files: list[str] = []
        for full, base in file_terms:
            if full.lower() in content or (base and base.lower() in content):
                matched_files.append(full)
            elif base and base.lower() in tags:
                matched_files.append(full)

        total = len(matched_symbols) + len(matched_files)
        if total == 0:
            continue
        out.append(
            ImpactMatch(
                memory_id=mid,
                matched_symbols=matched_symbols,
                matched_files=matched_files,
                match_count=total,
            )
        )

    out.sort(key=lambda im: (-im.match_count, str(im.memory_id)))
    return out


__all__ = ["ImpactMatch", "match_memories"]
