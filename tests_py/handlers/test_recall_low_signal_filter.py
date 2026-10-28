"""Issue #706: capture provenance, rather than arbitrary tags, controls hiding."""

from __future__ import annotations

import pytest

from mcp_server.handlers.recall_helpers import filter_low_signal, _injectable


@pytest.mark.parametrize("tags", [
    ["audit"], ["automated"], ["stage-3"], ["tool:edit"],
    ["auto-captured", "_backfill"], '["audit", "stage-11"]', [],
])
@pytest.mark.parametrize("origin", ["deliberate", "legacy", "unknown", None])
def test_user_tags_never_hide_memory(tags, origin):
    memory = {"memory_id": 1, "tags": tags}
    if origin is not None:
        memory["capture_origin"] = origin
    assert filter_low_signal([memory]) == ([memory], 0)
    assert _injectable(memory)


@pytest.mark.parametrize("origin", ["local_action", "network"])
def test_capture_marker_hides_even_without_tags(origin):
    captured = {"memory_id": 1, "capture_origin": origin}
    deliberate = {"memory_id": 2, "capture_origin": "deliberate", "tags": ["audit"]}
    assert filter_low_signal([captured, deliberate]) == ([deliberate], 1)
    assert not _injectable(captured)


@pytest.mark.parametrize("tag", ["audit", "automated", "stage-3"])
def test_default_tool_recall_preserves_deliberate_tagged_memory(tag):
    import asyncio
    from mcp_server.handlers.remember import handler as remember
    from mcp_server.handlers.recall import handler as recall

    written = asyncio.run(remember({
        "content": "paraphrase706 deliberate turbine maintenance decision",
        "tags": [tag], "force": True,
    }))
    result = asyncio.run(recall({"query": "paraphrase706 turbine", "min_heat": 0}))
    assert written["memory_id"] in [m["memory_id"] for m in result["memories"]]


def test_default_tool_reports_hidden_captures_and_opt_in_labels_them():
    import asyncio
    from mcp_server.handlers.remember import handler as remember
    from mcp_server.handlers.recall import handler as recall

    written = asyncio.run(remember({
        "content": "capture706 Bash failed because the database socket was absent",
        "origin_tool": "Bash", "force": True,
    }))
    default = asyncio.run(recall({
        "query": "capture706 database socket", "min_heat": 0,
    }))
    assert written["memory_id"] not in [m["memory_id"] for m in default["memories"]]
    assert default["low_signal_dropped"] >= 1
    included = asyncio.run(recall({
        "query": "capture706 database socket", "min_heat": 0,
        "include_low_signal": True,
    }))
    match = next(
        m for m in included["memories"] if m["memory_id"] == written["memory_id"]
    )
    assert match["capture_origin"] == "local_action"
    assert included["low_signal_dropped"] == 0


def test_legacy_system_source_marker_and_deliberate_override():
    legacy = {"source": "post_tool_capture"}
    deliberate = {"source": "post_tool_capture", "capture_origin": "deliberate"}
    assert filter_low_signal([legacy, deliberate]) == ([deliberate], 1)
