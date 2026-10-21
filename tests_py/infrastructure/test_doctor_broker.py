"""Doctor reports the store broker without starting one (ADR-1112 increment 5).

source: ADR-1112
"""

from __future__ import annotations

import os
import sys

import pytest

from mcp_server import doctor_broker
from mcp_server.infrastructure import broker_endpoint, config
from tests_py.conftest import _USE_PG

pytestmark = [
    pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL"),
    pytest.mark.skipif(sys.platform == "win32", reason="Unix transport"),
]


def test_doctor_reports_not_running_then_the_running_broker(broker_env, monkeypatch):
    root, children = broker_env
    monkeypatch.setattr(config, "CLAUDE_DIR", root)
    before = doctor_broker.store_broker_check()
    assert before["ok"] and before["detail"].startswith("not running"), before
    assert children == []  # doctor never starts a broker
    store = broker_endpoint.broker_store(os.environ["DATABASE_URL"], root, "test")
    try:
        after = doctor_broker.store_broker_check()
        assert after["ok"] and f"pid {children[0].pid}" in after["detail"], after
    finally:
        store.close()


@pytest.mark.parametrize(
    ("migration", "expected"),
    [
        (None, "no separation"),
        ("postgresql://cortex_migrate@127.0.0.1/cortex", "migration cortex_migrate"),
    ],
)
def test_doctor_reports_whether_the_roles_are_separate(
    migration, expected, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://cortex_runtime@127.0.0.1/cortex")
    if migration is None:
        monkeypatch.delenv("CORTEX_MIGRATION_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("CORTEX_MIGRATION_DATABASE_URL", migration)
    check = doctor_broker.database_roles_check()
    assert check["ok"] and expected in check["detail"], check
