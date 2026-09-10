# ADR-0494: mcp_server/hooks/post_commit_reindex.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/post_commit_reindex.py`; original SHA-256 `b7ec5c598462c789ca1e3b597a74b1972c307c7bb498bafcc28f6f8be5ec81ea`.

## Original comment, lines 61–63

````text
# source: ai-architect-mcp-codebase src/parser/mod.rs Language::from_extension
# (AST-parsed languages) + the indexer's .js-family light-link post-pass
# (File nodes + import edges, no AST symbols).
````

## Original docstring, lines 142–146

````text
"""Best-effort: True when the tool output marks a no-op/failed commit.

    When no output is captured we return False (proceed) — a spurious
    re-analyse is harmless; a missed one is the bug we are fixing.
    """
````

## Original comment, lines 179–180

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 226–227

````text
# Never resolve "python3"/"python" by PATH name — hits the Windows
    # Store stub. source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.2
````

