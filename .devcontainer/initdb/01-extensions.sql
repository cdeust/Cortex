-- Postgres init-script for the devcontainer's `db` service. This whole
-- directory (not this file alone) is bind-mounted at
-- /docker-entrypoint-initdb.d — single-file bind mounts proved unreliable
-- here: verified 2026-07-14 that mounting this file directly at
-- /docker-entrypoint-initdb.d/init-extensions.sql (a path absent from the
-- base pgvector/pgvector:pg16 image) made the container's runtime create
-- a DIRECTORY at that path instead of the file, and psql failed with
-- "could not read from input file: Is a directory". Mounting the parent
-- directory as a directory-to-directory bind avoids that failure mode.
--
-- Mirrors mcp_server/infrastructure/pg_schema.py::EXTENSIONS_DDL and the
-- identical idiom already validated in docker/entrypoint.sh's single-
-- container runtime image (both run "CREATE EXTENSION IF NOT EXISTS
-- vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;" before Cortex's own
-- schema DDL). Kept as a separate init script (rather than only relying on
-- scripts/setup_db.py at postCreateCommand) so the extensions exist from
-- the FIRST moment the `db` container reports healthy, before the `app`
-- container has run anything.
--
-- Runs exactly once, at first-ever initialization of the named volume
-- backing this service (official postgres image's
-- /docker-entrypoint-initdb.d/ contract — scripts here do not re-run on
-- container restart once PGDATA already exists).
-- source: https://github.com/docker-library/docs/blob/master/postgres/README.md#initialization-scripts

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
