"""Curation-gap detector for file-doc pages.

source: ADR-0299"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


# ── Section catalogue for a file-doc page ──────────────────────────
#
# Every file-doc page should answer these questions. Each entry has:
#   - ``name`` — slug used in frontmatter ``curation_gaps``.
#   - ``heading`` — the H2 the LLM should write under.
#   - ``probes`` — patterns that, if present in the body, signal the
#     section is covered. A page satisfies the section when at least
#     one probe hits — usually the heading itself plus content under it.
#   - ``min_chars_under_heading`` — extra signal: a heading present
#     but with under N chars of prose under it doesn't count as
#     covered (it's a placeholder skeleton).
#   - ``description`` — what the LLM should write under this heading.


@dataclass(frozen=True)
class CurationSection:
    name: str
    heading: str
    probes: tuple[str, ...]
    min_chars_under_heading: int
    description: str


# source: ADR-0299


FILE_DOC_SECTIONS: Final[tuple[CurationSection, ...]] = (
    CurationSection(
        name="purpose",
        heading="## Purpose",
        probes=("## Purpose", "## What this file does"),
        min_chars_under_heading=200,
        description=(
            "What this file is responsible for, in two to four sentences. "
            "Not a restatement of the filename — what behaviour it owns, "
            "what it must NOT do, where its boundary lies."
        ),
    ),
    CurationSection(
        name="public-api",
        heading="## Public API",
        probes=("## Public API", "## API", "## Exports"),
        min_chars_under_heading=150,
        description=(
            "Each exported symbol (function, class, constant) with a "
            "one-line semantic — what it does, what it returns, when "
            "to call it. NOT a bare list of names."
        ),
    ),
    CurationSection(
        name="dependencies",
        heading="## Dependencies",
        probes=("## Dependencies", "## Imports", "## Uses"),
        min_chars_under_heading=80,
        description=(
            "Why each import is here. 'json' is uninteresting; "
            "'sentence_transformers' (the embedding model) is. "
            "Group standard-library imports separately."
        ),
    ),
    CurationSection(
        name="callers",
        heading="## Callers",
        probes=("## Callers", "## Used by", "## Consumers"),
        min_chars_under_heading=100,
        description=(
            "Which files in the project depend on this one. The author "
            "should grep the repo for imports of this module and list "
            "the top callers with one-line context."
        ),
    ),
    CurationSection(
        name="behaviour",
        heading="## How it works",
        probes=("## How it works", "## Behaviour", "## Behavior", "## Implementation"),
        min_chars_under_heading=400,
        description=(
            "Walk through the file's main flow: entry point, key "
            "branches, state transitions. Diagram (mermaid) preferred "
            "for anything sequence-shaped."
        ),
    ),
    CurationSection(
        name="invariants",
        heading="## Invariants",
        probes=("## Invariants", "## Constraints", "## Contracts"),
        min_chars_under_heading=80,
        description=(
            "What must always be true about this file's outputs / "
            "internal state. Layer-boundary contracts, type guarantees, "
            "thread-safety, idempotency. Empty 'none' is fine when "
            "truly none — say so explicitly."
        ),
    ),
    CurationSection(
        name="failure-modes",
        heading="## What can go wrong",
        probes=("## What can go wrong", "## Failure modes", "## Errors"),
        min_chars_under_heading=120,
        description=(
            "How this file can fail in production and what the symptom "
            "looks like. The reader should be able to recognise the "
            "failure from a stack trace or log line."
        ),
    ),
    CurationSection(
        name="tests",
        heading="## Tests",
        probes=("## Tests", "## Test coverage", "## Testing"),
        min_chars_under_heading=80,
        description=(
            "Which test files exercise this file. Path + brief on what "
            "each test covers."
        ),
    ),
    CurationSection(
        name="sequence-diagram",
        heading="## Sequence diagram",
        probes=(
            "## Sequence diagram",
            "## Sequence",
            "```mermaid\nsequenceDiagram",
        ),
        min_chars_under_heading=120,
        description=(
            "A `mermaid` sequence diagram of the typical call flow "
            "involving this file — caller → this file → callees → "
            "return. Render with ```mermaid sequenceDiagram fences. "
            "For files that participate in no sequence (pure data "
            'types, constants), explicitly write "Not applicable — '
            'this file participates in no sequence flow" and explain '
            "why."
        ),
    ),
    CurationSection(
        name="flow-diagram",
        heading="## Flow diagram",
        probes=(
            "## Flow diagram",
            "## Flowchart",
            "## State diagram",
            "```mermaid\nflowchart",
            "```mermaid\nstateDiagram",
        ),
        min_chars_under_heading=120,
        description=(
            "A `mermaid` flowchart (or state diagram) of the file's "
            "branching logic, lifecycle, or decision tree. Use "
            "```mermaid flowchart TD/LR``` fences for branching, "
            "```mermaid stateDiagram-v2``` for state machines. "
            "Distinct from the sequence diagram above (sequenceDiagram "
            "covers call traces between participants; flowchart covers "
            "branching / lifecycle / trees within a single component). "
            'For files with no branching to depict, write "Not '
            'applicable" and explain why.'
        ),
    ),
    CurationSection(
        name="parameters",
        heading="## Parameters",
        probes=("## Parameters", "## Arguments", "## Options"),
        min_chars_under_heading=120,
        description=(
            "Exhaustive table of every parameter exposed by this "
            "file's public entry points. Columns: name | type | "
            "required | default | description. For files with no "
            "external parameter surface (internal helpers, pure "
            'data), write "Not applicable — this file exposes no '
            'external parameters."'
        ),
    ),
    CurationSection(
        name="request-example",
        heading="## Request example",
        probes=(
            "## Request example",
            "## Example request",
            "## Request",
            "## Invocation example",
        ),
        min_chars_under_heading=120,
        description=(
            "A concrete request example — for HTTP handlers, the "
            "full curl command including headers (Content-Type, "
            "Authorization, custom headers); for MCP tools, the "
            "JSON-RPC envelope with `method` and `params`; for "
            "library functions, the call site as it would appear "
            "in client code. Show headers explicitly — never omit "
            "them. For files that don't sit on a request boundary, "
            'write "Not applicable — this file is not invoked '
            'directly by callers; see [[Callers]] for the call chain."'
        ),
    ),
    CurationSection(
        name="response-example",
        heading="## Response example",
        probes=(
            "## Response example",
            "## Example response",
            "## Response",
            "## Return value",
        ),
        min_chars_under_heading=120,
        description=(
            "A concrete response example showing every field the "
            "caller receives — JSON for HTTP / MCP, return-value "
            "structure for library functions. Each non-obvious "
            "field annotated with one line explaining what it "
            "means. Include both success and the most common "
            "error shape if applicable. For files that produce "
            'no response surface, write "Not applicable — this '
            'file does not produce a response artifact."'
        ),
    ),
)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _section_body(body: str, heading: str) -> str | None:
    """Return the prose under ``heading`` (up to the next H2+) or None."""
    target = heading.strip()
    lines = body.splitlines()
    in_section = False
    out: list[str] = []
    target_depth: int | None = None
    for ln in lines:
        m = _HEADING_RE.match(ln)
        if m:
            depth = len(m.group(1))
            text = ("#" * depth) + " " + m.group(2).strip()
            if text == target:
                in_section = True
                target_depth = depth
                continue
            if in_section and depth <= (target_depth or 99):
                break
        if in_section:
            out.append(ln)
    if not in_section:
        return None
    return "\n".join(out).strip()


def _meaningful_chars(text: str) -> int:
    """Count chars of real prose (skip blank lines, bullets, fences)."""
    count = 0
    in_fence = False
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith(("#", "-", "*", "+")):
            continue
        count += len(s)
    return count


def missing_sections(body: str) -> list[CurationSection]:
    """Return the canonical sections this file-doc is missing.

    A section is considered missing when EITHER:
      * No probe heading appears in the body, OR
      * A probe heading appears but has fewer than its
        ``min_chars_under_heading`` of prose under it.
    """
    out: list[CurationSection] = []
    for section in FILE_DOC_SECTIONS:
        found = False
        for probe in section.probes:
            sec_body = _section_body(body, probe)
            if sec_body is None:
                continue
            found = True
            if _meaningful_chars(sec_body) >= section.min_chars_under_heading:
                # Section present AND substantive.
                found = True
                break
            # Heading exists but body is too thin — count as missing.
            found = False
        if not found:
            out.append(section)
    return out
