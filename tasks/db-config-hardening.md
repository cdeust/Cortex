# DATABASE_URL config hardening (5 suggestions)

Context: cortex MCP failed at session start (`-32000`). Root cause was a **stale
`postmaster.pid`** (PID 1255 reused by `mobilerepaird` after unclean shutdown),
not config. Fixed by removing the stale lock + `brew services restart`. These 5
items harden the *setup/config* layer so future failures are diagnosed correctly
and per-user DB config survives plugin updates.

Verified facts (via claude-code-guide, source: code.claude.com/docs plugins-reference):
- `userConfig` lives in **plugin.json** (NOT marketplace.json). Token: `${user_config.<key>}`.
- `.mcp.json` `env` block is a **hard override** of shell env.
- No `${VAR:-default}` syntax — fallback must be in code or via userConfig `default`.

## Tasks

- [x] **#3 + #1** — `userConfig.database_url` in `plugin.json` with `default`
      `postgresql://127.0.0.1:5432/cortex`. Non-sensitive (resolves silently to
      default → preserves install-and-forget; survives updates via settings.json
      pluginConfigs). Trade-off: a user-supplied password lands in settings.json
      plaintext — same exposure class as the prior hardcoded/shell approach.
- [x] **#2** — `.mcp.json`: `DATABASE_URL` → `${user_config.database_url}`.
- [x] **#2 guard** — `pg_store._get_database_url()`: empty OR `${…}` → settings default.
- [x] **#5** — `localhost` → `127.0.0.1`: `memory_config.py:47`, `setup_db.py`,
      `session_start.py:29`, `setup.sh:213,406`. Benchmarks/tests untouched.
- [x] **#4** — `setup_db.py`: three-way diagnostic (server-unreachable + stale-lock
      hint / db-missing / auth-failure). `auth_failed` surfaced in
      `session_start._build_cold_start_message`.

## Verification
- [x] live DB → status "ready" (536,499 memories) via venv python.
- [x] server-down (bad port) → needs_install + stale-lock hint present.
- [x] unexpanded `${user_config.database_url}` token → resolves to 127.0.0.1 default.
- [x] plugin.json / .mcp.json / marketplace.json valid JSON.
- [x] pytest test_doctor.py + test_doctor_mcp.py → 44 passed, 0 regressions.
- [x] GHSA-gvpp-v77h-5w8g: server-layer binding untouched; diff has no server/ files.

## Notes
- `setup_db.py` is now 349 lines (>300). Low-stakes setup script (§10 stakes-
  calibration → size informal); single cohesive responsibility. Left as-is; a
  later split would move the diagnostic helpers to `infrastructure/db_diagnostics.py`.
