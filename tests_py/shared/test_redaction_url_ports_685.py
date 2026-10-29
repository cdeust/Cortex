"""Issue #685: malformed diagnostic URL ports cannot break secret masking."""

from __future__ import annotations

import pytest

from mcp_server.shared.redaction import redact_url
from mcp_server.shared.redaction_gate import redact_text


@pytest.mark.parametrize(
    "host_port", ["db:5432", "db:5432;", "db:invalid", "db:99999", "[::1]:5432;"]
)
def test_url_masking_preserves_authority_without_validating_port(host_port):
    url = f"postgresql://u:fixture-secret@{host_port}/memory?sslmode=require"

    assert redact_url(url) == f"postgresql://u:***@{host_port}/memory?sslmode=require"


def test_redaction_gate_handles_url_followed_by_diagnostic_separator():
    text = "connect postgresql://u:fixture-secret@db:5432; next component"

    assert redact_text(text) == "connect postgresql://u:***@db:5432; next component"
