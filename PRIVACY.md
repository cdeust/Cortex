# Privacy Policy — Cortex (hypermnesia-mcp)

_Last updated: 2026-10-27_

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
credentials. Credentials that reach Cortex anyway (a token in a tool output, a
transcript, a memory you write) are replaced by `[REDACTED:<rule>]` before
anything is written: every database write, file, log line and embedding goes
through one redaction gate (ADR-1110). It detects the gitleaks 8.30.1 default
rule set (GitHub, Anthropic, OpenAI, AWS, Slack, Stripe and Google keys, JWTs,
private keys, keyword-anchored API keys and about 200 more shapes) plus URL
passwords and `password=` assignments. A secret that matches no rule (a bare
random string with no `key=` context, an encoded value) is not caught, and rows
written before this gate existed are not rewritten. Email addresses and other
personal data are not redacted.

## Where your data is stored

- **SQLite (default — Claude Code plugin installs, Claude Desktop `.mcpb`
  connector, Claude Cowork, and other sandboxed launches):** all memories,
  entities, the knowledge graph, and profiles are stored in a single local
  database file at `~/.claude/methodology/memory.db` (setting
  `CORTEX_CLAUDE_DIR` relocates this root, and everything derived from it, to
  a directory you choose). With no database configured, the Claude Code
  plugin uses this store and never connects to a PostgreSQL server. A
  configured PostgreSQL that is unreachable is an error shown at session
  start ("Cortex not ready"), never a silent switch to SQLite. Nothing is
  uploaded.
- **The plugin's own PostgreSQL (Claude Code plugin, macOS and Linux GNU,
  fresh installs that ran `claude --init-only`):** the same data, in a
  PostgreSQL server the plugin runs, listening on 127.0.0.1 only, with a
  random password kept in a file only you can read. Its data (the cluster,
  the password, its state) lives in `~/.claude/methodology/managed-pg/`, next
  to the backend marker; only its binaries live in the plugin's data
  directory. It is selected only after it started and its schema was created;
  otherwise, and on Windows, the SQLite store above is used, and the cause is
  shown at session start ("SQLite fallback: ..."). An existing SQLite store is
  not moved. Uninstalling the plugin removes the binaries, never the
  memories: delete `~/.claude/methodology/managed-pg/` to remove them. The
  Codex plugin and direct `hypermnesia-mcp` launches on the same account use
  this same server and store.
- **PostgreSQL + pgvector (opt-in — `install-plugin.sh --postgres`, large
  stores, shared team databases):** your data is stored in **your own**
  database, configured via the `DATABASE_URL` environment variable (default
  `postgresql://127.0.0.1:5432/cortex`); the opt-in setup script installs
  PostgreSQL locally on your machine, and an existing PostgreSQL install is
  detected and kept across plugin updates. Apart from its own server above,
  Cortex never provisions or connects to any database you did not configure.

Only your account can read it (ADR-1112). On macOS and Linux the database
(with its `-wal` and `-shm` files), logs, telemetry, wiki pages, artifacts and
profiles under `~/.claude/methodology`, the capture worker's directory,
`~/.claude/brain-index.json` and Cortex's cache directory (`~/.cache/cortex`;
inside the relocated root when `CORTEX_CLAUDE_DIR` is set) are created with mode `0600`
in `0700` directories; an install made by an earlier version is tightened the
first time the server or a session starts. On Windows those directories get an
access list granting only your user, inherited by everything inside. Files
Cortex writes into your own repositories (a `CLAUDE.md` section, `docs/adr`)
keep your usual permissions.

You own this data. Deleting the database file (or the relevant rows) permanently
removes it. The `forget` tool deletes individual memories: a hard delete
(the default) removes the memory and every stored copy of its text (archive,
wiki claims, drafts and derived pages, mined reminders and rules, extracted
entities, the raw-output artifact file). See *Your controls* below for the
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

1. **Runtime install, once per locked dependency set (Claude Code plugin).**
   The plugin's Setup hook (`claude --init-only`), or, when it did not run,
   the MCP server and two detached background jobs that hooks start (one for
   the base set, one for the machine-learning set and the model), download
   into the plugin's data directory (`~/.claude/plugins/data/hypermnesia-mcp-cortex-plugins/`):
   the pinned uv and the locked Python packages from PyPI (hash-checked
   against `uv.lock`), the machine-learning packages and the embedding model
   below; and, only when the machine's `python3` is older than 3.10, CPython
   3.12.13 from the python-build-standalone releases on GitHub, through uv.
   This happens again only for a plugin version whose `uv.lock` locks a
   different dependency set. One case comes before you install that version:
   when the local marketplace clone already holds it (`claude plugin
   marketplace update` refreshes the clone without installing), a third
   detached job runs the clone's own Setup and downloads its sets (about 1 GB
   with the machine-learning set). Nothing asks a git remote
   whether a release is out. These transfers fetch software only; no user
   content is sent. `CORTEX_EMBEDDING_ZERO_DOWNLOAD=1` skips the
   machine-learning packages and the model. When the plugin runs its own
   PostgreSQL server (below), Setup also downloads, once per pinned version,
   the PostgreSQL archive of theseus-rs/postgresql-binaries (18.6.0 on
   macOS, about 13 MB; 18.6.1 on Linux, about 40 MB) and a pgvector 0.8.7
   archive from this repository's own GitHub releases, each checked against a
   pinned sha256. The pgvector archives are compiled by Cortex's CI from the
   pinned upstream source commit against PostgreSQL 18.6.0, with a
   build-provenance attestation you can check with
   `gh attestation verify <archive> --repo cdeust/Cortex --source-ref refs/heads/main`
   (the workflow publishes only from main).
