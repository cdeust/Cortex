# ADR-0497: mcp_server/hooks/session_lifecycle.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/session_lifecycle.py`; original SHA-256 `981af3b30f67269a4b57111f31c66cdff321e0618848f03e6a90245f28b9b989`.

## Original comment, lines 108–108

````text
# source: session-length gates documented in _run_consolidation docstring
````

## Original docstring, lines 115–132

````text
"""Run memory consolidation ("dream" cycle) at session end.

    Implements automatic consolidation inspired by:
      - Borbely 1982: two-process model — consolidation pressure accumulates
        with new memories, fires when threshold exceeded.
      - Tononi & Cirelli 2003 (SHY): wakefulness (session activity) builds
        synaptic weight; consolidation restores homeostasis.
      - Dewar et al. 2012: rest after encoding boosts long-term retention.
      - McClelland et al. 1995 (CLS): interleaved replay for hippocampal →
        cortical transfer.

    Time/activity gates (engineering heuristics — thresholds not paper-prescribed):
      - Short sessions (<5 turns): skip full consolidation, only decay.
      - Medium sessions (5-20 turns): decay + compression.
      - Long sessions (>20 turns): full dream cycle (decay + compress + CLS).

    Non-blocking: logs errors but never raises.
    """
````

## Original comment, lines 337–341

````text
# issue #398: closes the store before this one-shot process exits
    # (see _store_lifecycle.py for the verified mechanism -- psycopg pool
    # threads are daemon threads; the fragile path is __del__'s
    # finalization-time join, which close() pre-empts by setting
    # _closed=True while the interpreter is still alive).
````

## Reviewed remaining docstring (mcp_server/hooks/session_lifecycle.py, interim lines 160–172)

````text
Build a session log entry from event data.

precondition: ``event["session_id"]`` is present (enforced by
``process_event``'s guard before this is called). postcondition:
``sessionId`` is the transcript-stem canonical identity (Q2 alignment,
decision 4255039 correction 7) when ``event["transcript_path"]`` is a
non-empty string; otherwise it degrades to the raw
``event["session_id"]`` — the documented divergence window (no
transcript_path in the SessionEnd payload, e.g. synthetic/test
events). No historical rows are rewritten; readers of session-log.json
(profile_builder, procedural_skill_writer) key on domain/tools/
duration, not sessionId, so old-vs-new rows are read-compatible.
````

## Rationale attached to lint directive (interim line 109)

````text
# ("engineering heuristics — thresholds not paper-prescribed")  # noqa: ERA001
````

## Original reviewed-docstring-refinement, interim lines 161–174

````text
Build a session log entry from event data.

    precondition: ``event["session_id"]`` is present (enforced by
    ``process_event``'s guard before this is called). postcondition:
    ``sessionId`` is the transcript-stem canonical identity (Q2 alignment,
    decision 4255039 correction 7) when ``event["transcript_path"]`` is a
    non-empty string; otherwise it degrades to the raw
    ``event["session_id"]`` — the documented divergence window (no
    transcript_path in the SessionEnd payload, e.g. synthetic/test
    events). No historical rows are rewritten; readers of session-log.json key on
    domain/tools/
    duration, not sessionId, so old-vs-new rows are read-compatible.

    source: ADR-0497
````

