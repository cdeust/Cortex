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
