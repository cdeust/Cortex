# ADR-0435: mcp_server/handlers/record_session_end_memory.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/record_session_end_memory.py`; original SHA-256 `3ad45053a5ada8f20205affaf5c81ae5a54824752a477ac5b315bad60c7c245e`.

## Original docstring, lines 1–18

````text
"""Memory-integration helpers for record_session_end.

Split out of record_session_end.py (Move 5: profile/session-log
bookkeeping is one concern, talking to the memory store is another —
also keeps record_session_end.py under the 500-line cap after M-D6
added lesson-candidate persistence, coding-standards.md §4.1).

Two write paths, both best-effort (a failure here must never fail
session-end):
  - ``_store_session_memory`` / ``_try_store_memory``: one episodic
    'session-summary' memory per session.
  - ``_build_lesson_candidate_args`` / ``_try_store_lesson_candidates``
    (M-D6, 7.6): one 'lesson-candidate' memory per non-empty
    self-critique top_suggestion — previously computed by
    generate_critique() and returned in the response, never persisted
    anywhere else (design §M-D6: "top_suggestions calculées puis
    perdues").
"""
````

