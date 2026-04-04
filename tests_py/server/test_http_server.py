"""Tests for mcp_server.server.http_server — UI visualization server with idle timeout."""

import json
from io import BytesIO
from unittest.mock import patch, MagicMock

import mcp_server.server.http_server as http_mod
from mcp_server.server.http_server import (
    start_ui_server,
    shutdown_server,
    _reset_idle_timer,
)


def _reset_module_state():
    """Reset module-level globals between tests."""
    http_mod._active_server = None
    if http_mod._idle_timer:
        http_mod._idle_timer.cancel()
    http_mod._idle_timer = None


class TestResetIdleTimer:
    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def test_creates_daemon_timer(self):
        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance
            _reset_idle_timer()
            assert http_mod._idle_timer is mock_instance
            assert mock_instance.daemon is True

    def test_cancels_previous_timer(self):
        old_timer = MagicMock()
        http_mod._idle_timer = old_timer
        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            MockTimer.return_value = MagicMock()
            _reset_idle_timer()
        old_timer.cancel.assert_called_once()
        # new timer should be set
        assert http_mod._idle_timer is not old_timer

    def test_timer_duration_is_600(self):
        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance
            _reset_idle_timer()
            MockTimer.assert_called_once()
            assert MockTimer.call_args[0][0] == 600.0

    def test_shutdown_callback_clears_active_server(self):
        """When the timer fires, _active_server should be cleared."""
        mock_server = MagicMock()
        http_mod._active_server = {"server": mock_server}

        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance
            _reset_idle_timer()
            # Extract the shutdown callback
            shutdown_fn = MockTimer.call_args[0][1]

        # Call the shutdown callback directly
        with patch("builtins.print"):
            shutdown_fn()

        assert http_mod._active_server is None
        mock_server.shutdown.assert_called_once()

    def test_shutdown_callback_noop_if_no_server(self):
        """Shutdown callback should be safe when no active server."""
        http_mod._active_server = None

        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance
            _reset_idle_timer()
            shutdown_fn = MockTimer.call_args[0][1]

        # Should not raise
        with patch("builtins.print"):
            shutdown_fn()

        assert http_mod._active_server is None

    def test_shutdown_callback_prints_message(self):
        mock_server = MagicMock()
        http_mod._active_server = {"server": mock_server}

        with patch("mcp_server.server.http_server.threading.Timer") as MockTimer:
            mock_instance = MagicMock()
            MockTimer.return_value = mock_instance
            _reset_idle_timer()
            shutdown_fn = MockTimer.call_args[0][1]

        with patch("builtins.print") as mock_print:
            shutdown_fn()
            mock_print.assert_called_once()
            assert "idle timeout" in str(mock_print.call_args)


