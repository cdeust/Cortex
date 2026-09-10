# ADR-1021: tests_py/invariants/test_pg_throwaway_db.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/invariants/test_pg_throwaway_db.py`, original SHA-256 `5e6fd543409c84b99257d543eb54fa14b2a17eaec60d16911c19fbaded3b4f32`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–18

````text
"""Tests for tests_py/_pg_throwaway_db.py — per-process throwaway PG database
lifecycle (issue #276/#287 boy-scout follow-up).

Extracted from `tests_py/conftest.py`'s module-level bootstrap, these
functions previously had no dedicated unit coverage of their own — only
whatever the full test-session bootstrap exercised implicitly. This file
closes that gap for the pieces that matter most: which orphan databases get
dropped (a wrong answer here either leaks throwaway databases forever or
drops one still in use), and that database creation/drop always degrade to
`None`/no-op on any failure rather than raising into collection.

Assertions are exact (`assert_called_once_with`, full SQL/message text)
rather than substring checks wherever a call site is otherwise mocked
permissively enough that a wrong argument or a corrupted literal would
still "work" against the fake — e.g. a fake `psycopg.connect` that accepts
any arguments cannot itself catch a real `test_db_url` silently swapped for
`None`; only asserting the exact call can.
"""
````

