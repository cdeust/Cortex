"""Where the POSIX ancestor walk stops: at pid 1, never before (ADR-0597).

Pid 1 is the root process (init, launchd); the walk does not follow an edge to
it, and it follows every edge to a pid above 1.

source: ADR-0597"""

from __future__ import annotations

import os

import mcp_server.infrastructure.session_registry as sr
from mcp_server.shared import platform as host_platform


def _walk(monkeypatch, start: int, chain: dict[int, tuple[int, str]]) -> int | None:
    monkeypatch.setattr(host_platform, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "getppid", lambda: start)
    monkeypatch.setattr(sr, "_ppid_and_comm", chain.get)
    return sr.find_claude_ancestor()


def test_the_walk_does_not_follow_an_edge_to_pid_1(monkeypatch):
    # pid 1 named claude is still the root, not the window's claude
    assert _walk(monkeypatch, 200, {200: (1, "bash"), 1: (0, "claude")}) is None


def test_the_walk_follows_an_edge_to_pid_2(monkeypatch):
    assert _walk(monkeypatch, 200, {200: (2, "bash"), 2: (1, "claude")}) == 2
