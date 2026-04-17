"""Wiki page templates + naming conventions.

Source: user directive "agent or llm on side to write with template and
naming conventions — keep the documentation organized".

Each page kind has:
  * A canonical front-matter schema (required fields + types)
  * A template body with labelled sections
  * A naming convention (slug pattern + path discipline)

The doc-grooming agent uses these templates to rewrite pages that drift
off-template. Human authors (or LLM-authored pages) should also follow
them — the agent won't overwrite a hand-written page whose front-matter
declares ``grooming: manual``.

All templates are pure strings with ``{{var}}`` placeholders. The
grooming agent fills placeholders from the existing page content +
metadata before rewriting.
"""

from __future__ import annotations

from typing import Final

# ── Required front-matter fields per page kind ──────────────────────────

REQUIRED_FRONTMATTER: Final[dict[str, tuple[str, ...]]] = {
    "adr": ("id", "title", "status", "date", "context", "decision", "consequences"),
    "specs": ("title", "status", "owner", "created", "updated"),
    "guides": ("title", "audience", "prerequisites", "updated"),
    "reference": ("title", "scope", "updated"),
    "conventions": ("title", "applies_to", "updated"),
    "lessons": ("title", "date", "triggering_event", "updated"),
    "notes": ("title", "updated"),
    "journal": ("title", "date"),
    "files": ("file_path", "language", "updated"),
}

# Valid values for `status` field (ADR + specs).
STATUS_VALUES: Final[dict[str, tuple[str, ...]]] = {
    "adr": ("proposed", "accepted", "rejected", "deprecated", "superseded"),
    "specs": ("draft", "review", "accepted", "implemented", "deprecated"),
}


# ── Templates ────────────────────────────────────────────────────────────


ADR_TEMPLATE = """---
id: {{id}}
title: {{title}}
status: {{status}}
date: {{date}}
supersedes: {{supersedes}}
---

# ADR-{{id}}: {{title}}

## Status

{{status}}

## Context

{{context}}

## Decision

{{decision}}

## Consequences

### Positive
{{consequences_positive}}

### Negative
{{consequences_negative}}

### Neutral
{{consequences_neutral}}

## Alternatives considered

{{alternatives}}

## References

{{references}}
"""


SPEC_TEMPLATE = """---
title: {{title}}
status: {{status}}
owner: {{owner}}
created: {{created}}
updated: {{updated}}
---

# {{title}}

## Problem

{{problem}}

## Goals

{{goals}}

## Non-goals

{{non_goals}}

## Design

{{design}}

## Invariants

{{invariants}}

## Open questions

{{open_questions}}

## References

{{references}}
"""


GUIDE_TEMPLATE = """---
title: {{title}}
audience: {{audience}}
prerequisites: {{prerequisites}}
updated: {{updated}}
---

# {{title}}

## When to use

{{when_to_use}}

## Prerequisites

{{prerequisites_detail}}

## Steps

{{steps}}

## Verification

{{verification}}

## Troubleshooting

{{troubleshooting}}
"""


REFERENCE_TEMPLATE = """---
title: {{title}}
scope: {{scope}}
updated: {{updated}}
---

# {{title}}

## Scope

{{scope_detail}}

## API / Interface

{{api}}

## Examples

{{examples}}

## See also

{{see_also}}
"""


CONVENTION_TEMPLATE = """---
title: {{title}}
applies_to: {{applies_to}}
updated: {{updated}}
---

# {{title}}

## Rule

{{rule}}

## Rationale

{{rationale}}

## Examples

### Correct
{{correct_examples}}

### Incorrect
{{incorrect_examples}}

## Enforcement

{{enforcement}}
"""


LESSON_TEMPLATE = """---
title: {{title}}
date: {{date}}
triggering_event: {{triggering_event}}
updated: {{updated}}
---

# {{title}}

## What happened

{{what_happened}}

## Why it went wrong

{{root_cause}}

## What we learned

{{lesson}}

## Rule going forward

{{rule}}

## References

{{references}}
"""


NOTE_TEMPLATE = """---
title: {{title}}
updated: {{updated}}
---

# {{title}}

{{body}}
"""


JOURNAL_TEMPLATE = """---
title: {{title}}
date: {{date}}
---

# {{title}}

## Summary

{{summary}}

## Details

{{details}}
"""


FILE_TEMPLATE = """---
file_path: {{file_path}}
language: {{language}}
updated: {{updated}}
---

# {{file_path}}

## Purpose

{{purpose}}

## Public API

{{public_api}}

## Dependencies

{{dependencies}}

## Notes

{{notes}}
"""


TEMPLATES: Final[dict[str, str]] = {
    "adr": ADR_TEMPLATE,
    "specs": SPEC_TEMPLATE,
    "guides": GUIDE_TEMPLATE,
    "reference": REFERENCE_TEMPLATE,
    "conventions": CONVENTION_TEMPLATE,
    "lessons": LESSON_TEMPLATE,
    "notes": NOTE_TEMPLATE,
    "journal": JOURNAL_TEMPLATE,
    "files": FILE_TEMPLATE,
}


def template_for(kind: str) -> str | None:
    """Return the template for a page kind, or None if unknown."""
    return TEMPLATES.get(kind)


def required_fields(kind: str) -> tuple[str, ...]:
    """Return the required front-matter keys for a page kind."""
    return REQUIRED_FRONTMATTER.get(kind, ("title", "updated"))


def valid_status_values(kind: str) -> tuple[str, ...]:
    """Return the valid ``status`` values for a page kind, or ()."""
    return STATUS_VALUES.get(kind, ())


# ── Naming conventions ───────────────────────────────────────────────────


class NamingConvention:
    """Canonical naming rules per page kind.

    Each rule pair ``(regex_pattern, description)`` defines how a slug
    must be shaped. The grooming agent applies the rule to rename pages
    off the convention.
    """

    ADR = (
        r"^\d{4}-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        "ADR: <4-digit>-<kebab-slug>.md (e.g., 0042-prefer-plan-over-list.md)",
    )

    SPEC = (
        r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        "Spec: <kebab-slug>.md (e.g., phase-5-pool-admission-design.md)",
    )

    DEFAULT = (
        r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        "Page: <kebab-slug>.md — lowercase alphanum + hyphens, no "
        "underscores, no leading/trailing hyphens.",
    )


def naming_convention(kind: str) -> tuple[str, str]:
    """Return (regex_pattern, human description) for a page kind."""
    if kind == "adr":
        return NamingConvention.ADR
    if kind == "specs":
        return NamingConvention.SPEC
    return NamingConvention.DEFAULT
