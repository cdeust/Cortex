# ADR-0966: tests_py/handlers/test_wiki_write_path_governance.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/handlers/test_wiki_write_path_governance.py`, original SHA-256 `15ceb4d01f70938485d6fec0311d11d45f495b99c7c8b602fee32518450cee9b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–12

````text
"""Issue #110: write-time frontmatter normalization now applies to every
``write_page`` caller, not just the governed ``wiki_write`` tool path.

These tests exercise two of the direct (governance-bypassing) callers —
``wiki_adr`` and ``wiki_link`` — end to end through their real handlers,
proving the normalization boundary moved down to
``infrastructure.wiki_store.write_page`` actually covers them. See
``tests_py/architecture/test_write_page_call_sites.py`` for the audited
whitelist of every direct caller, and
``tests_py/handlers/test_wiki_write_frontmatter_validation.py`` for the
equivalent coverage of the governed path.
"""
````

