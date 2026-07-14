# Privacy Policy — Cortex (hypermnesia-mcp)

_Last updated: 2026-07-12_

Cortex is a **local-first** memory server for Claude. It is designed so that your
data stays on your machine. This policy describes exactly what data Cortex
handles, where it is stored, and what (if anything) leaves your device.

## What data Cortex processes

To build and retrieve memory, Cortex reads and processes:

- **Claude Code session data** on your machine under `~/.claude/` — conversation
  transcripts (`projects/*/**.jsonl`), memory notes (`*.md`), and session logs.
- **Content you explicitly store** via the `remember`, `wiki_write`, `anchor`,
  and ingestion tools (decisions, lessons, notes, code/PRD references).
- **Derived metadata** — keyword/entity extraction, embeddings, heat/decay
  scores, and cognitive-profile statistics computed from the above.

Cortex does **not** ask for, collect, or process passwords, payment data, or
credentials. If you place such data into a memory yourself, it is stored exactly
like any other memory (locally) — avoid doing so.

## Where your data is stored

- **SQLite (default — Claude Desktop `.mcpb` connector, Claude Cowork, and
  other sandboxed launches):** all memories, entities, the knowledge graph, and
  profiles are stored in a single local database file at
  `~/.claude/methodology/memory.db`. If a configured PostgreSQL instance is
  unreachable, Cortex falls back to this SQLite store with an explicit warning
  in the logs. Nothing is uploaded.
- **PostgreSQL + pgvector (Claude Code plugin / CLI mode, large stores, shared
  team databases):** your data is stored in **your own** database, configured
  via the `DATABASE_URL` environment variable (default
  `postgresql://127.0.0.1:5432/cortex`); the plugin's setup script installs
  PostgreSQL locally on your machine. Cortex never provisions or connects to
  any database you did not configure.

You own this data. Deleting the database file (or the relevant rows) permanently
removes it. The `forget` tool deletes individual memories.

## What leaves your machine

Cortex itself does **not** transmit your memories, conversations, profiles, or
any personal content to the author, to Anthropic, or to third-party analytics.
There is no telemetry phone-home **by default**; the `get_telemetry` tool
reports **local** performance statistics only, and every recorded sample is
appended to a local, no-egress JSONL file
(`~/.claude/methodology/telemetry.jsonl`).

The only outbound network activity is:

1. **One-time model download.** On first use, the open-source embedding model
   (`sentence-transformers`, all-MiniLM-L6-v2) and the reranking model
   (`flashrank`, ms-marco-MiniLM) are downloaded from the public Hugging Face
   model hub. These transfers fetch **model files only** — no user content is
   sent. After the first download the models run fully offline.
2. **Integrations you explicitly enable.** If you configure optional upstream MCP
   servers or a remote PostgreSQL database, Cortex communicates only with the
   endpoints you provided.
3. **Optional OTLP telemetry export (opt-in, OFF by default).** If you set the
   `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable, Cortex additionally
   mirrors the same aggregate, content-free metrics already visible via
   `get_telemetry` (per-tool call counts, latencies, and result counts —
   never memory content) to the OTLP collector endpoint you configured.
   Requires the optional `[otel]` install extra. Absent this env var, nothing
   changes: the local JSONL sink remains the only telemetry sink.

## Data sharing

Cortex does not sell, share, or disclose your data to any third party. There are
no third-party trackers, advertising SDKs, or analytics services in the server.

## Data retention

Data persists in your local store until you delete it. Cortex applies a local
thermodynamic decay/consolidation process that compresses or prunes low-value
memories over time; this is a local maintenance operation, not a transfer.

## Your controls

- `forget` — delete a specific memory.
- Delete `~/.claude/methodology/memory.db` — remove all SQLite-stored data.
- For PostgreSQL, manage retention directly in your database.

## Contact

Questions about this policy: **admin@ai-architect.tools** ·
issues: https://github.com/cdeust/Cortex/issues
