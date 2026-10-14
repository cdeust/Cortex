"""SessionStart hook external-memory-source detection and first-run backfill.

source: ADR-0498"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from mcp_server.hooks.session_start_common import _log


def _detect_external_sources() -> list[dict]:
    """Detect other AI memory systems that can be imported into Cortex."""
    sources = []

    # claude-mem SQLite
    claude_mem_db = Path.home() / ".claude-mem" / "claude-mem.db"
    if claude_mem_db.exists():
        try:
            conn = sqlite3.connect(str(claude_mem_db))
            count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            conn.close()
            if count > 0:
                sources.append(
                    {"name": "claude-mem", "count": count, "path": str(claude_mem_db)}
                )
        except Exception:  # noqa: BLE001 — external-source probe — failure is reported as a count-0 source entry in the banner
            sources.append(
                {"name": "claude-mem", "count": 0, "path": str(claude_mem_db)}
            )

    # Cursor conversations
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        cursor_files = list(cursor_dir.glob("**/*.jsonl"))
        if cursor_files:
            sources.append(
                {"name": "Cursor", "count": len(cursor_files), "path": str(cursor_dir)}
            )

    # ChatGPT exports in Downloads
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        chatgpt_files = list(downloads.glob("**/conversations.json"))
        if chatgpt_files:
            sources.append(
                {
                    "name": "ChatGPT",
                    "count": len(chatgpt_files),
                    "path": str(chatgpt_files[0]),
                }
            )

    return sources


def _auto_backfill() -> int:
    """Run backfill + cascade automatically on first install.

    Returns number of memories imported.
    """
    try:
        from mcp_server.handlers.backfill_memories import handler as backfill_handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        result = asyncio.run(
            backfill_handler(
                {
                    "max_files": 100,
                    "min_importance": 0.35,
                    "force_reprocess": False,
                }
            )
        )
        imported = result.get("backfilled", 0)
        cascade_advanced = result.get("cascade_advanced", 0)
        _log(f"Auto-backfill: {imported} imported, {cascade_advanced} cascaded")
        return imported
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"Auto-backfill failed (non-fatal): {exc}")
        return 0


def _print_external_sources() -> None:
    """Detect and report importable external memory sources."""
    try:
        sources = _detect_external_sources()
        if not sources:
            return
        lines = ["\n### External Memory Sources Detected\n"]
        for s in sources:
            count_str = f" ({s['count']} items)" if s.get("count") else ""
            lines.append(f"- **{s['name']}**{count_str} — `{s['path']}`")
        lines.append("\nUse `/cortex-import` to import these into Cortex.")
        print("\n".join(lines))
        _log(f"Detected {len(sources)} external memory sources")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"External source detection failed (non-fatal): {exc}")
