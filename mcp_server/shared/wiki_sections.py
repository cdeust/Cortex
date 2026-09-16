"""One reading of a wiki draft's sections: a heading and a body, both text.

A section reaches the pipeline either as a dict, from an MCP client through
`wiki_refine_draft`, or as a `Section` object from the template synthesizer,
and either field can be absent or hold something that is not text. Every
consumer used to spell that out for itself, and disagreed: the Markdown
renderer skipped a section with no heading while the `wiki.pages` mirror kept
it under an empty key, and the curator called `.strip()` on whatever it found.

source: ADR-1071"""

from __future__ import annotations

from typing import Any


def is_text(value: Any) -> bool:
    """Non-blank text. The shape a heading and a body must have."""
    return isinstance(value, str) and bool(value.strip())


def _field(section: Any, name: str) -> Any:
    if isinstance(section, dict):
        return section.get(name)
    return getattr(section, name, None)


def heading_of(section: Any) -> str | None:
    """The section's heading, stripped, or None when it carries no usable one."""
    heading = _field(section, "heading")
    return heading.strip() if is_text(heading) else None


def body_of(section: Any) -> str:
    """The section's body, or an empty string when it carries no text."""
    body = _field(section, "body")
    return body if is_text(body) else ""


def titled_sections(sections: Any) -> list[tuple[str, str]]:
    """The (heading, body) pairs a page can carry, in order.

    A section with no usable heading has nowhere to go on the page and is
    dropped, which is what the Markdown renderer has always done.
    """
    pairs: list[tuple[str, str]] = []
    for section in sections or []:
        heading = heading_of(section)
        if heading is not None:
            pairs.append((heading, body_of(section)))
    return pairs
