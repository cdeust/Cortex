"""Wiki bidirectional link maintenance — pure, deterministic.

Links live inside each page under a ``## Related`` section, rendered as
a sorted bullet list. ``apply_link`` is idempotent: adding the same link
twice produces identical output. Every relation has a fixed inverse so
``wiki_link(a, b, rel)`` can update both pages with the correct symmetry.

The relation vocabulary is intentionally small and hardcoded — extending
it requires a code change so consumers can rely on canonical semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fixed vocabulary: relation → its inverse.
RELATIONS: dict[str, str] = {
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "implements": "implemented_by",
    "implemented_by": "implements",
    "depends_on": "depended_on_by",
    "depended_on_by": "depends_on",
    "derived_from": "derives",
    "derives": "derived_from",
    "see_also": "see_also",
}

RELATED_HEADING = "## Related"


@dataclass(frozen=True)
class LinkEntry:
    relation: str
    target: str  # path (relative to wiki root) of the other page


def inverse_of(relation: str) -> str:
    """Return the inverse relation. Raises ``KeyError`` on unknown input."""
    return RELATIONS[relation]


def _format_entry(entry: LinkEntry) -> str:
    return f"- {entry.relation} → [{entry.target}]({entry.target})"


def _parse_entry(line: str) -> LinkEntry | None:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None
    payload = stripped[2:]
    if " → " not in payload:
        return None
    rel, _, rest = payload.partition(" → ")
    rel = rel.strip()
    if rel not in RELATIONS:
        return None
    # rest looks like "[target](target)" — extract the URL portion.
    target = rest.strip()
    if target.startswith("[") and "](" in target and target.endswith(")"):
        target = target.split("](", 1)[1][:-1]
    return LinkEntry(relation=rel, target=target)


def _split_body_and_related(body: str) -> tuple[str, list[LinkEntry]]:
    """Return (body_without_related, parsed_entries)."""
    lines = body.splitlines()
    heading_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == RELATED_HEADING:
            heading_idx = idx
            break
    if heading_idx is None:
        return body, []
    before = lines[:heading_idx]
    # Consume the existing related block until the next level-2 heading or EOF.
    entries: list[LinkEntry] = []
    idx = heading_idx + 1
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("## "):
            break
        parsed = _parse_entry(line)
        if parsed is not None:
            entries.append(parsed)
        idx += 1
    after = lines[idx:]
    # Drop trailing blank lines from ``before`` so re-rendering is stable.
    while before and before[-1] == "":
        before.pop()
    # ``after`` keeps any subsequent sections verbatim.
    rebuilt = "\n".join(before)
    if after:
        rebuilt = (rebuilt + "\n\n" if rebuilt else "") + "\n".join(after)
    return rebuilt, entries


def _render_related(entries: list[LinkEntry]) -> str:
    if not entries:
        return ""
    # Sort by (relation, target) for byte-stable output.
    sorted_entries = sorted(entries, key=lambda e: (e.relation, e.target))
    lines = [RELATED_HEADING, ""]
    lines.extend(_format_entry(e) for e in sorted_entries)
    return "\n".join(lines) + "\n"


def apply_link(body: str, entry: LinkEntry) -> str:
    """Add a link entry to the Related section. Idempotent.

    Preserves all other sections and the original body verbatim aside from
    the Related block, which is regenerated sorted.
    """
    if entry.relation not in RELATIONS:
        raise ValueError(f"unknown relation: {entry.relation}")
    base, existing = _split_body_and_related(body)
    merged: list[LinkEntry] = list(existing)
    if entry not in merged:
        merged.append(entry)
    rendered = _render_related(merged)
    if not base:
        return rendered
    separator = "" if base.endswith("\n") else "\n"
    return f"{base}{separator}\n{rendered}"
