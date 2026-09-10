# ADR-0417: mcp_server/handlers/injection_receipts.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/injection_receipts.py`; original SHA-256 `7d8e896131114993647e09669c15c0b1389229a062d1a74b40a5d60e7a0d53dd`.

## Original docstring, lines 1–8

````text
"""Injection-receipt emission for context-injecting channels.

Blame path T1/T2 (decision Cortex 4255039): every channel that injects
memory content into a context emits an append-only receipt at injection
time — the presence-in-context evidence the blame path resolves against.
T1 wired the recall channel; T2 wires the hook channels (session_start,
auto_recall, agent_briefing) and hardens the channel enum.
"""
````

## Original comment, lines 22–26

````text
# Hardened channel enum (T2, decision 4255039 correction 3): the four
# channels that inject memory content into a context. agent_briefing
# (SubagentStart) was the forgotten fourth channel flagged by the jury.
# The DDL CHECK constraints in pg_schema.py / sqlite_schema.py mirror
# these values — parity is asserted by test, not by convention.
````

## Original docstring, lines 33–39

````text
"""Render the in-context receipt marker (correction 2).

    The marker travels INSIDE the injected text so the model can later
    pass the receipt id back to ``cortex:why(receipt_ids=[...])`` — the
    receipt-based primary path; server-side session-temporal resolution
    does not exist in MCP.
    """
````

## Original docstring, lines 49–63

````text
"""Render the in-context fetch key for ONE truncated memory line.

    Distinct from ``receipt_marker``: a receipt answers "which memories
    were in context" (``why``, Pearl rung-1 presence evidence), it does
    not hand back content. This marker answers "how do I read the rest of
    THIS line" — the model passes the id to ``recall(memory_id=...)``.

    Same stance ``core/response_budget.py`` already takes for bounded MCP
    responses: "Truncated items ... keep their id, so truncation is never
    a dead end: full content stays dynamically loadable by id". Injected
    banner text was the one truncation path in the system that did not
    keep it, so its truncation WAS a dead end — the reader could see that
    a memory had been cut but had no handle to fetch the remainder, only
    a fresh search whose top hit is not guaranteed to be the same row.
    """
````

## Original docstring, lines 68–79

````text
"""Derive the session identity from the transcript file name.

    Decision 4255039 correction 7: the hook event's ``session_id`` field
    diverges from the transcript identity across resume/clear chains
    (verified 148/200 lines on fixture 7374abf5). The transcript file
    basename is the stable identity; when no transcript_path is present
    the honest value is None (session_id is NULLable by design).

    The hook event is EXTERNAL input (system boundary) — a malformed
    transcript_path of any non-string type degrades to None rather than
    raising into the hook's primary injection path.
    """
````

## Original docstring, lines 86–92

````text
"""Map an injected payload to receipt items, rank = injection order.

    Internal contract, trusted here: every injected entry carries an
    int-coercible ``memory_id``. A missing id is an upstream programming
    bug and MUST raise loudly: swallowing it would silently drop
    receipts in production and hide the regression.
    """
````

## Original docstring, lines 119–131

````text
"""Persist a receipt mirroring the bound payload; return receipt_id.

    Must be called AFTER bound_payload (transcript↔DB parity invariant,
    decision 4255039): entries dropped by the response budget were never
    injected; truncated entries keep their id and ARE in context.
    ``rank`` = index in the injected payload (0 = top result), persisted
    verbatim — blame ordering replays recorded facts only.

    Returns None — without failing the recall read path — when nothing
    was injected or when the receipt write fails (I/O is the only named
    degradation mode). Contract violations (unknown channel, missing
    memory_id) raise before any I/O is attempted.
    """
````

