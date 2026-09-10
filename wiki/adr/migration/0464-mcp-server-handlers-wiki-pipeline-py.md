# ADR-0464: mcp_server/handlers/wiki_pipeline.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_pipeline.py`; original SHA-256 `bc115b102291a2c675a0b04bb5f0cce122b58efc71d15fe2ec6a340c4fc26137`.

## Original docstring, lines 79–86

````text
"""Run a handler coroutine; return its summary or an error dict.

    The stage error is LOGGED as well as returned. Returning it alone made
    a wholly dead pipeline indistinguishable from an idle one: on SQLite
    every stage raised, each error became a string in the summary, and the
    payload still looked like success (issue #206). The log line is the
    signal an operator can actually see.
    """
````

