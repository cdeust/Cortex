# What a Cortex backup must contain (audit, 2026-11-05)

First slice of #731. The issue's first acceptance item asks to "define
included/excluded owned resources". This document answers one question: which
files and stores does a Cortex install write on the user's machine, where does
each one live, and which of them a portable backup must carry. It changes no
code and defines no archive format; the manifest, the consistent snapshot and
the restore check are later slices.

Revision read: Cortex `main` at `8ef4813`. Nothing was executed against a user
datastore: every statement below is read from the cited lines. Statements
marked *inferred* were derived from code, not observed in a running process.

## 1. The roots

Cortex already names the directories it treats as personal data:
`private_roots()` returns `<root>/methodology`, `<root>/.capture-worker` and
the cache directory, and `private_files()` returns `<root>/brain-index.json`
(`mcp_server/shared/private_paths.py:67-74`). `<root>` is `~/.claude`, or
`CORTEX_CLAUDE_DIR` when it is set (`mcp_server/infrastructure/config.py:16-22`,
`mcp_server/shared/private_paths.py:49-51`). The cache directory is
`CORTEX_CACHE_DIR`, else `$XDG_CACHE_HOME/cortex`, else `<root>/cache/cortex`
when `CORTEX_CLAUDE_DIR` is set, else `~/.cache/cortex`
(`mcp_server/shared/private_paths.py:54-63`).

These four entries are the starting set of a backup. Section 4 lists the files
Cortex writes outside them.

## 2. Inventory

Class **A** = user data that cannot be rebuilt (a backup must carry it).
Class **D** = derived data that can be rebuilt from class A or from the user's
sources, at a cost. Class **S** = process state, locks and logs (a restore does
not need it). Class **X** = not Cortex's to back up.

