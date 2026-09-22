"""Mixed project aliases must not suppress distinct scopes (PR #631 review)."""

import pytest

from mcp_server.hooks import preemptive_context as hook
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py.infrastructure.test_file_memory_priming import _insert, _rows


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("first_matches", [False, True])
def test_alias_cooldowns_follow_queried_scope(
    tmp_path, monkeypatch, reverse, first_matches
):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    (real / "cue.py").write_text("cue\n")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    first, second = (real, alias) if reverse else (alias, real)
    store = get_shared_store()
    target = _insert(store, "cue.py", directory=str(second))
    initial = _insert(store, "cue.py", directory=str(first)) if first_matches else None
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "cue.py"},
    }
    hook.process_event({**event, "cwd": str(first)})
    assert _rows(store)[target]["heat_base"] == 0.5
    hook.process_event({**event, "cwd": str(second)})
    assert _rows(store)[target]["heat_base"] == pytest.approx(0.6)
    if initial is not None:
        assert _rows(store)[initial]["heat_base"] == pytest.approx(0.6)
    hook.process_event({**event, "cwd": str(second)})
    assert _rows(store)[target]["heat_base"] == pytest.approx(0.6)
