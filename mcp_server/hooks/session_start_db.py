"""SessionStart hook database access: PostgreSQL setup/connect, checkpoint and counts.

source: ADR-0498"""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

from mcp_server.hooks.session_start_common import _DATABASE_URL, _PLUGIN_ROOT, _log
from mcp_server.infrastructure.hook_queries import (
    session_active_checkpoint,
    session_memory_count,
)


def _try_setup_db() -> dict | None:
    """Run setup_db.py and return its result, or None on failure."""
    setup_script = (
        Path(__file__).resolve().parent.parent.parent / "scripts" / "setup_db.py"
    )
    if not setup_script.exists():
        # Try relative to CLAUDE_PLUGIN_ROOT
        if _PLUGIN_ROOT:
            setup_script = Path(_PLUGIN_ROOT) / "scripts" / "setup_db.py"
        if not setup_script.exists():
            return None
    try:
        r = subprocess.run(
            [sys.executable, str(setup_script)],
            capture_output=True,
            timeout=15,
            text=True,
            encoding="utf-8",  # setup_db.py prints json.dumps, ASCII
            env={**os.environ, "DATABASE_URL": _DATABASE_URL},
        )
        if r.stdout.strip():
            return json.loads(r.stdout.strip())
        return None
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"setup_db failed: {exc}")
        return None


def _pg_store():
    """The shared PostgreSQL store, or None when it cannot be opened.

    The hook holds no database connection of its own (ADR-1112); its
    queries are store operations (``infrastructure/hook_queries.py``)."""
    try:
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary

        return get_shared_store()
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"PostgreSQL store unavailable: {exc}")
        return None


def _parse_json_list(val) -> list:
    """Tolerant list coercion for checkpoint columns (JSON text or list)."""
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) or []
    except (ValueError, TypeError):
        return [val] if isinstance(val, str) and val.strip() else []


def _checkpoint_from_row(row: dict | None) -> dict | None:
    """Map a checkpoint row (PG dict_row or SQLite normalized row) to the
    banner's checkpoint shape. Shared by both backend paths."""
    if not row:
        return None
    return {
        "current_task": row.get("current_task", ""),
        "next_steps": _parse_json_list(row.get("next_steps")),
        "open_questions": _parse_json_list(row.get("open_questions")),
        "active_errors": _parse_json_list(row.get("active_errors")),
        "key_decisions": _parse_json_list(row.get("key_decisions")),
        "directory": row.get("directory_context", ""),
    }


def _fetch_checkpoint(store) -> dict | None:
    """Fetch the latest active checkpoint."""
    try:
        row = store.call(session_active_checkpoint)
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"checkpoint fetch failed (non-fatal): {exc}")
        return None

    return _checkpoint_from_row(row)


def _count_memories(store) -> int:
    """Count total memories."""
    try:
        return store.call(session_memory_count)
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"memory count failed (non-fatal): {exc}")
        return 0


def _count_session_files() -> int:
    """Count JSONL session files in ~/.claude/projects/."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return 0
    count = 0
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            count += len(list(project_dir.glob("*.jsonl")))
    return count