2. **One-time model download.** On first use, the open-source embedding model
   (`sentence-transformers`, all-MiniLM-L6-v2) and the reranking model
   (`flashrank`, ms-marco-MiniLM) are downloaded from the public Hugging Face
   model hub. These transfers fetch **model files only** — no user content is
   sent. After the first download the models run fully offline. To forbid the
   reranker fetch outright (air-gapped installs, or any environment where an
   unexpected outbound connection is unacceptable), set
   `CORTEX_RERANKER_OFFLINE=1`: Cortex then refuses the download when the model
   is not already cached and degrades to first-stage retrieval scores, logging
   a warning that names the path it expected, rather than reaching out.
3. **Code-intelligence server installation, when you run `scripts/setup.sh`.**
   This explicit setup step can install ai-architect-mcp-codebase from
   `cdeust/ai-architect-mcp-codebase` GitHub Releases (about 46 MB, measured
   by the 2026-10-10 audit in issue #705). When no release fits, it can clone
   that repository and build it with Rust, downloading the hash-pinned
   toolchain from `sh.rustup.rs` and packages from crates.io if needed.
   SessionStart only discovers and registers an installed server; it never
   downloads or builds one. `CORTEX_AUTO_INSTALL_PIPELINE=0` disables this
   setup step too.
4. **Integrations you explicitly enable.** If you configure optional upstream MCP
   servers or a remote PostgreSQL database, Cortex communicates only with the
   endpoints you provided.
5. **Optional OTLP telemetry export (opt-in, OFF by default).** If you set the
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

- `CORTEX_CAPTURE_MODE` controls the Claude Code plugin's PostToolUse auto-capture.
  Unset or `full` preserves the existing capture filters and novelty gate.
  `writes-only` admits Edit, Write, MultiEdit, NotebookEdit and Bash; Read,
  NotebookRead, Glob, Grep, WebFetch and WebSearch are excluded. Bash is classified
  by tool name, so its output may be captured even when the command only reads.
  `off` disables PostToolUse auto-capture. An invalid value logs a configuration
  error and skips capture for that event; an empty value is invalid too.
  Set the variable in the environment that launches Claude Code, for example
  `CORTEX_CAPTURE_MODE=writes-only claude`. This control governs this hook;
  session-lifecycle transcript processing and explicit memory tools have their
  own paths. Previously stored memories and artifacts remain until deleted.
- `forget` — delete a specific memory. A **hard** delete (the default) removes,
  in one transaction that either completes or changes nothing (ADR-1111):
  1. the memory row itself, with its full-text and vector index entries;
  2. its compression archive (the original text kept when a memory is
     summarised);
  3. the wiki claims, drafts and citations derived from it, and a wiki page
     compiled or promoted from it (row and file; the wiki index is rebuilt),
     unless the memory is only a pointer at a page you wrote;
  4. the reminders and rules mined from it, and the entities extracted from
     its text that no other memory refers to;
  5. the raw-output **artifact** file the memory body pointed at, under
     `~/.claude/methodology/artifacts/`. An oversized auto-capture keeps only a
     short gist in the row and the full raw text in that file, so deleting the
     row alone would leave your content on disk.

  On SQLite the deleted bytes are also overwritten in the database file and its
  write-ahead log. On PostgreSQL the rows are unreachable at once, but the
  server reclaims their disk space only at its next `VACUUM` (run
  `VACUUM FULL` yourself if the bytes must go immediately). Copies that do
  not reference the memory (a summary consolidated from several memories,
  backups, other versions of an edited memory) are not removed by forgetting
  this one.

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
- Export and import a project's memories (ADR-1113):
  `python -m mcp_server.portability export <project-root> <file>` writes the
  memories of that project and its subdirectories (add `--include-global` for
  your global memories) to a JSON Lines file, readable and owner-only, with
  secrets redacted; `python -m mcp_server.portability import <file>
  [--into <project-root>]` loads it into this or another installation, once.
- Delete `~/.claude/methodology/memory.db` — remove all SQLite-stored data.
- Delete `~/.claude/methodology/artifacts/` — remove all raw-output artifacts,
  including any left by soft deletes or still shared between memories.
- For PostgreSQL, manage retention directly in your database.

### Exact duplicate consolidation

Consolidation retains superseded duplicate rows. Hard forgetting a memory also erases
its byte-identical retained copies connected by supersession edges within the same write
scope, in the same transaction. Independent memories and other scopes remain separate.
Soft forgetting and backups retain their existing behavior.

## Contact

Questions about this policy: **admin@ai-architect.tools** ·
issues: https://github.com/cdeust/Cortex/issues
