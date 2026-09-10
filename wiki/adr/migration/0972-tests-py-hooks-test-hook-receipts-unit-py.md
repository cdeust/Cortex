# ADR-0972: tests_py/hooks/test_hook_receipts_unit.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/hooks/test_hook_receipts_unit.py`, original SHA-256 `6cd28deed3fcd760e246c3fea7478552a5b867cff58cef7d34c6fda8d0dde9ab`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–14

````text
"""DB-free unit tests for the T2 hook receipt plumbing (decision 4255039).

Complements the PG-gated end-to-end tests in test_hook_receipts.py with
the branches those tests cannot reach deterministically:

* auto_recall's injection-budget drop — the parity invariant's teeth:
  a memory dropped by _MAX_INJECTION_CHARS was never in context and must
  not be attested by the receipt (correction 11). Killed mutants: moving
  ``included.append`` above the budget break, or returning the fetched
  list instead of the included one.
* the marker-less degradation rendering — a failed receipt write yields
  receipt_id=None and the banner must render WITHOUT a marker (I/O is
  the only named degradation mode; the injection itself never breaks).
"""
````

