# ADR-0978: tests_py/infrastructure/test_config.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_config.py`, original SHA-256 `2274100603ec055e39b2d7336c26243413f4c6ca0f25bce135518de0bb5e3c65`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 75–81

````text
"""The ``CORTEX_CLAUDE_DIR`` seam (issue #219).

    This suite cannot assert the *ambient* ``CLAUDE_DIR``: conftest sets the
    override before the first import precisely so no test can touch the
    operator's real tree. What the production contract actually promises is
    tested here instead, both arms, on freshly imported instances.
    """
````

