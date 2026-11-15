"""Tests for the log line ``apply_backend_resolution`` writes per dropped setting.

Source: issue #704, note 4 of review 1 of #1052 (a blank or unexpanded store
setting was removed without a trace) and the notes of the reviews of #1057 to #1059.
Split from test_backend_marker.py: the tests below would take that file past
the 300-line cap (review of #1058, note 1).
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
    # stopped after its first removal would pass. Reviews of #1058 (note 3)
    # and #1059 (note 2): env is built in an order whose forward, reversed and
    # sorted iterations all differ from the expected one, so a loop over the
    # environment instead of over the variable names fails the order check.
    logger = "mcp_server.infrastructure.backend_marker"
    env = {
        "CORTEX_MEMORY_DATABASE_URL": "${user_config.database_url}",
        "DATABASE_URL": " ",
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


def test_a_valid_setting_is_kept_and_not_logged(caplog, tmp_path):
    # Review of #1059, note 3: with no valid setting in any test, a
    # _drop_unset that logged every present store variable would pass.
    logger = "mcp_server.infrastructure.backend_marker"
    url = "postgresql://user@db.example/cortex"
    env = {"DATABASE_URL": url, "CORTEX_MEMORY_STORE_BACKEND": ""}
    with caplog.at_level("INFO", logger=logger):
        apply_backend_resolution(env, marker_path=tmp_path / "absent.json")
    assert env["DATABASE_URL"] == url
    assert "CORTEX_MEMORY_STORE_BACKEND" not in env
    assert [r for r in caplog.record_tuples if r[0] == logger] == [
        (logger, 20, "CORTEX_MEMORY_STORE_BACKEND is blank: treated as not set")
    ]
