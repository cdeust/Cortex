---
created: 2026-09-22T23:11:45Z
kind: adr
number: 1087
status: accepted
tags: [adr]
title: Isolate every ML-importing child process spawned by scripts/setup.py
---
# ADR-1087: Isolate every ML-importing child process spawned by scripts/setup.py

## Status

accepted

## Context

Issue #621 established that the vendored `deps/` directory must be isolated from the interpreter's user site-packages before importing the ML stack (sentence-transformers → transformers → torch/torchaudio): a plain `sys.path` entry is not isolation, since packages `deps/` does not vendor keep resolving from user site-packages, and a coherent user-site CUDA torch/torchvision/torchaudio set paired with the vendored CPU torch aborts the process. `scripts/launcher_site.isolate_deps()` fixes this for the main process (`scripts/launcher.py`, `scripts/setup.py`'s own `verify()` step).

Issue #633 (reported on Windows, 4.23.1) showed the fix does not reach every process that imports the ML stack. Three call sites launch a *child* process that reaches `deps/` only through the `PYTHONPATH` environment variable, which cannot process `.pth` files and cannot cut user site-packages the way `isolate_deps()` does in-process:
1. `scripts/setup.py::cache_embedding_model()` (Windows/cross-platform path)
2. `scripts/lib/precache_embedding_model.sh::precache_embedding_model_step()` (macOS/Linux `--postgres` path)
3. `scripts/setup.py::setup_database()` — audited and found NOT to need this: its child (`setup_db.py`) imports only `psycopg` and `mcp_server.infrastructure.pg_schema`, neither part of the torch/torchaudio split.

Both (1) and (2) previously carried "Known gap" comments acknowledging this and choosing to warn rather than fail, deferring the fix.

## Decision

Every child process spawned by setup that imports the ML stack (sentence-transformers) must bootstrap its own `launcher_site.isolate_deps(deps_dir)` call before that import, using a small inline Python prelude prepended to the child's `-c` source:

    import sys; sys.path.insert(0, <script_dir>)
    import launcher_site
    launcher_site.isolate_deps(<deps_dir>)
    <rest of the child's work>

`<script_dir>` is the directory containing `launcher_site.py` (derivable from a value the caller already has — `SCRIPT_DIR` in `scripts/setup.py`, `${project_dir}/scripts` in the bash library — so no new parameter is needed on tested function signatures). Paths are embedded via `repr()`, not an f-string, so a Windows path's backslashes escape correctly inside the child's source.

`scripts/setup.py::cache_embedding_model()`'s payload construction is pulled into a standalone `_model_cache_child_source(script_dir, deps_dir) -> str` function so it is unit-testable (compiled and run against a stubbed `sentence_transformers`) rather than only ever exercised as an opaque string mocked out by every test that touches `cache_embedding_model`.

`scripts/setup.py::_model_checks()` additionally widens its exception handling from `except ImportError` to `except Exception`, matching the module's own `_postgres_checks()` pattern: a torch/torchaudio ABI mismatch surfaces as `OSError`/`RuntimeError` deep inside the import chain, and letting that escape crashes the whole `verify()` step before it can print a `[FAIL]` row for `scripts/lib/setup_py_step.sh` to name — reproducing the exact "exited before reporting any check" failure mode issue #633 also reports.

`setup_database()` is left unchanged; its comment is corrected to state why (no ML-stack import) instead of citing this fix as still-outstanding for it.

## Consequences

Pre-caching the embedding model during install now succeeds on a machine whose user site-packages carries a conflicting torch/torchaudio build, on every OS `scripts/setup.py` and `scripts/setup.sh` run on — previously it silently degraded to "download on first use" with no diagnostic pointing at the cause. `verify()`'s dependency checks now report a `[FAIL] sentence-transformers` row instead of crashing the process on the same class of environment conflict, so `scripts/lib/setup_py_step.sh`'s failure-naming logic (issue #621) has a row to name.

Cost: `_model_cache_child_source` is one more function to keep in sync if the child payload's shape changes; the bootstrap prelude adds a few milliseconds of import overhead per setup run, negligible against the ~100MB model download it precedes.

Out of scope: a PostgreSQL → SQLite backend migration path (a pre-existing gap, unrelated to this isolation fix) — flagged for a separate issue rather than folded in here.
