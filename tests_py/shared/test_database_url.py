"""One rule for which configured value names a database (issue #704)."""

import pytest

from mcp_server.shared.database_url import (
    named_database_url,
    names_a_database,
    names_a_setting,
)


@pytest.mark.parametrize(
    "value", [None, "", " ", "\t\n", "${DATABASE_URL}", "${user_config.database_url}"]
)
def test_blank_or_unexpanded_values_name_nothing(value):
    assert not names_a_database(value)
    assert named_database_url(value) == ""


def test_the_first_naming_candidate_wins_stripped():
    assert (
        named_database_url(
            None, " ", "${user_config.database_url}", " postgresql:///a "
        )
        == "postgresql:///a"
    )


def test_a_naming_value_is_returned_unchanged_but_stripped():
    assert named_database_url("postgresql://u@h/db\n") == "postgresql://u@h/db"


def test_no_candidate_names_nothing():
    assert named_database_url() == ""


@pytest.mark.parametrize(
    "dsn",
    [
        "host=localhost dbname=cortex user=cortex password='abc${xyz'",
        "postgresql://u:p${q}@h/db",
    ],
)
def test_a_dollar_brace_inside_a_dsn_still_names_a_database(dsn):
    # Only a whole ${name} token is an unexpanded interpolation; a literal
    # password is libpq's to parse (review 2 of #1051).
    assert names_a_database(dsn)
    assert named_database_url(f" {dsn} ") == dsn


@pytest.mark.parametrize("value", [None, "", "  ", "${user_config.store_backend}"])
def test_a_blank_or_unexpanded_setting_is_no_setting(value):
    # note 3 of the review of #1051: manifest.json interpolates
    # ${user_config.store_backend} as it does ${user_config.database_url}.
    assert not names_a_setting(value)


@pytest.mark.parametrize("value", ["sqlite", " postgresql ", "a${b}"])
def test_any_other_value_is_a_setting(value):
    assert names_a_setting(value)
