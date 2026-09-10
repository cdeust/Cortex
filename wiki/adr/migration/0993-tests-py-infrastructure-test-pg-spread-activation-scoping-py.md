# ADR-0993: tests_py/infrastructure/test_pg_spread_activation_scoping.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_pg_spread_activation_scoping.py`, original SHA-256 `3a4d055aeb764c4878297161111f0c0573404039529479bbcf346cf89e4bd9b6`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–24

````text
"""Live-PG tests for spread_activation_memories (ADR-0054).

Two coupled defects, fixed together and tested together per the ADR's
"never one without the other" decision:

1. The stored procedure declared a plain ``WITH`` for its self-referencing
   ``spread`` CTE instead of ``WITH RECURSIVE`` -- every single call raised
   ``relation "spread" does not exist``, silently swallowed by
   ``recall_pipeline.spreading_activation_expand``'s bare
   ``except Exception``. The channel has been 100% dead in production
   since its introduction (8228a0d2). Test (a) below is the integration
   test that would have caught this on day one -- the existing test suite
   only ever exercised a Python-side ``_FakeStore`` double
   (tests_py/core/test_pg_recall_pipeline.py), never the real PL/pgSQL
   function.
2. Once fixed, the function had no domain filter: the entity graph is
   shared by design (see pg_schema.py module comment), but the final
   entity->memory mapping was unscoped, measured at 52.8% cross-domain
   injection (scratchpad/spread-activation-scoping-design.md §2.3). Tests
   (b)/(c) pin the fix: default scoped, opt-out via domain=None.

Runs against cortex_test (conftest.py redirects DATABASE_URL and isolates
entities/relationships/memories between tests).
"""
````

