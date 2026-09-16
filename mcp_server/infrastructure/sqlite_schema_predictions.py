"""SQLite DDL for prediction records.

A prediction is written open, carrying the confidence its author held, and
is later resolved against an observation with a verdict and a reference to
the evidence. Cortex never fetches that evidence: the caller supplies it,
which is what keeps the contract usable in any repository rather than only
where this project's own review conventions run (issue #597).

The PostgreSQL counterpart is `pg_schema.PREDICTIONS_DDL`.

source: ADR-1076"""

from __future__ import annotations

PREDICTIONS_DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    claim           TEXT NOT NULL,
    prediction      TEXT NOT NULL,
    test            TEXT NOT NULL,
    confidence      REAL NOT NULL
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    domain          TEXT NOT NULL DEFAULT '',
    directory       TEXT NOT NULL DEFAULT '',
    memory_id       INTEGER,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'resolved')),
    verdict         TEXT
                    CHECK (verdict IN ('confirmed', 'refuted', 'abandoned')),
    observed        TEXT,
    source_kind     TEXT
                    CHECK (source_kind IN ('review', 'ci', 'test', 'manual')),
    source_ref      TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at     TEXT,
    CHECK (
        (status = 'open' AND verdict IS NULL AND source_ref IS NULL)
        OR (status = 'resolved' AND verdict IS NOT NULL
            AND source_kind IS NOT NULL AND source_ref IS NOT NULL)
    )
)
"""

PREDICTION_INDEXES_DDL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_predictions_status "
    "ON predictions (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_predictions_domain ON predictions (domain)",
]


def get_prediction_ddl() -> list[str]:
    """Every prediction-record statement, in execution order."""
    return [PREDICTIONS_DDL, *PREDICTION_INDEXES_DDL]
