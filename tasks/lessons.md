# Lessons Learned

## 2026-03-22 — Audit & Deprecation Fix

**Issue**: `asyncio.get_event_loop()` is deprecated in Python 3.10+. All 68 test failures under `-W error` were caused by this single pattern across 14 files.

**Fix**:
- Tests: `asyncio.get_event_loop().run_until_complete(x)` → `asyncio.run(x)`
- Production (async context): `asyncio.get_event_loop()` → `asyncio.get_running_loop()`

**Rule**: Never use `asyncio.get_event_loop()` in new code. Always use `asyncio.run()` for top-level or `asyncio.get_running_loop()` inside async functions.

## 2026-03-22 — MCP Server Connection

**Observation**: MCP server starts fine, handshake works, all 9 tools register correctly. Previous session's "not connected" error was transient — likely a timing issue during Claude Code's MCP startup sequence.

**Rule**: When MCP connection fails, verify the server independently first (`echo initialize | python3 -m mcp_server`) before assuming code bugs.
