---
created: 2026-10-21T01:41:51Z
kind: adr
number: 1112
status: accepted
tags: [privacy, zero-trust, file-permissions, storage, windows]
title: Personal data is stored owner-only
---
# ADR-1112: Personal data is stored owner-only

## Status

accepted

## Context

The three-pillar audit of 2026-10-21 (E18) measured on its host `~/.claude/methodology` 0755, `memory.db` 0644, `artifacts/` 0755, `telemetry.jsonl` 0644 and logs 0644, and in a stock Linux container `methodology` 0775, `memory.db` 0644, logs and `telemetry.jsonl` 0664. Only the capture spool, socket and locks were forced to 0600/0700 (`capture_spool.py:34-36`, `capture_socket.py:22-24`); the store and the artifacts followed the umask (`sqlite_store.py:126`, `artifact_store.py:39`). On a shared host any local account could read every memory, transcript excerpt and log line. The same modes were confirmed read-only on this host on 2026-10-21 (`stat` of `~/.claude/methodology`, `memory.db`, `consolidate.log`, `telemetry.jsonl`).

Two layers write the data: Cortex's own writers (since ADR-1110, every file goes through `shared/gated_files.py`, the rotating log of `shared/log_rotation.py`, or SQLite through `infrastructure/sqlite_connection_registry.py`) and installs made before this change, whose files already exist with umask modes. A process-wide `umask(0o077)` was not chosen: it would also make files Cortex writes into the user's own repository (`CLAUDE.md` sections, `docs/adr` mirrors, a project wiki) unreadable to other tools and accounts that legitimately read the repository.

The cache root was hard-coded in three places (`session_registry.py:40` and `groomer_coordinator.py:70` as `~/.cache/cortex`, `mcp_client.py:555` for upstream logs) and did not follow `CORTEX_CLAUDE_DIR`, although PRIVACY.md says that variable relocates the root "and everything derived from it". As a consequence the test suite on `main`, which relocates `CORTEX_CLAUDE_DIR` to a throwaway directory, still wrote session-registry and groomer files into the developer's real `~/.cache/cortex` (measured with an instrumented run on 2026-10-21: every hook test that registers a session or a groomer).

## Decision

