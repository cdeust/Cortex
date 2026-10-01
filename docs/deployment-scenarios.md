# Cortex — Deployment Scenarios

Scenarios that have caused friction for Discord users: running under WSL,
connecting with TLS client-certificate authentication instead of a password,
and downloading model weights behind a corporate proxy / inspection CA.

---

## WSL (Windows Subsystem for Linux)

Cortex runs as a Linux process under WSL — no Windows-specific code paths are
active. The win32 branches in `scripts/setup.py` (ANSI colour suppression,
service-start hints) are gated on `sys.platform == "win32"` and are inert
inside WSL.

**Two things to get right:**

1. **File paths must be in WSL (POSIX) form.** Any path you pass in
   `DATABASE_URL` or `sslcert`/`sslkey`/`sslrootcert` query parameters must
   use the `/mnt/c/...` prefix that WSL exposes, not the Windows
   `C:\...` form. Example:

   ```
   sslcert=/mnt/c/Users/yourname/certs/client.crt
   ```

2. **PostgreSQL must be reachable from inside WSL.** If PostgreSQL is running
   on the Windows host, set `DATABASE_URL` to point at the Windows host IP or
   `$(hostname).local` from inside WSL. If PostgreSQL is installed inside WSL
   itself (recommended), `localhost` works as normal.

Everything else — hook registration, `python3 -m mcp_server.doctor`,
`scripts/setup_db.py`, `scripts/setup.py` — works without modification.

---

## Client-certificate authentication (no password)

Cortex passes `DATABASE_URL` directly to libpq via
`psycopg.connect(url)` (`mcp_server/infrastructure/pg_store.py`, line 133)
and to `psycopg_pool.ConnectionPool(conninfo=url, ...)`. This means every
standard libpq TLS parameter works as a query parameter in the DSN — no
password required.

### Example DSN

```
DATABASE_URL="postgresql://USER@HOST:5432/cortex?sslmode=verify-full&sslcert=/path/to/client.crt&sslkey=/path/to/client.key&sslrootcert=/path/to/ca.crt"
```

Set this in your environment before starting Claude Code (or before running
`scripts/setup_db.py`):

```bash
export DATABASE_URL="postgresql://myuser@db.example.com:5432/cortex?sslmode=verify-full&sslcert=/etc/certs/client.crt&sslkey=/etc/certs/client.key&sslrootcert=/etc/certs/ca.crt"
```

### Required: key-file permissions

libpq rejects a private key that is world-readable. Set the mode before
starting Cortex:

```bash
chmod 600 /path/to/client.key
```

### No password field needed

Cortex never requires a password field in `DATABASE_URL`. Authentication is
delegated entirely to libpq, so `pg_hba.conf` `cert` auth (or `scram-sha-256`
over TLS, or peer auth for local sockets) all work without any Cortex-side
changes.

### Secret redaction in logs and doctor output

`python3 -m mcp_server.doctor` and internal log lines pass `DATABASE_URL`
through `mcp_server.shared.redaction.redact_url` before printing. That
function masks only:

- the userinfo password (`user:secret@host` → `user:***@host`)
- the `?password=` and `?pgpassword=` query parameters

TLS parameters (`sslcert`, `sslkey`, `sslrootcert`, `sslmode`) are not
treated as secrets and are preserved verbatim in log output. A cert-based DSN
that contains no password field is printed unchanged.

---

## Dev container (VS Code / Claude Code — issue #118)

One command, no local Python/Postgres/model setup: open the repo in a
container that already has Claude Code, PostgreSQL+pgvector, and Cortex's
embedding/reranker models ready to go.

```
Open in VS Code → "Dev Containers: Reopen in Container"
# or, headless:
devcontainer up --workspace-folder .
```

### What's included

- **`.devcontainer/devcontainer.json`** — pins the
  `ghcr.io/anthropics/devcontainer-features/claude-code` feature and the
  `ghcr.io/devcontainers/features/node` feature (Node 22), sets
  `DISABLE_AUTOUPDATER=1`, and runs
  `python scripts/setup_db.py && python -m mcp_server.doctor` as
  `postCreateCommand` — the container is not considered ready until `doctor`
  exits 0.
