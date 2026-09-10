# ADR-0985: tests_py/infrastructure/test_pg_alpha_integral.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_pg_alpha_integral.py`, original SHA-256 `365f60a7d3adcd68fc918b742b723e847cf7bc04eeb00924855aa2b30376d532`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–20

````text
"""Parity + monotonicity tests for the piecewise α-integral decay exponent.

Root cause (forgetting-curve fidelity benchmark, 2026-06-30): effective_heat()
applied α(final stage)·hours_elapsed. When a trace matured (α drops, e.g.
late_ltp 0.8 → consolidated 0.5) the lower α was applied retroactively to the
whole past, so the decay exponent shrank across a stage boundary and heat ROSE
with age — non-physical, non-monotonic forgetting (B_consolidated 6h 0.98982 →
8h 0.99151). Fix: the decay exponent is ∫ α(stage(s)) ds (alpha_integral), and
effective_heat() uses the difference of cumulative integrals over the decay
window. α>0 everywhere ⇒ the integral is increasing ⇒ forgetting is monotone.

These tests pin:
  1. SQL alpha_integral() == a Python oracle mirroring effective_stage's walk.
  2. alpha_integral is non-decreasing in τ (the property that makes forgetting
     monotone) and single-stage traces reduce exactly to α·τ.
  3. effective_heat() is monotone non-increasing across an age grid for every
     benchmark profile — the direct regression for the shipped defect.

Runs against cortex_test (conftest redirects DATABASE_URL).
"""
````