class TestStartUiServer:
    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def test_reuses_existing_server(self):
        """If a server already exists, just update graph_data and return URL."""
        existing = {
            "server": MagicMock(),
            "url": "http://127.0.0.1:9999",
            "graph_data": {},
            "graph_json": "{}",
        }
        http_mod._active_server = existing

        with patch("mcp_server.server.http_server._reset_idle_timer"):
            url = start_ui_server({"nodes": [1]})

        assert url == "http://127.0.0.1:9999"
        assert http_mod._active_server["graph_data"] == {"nodes": [1]}
        assert http_mod._active_server["graph_json"] == json.dumps({"nodes": [1]})

    def test_reads_html_from_custom_path(self):
        """Should read the html_file kwarg path."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html>test</html>")
            tmp_path = f.name

        try:
            mock_server = MagicMock()
            mock_server.server_address = ("127.0.0.1", 4444)

            with (
                patch(
                    "mcp_server.server.http_server.HTTPServer", return_value=mock_server
                ),
                patch("mcp_server.server.http_server.threading.Thread") as MockThread,
                patch("mcp_server.server.http_server._reset_idle_timer"),
                patch("builtins.print"),
            ):
                mock_thread = MagicMock()
                MockThread.return_value = mock_thread

                url = start_ui_server({"nodes": []}, html_file=tmp_path)

            assert url == "http://127.0.0.1:4444"
            mock_thread.start.assert_called_once()
        finally:
            os.unlink(tmp_path)

    def test_raises_on_missing_html_file(self):
        """Should raise RuntimeError if html file doesn't exist."""
        import pytest

        with pytest.raises(RuntimeError, match="Could not read UI file"):
            start_ui_server({"nodes": []}, html_file="/nonexistent/path.html")

    def test_starts_server_on_port_3456_first(self):
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 3456)

        with (
            patch(
                "mcp_server.server.http_server.HTTPServer", return_value=mock_server
            ) as MockHTTP,
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print"),
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            MockThread.return_value = MagicMock()
            url = start_ui_server({"nodes": []})

        assert url == "http://127.0.0.1:3456"
        # First call should be with port 3456
        first_call = MockHTTP.call_args_list[0]
        assert first_call[0][0] == ("127.0.0.1", 3456)

    def test_falls_back_to_port_0_on_oserror(self):
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 5678)

        def side_effect(addr, handler):
            if addr[1] == 3456:
                raise OSError("port in use")
            return mock_server

        with (
            patch("mcp_server.server.http_server.HTTPServer", side_effect=side_effect),
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print"),
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            MockThread.return_value = MagicMock()
            url = start_ui_server({"nodes": []})

        assert url == "http://127.0.0.1:5678"

    def test_raises_if_both_ports_fail(self):
        import pytest

        def side_effect(addr, handler):
            raise OSError("port in use")

        with (
            patch("mcp_server.server.http_server.HTTPServer", side_effect=side_effect),
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            with pytest.raises(OSError):
                start_ui_server({"nodes": []})

    def test_server_thread_is_daemon(self):
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 3456)

        with (
            patch("mcp_server.server.http_server.HTTPServer", return_value=mock_server),
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print"),
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            mock_thread = MagicMock()
            MockThread.return_value = mock_thread
            start_ui_server({"nodes": []})

        MockThread.assert_called_once()
        assert (
            MockThread.call_args[1].get("daemon") is True
            or MockThread.call_args.kwargs.get("daemon") is True
        )

    def test_sets_active_server_state(self):
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 3456)

        with (
            patch("mcp_server.server.http_server.HTTPServer", return_value=mock_server),
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print"),
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            MockThread.return_value = MagicMock()
            start_ui_server({"key": "val"})

        assert http_mod._active_server is not None
        assert http_mod._active_server["url"] == "http://127.0.0.1:3456"
        assert http_mod._active_server["port"] == 3456
        assert http_mod._active_server["graph_data"] == {"key": "val"}
        assert http_mod._active_server["graph_json"] == json.dumps({"key": "val"})

    def test_prints_startup_message(self):
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 3456)

        with (
            patch("mcp_server.server.http_server.HTTPServer", return_value=mock_server),
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print") as mock_print,
            patch("pathlib.Path.read_text", return_value="<html></html>"),
        ):
            MockThread.return_value = MagicMock()
            start_ui_server({"nodes": []})

        mock_print.assert_called_once()
        assert "UI server started" in str(mock_print.call_args)


class TestShutdownServer:
    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def test_shutdown_active_server(self):
        mock_server = MagicMock()
        http_mod._active_server = {"server": mock_server}
        shutdown_server()
        mock_server.shutdown.assert_called_once()
        assert http_mod._active_server is None

    def test_shutdown_cancels_timer(self):
        mock_timer = MagicMock()
        http_mod._idle_timer = mock_timer
        http_mod._active_server = {"server": MagicMock()}
        shutdown_server()
        mock_timer.cancel.assert_called_once()
        assert http_mod._idle_timer is None

    def test_shutdown_noop_when_no_server(self):
        """Should not raise when there's nothing to shut down."""
        http_mod._active_server = None
        http_mod._idle_timer = None
        shutdown_server()  # should not raise
        assert http_mod._active_server is None

    def test_shutdown_cancels_timer_even_without_server(self):
        mock_timer = MagicMock()
        http_mod._idle_timer = mock_timer
        http_mod._active_server = None
        shutdown_server()
        mock_timer.cancel.assert_called_once()
        assert http_mod._idle_timer is None


class TestHandlerBehavior:
    """Test the inner Handler class by invoking start_ui_server and making requests."""

    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def _create_handler_class(self, graph_data=None):
        """Start a server and capture the Handler class passed to HTTPServer."""
        if graph_data is None:
            graph_data = {"nodes": [], "edges": []}

        captured = {}

        def capture_handler(addr, handler_cls):
            captured["handler_cls"] = handler_cls
            mock = MagicMock()
            mock.server_address = ("127.0.0.1", 3456)
            return mock

        with (
            patch(
                "mcp_server.server.http_server.HTTPServer", side_effect=capture_handler
            ),
            patch("mcp_server.server.http_server.threading.Thread") as MockThread,
            patch("mcp_server.server.http_server._reset_idle_timer"),
            patch("builtins.print"),
            patch("pathlib.Path.read_text", return_value="<html>test</html>"),
        ):
            MockThread.return_value = MagicMock()
            start_ui_server(graph_data)

        return captured["handler_cls"]

    def _make_handler(self, handler_cls, path="/"):
        """Instantiate a handler with mocked request/client."""
        handler = handler_cls.__new__(handler_cls)
        handler.path = path
        handler.wfile = BytesIO()
        handler.requestline = f"GET {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.command = "GET"
        handler.headers = {}
        handler._headers_buffer = []
        # Mock the methods that write headers
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_get_root_returns_html(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")

        with patch("mcp_server.server.http_server._reset_idle_timer"):
            handler.do_GET()

        handler.send_response.assert_called_with(200)
        # Check Content-Type header
        header_calls = [c[0] for c in handler.send_header.call_args_list]
        assert ("Content-Type", "text/html; charset=utf-8") in header_calls
        # Check body written
        written = handler.wfile.getvalue()
        assert b"<html>test</html>" in written

    def test_get_graph_returns_json(self):
        graph = {"nodes": [{"id": "a"}], "edges": []}
        handler_cls = self._create_handler_class(graph)
        handler = self._make_handler(handler_cls, "/graph")

        with patch("mcp_server.server.http_server._reset_idle_timer"):
            handler.do_GET()

        handler.send_response.assert_called_with(200)
        header_calls = [c[0] for c in handler.send_header.call_args_list]
        assert ("Content-Type", "application/json") in header_calls
        written = handler.wfile.getvalue()
        assert json.loads(written) == graph

    def test_get_sets_no_cache(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")

        with patch("mcp_server.server.http_server._reset_idle_timer"):
            handler.do_GET()

        header_calls = [c[0] for c in handler.send_header.call_args_list]
        assert ("Cache-Control", "no-cache") in header_calls

    def test_do_options_returns_204(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")

        handler.do_OPTIONS()

        handler.send_response.assert_called_with(204)
        header_calls = [c[0] for c in handler.send_header.call_args_list]
        assert ("Access-Control-Allow-Origin", "http://127.0.0.1") in header_calls
        assert ("Access-Control-Allow-Methods", "GET, OPTIONS") in header_calls

    def test_log_message_suppressed(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")
        # log_message should be a no-op, not raise
        handler.log_message("test %s", "msg")

    def test_send_header_cors_is_noop(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")
        # Should not raise
        handler.send_header_cors()

    def test_get_resets_idle_timer(self):
        handler_cls = self._create_handler_class()
        handler = self._make_handler(handler_cls, "/")

        with patch("mcp_server.server.http_server._reset_idle_timer") as mock_reset:
            handler.do_GET()
            mock_reset.assert_called()
