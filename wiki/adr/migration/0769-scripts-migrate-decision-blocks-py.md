# ADR-0769: scripts/migrate_decision_blocks.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/migrate_decision_blocks.py`; original SHA-256 `2af13de88798df255380d223d85b78c8567c051b0e1199cc757d032f2e8685e2`.

## Original docstring, lines 1–6

````text
"""Inventory long decision comments; extract only an explicitly reviewed block.

Inventory never changes files. Apply requires the exact content hash, a new ADR
ID, title and filename slug. Runtime docstrings are inventoried but never moved:
changing __doc__ is not a comment-only refactor. See issue #514 / ADR-0056.
"""
````

## Original comment, lines 28–28

````text
# source: issue #514 investigation: decision blocks of 25+ lines are candidates.
````

