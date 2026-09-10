# ADR-0997: tests_py/infrastructure/test_pg_user_mood.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_pg_user_mood.py`, original SHA-256 `fe85cebb7e3a480bab1ba3a3b2e2ddd8d6b74e4e29bf1a4c6bb204111314d9de`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–19

````text
"""User-mood wiring tests for PgMemoryStore.

Closes the production no-op gap surfaced by Phase B calibration:
``mcp_server/core/pg_recall.py:_get_user_mood(store)`` duck-types against
``store.get_user_mood()`` and previously always returned None because no
such method existed. These tests pin the new contract:

  - ``get_user_mood()`` returns a scalar float in [-1, +1] (the bridge contract)
  - ``set_user_mood()`` upserts and bumps ``updated_at``
  - ``get_user_mood_state()`` exposes both valence and arousal for future use
  - Out-of-range values are clamped at write time

Touches the real ``cortex`` PostgreSQL instance via the same fixture
pattern as ``test_pg_pool.py``. The DDL adds ``user_mood`` only via
``CREATE TABLE IF NOT EXISTS`` so an in-flight benchmark on the same DB
is unaffected.

Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
"""
````

