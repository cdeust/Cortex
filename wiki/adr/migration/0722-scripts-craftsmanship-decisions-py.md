# ADR-0722: scripts/craftsmanship_decisions.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/craftsmanship_decisions.py`; original SHA-256 `c6d4dd6b5474436ca9fe5493965743389e87d4590960e1bcc03ae7943d664ca8`.

## Original docstring, lines 1–5

````text
"""Resolve explicit source decision IDs and verify the reviewed wiki mirror.

These integrity checks cannot be grandfathered through the size/debt baseline.
Paper citations and ordinary source paths retain their existing interpretation.
"""
````

