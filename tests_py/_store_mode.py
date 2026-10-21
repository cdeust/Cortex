"""Which store the test processes use (ADR-1112 increment 5).

In production every process but the store broker talks to the broker. By
default the suite runs the store in process (what the broker itself
executes), so a monkeypatch reaches the code it patches;
``CORTEX_TEST_BROKER_MODE=1`` runs the same tests through real brokers (CI
job ``test-broker-mode``). Called when ``conftest.py`` imports the session
fixtures (``_broker_mode_session``); the store reads it when a store is
made, so no import order matters.

source: ADR-1112
"""

from __future__ import annotations

import os

# source: ADR-1112 a broker-mode session's brokers exit soon after its clients
_BROKER_IDLE_SECONDS = "5"


def select_store_mode() -> bool:
    """Set the store mode in the environment; True in broker mode."""
    if os.environ.get("CORTEX_TEST_BROKER_MODE") == "1":
        os.environ.pop("CORTEX_STORE_IN_PROCESS", None)
        os.environ.setdefault("CORTEX_BROKER_IDLE_SECONDS", _BROKER_IDLE_SECONDS)
        return True
    os.environ["CORTEX_STORE_IN_PROCESS"] = "1"
    return False
