#!/usr/bin/env python3
"""Re-validate file-existence staleness for memories — fleet-watch #110.

Runs ``handlers.consolidation.memory_staleness_pass`` against the shared store:
for every non-stale, file-referencing memory whose referenced paths no longer
resolve on disk, sets ``is_stale=TRUE`` (mark-only; never de-stales — see the
pass docstring). This makes the staleness the injection banners surface
(age · grade · stale) actually fire, instead of waiting for a manual
``validate_memory`` run.

Usage
-----

Dry-run (default) — report what would be marked, write nothing::

    uv run python scripts/memory_staleness_revalidate.py

Apply the change to the DB::

    uv run python scripts/memory_staleness_revalidate.py --apply

Idempotent: a re-run skips rows already marked stale (``include_stale=False``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from mcp_server.handlers.consolidation.memory_staleness_pass import (  # noqa: E402
    DEFAULT_STALENESS_SCAN_LIMIT,
    revalidate_staleness,
)
from mcp_server.handlers.validate_memory import _resolve_existing_paths  # noqa: E402
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


class _DryRunStore:
    """Wraps the real store; reads pass through, mark writes are suppressed."""

    def __init__(self, inner):
        self._inner = inner

    def get_all_memories_for_validation(self, limit, *, after_id, include_stale):
        return self._inner.get_all_memories_for_validation(
            limit, after_id=after_id, include_stale=include_stale
        )

    def mark_memory_stale(self, memory_id, stale=True):
        pass  # dry-run: count via the pass's return value, write nothing


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="Write is_stale to the DB.")
    p.add_argument("--limit", type=int, default=DEFAULT_STALENESS_SCAN_LIMIT)
    p.add_argument("--threshold", type=float, default=0.5)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    target = store if args.apply else _DryRunStore(store)
    counts = revalidate_staleness(
        target, _resolve_existing_paths, limit=args.limit, threshold=args.threshold
    )
    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    label = "marked_stale" if args.apply else "would_mark_stale"
    print(f"{mode}: scanned={counts['scanned']} {label}={counts['marked_stale']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
