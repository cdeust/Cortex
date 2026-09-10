# ADR-0960: tests_py/handlers/test_why.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/handlers/test_why.py`, original SHA-256 `add8112c0184c8057b7c6c24f3adfd8ec9f65612fcb3a85ea6e3a2d18b395ca4`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–14

````text
"""Unit tests for the why handler (blame path T3, decision 4255039).

Falsifiable T3 criteria at the handler boundary:

* evidence rows replay the store rows verbatim, in store order —
  recorded facts only, nothing recomputed or reordered client-side;
* unknown receipt ids are reported, never silently dropped;
* superseded and hard-forgotten memories are SURFACED with their state,
  never filtered — receipts are historical evidence;
* the response passes through the same measured budget as recall
  (anti-flooding, correction 5) — truncated rows keep their memory_id;
* malformed receipt_ids raise loudly — a bad id list is a caller bug,
  not a degradation mode.
"""
````

