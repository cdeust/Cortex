"""Background worker that invokes ``consolidate`` autonomously.

Spawned by the SessionStart hook when the consolidate stamp is older
than the configured TTL (default 6h). Runs detached from the parent
process so SessionStart returns immediately — the user never waits.

Invocation::

    python -m mcp_server.hooks.consolidate_background [--deep]

Exit code:
  * 0 on success.
  * 1 on recoverable error (logged, won't crash loop).
  * 2 on fatal misconfiguration.

The stamp is at ``~/.claude/methodology/.last_consolidate`` and carries
the ISO timestamp of the last successful run. Updated on every successful
exit. SessionStart reads it to decide whether to spawn this worker.

User direction 2026-05-18: "Consolidate cycle I shouldn't have to run
manually. It should be completely automatic." This module is the
mechanism that makes that true — no cron, no daemon required; every
session opens against a recently-consolidated store.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


STAMP_PATH: Path = Path.home() / ".claude" / "methodology" / ".last_consolidate"


def _write_stamp(now: str | None = None) -> None:
    """Record a successful consolidate at ``now`` (or current UTC)."""
    STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    iso = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    STAMP_PATH.write_text(iso, encoding="utf-8")


def read_stamp() -> datetime | None:
    """Return the timestamp of the last successful consolidate, or None."""
    if not STAMP_PATH.is_file():
        return None
    try:
        raw = STAMP_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return datetime.fromisoformat(raw)
    except (OSError, ValueError):
        return None


def main() -> None:
    deep = "--deep" in sys.argv[1:]

    # Lazy import so a failure here doesn't crash the spawn loop.
    try:
        from mcp_server.handlers.consolidate import handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[bg-consolidate] import failed: {exc}", file=sys.stderr)
        sys.exit(1)

    args: dict[str, Any] = {
        # Standard knobs from the handler schema; deep=False is the
        # default so the cycle stays cheap enough to run every 6 hours.
        "decay": True,
        "compress": True,
        "cls": True,
        "memify": True,
        "deep": deep,
        # Wiki maintenance ON by default — purge stubs + classifier
        # rejects, audit coverage. The defaults in the handler match
        # the autonomous policy (both axes apply, cap 500/cycle).
        "wiki": True,
    }

    start = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[bg-consolidate] starting at {start} deep={deep}", file=sys.stderr)
    try:
        result = asyncio.run(handler(args))
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        # Non-fatal: keep the stamp untouched so the next session retries.
        print(f"[bg-consolidate] handler raised: {exc}", file=sys.stderr)
        sys.exit(1)

    status = result.get("status") if isinstance(result, dict) else "unknown"
    duration = result.get("duration_ms") if isinstance(result, dict) else None
    print(
        f"[bg-consolidate] finished status={status} duration_ms={duration}",
        file=sys.stderr,
    )

    # Always write the stamp on a returned result — even partial
    # failures are progress (decay ran, wiki purge ran, etc.). A total
    # failure raises and we exit non-zero above.
    try:
        _write_stamp()
    except OSError as exc:
        print(f"[bg-consolidate] stamp write failed: {exc}", file=sys.stderr)

    # Echo the wiki block to stderr so the log file shows what changed.
    wiki = result.get("wiki") if isinstance(result, dict) else None
    if isinstance(wiki, dict):
        print(
            f"[bg-consolidate] wiki: "
            f"stub purged={wiki.get('stub', {}).get('purged', 0)} "
            f"classifier purged={wiki.get('classifier', {}).get('purged', 0)} "
            f"pending_total={wiki.get('pending_total', 0)}",
            file=sys.stderr,
        )

    sys.exit(0 if status == "ok" else 1)


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
