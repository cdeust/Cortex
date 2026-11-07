"""Every fake postmaster a test starts dies with that test, on any exit path.

PR #748's round-5 review: tests that block or are mutated left
``fake_postgres`` orphans (ppid 1) behind. The fixture holds an exclusive
``flock`` on a lifeline file for the test's duration and exports its path;
each fake waits for a shared lock on it and exits when granted. The kernel
releases the test's lock when the test ends however it ends (teardown, a
failure, ``os._exit`` from pytest-timeout, a kill), so no fake outlives it.
Teardown then waits for the fakes' group locks: events, never a timer.

source: ADR-1114
"""

from __future__ import annotations

import fcntl
import os

import pytest


@pytest.fixture(autouse=True)
def fake_pg_lifeline(tmp_path, monkeypatch):
    path = tmp_path / "fake-pg-lifeline"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    monkeypatch.setenv("FAKE_PG_LIFELINE", str(path))
    yield path
    os.close(fd)  # every fake of this test exits on this event
    # each fake took the shared lock before it exits: the exclusive one is
    # granted once none holds it any more
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.close(fd)
