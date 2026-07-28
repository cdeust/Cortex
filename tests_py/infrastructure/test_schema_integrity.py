"""Schema-integrity audit across hooks/ and handlers/.

Issue #20 root cause: a SELECT against ``memories.heat`` shipped to
production. ``heat`` is not a stored column — it is a derived field
computed by ``effective_heat()``. The error silently broke the
UserPromptSubmit hook on every fire because the hook's ``except
Exception`` swallowed the PG error.

This test is the abstraction barrier preventing recurrence: it
extracts every SQL string literal that targets the ``memories`` table
from hooks/handlers and runs ``EXPLAIN`` against the live schema.
``EXPLAIN`` does not execute the query but it *does* validate every
column reference — the planner rejects unknown columns with the same
``column "X" does not exist`` error that broke production.

Method: lightweight regex finds string blobs that contain
``FROM memories`` / ``UPDATE memories`` / ``INTO memories``.
Parameter placeholders (``%s``) are substituted with safe NULL casts
so the planner can resolve types. Queries that reference columns
from other tables (joins to ``wiki.pages``, etc.) still work because
``EXPLAIN`` validates *all* referenced columns.

False positives are possible (split-line SQL not concatenated, format
strings, dynamic SQL). When found, add the offending blob hash to
``_KNOWN_BENIGN_BLOBS`` and document the reason.

Pre/post:
- pre: PG reachable; ``memories`` table created via PgMemoryStore init.
- post: every memories-touching SQL blob in hooks/ and handlers/
  parses cleanly under ``EXPLAIN``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from tests_py.conftest import _USE_PG, _TEST_DB_URL  # type: ignore


pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — schema integrity needs live schema"
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = [
    _REPO_ROOT / "mcp_server" / "hooks",
    _REPO_ROOT / "mcp_server" / "handlers",
]


# Triple-quoted Python strings are the SQL home; single-quoted
# concatenated strings are also common.
_TRIPLE_RE = re.compile(r'"""([\s\S]*?)"""')
_TRIPLE_RE_2 = re.compile(r"'''([\s\S]*?)'''")
# Concatenated single-line double-quoted strings:
#     "SELECT id, content "
#     "FROM memories WHERE ..."
# Captured with a regex that tolerates whitespace + newlines between
# adjacent string literals.
_CONCAT_RE = re.compile(r'((?:"(?:[^"\\\n]|\\.)*"\s*)+)')

# Tokens that mean "this blob talks to the memories table":
_MEMORIES_PRESENT = re.compile(
    r"\b(?:FROM|UPDATE|INTO|JOIN)\s+memories\b", re.IGNORECASE
)

# Strip Python f-string / .format placeholders before EXPLAIN. Keep
# %s / %(name)s — psycopg-style placeholders we substitute below.
_PYFMT_BRACES = re.compile(r"\{[^{}]*\}")

# psycopg parameter placeholder. Replace with NULL-cast for EXPLAIN.
_PG_PARAM = re.compile(r"%s|%\(\w+\)s")


def _gather_python_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        files.extend(d.rglob("*.py"))
    return files


def _extract_sql_blobs(source: str) -> list[str]:
    """Return string literals that target the memories table."""
    blobs: list[str] = []

    for m in _TRIPLE_RE.finditer(source):
        blobs.append(m.group(1))
    for m in _TRIPLE_RE_2.finditer(source):
        blobs.append(m.group(1))

    # Concatenated double-quoted strings — strip surrounding quotes and
    # join. Single literals are also matched.
    for m in _CONCAT_RE.finditer(source):
        chunk = m.group(1)
        # Re-extract individual quoted segments and concat them.
        parts = re.findall(r'"((?:[^"\\\n]|\\.)*)"', chunk)
        joined = "".join(parts)
        if len(joined) > 20:
            blobs.append(joined)

    # Filter to memories-touching blobs only.
    return [b for b in blobs if _MEMORIES_PRESENT.search(b)]


def _looks_like_sql(blob: str) -> bool:
    """Heuristic: must contain a SQL verb."""
    return bool(re.search(r"\b(SELECT|UPDATE|INSERT|DELETE|WITH)\b", blob, re.I))


def _prepare_for_explain(blob: str) -> str:
    """Substitute placeholders with typed NULLs so EXPLAIN can plan."""
    # Drop docstring tail like ``\n    """`` artifacts (we already stripped triple
    # quotes).
    sql = blob.strip()
    # Replace f-string-style braces with NULL.
    sql = _PYFMT_BRACES.sub("NULL", sql)
    # Replace psycopg %s placeholders with safely-typed NULL.
    sql = _PG_PARAM.sub("NULL", sql)
    return sql


# Blob fingerprints we have manually reviewed and confirmed benign.
# Add a (hash, reason) entry if a blob fails EXPLAIN for a non-bug
# reason (e.g. uses a dynamically-built SQL fragment that's not a
# complete statement).
_KNOWN_BENIGN_BLOBS: dict[str, str] = {}


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@pytest.fixture(scope="module")
def _live_conn():
    import psycopg

    # Ensure schema is fully initialised, including effective_heat(). Close
    # the bootstrap store immediately so its psycopg connection is not leaked.
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    PgMemoryStore(database_url=_TEST_DB_URL).close()

    conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
    yield conn
    conn.close()


def test_no_hook_or_handler_sql_references_unknown_columns(_live_conn) -> None:
    """Run EXPLAIN on every memories-touching SQL blob in hooks/handlers.

    A blob that references ``memories.heat`` (or any other unknown
    column) fails with ``column "X" does not exist`` — the same error
    that broke production in issue #20.
    """
    failures: list[tuple[str, str, str]] = []  # (file, error_summary, sql_excerpt)
    audited = 0

    for path in _gather_python_files():
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "memories" not in source:
            continue

        rel = str(path.relative_to(_REPO_ROOT))

        for blob in _extract_sql_blobs(source):
            if not _looks_like_sql(blob):
                continue
            digest = _digest(blob)
            if digest in _KNOWN_BENIGN_BLOBS:
                continue

            sql = _prepare_for_explain(blob)
            audited += 1
            try:
                # EXPLAIN inside a savepoint so failures don't poison
                # the connection state. autocommit=True means each
                # EXPLAIN is its own transaction.
                _live_conn.execute(f"EXPLAIN {sql}")
            except Exception as exc:
                msg = str(exc).splitlines()[0][:200]
                # Only flag the column-existence failure mode — other
                # planner errors (missing functions, type mismatches
                # from NULL substitution) are out of scope and would
                # generate noise.
                if "does not exist" in msg or "no such column" in msg.lower():
                    failures.append((rel, msg, sql[:200]))

    assert audited > 0, "regex extracted zero SQL blobs — extraction is broken"

    assert not failures, (
        f"SQL in hooks/handlers references unknown columns "
        f"({len(failures)} failure(s) across {audited} audited blob(s)):\n"
        + "\n".join(
            f"  {f}: {err}\n    SQL: {sql_excerpt}" for f, err, sql_excerpt in failures
        )
        + "\n\nFix the SQL — see issue #20 for the reference fix pattern "
        "(use effective_heat(m, NOW()) instead of memories.heat)."
    )
