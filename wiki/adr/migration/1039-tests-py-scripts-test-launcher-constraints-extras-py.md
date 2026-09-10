# ADR-1039: tests_py/scripts/test_launcher_constraints_extras.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/scripts/test_launcher_constraints_extras.py`, original SHA-256 `ecc23aa315432c92cc9e9e92b1161b1ac13a4c1a93d54ae9cc1ba1f336b3720e`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–20

````text
"""Tests for the constraints-file extras strip in scripts/launcher_deps_install.py.

Source: measured 2026-08-02 on macOS, Python 3.14.4 / pip 26.0.1. A plugin
install of the ML stack aborted with ``ERROR: Constraints cannot have
extras``. ``launcher_deps.ensure_all_deps`` passes ``BASE_PACKAGES``
verbatim as the ``-c`` constraints file, and one of its entries carries an
extra (``psycopg[binary]==3.3.4``). pip has always documented constraints
files as version-only; it now rejects extras outright. Reproduced the same
day on pip 25.2 / Python 3.13, so this is not a pip-26-only regression.

The damage was silent: only the ML install passes constraints, so the base
stack installed fine while sentence-transformers and flashrank never landed
— leaving recall on first-stage scores with no failed check to notice, the
same failure shape as the 2026-07-10 FlashRank incident.

The first test is the regression proper: it asserts the bytes written to the
constraints file, which is what pip actually parses. The last is the
end-to-end guard against the real pin list drifting back into a spec pip
rejects.
"""
````

