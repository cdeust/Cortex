# ADR-0782: scripts/setup.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/setup.py`; original SHA-256 `c424747d42622a8272849efc6cbaefc5a6d1319b70351997a3bc8cc3d30bcd0b`.

## Original docstring, lines 2–30

````text
"""Cortex — Cross-platform setup script.

Works on Windows, macOS, and Linux. Installs Python dependencies and,
per backend, sets up the database schema and pre-caches the embedding
model.

Usage:
    python3 scripts/setup.py                                # PostgreSQL path
    CORTEX_MEMORY_STORE_BACKEND=sqlite python3 scripts/setup.py   # SQLite path

SQLite mode (the Claude Code plugin's zero-config DEFAULT since the
sqlite-first install change; scripts/install-plugin.sh invokes this
script with CORTEX_MEMORY_STORE_BACKEND=sqlite on every OS):
    Skips PostgreSQL provisioning, schema setup, and the eager
    embedding-model pre-cache entirely. The store schema auto-creates on
    first open (SqliteMemoryStore._init_schema) and the embedding model
    downloads lazily on first encode (~100 MB, one-time — source:
    embedding_engine._ensure_model; size figure per PRIVACY.md /
    scripts/setup.sh step 5). Result: Python deps + verification only.
    This same flag is what gives the Windows postInstall path CI
    coverage on a runner with no PostgreSQL server (source: issue #113).

PostgreSQL mode (default when the flag is unset — the --postgres opt-in
path of scripts/install-plugin.sh on Windows, and the manual
cross-platform path):
    PostgreSQL must already be installed and running:
      https://www.postgresql.org/download/windows/
      Also install pgvector: https://github.com/pgvector/pgvector#windows
"""
````

## Original comment, lines 139–139

````text
# source: pyproject.toml requires-python = ">=3.10"
````

## Original comment, lines 143–144

````text
# source: structural — the probe counts the two required extensions
# ('vector', 'pg_trgm'); both present == 2 rows
````

## Original comment, lines 405–407

````text
# SQLite mode (see module docstring): no PostgreSQL server is
    # provisioned, so skip the PG-specific checks rather than reporting a
    # false failure for a step that was intentionally not run.
````

