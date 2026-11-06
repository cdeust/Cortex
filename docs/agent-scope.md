# Agent scope: what `agent_topic` does and does not guarantee

Status: describes the code on `main` as of 2026-11-05 (issue #718, slice 1).
Whether Cortex should offer a *private* agent scope is an open product
decision recorded in issue #718; this page documents the contract that exists
today so that no caller mistakes an agent label for a privacy boundary.

## Summary

`agent_topic` is a **ranking boost**, not an eligibility filter. A memory
written under agent `alpha` is returned to a recall made for agent `beta`
whenever it matches the query; it only ranks lower than it would for `alpha`.
Agents that share a store share their memories.

## Per surface

| Surface | Unrooted connection | Rooted (`CORTEX_ROOT_AGENT_TOPIC` set) |
|---|---|---|
| `remember` | stores the caller's `agent_topic` in `memories.agent_context` | stores the root topic; the parameter is absent from the tool schema |
| `recall` search | boosts memories whose `agent_context` equals `agent_topic`; others still match | boosts the root topic; others still match |
| `recall` with `memory_id` | returns the memory whatever its `agent_context` | returns nothing unless `agent_context` equals the root topic |
| `include_related`, `unified_search` and every other tool | no agent check | no agent check |

Code, so the table can be checked:

- Boost on PostgreSQL: `agent_boosted` in `recall_memories`
  (`mcp_server/infrastructure/pg_schema.py`, the `CASE WHEN p_agent_topic`
  expression).
- Boost on SQLite: `_apply_agent_boost` in
  `mcp_server/infrastructure/sqlite_store_recall.py` and the agent partition in
  `mcp_server/infrastructure/sqlite_store_recall_fill.py` (ADR-0616, ADR-1109).
- Rooted forcing and the fetch-by-id check: `root_agent_topic()` is read in
  exactly three places, `mcp_server/handlers/remember.py`, `_handler_impl` and
  `_fetch_by_id` in `mcp_server/handlers/recall.py`, plus the schema stripping
  in `mcp_server/tool_registry_memory.py` (ADR-0534, ADR-0698).

## What the tests prove

`tests_py/handlers/test_agent_scope_contract.py` writes one memory for each of
two agents into a real SQLite store and asserts the table above: a recall
scoped to `alpha` returns `beta`'s memory, rooted or not, and a rooted
fetch-by-id hides `beta`'s memory. `tests_py/handlers/test_connection_rooted_scoping.py`
covers the schema stripping and the forced topic.

## Not verified

- The PostgreSQL rows of the table are read from the SQL, not run by
  `test_agent_scope_contract.py`, which uses SQLite only.
- No property against a hostile tenant is claimed: Cortex has no
  authentication between agents of one store, and a rooted connection is a
  convenience for cooperating agents, not an isolation mechanism.
