"""Tests for the log line ``apply_backend_resolution`` writes per dropped setting.

Source: issue #704, note 4 of review 1 of #1052 (a blank or unexpanded store
setting was removed without a trace) and the notes of the reviews of #1057.
Split from test_backend_marker.py, which is at the 300-line cap.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.backend_marker import apply_backend_resolution


@pytest.mark.parametrize(
    "name",
    ["DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL", "CORTEX_MEMORY_STORE_BACKEND"],
)
@pytest.mark.parametrize(
    ("value", "reason"),
    [(" ", "blank"), ("${user_config.database_url}", "an unexpanded ${...}")],
)
def test_a_dropped_value_is_logged_by_name_only(caplog, tmp_path, name, value, reason):
    # Note 4 of review 1 of #1052: a dropped value left no log line.
    logger = "mcp_server.infrastructure.backend_marker"
    with caplog.at_level("INFO", logger=logger):
        apply_backend_resolution({name: value}, marker_path=tmp_path / "absent.json")
    assert caplog.record_tuples == [
        (logger, 20, f"{name} is {reason}: treated as not set")
    ]


def test_every_dropped_variable_is_removed_and_logged(caplog, tmp_path):
    # Review 2 of #1057, note 2: with one variable per call, a loop that
    # stopped after its first removal would pass.
    logger = "mcp_server.infrastructure.backend_marker"
    env = {
        "DATABASE_URL": " ",
        "CORTEX_MEMORY_DATABASE_URL": "${user_config.database_url}",
        "CORTEX_MEMORY_STORE_BACKEND": "",
    }
    with caplog.at_level("INFO", logger=logger):
        apply_backend_resolution(env, marker_path=tmp_path / "absent.json")
    assert env == {}
    assert caplog.record_tuples == [
        (logger, 20, "DATABASE_URL is blank: treated as not set"),
        (
            logger,
            20,
            "CORTEX_MEMORY_DATABASE_URL is an unexpanded ${...}: treated as not set",
        ),
        (logger, 20, "CORTEX_MEMORY_STORE_BACKEND is blank: treated as not set"),
    ]
