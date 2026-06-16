# Cortex — Troubleshooting: Slow or Stalled Codebase Ingest

This guide is for macOS users (and most steps transfer to Linux) whose
`ingest_codebase` call appears to hang. Follow the sections in order — most
hangs are diagnosed and resolved within the first two sections.

---

## 1. Is it hung or just slow?

**Do not kill the process yet.** Ingest is checkpointed; killing it wastes
progress only if you never resume. First, determine whether work is actually
happening.

### Find the process IDs

```bash
ps aux | grep -iE "cortex|launcher\.py|automatised-pipeline|mcp_server" | grep -v grep
```

Note the PIDs in the second column.

### Attach a sampling profiler without stopping the process

**macOS built-in (no install required, does not pause the process):**

```bash
sample <PID> 5 -file /tmp/cortex.sample
open /tmp/cortex.sample   # opens in Instruments
```

**Cross-platform — py-spy (install once, then use for any Python process):**

```bash
pip install py-spy

# Snapshot of every thread's current stack:
py-spy dump --pid <PID>

# Live top-like view (refresh every second):
py-spy top --pid <PID>
```

### Reading the result

Look at the top (most active) frame:

| Top frame contains | Meaning |
|---|---|
| `encode` / `torch` / `SentenceTransformer` | Embedding generation — **working, just slow** |
| `analyze_codebase` / `kuzu` / the AP binary | Graph analysis step — **working** |
| `fetch_symbols_page` / `cypher` / `kuzu` | Symbol fetch from graph — **working** |
| `execute` / `copy` / `pg` / `psycopg` | Postgres write — **working** |
| `socket.recv` / `read` / `select` at ~0% CPU | **Blocked** — network, model download, or DB lock |
| `urllib` / `requests` / `http.client` | **Blocked on model download** — see Section 4 |

A process spending sustained time in `encode()` is doing real work. A process
pinned in `socket.recv` at near-zero CPU for more than two minutes is stalled.

---

## 2. Is it making progress?

### Check CPU

```bash
top -pid <PID>   # macOS
# or
top -p <PID>     # Linux
```

Sustained CPU above a few percent means embedding or I/O is active. Near-zero
CPU for more than ~90 seconds is the clearest stall signal.

### Check the database directly

Run each query twice, about 30 seconds apart. If `n_tup_ins` is climbing
between runs, rows are being written — ingest is alive.

```sql
-- How many rows have been inserted into each table?
-- Run twice ~30s apart; climbing numbers = progress.
SELECT relname, n_tup_ins
FROM pg_stat_user_tables
ORDER BY n_tup_ins DESC
LIMIT 10;
```

```sql
-- What queries are running right now?
SELECT pid, state, now() - query_start AS dur, left(query, 80)
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY dur DESC;
```

Connect to the database with:

```bash
psql "$DATABASE_URL"
# or, if DATABASE_URL is unset:
psql postgresql://127.0.0.1:5432/cortex
```

If `pg_stat_activity` shows an `INSERT` or `COPY` query that has been running
for several minutes, that is the entity-write stage working through a large
symbol corpus. If there are no active queries and CPU is near zero, something
upstream is blocked.

---

## 3. Is it safe to stop?

**Yes.** You can press `Ctrl-C` at any point during the entity-ingest stage
(Phase 2) without losing work. The `_ingest_entities` function in
`mcp_server/handlers/ingest_codebase.py` writes an advisory checkpoint after
every page of symbols is committed to Postgres. On resume, `_checkpoint_read`
recovers the last committed page offset and total row count; at most one page
of work is repeated (the page that was in flight when the process stopped).
The `_checkpoint_read` / `_checkpoint_write` / `_checkpoint_clear` helpers
delegate to `store.get_ingest_progress` / `store.set_ingest_progress` /
`store.clear_ingest_progress` on the store, and the page writes are
idempotent (`NOT EXISTS` dedup), so replaying a page is harmless.

### Resume from checkpoint (default)

Simply re-run the same `ingest_codebase` call:

```bash
uv run python scripts/dev_run_ingest.py /path/to/your/project
```

The handler reads the stored offset and continues from where it stopped.

### Force a clean re-index

Pass `--force` to discard the checkpoint and rebuild from scratch:

```bash
uv run python scripts/dev_run_ingest.py /path/to/your/project --force
```

Inside Claude Code, pass `force_reindex: true` to the `ingest_codebase` tool.

> **Note:** Stopping during Phase 1 (graph analysis, the upstream
> `analyze_codebase` subprocess) or Phase 4 (process wiki pages) is also safe
> — those phases have no partial state to preserve.

---

## 4. Stalled model download

### Symptoms

- CPU near zero
- `py-spy dump` shows `urllib` / `http.client` / `requests` in the stack
- The `~/.cache/huggingface/` directory is not growing

### What is happening

On a first run, `sentence-transformers` downloads the `all-MiniLM-L6-v2`
embedding model (~100 MB) from HuggingFace. `scripts/setup.sh` includes a
pre-cache step that runs this download before the MCP server starts, but if
that step was skipped or the cache is missing, the download happens inline
during the first `encode()` call.

### Check

