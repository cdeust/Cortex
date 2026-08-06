"""Reference-counted removal of raw-output artifacts.

`artifact_store` writes content-addressed artifacts and never removes them.
That is safe while nothing deletes memories, but `forget` claims — in
PRIVACY.md, to users — that it deletes a memory. A gist+pointer memory keeps
its FULL raw text in the artifact, so deleting only the row leaves the content
readable on disk (issue #366).

Removal cannot be unconditional. `store_artifact` is content-addressed with
dedup: two captures of byte-identical output map to ONE file. Deleting that
file when the first of two referring memories is forgotten would leave the
second memory's pointer dangling at a path that no longer exists. So this
module answers "is anyone still referring to this artifact?" before unlinking.

Separate module from `artifact_store` on purpose: that one owns filesystem
writes and has no database dependency. Garbage collection needs both the store
and the filesystem, and mixing them into the writer would give it two reasons
to change (SRP).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_server.infrastructure.row_factory import DICT_ROW

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection

logger = logging.getLogger(__name__)


def count_artifact_references(conn: StoreConnection, artifact_path: str) -> int:
    """Number of memories whose body still points at ``artifact_path``.

    Pre: ``conn`` is a live store connection (PgMemoryStore's psycopg
    connection or the SQLite `PsycopgCompatConnection`, which translates the
    ``%s`` placeholder); ``artifact_path`` is a non-empty path string.
    Post: returns the count of rows in ``memories`` whose ``content`` contains
    the path. Substring match is the correct test here because the pointer line
    embeds the path verbatim and is the only place a memory body carries it.

    Uses ``COUNT(*) AS c`` + ``row["c"]`` with ``row_factory=DICT_ROW``, the
    shared cross-backend scalar convention (cf. count_relationships /
    count_entities): the SQLite compat cursor yields mapping rows, so reading
    by position raises KeyError there.

    Raises whatever the driver raises — a failure to COUNT must NOT be read as
    "zero references", which would delete a still-referenced artifact. The
    caller decides how to degrade; see ``delete_artifact_if_unreferenced``.
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE content LIKE %s",
            (f"%{artifact_path}%",),
        )
        row = cur.fetchone()
    return int(row["c"]) if row else 0


def delete_artifact_if_unreferenced(
    conn: StoreConnection, artifact_path: str | None
) -> bool:
    """Unlink ``artifact_path`` when no memory refers to it any more.

    Pre: the referring memory row has ALREADY been deleted — otherwise it
    counts itself and the artifact is never collected. ``artifact_path`` may be
    None (memory had no artifact), in which case this is a no-op.
    Post: returns True only when the file was actually unlinked. Returns False
    when there was no artifact, when another memory still refers to it, when
    the file is already gone, or when the reference count could not be
    established. Never raises: a failure to collect an artifact must not fail
    the deletion of the memory the user asked to forget, and every non-removal
    path logs why.
    """
    if not artifact_path:
        return False

    try:
        references = count_artifact_references(conn, artifact_path)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary, see docstring
        # Fail CLOSED: an unknown reference count must not authorize a delete.
        logger.warning(
            "artifact reference count failed for %s — keeping the file: %s",
            artifact_path,
            exc,
        )
        return False

    if references > 0:
        logger.info(
            "artifact %s kept — still referenced by %d memory/memories",
            artifact_path,
            references,
        )
        return False

    path = Path(artifact_path)
    try:
        path.unlink()
    except FileNotFoundError:
        logger.info("artifact %s already absent — nothing to remove", artifact_path)
        return False
    except OSError as exc:
        logger.warning("artifact %s could not be removed: %s", artifact_path, exc)
        return False
    logger.info("artifact %s removed (last referrer forgotten)", artifact_path)
    return True
