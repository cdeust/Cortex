# ADR-0386: mcp_server/handlers/curate_wiki_uncited.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/curate_wiki_uncited.py`; original SHA-256 `0c1f1cba47444d3ce6be8f77d8a443c71a47dfbace0e6951a61cc5d7bbbf8646`.

## Original docstring, lines 1–14

````text
"""curate_wiki's I6-D7 reverse loop: report uncited deliberate memories.

Split out of ``curate_wiki.py`` (was pushing that file past the 500-line
limit, CLAUDE.md "Code Quality Rules") — also a genuine separation of
concerns (Move 5): job-planning (cluster/coverage/reauthor jobs, the
"what should get written next" question) and this report (the "what
already exists but is undocumented" question) are independent read
paths that happen to share one MCP tool surface (``curate_wiki``'s
``report_uncited_deliberate`` flag) for discoverability.

Read-only by construction: this module never calls ``wiki_write``,
``insert_citation``, or any other write path. It lists candidates; a
human or the in-session LLM decides what, if anything, to author.
"""
````

## Original docstring, lines 26–32

````text
"""I6-D7 reverse loop: report, never write. See
    ``list_uncited_deliberate_memories`` for the precise criteria.

    Best-effort: any DB failure degrades to an empty report rather than
    raising — this is a documentation-planning aid, not a load-bearing
    write path.
    """
````

