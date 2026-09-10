# ADR-0955: tests_py/handlers/test_remember_provenance_at_write.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/handlers/test_remember_provenance_at_write.py`, original SHA-256 `6f04e77a12f4fa3e1ef68ff2d378e9322e44b107a2fd155345d246af7d3b385f`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 205–208

````text
"""Live repro (memory 4341427, 2026-08-08): omit `directory` —
        resolution silently uses the process cwd, which need not be the
        writer's project root. The hint must name that root and say so,
        never conflate this with a genuinely-dead path."""
````

