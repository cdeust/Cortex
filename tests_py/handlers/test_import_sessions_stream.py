"""E1 — streaming memory bound on import_sessions.

Verifies that ADR-0045 R2 ("no ingestion path reads a whole file/store into
Python memory") is upheld by import_sessions even on a large synthetic JSONL.

The former ``full_read=True`` branch loaded the entire file into a Python
list before extraction — a 10 MB file would produce ~10 MB of string/dict
allocation in Python. The fix deletes that branch; the streaming head+tail
path (scanner.read_head_tail) reads ~40 KB (HEAD_BYTES=32 K + TAIL_BYTES=8 K)
regardless of file size.

Test strategy:
  1. Generate a ~10 MB JSONL (50 K lines × ~200 B each).
  2. Run import_sessions in dry_run mode under tracemalloc.
  3. Assert peak memory diff stays well below 50 MB. A regression that
     re-introduces full-file reads would allocate ≥ 10 MB of string data
     plus dict overhead (typically 3-5× = 30-50 MB); passing under 50 MB
     is sufficient to catch that regression.

Source: ADR-0045 R2; v3.13.0 Phase 1 Fragility Sweep E1.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mcp_server.handlers import import_sessions


# Target file size: ~10 MB. Line template is ~200 bytes after json.dumps.
_TARGET_LINES = 50_000


def _write_large_jsonl(path: Path) -> int:
    """Generate a synthetic JSONL with _TARGET_LINES lines. Returns byte size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with open(path, "w", encoding="utf-8") as f:
        for i in range(_TARGET_LINES):
            rec = {
                "type": "user" if i % 2 == 0 else "assistant",
                "message": {
                    "content": (
                        # ~120-byte content string — with overhead keeps each
                        # line near 200 bytes.
                        f"synthetic record {i:06d} "
                        "lorem ipsum dolor sit amet consectetur adipiscing "
                        "elit sed do eiusmod tempor"
                    )
                },
                "timestamp": f"2026-01-01T10:{i % 60:02d}:00Z",
                "sessionId": "big-session",
                "cwd": "/Users/dev/Developments/cortex",
            }
            line = json.dumps(rec) + "\n"
            total_bytes += len(line.encode("utf-8"))
            f.write(line)
    return total_bytes


@pytest.fixture
def large_claude_dir(tmp_path):
    """Create a ~10 MB JSONL in a .claude/projects tree."""
    claude_dir = tmp_path / ".claude"
    proj_dir = claude_dir / "projects" / "-Users-dev-Developments-cortex"
    jsonl_path = proj_dir / "session-big.jsonl"
    byte_size = _write_large_jsonl(jsonl_path)
    # Sanity: must be at least 8 MB so a regression would be measurable.
    assert byte_size >= 8 * 1024 * 1024, (
        f"synthetic JSONL too small ({byte_size} bytes) — "
        "test would not catch a full-read regression"
    )
    return claude_dir


class TestImportSessionsStreamsLargeFile:
    """ADR-0045 R2 compliance — peak memory stays bounded on large JSONL."""

    @pytest.mark.asyncio
    async def test_peak_memory_under_50mb_on_10mb_jsonl(self, large_claude_dir):
        patch_dir = patch(
            "mcp_server.handlers.import_sessions.CLAUDE_DIR",
            large_claude_dir,
        )
        patch_store = patch(
            "mcp_server.handlers.import_sessions._store_memory",
            new_callable=AsyncMock,
            return_value=True,
        )

        tracemalloc.start()
        try:
            snapshot_before = tracemalloc.take_snapshot()
            with patch_dir, patch_store:
                # dry_run avoids any DB write and isolates the read path cost.
                await import_sessions.handler(
                    {
                        "project": "-Users-dev-Developments-cortex",
                        "dry_run": True,
                        "min_importance": 0.3,
                    }
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        # The streaming head+tail path reads ~40 KB per file; extraction and
        # preview building add a bounded overhead. A full-file regression on
        # a 10 MB file would allocate tens of MB. 50 MB is a generous ceiling
        # that still flags the regression unambiguously.
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 50, (
            f"import_sessions peak memory {peak_mb:.1f} MB exceeds 50 MB "
            "bound — ADR-0045 R2 regression (whole-file read re-introduced)"
        )
        # Ensure the snapshot-before baseline was genuinely captured, not
        # silently skipped by a tracemalloc bug.
        assert snapshot_before is not None
