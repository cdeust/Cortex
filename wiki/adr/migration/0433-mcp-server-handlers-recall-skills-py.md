# ADR-0433: mcp_server/handlers/recall_skills.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/recall_skills.py`; original SHA-256 `7ebdbc317e8d502af43945d77facda982c21a931a24a25e0b6bd385ff2f350ca`.

## Original docstring, lines 101–106

````text
"""Capability contract for the procedural-skills subsystem (PG-only).

    The SQLite backend has no procedural_skills table; the empty result is
    the named degraded mode, decided by a static member check rather than
    an AttributeError swallowed by the broad except below.
    """
````

