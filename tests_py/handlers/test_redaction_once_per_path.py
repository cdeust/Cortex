"""Captured text is redacted once per process (review of PR #775, N2).

PostToolUse redacted the tool output, then the memory content built from
it; the artifact writer redacted the output again, and the worker's store
redacted the content it had just redacted. The hook and the worker are
separate processes and the worker does not trust its socket payload, so
each redacts once: the hook its content, the worker what it receives. Text
the gate already returned in a process is not redacted again there; a value
derived from it (a normalised signature, an FTS augmentation) is a new text
and is redacted on its own.

The counter wraps the step every redaction ends in, so it counts
redactions, not the detector's internal reads.
"""

from __future__ import annotations

import asyncio
import collections
from unittest.mock import patch

import pytest

from mcp_server.shared import redaction_gate

# source: review of PR #775 — one redaction per output byte; the margin is
# the short header the hook puts around the output
_ONE_PASS = 1.15

# Short field values (a timestamp, an enum name) are separate parameters,
# each redacted where it is bound; the property is about captured text.
# source: review of PR #775 — bulk text, here 1 KB and up
_BULK = 1_000

_BODY = "".join(f"line {i} build step ok module_{i}\n" for i in range(2000))


@pytest.fixture()
def redacted(monkeypatch):
    texts: list[str] = []
    real = redaction_gate.redact_spans

    def counting(text, spans):
        texts.append(str(text))
        return real(text, spans)

    monkeypatch.setattr(redaction_gate, "redact_spans", counting)
    return texts


@pytest.mark.parametrize("size", [2_000, 60_000], ids=["inline", "gisted"])
def test_capture_hook_redacts_each_output_byte_once(redacted, size, tmp_path):
    from mcp_server.hooks import post_tool_capture
    from mcp_server.infrastructure import artifact_store

    output = _BODY[:size]
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": output,
        "cwd": "/w",
    }
    with (
        patch.object(post_tool_capture, "_should_capture", return_value=(True, "")),
        patch.object(post_tool_capture, "_maybe_run_cascade"),
        patch.object(post_tool_capture, "_store_memory", lambda *a: None),
        patch.object(artifact_store, "ARTIFACTS_DIR", tmp_path),
    ):
        post_tool_capture.process_event(event)
    ratio = sum(map(len, redacted)) / len(output)
    assert ratio <= _ONE_PASS, [len(t) for t in redacted]


def test_worker_redacts_no_text_twice(redacted):
    from mcp_server.handlers.remember import handler

    content = _BODY[:20_000]
    result = asyncio.run(handler({"content": content, "force": True}))
    assert result.get("stored") is True
    counts = collections.Counter(t for t in redacted if len(t) >= _BULK)
    assert counts[content] == 1, counts[content]
    twice = {t[:40]: n for t, n in counts.items() if n > 1}
    assert not twice, twice
