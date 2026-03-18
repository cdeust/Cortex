"""Tests for mcp_server.errors — typed error hierarchy."""

from mcp_server.errors import (
    AnalysisError,
    McpConnectionError,
    MethodologyError,
    StorageError,
    ValidationError,
)


class TestMethodologyError:
    def test_has_code_message_and_details(self):
        err = MethodologyError("something broke", -32000, {"key": "val"})
        assert str(err) == "something broke"
        assert err.code == -32000
        assert err.details == {"key": "val"}

    def test_defaults_code_to_neg32000(self):
        assert MethodologyError("test").code == -32000

    def test_defaults_details_to_none(self):
        assert MethodologyError("test").details is None

    def test_is_instance_of_exception(self):
        assert isinstance(MethodologyError("test"), Exception)


class TestValidationError:
    def test_is_instance_of_methodology_error(self):
        assert isinstance(ValidationError("bad"), MethodologyError)

    def test_is_instance_of_exception(self):
        assert isinstance(ValidationError("bad"), Exception)

    def test_has_code_neg32602(self):
        assert ValidationError("bad").code == -32602

    def test_carries_details(self):
        details = {"field": "session_id", "tool": "record_session_end"}
        err = ValidationError("missing field", details)
        assert err.details == details

    def test_has_correct_message(self):
        assert str(ValidationError("field is required")) == "field is required"


class TestStorageError:
    def test_is_instance_of_methodology_error(self):
        assert isinstance(StorageError("disk full"), MethodologyError)

    def test_has_code_neg32001(self):
        assert StorageError("disk full").code == -32001

    def test_carries_details(self):
        err = StorageError("write failed", {"path": "/tmp/x"})
        assert err.details == {"path": "/tmp/x"}


class TestAnalysisError:
    def test_is_instance_of_methodology_error(self):
        assert isinstance(AnalysisError("fail"), MethodologyError)

    def test_has_code_neg32002(self):
        assert AnalysisError("fail").code == -32002

    def test_carries_details(self):
        err = AnalysisError("no data", {"domain": "web"})
        assert err.details == {"domain": "web"}

    def test_is_instance_of_exception(self):
        assert isinstance(AnalysisError("fail"), Exception)


class TestMcpConnectionError:
    def test_is_instance_of_methodology_error(self):
        assert isinstance(McpConnectionError("refused"), MethodologyError)

    def test_is_instance_of_exception(self):
        assert isinstance(McpConnectionError("refused"), Exception)

    def test_has_code_neg32003(self):
        assert McpConnectionError("refused").code == -32003

    def test_carries_details(self):
        err = McpConnectionError("timeout", {"server": "ai-architect"})
        assert err.details == {"server": "ai-architect"}
