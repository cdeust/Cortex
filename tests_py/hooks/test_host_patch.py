"""Tests for the Codex ``apply_patch`` to Edit/Write translator.

Ported fixtures from zetetic-team-subagents ``tests/test_host_events.py``
(commit 4c2bc9b, PR #139), adapted to call ``host_patch.patch_events``
directly rather than the full ``normalize_event`` dispatcher this repo
splits it from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.hooks.host_event_errors import HostEventError
from mcp_server.hooks.host_patch import patch_events


def _patch_event(cwd: Path, body: str) -> dict:
    return {
        "cwd": str(cwd),
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n" + body + "\n*** End Patch"},
    }


def test_add_file_produces_write_with_full_content(tmp_path: Path) -> None:
    events = patch_events(_patch_event(tmp_path, "*** Add File: new.py\n+one\n+two"))
    assert len(events) == 1
    assert events[0]["tool_name"] == "Write"
    assert events[0]["tool_input"]["file_path"] == str(tmp_path / "new.py")
    assert events[0]["tool_input"]["content"] == "one\ntwo\n"
    assert not (tmp_path / "new.py").exists()


def test_update_file_produces_edit_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "source.py"
    target.write_text("before\n")
    events = patch_events(
        _patch_event(tmp_path, "*** Update File: source.py\n@@\n-before\n+after")
    )
    assert events == [
        {
            "cwd": str(tmp_path),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": "before\n",
                "new_string": "after\n",
            },
        }
    ]
    assert target.read_text() == "before\n"


def test_update_with_move_to_emits_edit_then_write(tmp_path: Path) -> None:
    target = tmp_path / "old.py"
    target.write_text("one\ntwo\n")
    body = "*** Update File: old.py\n*** Move to: moved.py\n@@\n-two\n+second"
    events = patch_events(_patch_event(tmp_path, body))
    assert [e["tool_name"] for e in events] == ["Edit", "Write"]
    assert events[0]["tool_input"]["file_path"] == str(target)
    assert events[1]["tool_input"]["file_path"] == str(tmp_path / "moved.py")
    assert events[1]["tool_input"]["content"] == "one\nsecond\n"
    assert target.read_text() == "one\ntwo\n"
    assert not (tmp_path / "moved.py").exists()


def test_delete_file_produces_edit_with_empty_new_string(tmp_path: Path) -> None:
    target = tmp_path / "gone.py"
    target.write_text("gone\n")
    events = patch_events(_patch_event(tmp_path, "*** Delete File: gone.py"))
    assert events == [
        {
            "cwd": str(tmp_path),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": "gone\n",
                "new_string": "",
            },
        }
    ]
    assert target.exists()


def test_end_of_file_anchor_matches_final_lines(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("head\ntail\n")
    body = "*** Update File: a\n head\n-tail\n+end\n*** End of File"
    events = patch_events(_patch_event(tmp_path, body))
    assert events[0]["tool_input"]["new_string"] == "head\nend\n"


def test_end_of_file_refuses_nonterminal_context(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("head\ntail\n")
    body = "*** Update File: a\n@@\n-head\n+end\n*** End of File"
    with pytest.raises(HostEventError):
        patch_events(_patch_event(tmp_path, body))


def test_nonexact_preimage_refuses_without_mutation(tmp_path: Path) -> None:
    target = tmp_path / "source.py"
    target.write_text("before\n")
    with pytest.raises(HostEventError):
        patch_events(
            _patch_event(tmp_path, "*** Update File: source.py\n@@\n-wrong\n+after")
        )
    assert target.read_text() == "before\n"


def test_ambiguous_preimage_refuses(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("same\nsame\n")
    with pytest.raises(HostEventError, match="ambiguous"):
        patch_events(_patch_event(tmp_path, "*** Update File: a\n@@\n-same\n+changed"))


@pytest.mark.parametrize(
    "body",
    [
        "*** Update File: missing.py\n@@\n-x\n+y",
        "*** Add File: source.py\n+overwrite",
        "*** Delete File: missing.py",
        "*** Update File: source.py\n@@ missing anchor\n-before\n+after",
        "*** Update File: source.py\n@@\n?bad",
        "*** Update File: source.py",
    ],
)
def test_invalid_operations_refuse_without_mutation(tmp_path: Path, body: str) -> None:
    target = tmp_path / "source.py"
    target.write_text("before\n")
    with pytest.raises(HostEventError):
        patch_events(_patch_event(tmp_path, body))
    assert target.read_text() == "before\n"


@pytest.mark.parametrize("command", ["", "*** Begin Patch\n*** End Patch", "garbage"])
def test_malformed_envelope_refuses(tmp_path: Path, command: str) -> None:
    event = {
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"command": command},
    }
    with pytest.raises(HostEventError):
        patch_events(event)


def test_sequential_operations_use_prospective_state(tmp_path: Path) -> None:
    body = "*** Add File: a\n+first\n*** Update File: a\n@@\n-first\n+second"
    events = patch_events(_patch_event(tmp_path, body))
    assert events[1]["tool_input"]["old_string"] == "first\n"
    assert events[1]["tool_input"]["new_string"] == "second\n"
    assert not (tmp_path / "a").exists()
