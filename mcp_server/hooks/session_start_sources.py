"""SessionStart hook external-memory-source detection.

source: ADR-0498"""

from __future__ import annotations

from pathlib import Path

from mcp_server.hooks.session_start_common import _log
from mcp_server.infrastructure.db_connect import sqlite_connect


def _claude_mem_source() -> dict | None:
    """The claude-mem SQLite database, with its observation count."""
    claude_mem_db = Path.home() / ".claude-mem" / "claude-mem.db"
    if not claude_mem_db.exists():
        return None
    try:
        conn = sqlite_connect(str(claude_mem_db))  # source: ADR-1110
        count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.close()
    except Exception:  # noqa: BLE001 — external-source probe — failure is reported as a count-0 source entry in the banner
        return {"name": "claude-mem", "count": 0, "path": str(claude_mem_db)}
    if count > 0:
        return {"name": "claude-mem", "count": count, "path": str(claude_mem_db)}
    return None


def _cursor_source() -> dict | None:
    """Cursor conversations under ~/.cursor."""
    cursor_dir = Path.home() / ".cursor"
    if not cursor_dir.exists():
        return None
    cursor_files = list(cursor_dir.glob("**/*.jsonl"))
    if not cursor_files:
        return None
    return {"name": "Cursor", "count": len(cursor_files), "path": str(cursor_dir)}


def _chatgpt_source() -> dict | None:
    """ChatGPT exports in ~/Downloads."""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        return None
    chatgpt_files = list(downloads.glob("**/conversations.json"))
    if not chatgpt_files:
        return None
    return {
        "name": "ChatGPT",
        "count": len(chatgpt_files),
        "path": str(chatgpt_files[0]),
    }


def _detect_external_sources() -> list[dict]:
    """Detect other AI memory systems that can be imported into Cortex."""
    probes = (_claude_mem_source(), _cursor_source(), _chatgpt_source())
    return [source for source in probes if source is not None]


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
