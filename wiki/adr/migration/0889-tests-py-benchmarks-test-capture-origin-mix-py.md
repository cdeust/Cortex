# ADR-0889: tests_py/benchmarks/test_capture_origin_mix.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/benchmarks/test_capture_origin_mix.py`, original SHA-256 `b00a834eb340cb13c2cda48a79b4ee836311ab60b03205ad825f6e809d97fde9`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–11

````text
"""benchmarks.lib.capture_origin_mix — measured production origin mixture.

Contract under test:
  - CAPTURE_ORIGIN_MIX sums to 1.0 and only names origins
    mcp_server.core.capture_origin actually recognises.
  - assign_capture_origins is deterministic (same n/seed -> same output,
    every call, matching benchmarks/reproduce.sh's "hit play, get the same
    numbers" contract) and produces a mixture, not a constant column — the
    property that makes the trust-factor gated arm able to discriminate W
    (docs/provenance/trust-factor-calibration.md).
"""
````

