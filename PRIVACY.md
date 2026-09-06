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

- **SQLite (default — Claude Code plugin installs, Claude Desktop `.mcpb`
  connector, Claude Cowork, and other sandboxed launches):** all memories,
  entities, the knowledge graph, and profiles are stored in a single local
  database file at `~/.claude/methodology/memory.db` (setting
  `CORTEX_CLAUDE_DIR` relocates this root, and everything derived from it, to
  a directory you choose). If a configured
  PostgreSQL instance is unreachable, Cortex falls back to this SQLite store
  with an explicit warning in the logs. Nothing is uploaded.
- **PostgreSQL + pgvector (opt-in — `install-plugin.sh --postgres`, large
  stores, shared team databases):** your data is stored in **your own**
  database, configured via the `DATABASE_URL` environment variable (default
  `postgresql://127.0.0.1:5432/cortex`); the opt-in setup script installs
  PostgreSQL locally on your machine, and an existing PostgreSQL install is
  detected and kept across plugin updates. Cortex never provisions or
  connects to any database you did not configure.

You own this data. Deleting the database file (or the relevant rows) permanently
removes it. The `forget` tool deletes individual memories: a hard delete
(the default) removes the memory row, any wiki claims derived from it, and the
raw-output artifact file its body pointed at — see *Your controls* below for the
exact scope, including the one case where an artifact is deliberately kept.

## What leaves your machine

Cortex itself does **not** transmit your memories, conversations, profiles, or
any personal content to the author, to Anthropic, or to third-party analytics.
There is no telemetry phone-home **by default**; the `get_telemetry` tool
reports **local** performance statistics only, and every recorded sample is
appended to a local, no-egress JSONL file
(`~/.claude/methodology/telemetry.jsonl`).

`CORTEX_CLAUDE_DIR` redirects that file to the selected configuration root.
Samples contain operation names, durations, byte counts, result counts and
completion status, without prompt or response content. `query_methodology`,
`session_start` and `auto_recall` are included. `tier` records the retrieval
route actually executed (`pg` for the current memory-store pipeline, or the
legacy dispatch tier); it is null when no retrieval route ran.
`reranked_count` counts passages successfully processed by the reranker,
including candidates later filtered out of the response.
For MCP calls, `bytes_out` measures the SDK's final UTF-8 text payload, including
error messages and excluding the transport envelope and structured-content
duplicate. Direct handler calls measure their serialized response (zero when
they raise without returning a response). Hook `bytes_out` measures stdout
after encoding and newline conversion. A silent hook records zero bytes.
Hook `ok` describes normal completion or exit code zero; it does not certify
that every optional retrieval source was available.

The only outbound network activity is:

1. **One-time model download.** On first use, the open-source embedding model
   (`sentence-transformers`, all-MiniLM-L6-v2) and the reranking model
   (`flashrank`, ms-marco-MiniLM) are downloaded from the public Hugging Face
   model hub. These transfers fetch **model files only** — no user content is
   sent. After the first download the models run fully offline. To forbid the
   reranker fetch outright (air-gapped installs, or any environment where an
   unexpected outbound connection is unacceptable), set
   `CORTEX_RERANKER_OFFLINE=1`: Cortex then refuses the download when the model
   is not already cached and degrades to first-stage retrieval scores, logging
   a warning that names the path it expected, rather than reaching out.
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

- `forget` — delete a specific memory. A **hard** delete (the default) removes,
  across every substrate that holds the content:
  1. the memory row itself;
  2. the wiki claim events derived from that memory;
  3. the raw-output **artifact** file the memory body pointed at, under
     `~/.claude/methodology/artifacts/` — an oversized auto-capture keeps only a
     short gist in the row and the full raw text in that file, so deleting the
     row alone would leave your content on disk.

  Two deliberate exceptions, both reported in the tool's result so you can see
  which applied:
  - **Artifacts are content-addressed and shared.** If a second memory still
    points at the same artifact (identical captured output dedups to one file),
    the file is kept until the last memory referring to it is forgotten —
    otherwise the surviving memory would lose its content. `artifact_deleted`
    is `false` in that case.
  - **`soft=true` keeps everything but the row's visibility.** A soft delete is
    recoverable by design (it sets `is_stale` and `heat=0`), so the artifact is
    deliberately retained. Use a hard delete when you want the content gone.
- Delete `~/.claude/methodology/memory.db` — remove all SQLite-stored data.
- Delete `~/.claude/methodology/artifacts/` — remove all raw-output artifacts,
  including any left by soft deletes or still shared between memories.
- For PostgreSQL, manage retention directly in your database.

## Contact

Questions about this policy: **admin@ai-architect.tools** ·
issues: https://github.com/cdeust/Cortex/issues
