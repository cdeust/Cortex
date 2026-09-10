# ADR-0995: tests_py/infrastructure/test_pg_store_near_dup.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_pg_store_near_dup.py`, original SHA-256 `22fe7bc0f9d4285da8a93b4eafe2f1220c6f26eb3828e73a7a6553129b1248fd`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 175–197

````text
"""Root cause (CI run 29109251545, 2026-07-10): this test used to
        assert effective_heat == heat_base (0.42) unconditionally. That is
        only true when the row's domain has a neutral (1.0) homeostatic
        factor — fetch_member_stats's SQL joins
        ``COALESCE(homeostatic_state.factor, 1.0)`` per domain
        (pg_store_near_dup.py), and that factor is real, mutable, per-
        domain server state, not a test-local constant. A same-session
        handler test (test_consolidate.py, real store) can leave a
        non-1.0 factor for the empty-string domain (conftest.py's
        ``homeostatic_state`` cleanup gap, now closed) — reproduced
        deterministically: 0.42 * 0.9409 == 0.395178, byte-for-byte the
        value CI observed. Fix: probe the SAME live factor
        ``fetch_member_stats`` reads (via ``store.get_homeostatic_factor``,
        the canonical accessor, pg_store.py) and assert against the
        derived expectation instead of a hardcoded constant — same
        "probe, don't predict" pattern as INC6.6
        (core/memory_reheat.py::compute_reheat_target). ``no_decay=TRUE``
        at insert (see ``_insert``) makes this structurally exact: the
        protected branch of ``effective_heat()`` is
        ``LEAST(1.0, GREATEST(0.0, heat_base * factor))`` with no time
        term, so the only free variable is the per-domain factor — no
        clock dependency remains once that is probed rather than assumed.
        """
````

