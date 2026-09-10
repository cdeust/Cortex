# ADR-0484: mcp_server/hooks/agent_briefing_query.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/agent_briefing_query.py`; original SHA-256 `34279dfedef45aab137ffbadc6613833d9efe91b4a79ef3f1b487cc15b9dd1ba`.

## Original docstring, lines 1–7

````text
"""PostgreSQL connection + the two-pass briefing query for agent_briefing.

Split out of ``agent_briefing.py`` (issue #401 — that file exceeded the
project's 300-line cap, docs/agent-guidance.md § Code Style) to isolate the hook's only
I/O (PG connect + the two SELECT passes) from prompt parsing and
event-processing control flow.
"""
````

## Original sql-comment, interim lines 48–69

````text

                -- memories.heat is not a stored column; use
                -- effective_heat(m, NOW()) for lazy A3 decay (matches
                -- production recall_memories semantics).
                -- Source: pg_schema.py EFFECTIVE_HEAT_FN.
                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                -- JOIN current_memories: briefing content — chain heads
                -- only; join keeps m table-typed for effective_heat().
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.agent_context = %s
                  AND effective_heat(m, NOW()) >= %s
                  AND NOT m.is_benchmark
                  -- Never brief an agent with a corrected (superseded)
                  -- fact — decision 4255039 correction 8.
                  AND m.superseded_by_id IS NULL
                  AND m.content_tsv @@ plainto_tsquery('english', %s)
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                
````

## Original sql-comment, interim lines 89–105

````text

                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                -- JOIN current_memories: same pattern as pass 1.
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.is_protected = TRUE
                  AND m.is_global = TRUE
                  AND m.agent_context != %s
                  AND NOT m.is_benchmark
                  -- Superseded decisions are corrected facts — never
                  -- re-inject (decision 4255039 correction 8).
                  AND m.superseded_by_id IS NULL
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                
````

