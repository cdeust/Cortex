# Visualization companion against Cortex's default stores (audit, 2026-11-05)

First slice of #724. The issue asks to audit and reuse the existing companion
(`hypermnesia-mcp-viz`, repository `cdeust/cortex-viz`) before anything else.
This document answers one question: from a default Cortex install, which
companion views can read the user's memory store, and what does the user see
when they cannot. It changes no code.

Revisions read: Cortex `main` at `2126d2a`; companion `main` at `e9c1a31`
(read-only shallow clone). Nothing was executed against a user datastore: every
statement below is read from the cited lines. Statements marked *inferred* were
derived from code, not observed in a running process.

## 1. The stores a default Cortex install writes

| Install path | Store | URL shape | Cited |
|---|---|---|---|
| Plugin, no database configured (Windows, older glibc, or no `claude --init-only`) | SQLite file `~/.claude/methodology/memory.db` | none (file path) | `PRIVACY.md:34` |
| Plugin after `claude --init-only` on macOS / Linux glibc ≥ 2.36 | Plugin-managed PostgreSQL on loopback | `postgresql://postgres:<password>@127.0.0.1:<port>/cortex` | `PRIVACY.md:44`; `mcp_server/infrastructure/managed_pg.py:36-38`, `:140-143` |
| CLI / dev, or `install-plugin.sh --postgres` | User-configured PostgreSQL | whatever `DATABASE_URL` names | `docs/agent-guidance.md` § Cortex |

The managed server's port is not fixed. The first start passes no preferred port
(`mcp_server/infrastructure/managed_pg_supervisor.py:118`), and `free_port`
then binds port 0, i.e. any free port chosen by the kernel
(`mcp_server/infrastructure/managed_pg_server.py:69-78`, `:165`). A restart
reuses the recorded port when it is free (`managed_pg_supervisor.py:75-79`).
The password lives in a file under the managed root (`managed_pg.py:69-70`,
`:142`), and the cluster requires it (`--auth=scram-sha-256`,
`scripts/launcher_pg_provision.py:71`).

## 2. What the companion reads

- The companion reads PostgreSQL only. Its reader is built on `psycopg` and
  `psycopg_pool` (`cortex_viz/infrastructure/memory_read.py:43-45`); its
  startup probe treats any `psycopg.Error` as "no database"
  (`cortex_viz/infrastructure/db_probe.py:60-100`).
- Its default URL is `postgresql://127.0.0.1:5432/cortex`, set in four places:
  `cortex_viz/infrastructure/memory_config.py:52`,
  `cortex_viz/infrastructure/memory_read.py:51`, `scripts/launcher.py:269-270`
  and the plugin's `database_url` setting (`.claude-plugin/plugin.json:25`).
- `memory_config.py:54-55` declares `SQLITE_FALLBACK_PATH` and
  `STORE_BACKEND = "auto"  # "auto" | "postgresql" | "sqlite"`, but no other
  line of `cortex_viz/` or `scripts/` reads either setting (`grep -rn`
  over both trees). The SQLite option is declared, not implemented.
- Nothing in the companion reads Cortex's managed-server status or password
  file (`grep -rni "managed.pg\|backend_marker"` over `cortex_viz/` and
  `scripts/`: no match).

## 3. Result per default store

| Cortex store | Companion default URL reaches it? | Views served | Cited |
|---|---|---|---|
| SQLite (`memory.db`) | No: not a PostgreSQL server | Trace only | §2 |
| Managed PostgreSQL | No (*inferred*): port is kernel-chosen, not 5432, and the URL carries no password | Trace only | §1, §2 |
| User PostgreSQL on `127.0.0.1:5432/cortex` without password | Yes | all six | §2 |
| User PostgreSQL elsewhere | Only after the user copies the URL into the companion's `database_url` | all six | companion `README.md:75` |

The managed-PostgreSQL row is *inferred* (not run): even a managed server that
the kernel happened to place on port 5432 would refuse the password-less URL,
because its cluster is created with `--auth=scram-sha-256`
(`scripts/launcher_pg_provision.py:71`).

## 4. What the user sees when the store is not reached

The companion starts in no-DB mode and keeps Trace (companion `README.md:92`).
The five store-backed views (Graph, Brain, Knowledge, Wiki, Board) answer HTTP
503 with:

> hypermnesia-mcp-viz is running in no-DB mode (Trace only). Install Cortex
> (https://github.com/cdeust/Cortex) and point DATABASE_URL at its PostgreSQL to
> enable this view.

(`cortex_viz/server/http_standalone_nodb.py:66-91`.) The startup line on stderr
says the same and adds "Start Cortex's PostgreSQL or fix DATABASE_URL"
(`db_probe.py:87-96`).

For a user whose Cortex runs on SQLite, both messages are wrong about the
cause: Cortex is installed and has no PostgreSQL to start. This is the case the
issue's third acceptance item names ("a failed dependency must not look like
an empty memory store"): here the store is not empty, it is absent from the
companion's view, and the message points at an install the user already has.

## 5. What Cortex's own documentation says

`README.md:149-165` names the companion in the rename notice and `README.md:577`
in the locality statement; no line of
`README.md`, `PRIVACY.md` or `docs/codex-plugin.md` says that its five
store-backed views need PostgreSQL (`grep -n -i "viz\|visual"` over the three
files). The companion's own README states it (`README.md:75`, `:92`), so a
Cortex user learns it only after installing the companion.

## 6. Dead read client in Cortex

`mcp_server/infrastructure/viz_client.py` (106 lines, ADR-0623) was written for
the `query_workflow_graph` handler. That handler is no longer in `mcp_server/`
(`grep -rln query_workflow_graph mcp_server`: only `viz_client.py` itself), and
no module imports `viz_client` (`grep -rn viz_client mcp_server`: no match
outside the file). Only `tests_py/infrastructure/test_viz_client.py` exercises
it. GitHub commit search places the extraction of the visualization stack in
`77dba678` (2026-06-13) and `67286929` (v3.21.0, 2026-06-15); this shallow
clone does not hold that history, so the exact removal commit is not verified.

## 7. Remaining slices of #724

Ordered so that each is autonomous and the owner's product decision comes
first, per the issue's *Alternatives considered*:

1. **Decision (owner):** the companion reads SQLite (implement the declared
   `STORE_BACKEND`), or the companion stays PostgreSQL-only and both READMEs say
   so. Either is consistent with the issue; it is a product choice.
2. **Companion:** discover the managed server's URL (status port and password
   file) instead of the fixed `5432` default, when the plugin-managed store is
   the one Cortex uses. Companion-owned work, per the issue's last acceptance
   item.
3. **Companion:** the no-DB message distinguishes "Cortex not found" from
   "Cortex found on a store this companion cannot read" (§4).
4. **Cortex:** one line in `README.md` next to the companion link stating which
   stores its views read (§5), once slice 1 is decided.
5. **Cortex:** remove `viz_client.py` and its test, or give it a caller (§6).
6. The rendered-UI acceptance items (keyboard, reduced motion, viewports, local
   assets) belong to the companion repository and need a running browser.
