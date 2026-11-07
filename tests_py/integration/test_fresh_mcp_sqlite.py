"""Issue #703: an unconfigured wheel server can remember through real stdio MCP."""

import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_fresh_server_remember_persists_in_sqlite(tmp_path):
    root = tmp_path / "claude"
    repo = Path(__file__).resolve().parents[2]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CORTEX_", "CLAUDE_", "PG", "PYTHON"))
        and key != "DATABASE_URL"
    }
    env.update(
        HOME=str(tmp_path / "home"),
        CORTEX_CLAUDE_DIR=str(root),
        PYTHONPATH=str(repo),
        CORTEX_EMBEDDING_ZERO_DOWNLOAD="1",
        CORTEX_RERANKER_OFFLINE="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server"], cwd=tmp_path, env=env
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool(
                "remember",
                {
                    "content": "The unconfigured Cortex wheel stores in SQLite.",
                },
            )
            assert not result.is_error, result
    marker = root / "methodology" / "backend.json"
    assert json.loads(marker.read_text())["backend"] == "sqlite"
    with sqlite3.connect(root / "methodology" / "memory.db") as db:
        contents = db.execute("SELECT content FROM memories").fetchall()
    assert any("unconfigured Cortex wheel" in content for (content,) in contents)
