# ADR-0784: scripts/setup_db.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/setup_db.py`; original SHA-256 `3cb544de4f02d0ac2d5017d4560fa37ff34379e3188ae2610358dcd8ea9dbffc`.

## Original comment, lines 93–95

````text
# Substrings that mark a PostgreSQL connection failure as authentication/
# authorization (not a missing database or a down server). Source: libpq
# error messages — postgresql.org/docs/current/protocol-error-fields.html
````

## Original docstring, lines 195–200

````text
"""Run full schema initialization via psycopg.

    Executes each DDL statement independently so a single failure
    (e.g. extension missing, column type mismatch) doesn't prevent
    the remaining tables and functions from being created.
    """
````

