"""Private rotating worker diagnostics, independent of the launching hook pipe."""

from __future__ import annotations

import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

# source: ADR-0488
LOG_BYTES = 196_000 * 30


def configure(runtime: Path) -> None:
    path = runtime / "worker.log"
    for candidate in (path, path.with_suffix(".log.1")):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("capture worker log must be an owner-controlled file")
    descriptor = os.open(
        path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600
    )
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    # source: ADR-0488
    handler = RotatingFileHandler(
        path, maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8"
    )
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
