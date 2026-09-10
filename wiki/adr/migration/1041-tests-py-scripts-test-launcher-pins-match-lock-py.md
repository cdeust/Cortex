# ADR-1041: tests_py/scripts/test_launcher_pins_match_lock.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/scripts/test_launcher_pins_match_lock.py`, original SHA-256 `91a8bdeb8910cec0967edcc2c914267d4257da259cd2e2af77db77641c29019f`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–31

````text
"""scripts/launcher_deps.py's pins must equal what the lock installs.

Why this file exists
--------------------
``launcher_deps.py`` hand-restates a slice of the resolved dependency set so a
plugin install can `pip install --target` it without a resolver. Every entry
carried a "source: uv.lock" comment — and nine of the eleven had drifted from
that source by the time this test was written (2026-07-29, during the
transformers 4 -> 5 security migration):

    fastmcp               3.2.4  vs 3.4.5
    pydantic             2.13.3  vs 2.13.4
    pydantic-settings    2.14.0  vs 2.14.2
    psycopg               3.3.3  vs 3.3.4
    psycopg-pool          3.3.0  vs 3.3.1
    pgvector              0.4.2  vs 0.5.0
    sentence-transformers 5.4.1  vs 5.6.1
    numpy   one pin for >=3.11   vs a three-way fork (2.2.6/2.4.6/2.5.1)

That is the same failure ``scripts/generate_pip_constraints.py`` was built to
end for the requirements files ("Hand-maintaining them would reintroduce the
drift this replaces"), reappearing in the one place that still restates the
lock by hand. Drift here is not cosmetic: it makes a plugin install resolve a
dependency combination no CI job has ever exercised.

The reconciliation target is ``requirements/setup.txt`` rather than uv.lock
directly. That file IS the lock — the generator exports it and CI's Lint job
runs ``generate_pip_constraints.py --check`` on every PR — but it is already
flattened to concrete ``name==version ; marker`` lines, so this test needs no
second lock parser to fall out of step with uv's own.
"""
````

