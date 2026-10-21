"""The store broker's capacity, idle exit and private log.

Each request class gets as many slots as its pool has connections, so a
running request always finds one: ``POOL_INTERACTIVE_MAX`` interactive and
``POOL_BATCH_MAX`` background slots (ADR-1112 decision 4: R is the
interactive pool, background never takes it). Every value can
be set from the environment; increment 4 measures them.

source: ADR-1112 decision 4; ADR-0534 (pool sizes); ADR-0488 (worker log)
"""

from __future__ import annotations

import logging
import math
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp_server.infrastructure.broker_scheduler import SchedulerPolicy
from mcp_server.infrastructure.broker_server import ServerPolicy
from mcp_server.infrastructure.memory_config import get_memory_settings

# source: the capture worker's CORTEX_CAPTURE_IDLE_SECONDS default (ADR-0512)
DEFAULT_IDLE_SECONDS = 300.0
# source: ADR-1112 queued requests per class before a caller waits for a place
DEFAULT_QUEUE_LIMIT = 256
# source: ADR-1112 under macOS's default 256 open files per process
DEFAULT_MAX_CLIENTS = 128
# source: ADR-0488 (the capture worker log budget)
LOG_BYTES = 196_000 * 30


def _number(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def server_policy() -> ServerPolicy:
    settings = get_memory_settings()
    return ServerPolicy(
        scheduler=SchedulerPolicy(
            interactive_slots=settings.POOL_INTERACTIVE_MAX,
            background_slots=settings.POOL_BATCH_MAX,
            queue_limit=int(_number("CORTEX_BROKER_QUEUE_LIMIT", DEFAULT_QUEUE_LIMIT)),
        ),
        idle_seconds=_number("CORTEX_BROKER_IDLE_SECONDS", DEFAULT_IDLE_SECONDS),
        max_connections=int(_number("CORTEX_BROKER_MAX_CLIENTS", DEFAULT_MAX_CLIENTS)),
    )


def configure_logging(directory: Path, stem: str) -> Path:
    """Owner-only rotating log ``directory/stem.log``; never memory content."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{stem}.log"
    for candidate in (path, path.with_suffix(".log.1")):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or (
            hasattr(os, "geteuid") and info.st_uid != os.geteuid()
        ):
            raise PermissionError("store broker log must be an owner-controlled file")
    flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    os.close(os.open(path, flags, 0o600))
    handler = RotatingFileHandler(
        path, maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return path
