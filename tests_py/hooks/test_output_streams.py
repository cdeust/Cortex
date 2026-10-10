"""``use_utf8_output``: the one place a hook decides its stdout/stderr encoding.

The streams are real ``TextIOWrapper`` objects over byte buffers whose
initial encoding is cp1252, the Windows pipe default; the assertions read the
bytes that reach the buffer.
"""

from __future__ import annotations

import io
import sys

import pytest

from mcp_server.hooks.output_streams import HookOutputStreamError, use_utf8_output

TEXT = "décision ✓ 日本語 ⟦rcpt:1⟧"


def _cp1252_stream() -> tuple[io.TextIOWrapper, io.BytesIO]:
    raw = io.BytesIO()
    # newline="\n": no \r\n translation, so the bytes are the same on Windows.
    return io.TextIOWrapper(raw, encoding="cp1252", newline="\n"), raw


def test_stdout_receives_the_exact_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    out, raw = _cp1252_stream()
    err, _ = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    use_utf8_output()
    print(TEXT)
    out.flush()
    assert raw.getvalue() == (TEXT + "\n").encode("utf-8")


def test_stdout_is_strict_so_a_lone_surrogate_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, raw = _cp1252_stream()
    err, _ = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    use_utf8_output()
    with pytest.raises(UnicodeEncodeError):
        print("bad \udcff")
        out.flush()
    assert b"?" not in raw.getvalue()


def test_stderr_is_utf8_and_a_diagnostic_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, _ = _cp1252_stream()
    err, raw = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    use_utf8_output()
    print(TEXT, "\udcff", file=sys.stderr)
    err.flush()
    assert raw.getvalue() == (TEXT + " \\udcff\n").encode("utf-8")


def test_it_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _cp1252_stream()
    err, _ = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    use_utf8_output()
    use_utf8_output()
    assert (out.encoding, out.errors) == ("utf-8", "strict")
    assert (err.encoding, err.errors) == ("utf-8", "backslashreplace")


@pytest.mark.parametrize("name", ["stdout", "stderr"])
def test_a_stream_that_cannot_be_reconfigured_is_a_hard_failure(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, _ = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", good)
    monkeypatch.setattr(sys, "stderr", good)
    monkeypatch.setattr(sys, name, io.StringIO())
    with pytest.raises(HookOutputStreamError, match=name):
        use_utf8_output()