1. **Where personal data lives** (`shared/private_paths.py`): `<claude dir>/methodology`, `<claude dir>/.capture-worker`, `<claude dir>/brain-index.json` and the cache root (`<claude dir>` is `CORTEX_CLAUDE_DIR` or `~/.claude`). The cache root is `CORTEX_CACHE_DIR` when set, else `<XDG_CACHE_HOME>/cortex` when that is set, else `<CORTEX_CLAUDE_DIR>/cache/cortex` when the data root is relocated, else `~/.cache/cortex`; the session registry, the groomer coordinator and the upstream MCP logs all resolve through it. `is_private(path)` answers for any path.
2. **Created private.** Under those roots `gated_files` writes files `0600` (an explicit mode still wins), the rotating log opens and keeps its file `0600` across rotation, the upstream MCP stderr mirror is created `0600`, and every directory level created or written into, from the file up to its root, is `0700` (`ensure_private_dir`). The SQLite database is created `0600` by the connection registry before SQLite opens it; SQLite gives the WAL and shared-memory files the database file's mode. Outside the roots nothing changes: a project file keeps the umask's mode, a replaced file keeps its mode.
3. **Existing installs** (`harden_private_storage`, called by the MCP server's `main()` before it serves and by the SessionStart hook): the roots themselves are made owner-only on every call; their whole content once per install, recorded by the stamp `methodology/.private-modes-v1`: directories `0700`, regular files lose their group and other bits (an executable keeps its owner execute bit), symlinks are neither followed nor changed. A path that cannot be changed (another owner, a read-only mount) is reported on stderr with its path and startup continues.
4. **Windows**: POSIX modes do not express owner-only there. Each existing root gets `icacls <root> /inheritance:r /grant:r <DOMAIN>\<user>:(OI)(CI)F`: inherited entries removed, full control for the current user only, inherited by every file and directory below.
5. **Test isolation** follows from decision 1: the suite already relocates `CORTEX_CLAUDE_DIR` (`tests_py/conftest.py`, incident #219), so the cache root of every test process, and of every child that inherits the environment, is inside the throwaway directory.

## Consequences

Evidence (2026-10-21, macOS arm64 Apple M4, APFS, umask 022): `tests_py/infrastructure/test_private_storage_modes.py` writes through production APIs (SQLite store, rotating log, artifact store, wiki store) and checks `memory.db`, `-wal`, `-shm`, logs, telemetry, artifacts and wiki pages at 0600 in 0700 directories, and a project wiki page at 0644; it uses only APIs present on `main`, where all 4 tests fail (three find 0644 files in 0755 directories; the fourth finds a project wiki page at 0600, which `main` wrote through `mkstemp` and this change returns to the umask). `tests_py/shared/test_private_paths.py` builds a legacy tree (0644/0664 files, 0775 directories, an executable, a symlink to a file outside) and checks the result, the once-per-install walk, the cache-root precedence, the stderr report of a refused change and the exact Windows ACL command. An instrumented full run (every hardening function raising on a path under the real `~/.cache/cortex`) ended with zero hits. Cost of the one-time walk on a synthetic tree of 20,000 files in 200 directories: 1.1 s for the first run (20,202 entries changed), 0.1 ms for every later run; the SessionStart hook timeout is 30 s (`.claude-plugin/plugin.json`).

Incident during development: one full run of the suite, made before decision 5 held, executed the hardening against the developer's real `~/.cache/cortex` (its directories became 0700 and its files 0600; nothing was deleted or rewritten). This is the state the shipped code gives that directory at the next server or session start; restoring the looser 0755 was refused by the session's permission policy, and the owner was told.

Limits:

- The Windows ACL is verified as a command (fake runner); it has not been executed on a Windows host here. The CI Windows leg runs the unit tests only; an install-e2e leg asserting ACLs and modes on every platform is planned (audit Track 1.4).
- A file created after the one-time walk by a process that does not write through the gate (the external code-analysis binary under `<cache root>/code-graphs`, a user's own tool) gets the umask's mode, but sits inside a `0700` root that other accounts cannot traverse.
- `~/.cortex` (code graphs written by the external pipeline) is not covered. `viz_client` reads the viz server's registry at `~/.cache/cortex/viz-server.json` directly; the file is inside the default cache root and is tightened with it.
- A developer environment with `XDG_CACHE_HOME` exported points the cache root of the test suite at that real cache (unchanged from `main`, where the groomer already honoured it).


## Addendum (2026-10-21): review of PR #775 (B3, N5, N6)

- **No mode change through a symbolic link (B3).** A data root that was a symlink was chmodded and walked (`os.walk` follows a top-level link), and `ensure_private_dir` chmodded each level by path: measured 0755/0644 outside the roots turned 0700/0600. Every change now opens the entry `O_NOFOLLOW` (plus `O_DIRECTORY`, `O_NONBLOCK`), checks it is the inode `lstat` saw and calls `fchmod`; the walk is `os.fwalk(follow_symlinks=False)`. A root that is a link is neither tightened nor walked and is reported at startup; `ensure_private_dir` stops at the first level that is a link. On Windows only roots that are real directories get the ACL.
- **Empty Windows user (N5).** An empty or blank `USERNAME` made the icacls principal empty in the call that removes inheritance; it is now refused with `OSError(EINVAL)` before icacls runs and reported at startup.
- **Lock files (N6).** `private_paths.open_lock_file` is the one opener of every lock file: `O_RDWR | O_CREAT | O_NOFOLLOW` at 0600, and a lock an older version left wider is tightened through the descriptor. The pipeline install lock and the groomer decision lock were created 0644.
