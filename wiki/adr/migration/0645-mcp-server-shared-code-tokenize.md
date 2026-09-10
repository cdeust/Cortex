---
title: "ADR-0645 — mcp_server/shared/code_tokenize.py rationale"
status: accepted
source: mcp_server/shared/code_tokenize.py
---

# ADR-0645 — mcp_server/shared/code_tokenize.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Cortex memories frequently carry code identifiers — ``normalizePaymentAmount``,
``snake_case_id``, ``HTTPRequest``. SQLite's FTS5 ``unicode61`` tokenizer treats
each of those as ONE opaque token, so a natural-language query for ``payment``
never matches a memory that only wrote ``normalizePaymentAmount``.
````

## module — original line 8 (docstring)

````text
FTS5 custom tokenizers require a compiled C extension (the ``fts5_tokenizer``
API is not reachable from Python's ``sqlite3``). This module achieves the same
effect purely in Python, on both sides of the index:
````

## module — original line 12 (docstring)

````text
  * **index time** — ``augment_content`` appends the sub-tokens of every
    identifier to the text handed to ``memories_fts``, so ``payment`` becomes a
    first-class indexed term alongside the original ``normalizePaymentAmount``.
  * **query time** — ``expand_fts_query`` rewrites each query word into an
    ``("word" OR "sub1" OR "sub2")`` group, so a query that *contains* a
    camelCase identifier still matches memories that stored the split words.
````

## module — original line 19 (docstring)

````text
Reference concept: the ``cbm_camel_split`` FTS5 tokenizer in the
codebase-memory-mcp project (C). This is the same split rule (camelCase +
snake_case + digit boundaries), realised as content/query rewriting rather than
a native tokenizer.
````

## module — original line 24 (docstring)

````text
Pure utility — no I/O, no domain knowledge. Shared layer (stdlib only).

````

## module — original line 59 (comment)

````text
# snake / kebab first so camel rules see clean segments
````

## module — original line 76 (comment)

````text
# Seed with words already present verbatim (lowercased) so a sub-token that
# is also a standalone word is not re-appended.
````
