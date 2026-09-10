---
title: "ADR-0693 — mcp_server/tool_profiles.py rationale"
status: accepted
source: mcp_server/tool_profiles.py
---

# ADR-0693 — mcp_server/tool_profiles.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Cortex registers its whole tool surface to every client on every session
(issue #177): the largest fixed token cost in the ecosystem, paid before the
user types anything. A profile narrows that surface for sessions that only
need the common recall/onboarding loop, without removing any tool from the
`full` surface.
````

## module — original line 9 (docstring)

````text
Two profiles:
````

## module — original line 11 (docstring)

````text
- ``full`` — every registered tool. **The default.** Shrinking the default
  surface is a breaking change (a client that called a now-hidden tool would
  break), so — mirroring ``ai-architect-mcp-codebase``'s ``ToolProfile`` reasoning
  and this wave's explicit decision — ``full`` stays the default. This
  diverges from #177 criterion 2's "default to the common-session profile";
  the divergence and its rationale are recorded in the CHANGELOG and PR.
- ``lean`` — the recall/onboarding surface an outside agent needs.
````

## module — original line 19 (docstring)

````text
Selection precedence: ``--profile`` CLI flag > ``CORTEX_MCP_PROFILE`` env var
> ``full`` (matches the ``CORTEX_*`` runtime-toggle convention, e.g.
``CORTEX_RUNTIME``).
````

## module — original line 23 (docstring)

````text
LEAN membership derivation (issue #177 criterion 1)
---------------------------------------------------
The set is derived from the documented tool tiers (``docs/mcp-tools.md``) and
the common-session workflow the issue itself characterises: a session doing
recall/onboarding "never calls ``wiki_migrate``, ``wiki_purge``,
``rebuild_profiles``, ``import_sessions``, ``backfill_memories`` or
``forget``". The runtime instrument that refines this per-deployment is
``get_telemetry`` (per-tool call counts in ``~/.claude/methodology/
telemetry.jsonl``); no committed telemetry corpus ships in-repo, so member-
ship is taxonomy-derived here and is intended to be tightened against a
deployment's own ``get_telemetry`` output rather than guessed wider.
````

## module — original line 35 (docstring)

````text
The lean set is exactly the tools the recall/onboarding loop touches:
  - onboarding entry: ``query_methodology`` (CLAUDE.md: "Call
    query_methodology at the beginning of every session");
  - store / retrieve: ``remember``, ``recall``, ``unified_search``,
    ``recall_hierarchical``;
  - maintenance the loop runs itself: ``consolidate``;
  - health / diagnostics: ``memory_stats``, ``check_setup``;
  - wiki read side ("wiki basics"): ``wiki_read``, ``wiki_list``.
Every lean tool is read-only or idempotent-write; no destructive tool
(``forget``, ``wiki_purge``, ``wiki_migrate``, delete-class) is a member, so
the destructive surface is excluded — and, per criterion 5, gated on call.

````

## module — original line 66 (comment)

````text
# The recall/onboarding surface. See module docstring for the derivation.
# source: docs/mcp-tools.md tiers + issue #177 common-session characterisation.
````

## module — original line 153 (comment)

````text
# ── Per-profile initialize instructions (issue #177 criterion 3) ────────────
#
# The server describes itself in the shape it was started in. Instructions are
# host-neutral: lifecycle automation belongs to the Claude plugin, while the
# stdio server remains useful through explicit tool calls on every MCP host.
````
