# Cortex — Deployment Scenarios

Two scenarios that have caused friction for Discord users: running under WSL
and connecting with TLS client-certificate authentication instead of a
password.

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

- `torch==2.11.0`, `sentence-transformers==5.4.1`, `flashrank==0.2.10` —
  `# source: uv.lock` (this repo).
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
