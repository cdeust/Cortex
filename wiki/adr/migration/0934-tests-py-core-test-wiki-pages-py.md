# ADR-0934: tests_py/core/test_wiki_pages.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/core/test_wiki_pages.py`, original SHA-256 `e430eba711a6135765389bf80e78be94f2b255ef03e52f0ccbe4f2262f1708e0`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 99–108

````text
"""Reproduction (wiki.pages.title corruption, 36 rows, 2026-07-14):

    a scalar value quoted per YAML convention because it contains a
    colon (``title: "Public API surface: automatised-pipeline"``) must
    have its surrounding quotes stripped, matching the block-list item
    branch (line ~103) and the inline-list branch (``_strip_inline_list``)
    which already do this. Before the fix, the scalar branch assigned
    ``raw_stripped`` verbatim, leaving the literal quote characters in
    ``fm["title"]`` and, downstream, in ``wiki.pages.title``.
    """
````

