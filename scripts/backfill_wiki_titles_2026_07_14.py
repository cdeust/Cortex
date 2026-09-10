"""One-shot migration: repair corrupted wiki page titles from their source frontmatter.

This script targets ONLY rows whose title still carries one of these two
corruption signatures (`title LIKE 'title:%'` or `title LIKE '"%"'`) and
re-derives the title from the CURRENT on-disk file via the same
`page_row_from_md` the live wiki_write/wiki_migrate path uses — not a
duplicated parser.

Usage:
    DATABASE_URL=postgresql://cdeust@localhost:5432/cortex \\
        python3 scripts/backfill_wiki_titles_2026_07_14.py [--dry-run]

Precondition: a CSV backup of (id, rel_path, title) for every affected
row has already been taken (see the task's
wiki-titles-backup.csv artifact) before this script is run with
--dry-run absent.
Postcondition: every wiki.pages row matched by the corruption signature
at start-of-run either (a) has its title replaced by the value
`page_row_from_md` derives from the current on-disk file, or (b) is
reported as "source file missing" and left untouched (never guessed).

source: ADR-0704"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.handlers.wiki_migrate import page_row_from_md  # noqa: E402
from mcp_server.infrastructure.config import WIKI_ROOT  # noqa: E402
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402

_CORRUPTION_SIGNATURE_SQL = "title LIKE 'title:%' OR title LIKE '\"%%\"'"


def find_affected_rows(conn) -> list[tuple[int, str, str]]:
    """Return (id, rel_path, title) for every row matching the corruption
    signature. Pure query — no writes.

    The store's cursor may use a dict_row factory (confirmed: rows come
    back as dicts, not positional tuples — see
    wiki_migrate.py::_existing_memory_ids for the same defensive
    pattern) so index by column name, not position.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, rel_path, title FROM wiki.pages "  # noqa: S608 — interpolated fragment is the module-level literal _CORRUPTION_SIGNATURE_SQL; no external input (docs/ASSURANCE-CASE.md §5)
            f"WHERE {_CORRUPTION_SIGNATURE_SQL} ORDER BY id"
        )
        raw_rows = cur.fetchall()
    out: list[tuple[int, str, str]] = []
    for r in raw_rows:
        if isinstance(r, dict):
            out.append((r["id"], r["rel_path"], r["title"]))
        else:
            out.append((r[0], r[1], r[2]))
    return out


def repair_row(
    conn, wiki_root: Path, row_id: int, rel_path: str, old_title: str, *, dry_run: bool
) -> str:
    """Re-derive and, unless dry_run, persist the corrected title for one row.

    postcondition: returns one of "fixed", "source_missing", "unchanged"
    (derived title equals the stored title — corruption signature was a
    false positive) — never raises for a missing file, only for a real
    DB error.
    """
    full = wiki_root / rel_path
    if not full.exists():
        return "source_missing"
    content = full.read_text(encoding="utf-8", errors="ignore")
    row = page_row_from_md(rel_path, content)
    new_title = row["title"]
    if new_title == old_title:
        return "unchanged"
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE wiki.pages SET title = %s, tended = NOW() WHERE id = %s",
                (new_title, row_id),
            )
    return "fixed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report only, no writes."
    )
    args = parser.parse_args()

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    conn = store._conn

    rows = find_affected_rows(conn)
    print(f"Found {len(rows)} rows matching the corruption signature.")

    outcomes: dict[str, int] = {"fixed": 0, "source_missing": 0, "unchanged": 0}
    for row_id, rel_path, old_title in rows:
        outcome = repair_row(
            conn, Path(WIKI_ROOT), row_id, rel_path, old_title, dry_run=args.dry_run
        )
        outcomes[outcome] += 1
        print(
            f"  [{outcome}] id={row_id} rel_path={rel_path!r} old_title={old_title!r}"
        )

    if not args.dry_run:
        conn.commit()

    print(f"\nSummary: {outcomes}")
    remaining = 0
    if not args.dry_run:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) AS n FROM wiki.pages "  # noqa: S608 — interpolated fragment is the module-level literal _CORRUPTION_SIGNATURE_SQL; no external input (docs/ASSURANCE-CASE.md §5)
                f"WHERE {_CORRUPTION_SIGNATURE_SQL}"
            )
            row = cur.fetchone()
            remaining = row["n"] if isinstance(row, dict) else row[0]
        print(f"Rows still matching corruption signature after migration: {remaining}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
