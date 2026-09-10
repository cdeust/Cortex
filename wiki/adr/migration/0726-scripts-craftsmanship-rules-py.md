# ADR-0726: scripts/craftsmanship_rules.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/craftsmanship_rules.py`; original SHA-256 `c4c8e27d7210562e75bf16d825b0b16ede1cd3a86a73991942892ce1d9d24c18`.

## Original docstring, lines 1–21

````text
"""Craftsmanship detectors: file size, method size, layer imports, magic
numbers — the four rules ``docs/agent-guidance.md`` § Code Style states but nothing
checks (issue: no automated pre-commit hook exists, admitted in that
section before this gate).

Every detector returns a set of stable ``Violation`` identifiers — stable
meaning the identifier text does not change just because a line count
shifted elsewhere in the file (see each function's docstring). Stability is
what lets ``check_craftsmanship.py`` diff today's violations against a
baseline without every violation appearing "new" on every commit.

This module owns rules 1-2 (file size, method size) plus the ``Violation``
type and the ``scan_source`` aggregator; rules 3-4 (layer imports, magic
numbers) live in ``craftsmanship_imports.py`` / ``craftsmanship_constants.py``
— split out because keeping all four here crossed the very 300-line cap
this gate enforces (a gate that exempted itself would not be credible).

No I/O in this module — the caller reads the file; this module is pure AST
analysis, same discipline as ``core/`` (this file lives in ``scripts/``
where that boundary is a convention, not an enforced layer rule).
"""
````

## Original comment, lines 30–31

````text
# source: docs/agent-guidance.md § Code Style — "300 lines max per file" — a local
# tightening of coding-standards.md §4.1 (500).
````

## Original comment, lines 33–34

````text
# source: docs/agent-guidance.md § Code Style — "40 lines max per method" — a local
# tightening of coding-standards.md §4.2 (50).
````

## Original docstring, lines 55–62

````text
"""The file's leading run of comment/blank lines, joined.

    No fixed line count (a prior version hardcoded "scan the first 5
    lines", an arbitrary constant flagged in review): a header is
    naturally delimited by the first line that is neither blank nor a
    comment, so this handles a one-line marker or a multi-line license
    block identically, with nothing to source or justify.
    """
````

## Original docstring, lines 111–118

````text
"""Rule 2 — a function/method body spans more than METHOD_LINE_LIMIT
    lines, measured by AST (``end_lineno - lineno``) per the task
    instruction, never by regex.

    ``node.lineno`` is the ``def`` line itself (decorators carry their own
    ``lineno`` in the AST since Python 3.8), so a decorated function is
    measured by its own body, not inflated by its decorator lines.
    """
````

## Original comment, lines 129–137

````text
# Sibling modules, imported at module level (not function-local — ruff
# PLC0415) as bare ``import X`` rather than ``from X import Y``: each
# sibling's own top does ``from craftsmanship_rules import Violation``,
# which only needs ``Violation`` to already exist in THIS module's
# namespace — true from this point on, since it is defined above. A bare
# ``import X`` here binds the module object without touching any of its
# attributes yet, so it is safe regardless of which of the three modules
# Python loads first; only ``scan_source`` below, called later, actually
# dereferences into them.
````