```bash
# Watch cache growth (macOS):
du -sh ~/.cache/huggingface/hub/ 2>/dev/null

# Or watch it update:
watch -n5 'du -sh ~/.cache/huggingface/hub/ 2>/dev/null'
```

If the directory is growing, the download is in progress — wait for it to
finish (typically 1–3 minutes on a home connection).

If the directory is not growing and CPU is near zero, you may have a network
interruption. Try:

```bash
# Pre-cache the model manually:
python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
print('cached:', model.encode(['test']).shape)
"
```

After a successful download, restart the MCP server (reload Claude Code's MCP
connection) and re-run ingest.

---

## 5. Common setup errors

These errors appear immediately rather than as a hang, but they cause ingest
to fail silently if the MCP server is already running without a healthy
database.

### PostgreSQL not running

```bash
pg_isready
# Expected: /tmp/.s.PGSQL.5432 - accepting connections
# Problem:  no response or "No such file or directory"
```

Fix on macOS:

```bash
brew services start postgresql@17
# Wait a few seconds, then verify:
pg_isready
```

### pgvector extension missing

```bash
psql postgresql://127.0.0.1:5432/cortex -c "SELECT extname FROM pg_extension;"
# Should include: vector
# and: pg_trgm
```

If missing, install and enable:

```bash
brew install pgvector   # macOS
psql postgresql://127.0.0.1:5432/cortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql postgresql://127.0.0.1:5432/cortex -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### DATABASE_URL not set

The Cortex MCP server and `scripts/dev_run_ingest.py` both require
`DATABASE_URL`. The default used during setup is
`postgresql://127.0.0.1:5432/cortex`.

```bash
echo $DATABASE_URL   # should print a postgresql:// URL

# If empty, export it before running ingest:
export DATABASE_URL="postgresql://127.0.0.1:5432/cortex"
```

Add the export to your shell profile (`~/.zshrc` or `~/.bashrc`) so it
persists across sessions.

### Re-run setup from scratch

If you are unsure which of the above applies, `scripts/setup.sh` is safe to
re-run — it is idempotent:

```bash
bash scripts/setup.sh
```

---

## 6. Getting visible progress going forward

### CLI with live progress bar (recommended)

`scripts/cortex_ingest.py` provides a live per-stage progress bar powered by
`rich` — the recommended way to run ingest when you want human-readable
feedback:

```bash
uv run python scripts/cortex_ingest.py /path/to/your/project
uv run python scripts/cortex_ingest.py /path/to/your/project --force
uv run python scripts/cortex_ingest.py /path/to/your/project --output-dir /tmp/my-graph --language python
```

The bar shows a spinner, a `[stage/total]` label, a completion count
(`done/total` or a running symbol count when the total is unknown), and
elapsed time. It renders above the terminal output so log lines do not
overwrite the bar.

Accepted flags:
- `project_path` — path to the codebase root (required, positional)
- `--force` — discard any cached graph and rebuild from scratch
- `--output-dir DIR` — override the default graph output directory
- `--language LANG` — language hint for the upstream analyser (default: `auto`)

### Direct CLI (machine-readable output)

`scripts/dev_run_ingest.py` runs the handler directly and prints a JSON
summary on completion. Use it for scripted or CI runs where machine-readable
output is preferable:

```bash
uv run python scripts/dev_run_ingest.py /path/to/your/project
uv run python scripts/dev_run_ingest.py /path/to/your/project --force
```

### MCP progress notifications

When called via the `ingest_codebase` MCP tool inside Claude Code, the handler
emits standard MCP progress notifications at the start of each of the six
ingest stages (`analyze graph`, `fetch files`, `ingest entities`, `ingest
edges`, `pull processes`, `enrich process symbols`). Each stage boundary
sends a fractional progress update (`progress / total = 1.0`) and a textual
info message (`[stage+1/6] <stage name>`). During the entity stage — the
longest one — updates are emitted as each symbol page completes (throttled to
~2 Hz): when the total symbol count is known the bar advances determinately,
and when it is not (uncapped ingest, no cheap count available) a running
`ingested N symbols…` text line is emitted instead so progress stays visibly
moving even though the fraction can't. Claude Code captures these and displays
them in the tool-call output.

### MCP server logs

The most direct low-level view of what is happening is the MCP server stderr.
Claude Code captures MCP server stderr in its MCP logs. Open the Claude Code
log panel and filter for the `codebase` or `cortex` MCP server entries to see
phase transitions and row counts as they are written.

---

## Quick reference: distinguish working-but-slow from blocked

| Signal | Interpretation |
|---|---|
| CPU > 10%, `encode` in stack | Embedding — normal, can take 30–90 min for large repos |
| CPU > 10%, Postgres `INSERT`/`COPY` active | Entity write — normal |
| CPU near 0%, `socket.recv` in stack | Blocked — check network, model download, DB |
| `pg_stat_user_tables.n_tup_ins` climbing | Progress is happening |
| No active Postgres queries, CPU near 0% for >2 min | Stalled — diagnose with profiler |
| `McpConnectionError` in MCP logs | Upstream `automatised-pipeline` server unreachable |
| `analyze_failed` in tool response | Graph analysis subprocess failed — check MCP logs |
