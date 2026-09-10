"""Reference-counted removal of raw-output artifacts.

source: ADR-0503"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_server.infrastructure.row_factory import DICT_ROW

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection

logger = logging.getLogger(__name__)


def count_artifact_references(conn: StoreConnection, artifact_path: str) -> int:
    """Return the number of memories whose body refers to artifact_path. Database
    errors propagate to the caller.

    source: ADR-0503"""
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

    source: ADR-0503"""
    if not artifact_path:
        return False

    try:
        references = count_artifact_references(conn, artifact_path)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary, see docstring
        # source: ADR-0503
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
