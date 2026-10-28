"""Test double for ``log_relay.spawn_logged`` (ADR-1110).

Hooks no longer hand a child an open log file; they call ``spawn_logged``,
which starts the redaction relay and the child. Tests that pinned the spawn
command, the log path and the detach options record them here instead of
intercepting ``subprocess.Popen`` (the relay contract itself is pinned in
``tests_py/infrastructure/test_log_relay.py``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from mcp_server.infrastructure.log_relay import LoggedSpawn


def fake_spawn(
    monkeypatch: Any,
    module: Any,
    *,
    popen: Callable[..., Any] | None = None,
    pid: int = 4242,
) -> list[dict[str, Any]]:
    """Patch ``module.spawn_logged``; return the list of recorded spawns.

    ``popen``, when given, plays the child's ``Popen``: it receives the
    command and ``log_path=`` plus the spawn options, and what it returns (or
    raises) is the child."""
    calls: list[dict[str, Any]] = []

    def _spawn(cmd: list[str], log_path: Path, **kwargs: Any) -> LoggedSpawn:
        calls.append({"cmd": cmd, "log_path": Path(log_path), "kwargs": kwargs})
        child = (
            popen(cmd, log_path=Path(log_path), **kwargs)
            if popen is not None
            else MagicMock(pid=pid)
        )
        return LoggedSpawn(child=child, relay=MagicMock(pid=pid + 1))

    monkeypatch.setattr(module, "spawn_logged", _spawn)
    return calls