- **`.devcontainer/docker-compose.yml`** — two services:
  - `app`: builds `.devcontainer/Dockerfile`, mounts the repo at
    `/workspace`, talks to `db` via `DATABASE_URL`.
  - `db`: `pgvector/pgvector:pg16` — the *same image*
    `benchmarks/reproduce.sh` already uses for its own ephemeral
    PostgreSQL instances — with `vector`/`pg_trgm` created by
    `.devcontainer/initdb/01-extensions.sql` at first boot (the same DDL as
    `mcp_server/infrastructure/pg_schema.py::EXTENSIONS_DDL` and
    `docker/entrypoint.sh`'s single-container runtime image).
- **`.devcontainer/Dockerfile`** — reuses the production build recipe from
  `../Dockerfile`'s builder stage (CPU-only torch wheel, `pip install
  .[postgresql]`), adds the `codebase` extra, and **prewarms the embedding
  model (`all-MiniLM-L6-v2`) and the FlashRank cross-encoder reranker at
  build time**, cached under `HF_HOME=/opt/model-cache/huggingface` /
  `XDG_CACHE_HOME=/opt/model-cache` — a durable image path, never `/tmp`
  (see `mcp_server/core/reranker.py`'s module docstring for the exact
  2026-07-11 incident this avoids: FlashRank's own default cache directory
  IS `/tmp`, and losing that cache mid-process causes recall to silently
  fall back to first-stage-only scores with no error logged).

### Version pinning

Every dependency this container introduces is pinned to a value verified
against this repo's own lockfile or the upstream registry, not guessed:

- Python packages (torch, sentence-transformers, flashrank and the rest) —
  installed with `uv sync --locked` from this repo's `uv.lock`, each
  artifact checked against the lock's sha256; no version is restated here.
- `ghcr.io/anthropics/devcontainer-features/claude-code:1.0.5` — the
  feature's own manifest at this tag reports `"options": {}` (verified
  2026-07-14 against `ghcr.io/v2/anthropics/devcontainer-features/
  claude-code/manifests/1.0.5`): **the feature exposes no version knob for
  the CLI it installs.** Its `install.sh` runs an unpinned
  `npm install -g @anthropic-ai/claude-code` regardless of which feature
  tag you pin — so pinning `:1.0.5` fixes the *install script* (and thus
  guards against a future script-level regression), but **not** which
  `@anthropic-ai/claude-code` release ends up in the image. This is the
  same install-script-vs-package-release gap referenced by this issue.
  There is currently no upstream mechanism to pin the CLI release itself
  through this feature; rebuild the container to pick up a newer CLI, and
  re-run `postCreateCommand` (`mcp_server.doctor` does not check the CLI
  version) to confirm the rest of the stack is still healthy.
- `ghcr.io/devcontainers/features/node:2.1.0` with `version: "22"` — pinned
  explicitly rather than accepting the `claude-code` feature's best-effort
  Node 18.x auto-install fallback (`install.sh`, only triggers when no
  Node is already present).

### Validation

`postCreateCommand` runs `python scripts/setup_db.py` (idempotent —
creates the database/extensions/schema if absent, no-ops otherwise; the
same script the plugin's SessionStart hook already uses) followed by
`python -m mcp_server.doctor`, which must exit 0: Python version, PG
driver import, `DATABASE_URL` reachability, `pgvector`/`pg_trgm`
extensions, schema presence, and the `POOL_INTERACTIVE_MAX` invariant.

Verified locally (2026-07-14, `docker compose up -d` from a checkout under
`$HOME`, both services healthy): `\dx` inside `db` lists `vector 0.8.4` and
`pg_trgm 1.6`; `python scripts/setup_db.py` returns
`{"status": "ready", ...}`; `python -m mcp_server.doctor` exits 0 with
every required check green (the only warning is the optional
codebase-pipeline capability, expected without the separate Rust
component). The FlashRank ONNX model's on-disk `mtime` inside the running
container matches the image's build time, not the container's start
time — confirming the model was baked into the image layer and not
downloaded at first use. **Caveat specific to this verification, not to
the devcontainer itself:** the *first* attempt, from a checkout under
`/tmp`, hit a Docker Desktop bind-mount quirk on this machine (a
single-file mount at a path absent from the base image materialized as an
empty directory instead of the file — `.devcontainer/initdb/` mounts a
*directory* for exactly this reason, see that directory's file header).
Re-running the identical compose file from a `$HOME`-rooted checkout
worked without any file changes, isolating the quirk to `/tmp` bind
mounts in this environment, not to the compose/Dockerfile content.

---

## Remote PostgreSQL

Any host reachable from the machine running Cortex works in `DATABASE_URL`.
Both the runtime (`mcp_server/infrastructure/pg_store.py`) and the hook
bootstrap (`scripts/setup_db.py`) read `DATABASE_URL` from the environment
and connect to whatever host the DSN specifies.

**One caveat with the convenience installer:** `scripts/setup.py` derives the
host and port from `DATABASE_URL` via `urllib.parse` and passes them to
`pg_isready -h HOST -p PORT`. This means the installer correctly probes the
remote host rather than localhost, as long as `DATABASE_URL` is set before
running the script. If `DATABASE_URL` is unset, the installer falls back to
`localhost:5432`.

Verify a remote connection with:

```bash
python3 -m mcp_server.doctor
```

The `DATABASE_URL` check and the `PG connection` check both probe the host
from your DSN.

---

## Corporate proxy / custom CA (model downloads)

Cortex downloads two model artifacts on first use, both from Hugging Face:

- **sentence-transformers embedding model** (`all-MiniLM-L6-v2`, ~100MB),
  fetched via `huggingface_hub`/`requests` inside
  `mcp_server/infrastructure/embedding_engine.py` (`_ensure_model`), and
  pre-cached once by `scripts/setup.py` (`cache_embedding_model`, step 5).
- **FlashRank cross-encoder reranker** (`ms-marco-MiniLM-L-12-v2`, ~34MB
  ONNX), fetched by the `flashrank` library itself from
  `https://huggingface.co/prithivida/flashrank/resolve/main/{model}.zip`
  (`mcp_server/core/reranker.py`, module docstring; verified by reading the
  installed `flashrank==0.2.10` package, not assumed).

Neither of these paths has Cortex-specific proxy/CA handling — there is none
to add. Both `sentence-transformers`/`huggingface_hub` and `flashrank` use
Python's `requests` under the hood, which honors the standard environment
variables natively. `scripts/setup.py` passes the pre-caching step through
`subprocess.run(..., env={**os.environ, ...})` (see `cache_embedding_model`),
so anything exported in your shell before running the installer reaches the
download.

### Proxy variables (read by `requests`/`urllib3`, and by `huggingface_hub`)

```bash
export HTTPS_PROXY="http://proxy.corp.example.com:8080"
export HTTP_PROXY="http://proxy.corp.example.com:8080"
export NO_PROXY="localhost,127.0.0.1,.corp.example.com"
```

These are read once per process at first HTTP(S) request. Set them before
running `scripts/setup.py`, and before starting Claude Code / the Cortex MCP
server if the reranker or embedding model has not been cached yet.

### The central trap: which CA variable Python actually reads

If your proxy terminates TLS and re-signs traffic with a corporate root CA
(common with inspection proxies), **the variable that matters for Cortex's
downloads is a Python/`requests` variable, not a Node one**:

| Variable | Honored by | Relevant to Cortex? |
|---|---|---|
| `REQUESTS_CA_BUNDLE` | Python `requests` (and therefore `huggingface_hub`, `sentence-transformers`, `flashrank`) | **Yes — this is the one to set.** |
| `SSL_CERT_FILE` | Python's `ssl` module directly (used by libraries that bypass `requests`) | Yes, as a second/fallback path — set alongside `REQUESTS_CA_BUNDLE` for defense in depth. |
| `NODE_EXTRA_CA_CERTS` | Node.js's TLS stack | **No.** This only affects Claude Code's own Node process (npm registry TLS, Claude Code's network calls). It has zero effect on Cortex's Python model downloads. Setting only this variable and expecting model downloads to trust the corporate CA is the classic mistake this section exists to head off. |

```bash
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/corp-ca-bundle.crt
export SSL_CERT_FILE=/etc/ssl/certs/corp-ca-bundle.crt
```

If you already set `NODE_EXTRA_CA_CERTS` for Claude Code itself, keep it —
it is still required for Claude Code's own TLS — but it is a separate,
additional variable, not a substitute for `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`.

### Cache location: never let it land in `/tmp`

Cortex has already been bitten by exactly this failure mode once, in the
reranker: FlashRank 0.2.10's own default `cache_dir` is `/tmp`
(`flashrank/Config.py`, `default_cache_dir = "/tmp"`). macOS periodically
purges `/tmp`, which silently disabled reranking for the remainder of a
process's life and went unnoticed through 6 benchmark runs (fixed in
`bb1c581f`, "fix(reranker): durable cache_dir + non-silent failure + bench
fail-fast", 2026-07-11). The fix was to pass an **explicit, durable**
`cache_dir` — `reranker_cache_dir()` in `mcp_server/core/reranker.py`,
which resolves to `~/.cache/flashrank` and honors `$XDG_CACHE_HOME` via
`mcp_server.shared.platform.cache_dir()` — instead of relying on the
library default.

The sentence-transformers embedding model does **not** have this same
Cortex-side override: `embedding_engine.py` calls `SentenceTransformer(...)`
without a `cache_folder` argument, so it defers entirely to
`huggingface_hub`'s own cache resolution — `$HF_HOME` if set, else the
library default `~/.cache/huggingface`. That default is durable (not
`/tmp`) on every platform `huggingface_hub` supports, so there is no
equivalent bug here today, but the lesson still applies operationally: if
you redirect the cache, redirect it somewhere persistent.

```bash
# Optional: put both model caches under one durable, shared location
export HF_HOME=/opt/cortex-cache/huggingface
export XDG_CACHE_HOME=/opt/cortex-cache        # FlashRank reads this via
                                                 # mcp_server.shared.platform.cache_dir()
```

Do **not** point either variable at `/tmp` or any other path a cleanup job,
container restart, or OS policy can purge — you will reproduce the exact
silent-failure pattern from the FlashRank incident, except for the
embedding model instead of the reranker.

### Air-gapped / no outbound internet

If the deployment environment has no route to `huggingface.co` at all (a
stricter case than a proxy — no egress permitted, even through a proxy),
neither `HTTPS_PROXY` nor the CA variables above help; the download itself
must not happen at runtime. Two options:

1. **Pre-warm the cache at build time.** Run the same pre-caching step
   `scripts/setup.py` performs (`cache_embedding_model`) and the
   FlashRank `Ranker(...)` construction inside your container/VM image
   build, while the build host still has network access, then ship the
   resulting `$HF_HOME` and `$XDG_CACHE_HOME/flashrank` directories baked
   into the image. This is the approach tracked for the official devcontainer
   in [#118](https://github.com/cdeust/Cortex/issues/118).
2. **Mirror Hugging Face internally.** Point `HF_HOME`'s resolution at an
   internal Hugging Face Hub mirror (or a static file mirror serving the
   same paths) reachable from the air-gapped network, and set
   `HF_ENDPOINT` to that mirror's base URL — this is a `huggingface_hub`
   convention, not a Cortex-specific mechanism; Cortex's downloads are
   ordinary `huggingface_hub`/`flashrank` HTTP calls and inherit whatever
   endpoint those libraries are configured to use.

See also the TLS client-certificate section above for a related but
distinct concern — that section covers CA/cert configuration for Cortex's
own PostgreSQL connection, not model downloads. The proxy/CA variables in
this section apply only to the outbound HTTPS calls
`sentence-transformers`/`huggingface_hub`/`flashrank` make; they have no
effect on `DATABASE_URL`'s `sslcert`/`sslkey`/`sslrootcert` parameters, and
vice versa.

---

## Two headless CI regimes — pick one per job, never both

Running `claude -p` (headless, no interactive session) in your own CI is a
different decision from running Cortex's *own* test suite (`.github/workflows/ci.yml`,
which never invokes the Claude CLI at all). This section is for teams that
drive Claude Code itself inside a pipeline — linting with an agent, an
authoring/review bot, a scheduled task — and need to decide whether Cortex's
memory is available to it. The two regimes are mutually exclusive by
construction; do not expect both properties from a single job.

### Regime A — `claude -p --bare`: reproducible, no Cortex

`--bare` loads no project/user settings, no hooks, and no MCP servers — it
forces `ANTHROPIC_API_KEY` billing and starts from a blank configuration
slate every invocation (see `mcp_server/handlers/consolidation/claude_cli.py`,
module docstring, "Solo mode" discussion, for the verified behavior Cortex's
own headless wiki-authoring drain relies on when contrasting `--bare` against
`--safe-mode`). Because MCP servers never load in this mode, **Cortex is not
present**: no `SessionStart` context injection, no `remember`/`recall`, no
consolidation. The job's output depends only on the prompt, the pinned CLI
version, and whatever files are in the checkout — nothing else.

Use this regime when the job's correctness argument is "this must produce
the same result on every run" — e.g. a CI check that a diff violates no
lint rule, or a report-generation step being asserted against a golden file.
Reproducibility is the whole point; adding Cortex's memory would make the
job's output depend on accumulated state from prior runs, which defeats that
argument.

### Regime B — containerized, pinned versions, with memory

Run the Claude CLI (pinned version) and Cortex (pinned plugin/package
version, PostgreSQL reachable) normally inside a container — project/user
settings, hooks, and MCP servers all load as they would locally. `SessionStart`
injects hot/anchored memories, `remember`/`recall` work, and the autonomous
wiki cycle can consolidate across scheduled runs. This gives the pipeline
continuity: a nightly review-agent job can accumulate "we already flagged
this pattern" across weeks of runs instead of starting blank every time.

The trade-off is exactly the one this repo already documents for release
benchmarks (see `CLAUDE.md`, Build & Test): a job with persistent state
behind it is not byte-for-byte reproducible run-to-run, because the DB state
differs. Do not use this regime to gate anything that must be a clean,
repeatable pass/fail (that is what Regime A, or `benchmarks/reproduce.sh`'s
isolated ephemeral container, is for) — use it for jobs whose value *is*
the accumulated memory.

### The rule

One job, one regime. A job that needs both a clean reproducible verdict and
persistent Cortex memory is asking for a contradiction — `--bare` strips the
MCP/hooks layer that memory depends on, and enabling that layer reintroduces
the run-to-run state dependency `--bare` exists to remove. If a pipeline
needs both properties, split it into two jobs instead of one.
