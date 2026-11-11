"""A prospective trigger carries no text into another project (GHSA-7848-qh48-mx2w).

Review 1 of pull request 981: `remember` turns a phrase such as `TODO:` into a
`keyword_match` trigger, and a trigger used to fire in every project whose first
message or query shared a keyword. The write passed every domain and directory
check, so the advisory's primitive stayed open through this channel. Reproduced
on the real handlers and store with two git repositories, `alpha` and `beta`.
"""

from __future__ import annotations

import pytest

from mcp_server.core.prospective import trigger_in_scope
from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope, query_methodology
from mcp_server.handlers.create_trigger import handler as create_trigger
from mcp_server.handlers.recall_helpers import inject_triggered_memories
from mcp_server.handlers.remember import handler as remember_handler
from tests_py.handlers import test_ghsa_7848_cross_project_write as _base

projects = _base.projects  # alpha and beta under `dev`; the session runs in beta

MARKER = "rotate the GHSA7848 deploy credentials"
MESSAGE = "please rotate the deploy credentials"


def _fired(directory) -> list[str]:
    fired = query_methodology._get_fired_triggers(str(directory), MESSAGE)
    return [t["content"] for t in fired]


async def _write_todo(projects) -> None:
    await remember_handler(
        {
            "content": f"TODO: {MARKER}",
            "directory": str(projects / "beta"),
            "force": True,
        }
    )


@pytest.mark.asyncio
async def test_a_todo_written_in_beta_does_not_fire_in_alpha(projects):
    await _write_todo(projects)
    assert _fired(projects / "alpha") == []


@pytest.mark.asyncio
async def test_an_alpha_trigger_stored_first_does_not_stop_the_beta_one(projects):
    store = query_methodology._try_get_memory_store()
    store.insert_prospective_memory(
        {
            "content": "an alpha reminder",
            "trigger_condition": "deploy",
            "trigger_type": "keyword_match",
            "target_directory": str(projects / "alpha"),
            "is_active": True,
            "triggered_count": 0,
            "created_by": "test",
        }
    )
    await _write_todo(projects)
    assert _fired(projects / "beta") == [MARKER]


@pytest.mark.asyncio
async def test_a_todo_written_in_beta_still_fires_in_beta(projects):
    await _write_todo(projects)
    assert _fired(projects / "beta") == [MARKER]


@pytest.mark.asyncio
async def test_recall_in_alpha_does_not_inject_a_trigger_of_beta(projects, monkeypatch):
    await _write_todo(projects)
    store = query_methodology._try_get_memory_store()
    in_beta = inject_triggered_memories([], MESSAGE, store)
    monkeypatch.setenv(_write_scope.SESSION_ENV, str(projects / "alpha"))
    in_alpha = inject_triggered_memories([], MESSAGE, store)
    assert [r["content"] for r in in_beta] == [f"TODO: {MARKER}"]
    assert in_alpha == []


@pytest.mark.asyncio
async def test_create_trigger_refuses_another_projects_directory(projects):
    with pytest.raises(ValidationError, match=r"^create_trigger: .*WRITES=alpha"):
        await create_trigger(
            {
                "content": MARKER,
                "trigger_condition": "deploy",
                "target_directory": str(projects / "alpha"),
            }
        )


@pytest.mark.asyncio
async def test_create_trigger_without_a_directory_stays_in_the_session(projects):
    made = await create_trigger({"content": MARKER, "trigger_condition": "deploy"})
    assert made["target_directory"] == str(projects / "beta")


@pytest.mark.parametrize(
    ("target", "root", "expected"),
    [
        ("/dev/beta", "/dev/beta", True),
        ("/dev/beta", "/dev/beta/src", True),
        ("/dev/beta", "/dev/alpha", False),
        ("", "/dev/beta", False),
        (None, "/dev/beta", False),
        ("/dev/beta", None, False),
    ],
)
def test_a_trigger_fires_only_where_its_directory_is_served(target, root, expected):
    trigger = {"trigger_type": "keyword_match", "target_directory": target}
    assert trigger_in_scope(trigger, root) is expected


def test_a_directory_trigger_is_decided_by_its_own_condition():
    trigger = {"trigger_type": "directory_match", "target_directory": "/dev/beta"}
    assert trigger_in_scope(trigger, "/dev/alpha") is True
