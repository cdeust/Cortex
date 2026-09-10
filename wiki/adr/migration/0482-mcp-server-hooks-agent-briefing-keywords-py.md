# ADR-0482: mcp_server/hooks/agent_briefing_keywords.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/agent_briefing_keywords.py`; original SHA-256 `cc714791bcf39662791ad34e21e28b05c875d082d64f1a49810dbb547781d3a1`.

## Original docstring, lines 1–7

````text
"""Task-prompt keyword extraction for the agent_briefing hook's FTS query.

Split out of ``agent_briefing.py`` (issue #401 — that file exceeded the
project's 300-line cap, docs/agent-guidance.md § Code Style) to isolate pure text
processing (no I/O, no dependency on the rest of the hook) from prompt
parsing/event control flow and the PG query.
"""
````

## Original comment, lines 11–11

````text
# source: "words longer than 3 chars" per _extract_task_keywords docstring
````

