"""Content-addressed filesystem store for full raw tool-output artifacts.

Content addressing (sha256 of the content) makes repeated identical outputs
dedup to a single file, and monthly sharding (<yyyy-mm>/) keeps directory
fan-out bounded over time.

source: ADR-0504"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.infrastructure.config import METHODOLOGY_DIR
from mcp_server.shared import gated_files
from mcp_server.shared.redaction_gate import redact_text

ARTIFACTS_DIR = METHODOLOGY_DIR / "artifacts"

# source: ADR-0504
_ADDRESS_LEN = 16


def store_artifact(content: str, *, created_at: datetime | None = None) -> Path:
    """Write ``content`` to a content-addressed Markdown artifact, return path.

    Pre: content is a string. created_at, if given, dates the monthly shard;
    defaults to now (UTC).
    Post: the file ``ARTIFACTS_DIR/<yyyy-mm>/<sha256(content)[:16]>.md`` exists
    and holds ``content`` as UTF-8. Content-addressed: if the file already
    exists it is NOT rewritten (dedup — identical content maps to one path).
    Parent directories are created as needed. Returns the artifact path.
    """
    return write_artifact(content, created_at=created_at)[0]


def write_artifact(
    content: str, *, created_at: datetime | None = None
) -> tuple[Path, bool]:
    """Same as :func:`store_artifact`, and say whether this call created the file.

    Post: returns ``(path, created)``. ``created`` is True only when this call
    published the file; False when it already existed, in which case another
    memory may refer to it and only reference-counted removal may delete it
    (ADR-0503). The file is published exclusively, so two writers of the same
    content cannot both report ``created`` (issue #737).
    """
    # source: ADR-1110 — the address is taken over the redacted text, so the
    # name of the file is not derived from a secret either.
    content = redact_text(content)
    when = created_at or datetime.now(timezone.utc)
    shard = ARTIFACTS_DIR / f"{when.year:04d}-{when.month:02d}"
    address = hashlib.sha256(content.encode("utf-8")).hexdigest()[:_ADDRESS_LEN]
    path = shard / f"{address}.md"
    if path.exists():
        return path, False
    try:
        gated_files.write_text(path, content, exclusive=True)
    except FileExistsError:
        return path, False
    return path, True


def discard_created_artifact(path: Path) -> None:
    """Remove an artifact that :func:`write_artifact` created for a capture that
    was not delivered, so no file is left that no memory refers to.

    Pre: ``path`` was returned with ``created`` True by this process, and the
    memory that would have referred to it was never handed over (issue #737).
    An already absent file is not an error."""
    path.unlink(missing_ok=True)
