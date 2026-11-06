"""``safe_handler``'s error path: what it logs and counts when a handler fails.

The admission change of issue #728 rewrote ``safe_handler``; these cases pin
the error path it kept, so every mutant of the function is killed (ADR-1122).
"""

from __future__ import annotations

import logging

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.handlers.admission import reset_semaphores
from mcp_server.observability import metrics
from mcp_server.tool_error_handler import safe_handler

_LOGGER = "mcp_server.tool_error_handler"
# source: mcp_server/handlers/latency_class.py — interactive, budget 4.
_TOOL = "detect_gaps"


@pytest.fixture(autouse=True)
def _clean_state():
    reset_semaphores()
    metrics.reset()
    yield
    reset_semaphores()
    metrics.reset()


async def _failing(args: dict) -> dict:
    raise ValueError("bad input")


def _messages(caplog, level: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER and r.levelno == level
    ]


@pytest.mark.asyncio
async def test_named_failure_is_logged_and_counted(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    with pytest.raises(ToolError, match="^ValueError: bad input$"):
        await safe_handler(_failing, {}, _TOOL)
    assert _messages(caplog, logging.ERROR) == [
        "safe_handler caught ValueError in tool 'detect_gaps'"
    ]
    out = metrics.render()
    assert 'cortex_tool_calls_total{status="error",tool="detect_gaps"} 1' in out


@pytest.mark.asyncio
async def test_unnamed_failure_is_logged_and_not_counted(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    with pytest.raises(ToolError, match="^ValueError: bad input$"):
        await safe_handler(_failing, {})
    assert _messages(caplog, logging.ERROR) == [
        "safe_handler caught ValueError in tool '<unnamed>'"
    ]
    assert "cortex_tool_calls_total" not in metrics.render()


@pytest.mark.asyncio
async def test_error_counter_failure_is_logged_and_the_tool_error_kept(
    caplog, monkeypatch
):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def broken_counter(name, labels=None, value=1):
        raise RuntimeError("counter down")

    monkeypatch.setattr(metrics, "inc_counter", broken_counter)
    with pytest.raises(ToolError, match="^ValueError: bad input$"):
        await safe_handler(_failing, {}, _TOOL)
    assert _messages(caplog, logging.DEBUG) == [
        "error-counter increment failed: counter down"
    ]
