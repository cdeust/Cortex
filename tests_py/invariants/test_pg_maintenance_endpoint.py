"""Maintenance connections must retain the test server's URI endpoint."""

from urllib.parse import parse_qs, urlsplit

import pytest

from tests_py._pg_throwaway_db import maintenance_url


@pytest.mark.parametrize(
    "query",
    [
        "host=/private/tmp/isolated-test-socket",
        "host=127.0.0.1&port=15432&sslmode=require",
        "service=isolated_test&application_name=test_probe",
    ],
)
def test_maintenance_connection_retains_endpoint_parameters(query):
    original = f"postgresql:///cortex_example_test?{query}"
    parsed = urlsplit(maintenance_url(original))
    assert parsed.path == "/postgres"
    assert parse_qs(parsed.query) == parse_qs(query)


def test_query_database_cannot_override_maintenance_database():
    query = "host=/private/tmp/isolated-test-socket&dbname=cortex_example_test"
    parsed = urlsplit(maintenance_url(f"postgresql:///cortex_example_test?{query}"))
    assert parsed.path == "/postgres"
    assert parse_qs(parsed.query) == {"host": ["/private/tmp/isolated-test-socket"]}


@pytest.mark.parametrize(
    "encoded_host,expected_host",
    [
        ("/private/tmp/socket", "/private/tmp/socket"),
        ("/private/tmp/socket%20with%20space", "/private/tmp/socket with space"),
        ("/private/tmp/socket+literal", "/private/tmp/socket+literal"),
    ],
)
def test_driver_receives_original_host_and_maintenance_database(
    encoded_host, expected_host
):
    psycopg = pytest.importorskip("psycopg")
    original = f"postgresql:///cortex_example_test?host={encoded_host}&dbname=other"
    effective = psycopg.conninfo.conninfo_to_dict(maintenance_url(original))
    assert effective["host"] == expected_host
    assert effective["dbname"] == "postgres"
