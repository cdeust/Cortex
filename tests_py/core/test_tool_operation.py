"""Equivalent explicit edits give equal style inputs from either host (#727).

The replay of issue #727: one-tool sessions with ``duration=None``. Before
this change ``Edit`` gave ``activeReflective=0.3`` and ``apply_patch`` an
empty observation; ``exec`` must stay empty, since its effect is opaque.
"""

import pytest

from mcp_server.core.profile_builder import _build_style_observation
from mcp_server.core.tool_operation import EDIT, READ, count_operation, operation_of


def test_claude_and_codex_explicit_edits_share_one_operation():
    assert operation_of("Edit") == EDIT
    assert operation_of("Write") == EDIT
    assert operation_of("apply_patch") == EDIT
    assert operation_of("Read") == READ
    assert operation_of("Grep") == READ


def test_opaque_exec_is_not_classified():
    assert operation_of("exec") is None
    assert operation_of("Bash") is None


def test_count_operation_reads_native_names():
    tools = ["apply_patch", "Edit", "exec", "Read"]
    assert count_operation(tools, EDIT) == 2
    assert count_operation(tools, READ) == 1


def test_apply_patch_session_observation_equals_edit_session():
    claude = _build_style_observation(None, ["Edit"])
    codex = _build_style_observation(None, ["apply_patch"])
    assert claude == {"activeReflective": 0.3}
    assert codex == claude


def test_exec_session_observation_stays_empty():
    assert _build_style_observation(None, ["exec"]) == {}


def test_read_session_observation_unchanged():
    assert _build_style_observation(None, ["Read"]) == {"activeReflective": -0.3}


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (100_000, 0.5),
        (600_000, 0.0),
        (1_000_000, 0.0),
        (1_800_000, 0.0),
        (2_000_000, -0.5),
    ],
)
def test_duration_alone_sets_active_reflective(duration, expected):
    assert _build_style_observation(duration, []) == {"activeReflective": expected}


def test_tool_mix_below_or_at_dominance_adds_nothing():
    assert (
        _build_style_observation(None, ["Edit", "Bash", "Bash", "Bash", "Bash"]) == {}
    )
    assert (
        _build_style_observation(None, ["apply_patch", "Edit", "exec", "exec", "exec"])
        == {}
    )
    assert (
        _build_style_observation(None, ["Read", "Grep", "exec", "exec", "exec"]) == {}
    )


def test_tool_mix_adds_to_the_duration_signal():
    edits = _build_style_observation(100_000, ["apply_patch", "apply_patch", "exec"])
    reads = _build_style_observation(100_000, ["Read", "Grep", "exec"])
    assert edits == {"activeReflective": pytest.approx(0.8)}
    assert reads == {"activeReflective": pytest.approx(0.2)}