| Resource | Path | Class | Cited |
|---|---|---|---|
| SQLite store (memories, entities, graph, wiki tables, checkpoints, ...) | `<root>/methodology/memory.db` with its `-wal` and `-shm` files, or `CORTEX_MEMORY_DB_PATH` / `CORTEX_MEMORY_SQLITE_FALLBACK_PATH` | A | `mcp_server/infrastructure/memory_config.py:51-52`; `scripts/launcher_pg_select.py:35-45`; `PRIVACY.md:34-38`, `:66` |
| Plugin-managed PostgreSQL cluster | `<root>/methodology/managed-pg/cluster` | A | `mcp_server/infrastructure/managed_pg.py:40`, `:64-66`, `:103-105`; `PRIVACY.md:44-55` |
| Managed cluster password | `<root>/methodology/managed-pg/password` | A (secret) | `mcp_server/infrastructure/managed_pg.py:68-70`, `:140-143` |
| Managed server state | `<root>/methodology/managed-pg/status.json`, `postmaster.json` | S | `mcp_server/infrastructure/managed_pg.py:72-79` |
| User-configured PostgreSQL | whatever `DATABASE_URL` names | X (the user's server) | `mcp_server/infrastructure/memory_config.py:50`; `PRIVACY.md:57-63` |
| Backend marker (which store this install uses) | `<root>/methodology/backend.json` | A | `mcp_server/infrastructure/backend_marker.py:48` |
| Wiki pages on disk | `<root>/methodology/wiki/` | A | `mcp_server/infrastructure/config.py:42`; `mcp_server/handlers/ingest_findings_writers.py:173` |
| Raw-output artifacts | `<root>/methodology/artifacts/` | A | `mcp_server/infrastructure/artifact_store.py:19` |
| Cognitive profiles | `<root>/methodology/domains/<id>.json`, `index.json`; legacy `profiles.json`, `profiles.json.v1_backup` | A (`record_session_end` accumulates each session into them; once Claude Code has deleted a transcript, `rebuild_profiles` cannot restore its share, and it keeps the stored profile for that reason) | `mcp_server/infrastructure/profile_store.py:20-22`, `:49`; `mcp_server/infrastructure/config.py:38`; `mcp_server/handlers/record_session_end.py:265-287`; `mcp_server/core/profile_rebuild_policy.py:1-15` |
| Session log | `<root>/methodology/session-log.json` | A (one entry appended per ended session, not rebuilt from transcripts) | `mcp_server/infrastructure/config.py:39`; `mcp_server/handlers/record_session_end.py:257`, `:322`; `mcp_server/hooks/session_lifecycle.py:254`, `:356` |
| MCP connection list | `<root>/methodology/mcp-connections.json` | A | `mcp_server/infrastructure/config.py:41` |
| Brain index | `<root>/brain-index.json` | D | `mcp_server/infrastructure/config.py:40` |
| Capture spool (transcripts queued, not yet ingested) | `<root>/.capture-worker/spool` | A while non-empty | `mcp_server/infrastructure/capture_spool.py:62-65`, `:73-79` |
| Capture worker runtime (socket, worker state) | `<root>/.capture-worker/` | S | `mcp_server/infrastructure/capture_socket.py:43-55` |
| Telemetry samples | `<root>/methodology/telemetry.jsonl` | S | `mcp_server/core/telemetry.py:69`; `PRIVACY.md:86-90` |
| Logs | `<root>/methodology/consolidate.log`, `pipeline_reanalyze.log` | S | `mcp_server/hooks/session_start_consolidate.py:41`; `mcp_server/hooks/post_commit_reindex.py:228` |
| Hook counters, locks, cooldowns | `<root>/methodology/hook-cascade/`, `session-lifecycle.lock`, `hook-cooldowns/` (only with `CORTEX_CLAUDE_DIR`; else `/tmp`) | S | `mcp_server/infrastructure/hook_cascade_counter.py:34`; `mcp_server/hooks/session_lifecycle.py:342`; `mcp_server/shared/hook_state_paths.py:12-17` |
| Cache: session registry, groomer coordination, upstream MCP logs | `<cache>/session-registry`, `groomer-coordinator`, `mcp-logs` | S | `mcp_server/infrastructure/session_registry.py:38`; `mcp_server/infrastructure/groomer_coordinator.py:75`; `mcp_server/infrastructure/mcp_client.py:555` |
| Code graphs from `ingest_codebase` | `~/.cache/cortex/code-graphs/<project-key>/` | D (rebuilt by re-ingesting the repository) | `mcp_server/handlers/ingest_codebase.py:105-108`; `mcp_server/infrastructure/ap_bridge.py:99-105` |
| Pipeline install (source, binary, lock) | `~/.claude/methodology/src/`, `bin/`, `.install.lock` | X (reinstallable) | `mcp_server/infrastructure/pipeline_discovery.py:75-78`; `mcp_server/infrastructure/pipeline_install_lock.py:15` |
| Plugin runtime and PostgreSQL binaries | the plugin's data directory | X (reinstalled with the plugin) | `PRIVACY.md:49-50` |
| Files Cortex writes into the user's repositories (`CLAUDE.md` section, `docs/adr`) | the repositories | X (under the user's version control) | `PRIVACY.md:72-74` |
| Claude Code transcripts Cortex reads | `$CLAUDE_CONFIG_DIR/projects` or `<root>/projects` | X (the host's data) | `mcp_server/infrastructure/config.py:31-36` |

## 3. What a backup carries, by store

- **SQLite install.** The class A set is `memory.db` (taken as one consistent
  copy with its `-wal`, not three separate file copies; the method is a later
  slice), `backend.json`, `wiki/`, `artifacts/`, `mcp-connections.json`, the cognitive
  profiles (`domains/`, `index.json` and any legacy `profiles.json*`),
  `session-log.json`, and the capture spool when it is not empty.
- **Managed PostgreSQL install.** Same set, with the cluster in place of
  `memory.db`. A copy of `managed-pg/cluster` taken while the server runs is not
  a consistent backup (*inferred* from PostgreSQL's file-level backup rules,
  which require the server to be stopped or a base-backup protocol); a logical
  dump through the URL of `managed_pg.py:140-143` is the other route. The
  password file is a secret: an archive that carries it must be protected as
  such, and an archive that omits it cannot reopen the cluster as copied.
- **User-configured PostgreSQL.** Cortex does not own the server. A Cortex
  backup can carry the files of section 2 that are not the database, and point
  to `pg_dump` for the rest, as `scripts/reclassify_team_scope_db.py:12-22`
  already requires a `pg_dump` custom-format archive before it writes.

## 4. Findings

1. **Not every Cortex path follows `CORTEX_CLAUDE_DIR`.** `.last_consolidate`
   (`mcp_server/hooks/consolidate_background.py:37`), the pipeline install
   (`mcp_server/infrastructure/pipeline_discovery.py:75-78`,
   `mcp_server/infrastructure/pipeline_install_lock.py:15`) and the code graphs
   (`mcp_server/handlers/ingest_codebase.py:108`) are built from the home
   directory, not from `<root>`. A backup that copies `<root>` therefore misses
   the code graphs under a relocated root. All three are class S, X or D, so no
   class A data is lost, but a restore into a fresh root does not get the code
   graphs back without re-ingesting.
2. **The code graphs do not follow the cache directory either.** They are
   written to `~/.cache/cortex/code-graphs` even when `XDG_CACHE_HOME` or
   `CORTEX_CACHE_DIR` moves `cortex_cache_dir()` elsewhere
   (`mcp_server/handlers/ingest_codebase.py:108` against
   `mcp_server/shared/private_paths.py:54-63`). They then sit outside every
   entry of `private_roots()` (*inferred*).
3. **The wiki has two homes.** Pages are files under `wiki/`, and the store has
   wiki tables (`wiki.pages`, `wiki.claim_events`, ... at
   `mcp_server/infrastructure/pg_schema.py:173-241`; `wiki_pages`,
   `wiki_claim_events` at `mcp_server/infrastructure/sqlite_schema_wiki.py:17`,
   `:87`). A consistent backup must take
   both at the same instant, or the restore check must say which one wins.
4. **No public tool or script produces or restores a complete backup today.**
   No handler under `mcp_server/handlers/` exports or restores a store as a
   whole; the only backup check in the tree is the `pg_dump` precondition of
   `scripts/reclassify_team_scope_db.py:12-22`.

## 5. Remaining slices of #731

1. A versioned manifest listing the class A entries above with a digest each
   (delivered: `mcp_server/core/backup_manifest.py`, `infrastructure/backup_scan.py`,
   `handlers/backup_manifest.py`).
2. A consistent snapshot of each store under concurrent writes (SQLite online
   backup; managed PostgreSQL stopped copy or logical dump). SQLite part
   delivered: `infrastructure/sqlite_snapshot.py`, `infrastructure/backup_stage.py`,
   `handlers/backup_snapshot.py`; the managed cluster is still refused.
3. Restore into a fresh `CORTEX_CLAUDE_DIR`, then verify integrity and a known
   memory and source query.
4. Refusal of an incomplete or incompatible archive, leaving the target intact.
5. Tested recovery and upgrade-rollback documentation per supported platform.
