# ADR-0976: tests_py/infrastructure/test_capture_origin_legacy_backfill.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_capture_origin_legacy_backfill.py`, original SHA-256 `2c35287a9f7c6314d1c656780d9d2dbb08d5ca467e011e86b2dc25f8a206896e`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–14

````text
"""The legacy backfill runs exactly once, on the upgrade that creates the
column (issue #368).

Why this is tested against a real pre-migration database rather than by
asserting substrings of the DDL: the property that matters is temporal — rows
present when the column is created become 'legacy', rows written afterwards
keep the 'unknown' DEFAULT and are demoted at read time. A text assertion on
the migration source cannot distinguish those two cases, and it is exactly
the distinction the whole design rests on.

SQLite's ALTER TABLE ... DROP COLUMN (3.35+) lets the test reconstruct the
pre-#365 shape from a current schema, so the upgrade path is exercised for
real instead of simulated.
"""
````

