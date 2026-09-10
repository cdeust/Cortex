# ADR-0933: tests_py/core/test_wiki_layout.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/core/test_wiki_layout.py`, original SHA-256 `8b84de1689a0fe84e0ce7d25304b6faae1a42f0a8e07b1eb554497f869ecfc7b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 96–101

````text
"""ADR-2244: PAGE_KINDS contains all 8 modern + 6 legacy kinds.

    Modern kinds drive new writes; legacy kinds remain accepted by
    ``page_path`` / ``domain_page_path`` so existing pages under
    notes/specs/conventions/lessons/guides/files stay readable.
    """
````

