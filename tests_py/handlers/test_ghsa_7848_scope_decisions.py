"""Each GHSA-7848 refusal reports its exact fields, and each scope decision is pinned.

The mutation gate of #940 (`unit`, run 42377328684) left survivors in four places:
the `details` of the global refusals, the environment each check reads, the scope
`remember` matches an exact duplicate on, the refusal of a superseding global write,
and the curation loop that skips a candidate this session may not change. Each test
below fails on one of those mutations; the session runs in `beta`.
"""

from __future__ import annotations

import subprocess

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope, anchor, remember
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.handlers.remember_helpers import try_curation
from mcp_server.shared import domain_mapping
from tests_py.handlers import test_ghsa_7848_cross_project_write as _base

projects = _base.projects
ALLOW = _write_scope.ALLOW_ENV
SESSION = _write_scope.SESSION_ENV
GLOBAL_REFUSAL = (
    "{tool}: is_global=true writes into every project's memory; "
    f"set {ALLOW}=* in the environment to allow it"
)
# Detected as global by its content alone, and by its tags alone.
BY_CONTENT = ("Always use tabs in every project.", [])
BY_TAGS = ("beta keeps its build notes here", ["global", "shared", "universal"])


def _refused(call):
    with pytest.raises(ValidationError) as caught:
        call()
    return caught.value


def _beta(projects):
    return {SESSION: str(projects / "beta")}


# ── The refusals and the environment they read ──────────────────────────────


def test_the_global_refusal_names_its_tool_and_field(projects):
    env = _beta(projects)
    for call in (
        lambda: _write_scope.require_global_allowed("t", env),
        lambda: _write_scope.global_scope((True, "explicit"), True, "t", env),
    ):
        error = _refused(call)
        assert str(error) == GLOBAL_REFUSAL.format(tool="t")
        assert error.details == {"tool": "t", "field": "is_global"}


def test_global_scope_reads_the_environment_it_is_given(projects, monkeypatch):
    monkeypatch.setenv(ALLOW, "*")  # the process allows it; the argument does not
    env = _beta(projects)
    _refused(lambda: _write_scope.global_scope((True, "r"), True, "t", env))
    detected = _write_scope.global_scope((True, "r"), False, "t", env)
    assert detected == (False, _write_scope.KEPT_LOCAL)
    star = {**env, ALLOW: "*"}
    assert _write_scope.global_scope((True, "r"), True, "t", star) == (True, "r")
    assert _write_scope.global_scope((False, "r"), True, "t", env) == (False, "r")


def test_a_global_memory_refusal_names_the_memory(projects):
    row = {"id": 42, "domain": "beta", "is_global": True}
    error = _refused(
        lambda: _write_scope.require_writable_memory(row, "t", _beta(projects))
    )
    assert str(error) == (
        "t: memory 42 is global, so changing it reaches every project; "
        f"set {ALLOW}=* in the environment to allow it"
    )
    assert error.details == {"tool": "t", "field": "memory_id", "memory_id": 42}


@pytest.mark.parametrize(
    "row",
    [
        {"id": 7, "domain": "alpha", "is_global": False},
        {"id": 7, "domain": "beta", "is_global": True},
    ],
    ids=["other-project", "global"],
)
def test_a_memory_check_reads_the_environment_it_is_given(projects, monkeypatch, row):
    monkeypatch.setenv(ALLOW, "*")  # the process allows it; the argument does not
    env = _beta(projects)
    _refused(lambda: _write_scope.require_writable_memory(row, "t", env))
    assert _write_scope.memory_writable(row, env) is False


def test_a_memory_with_no_domain_stays_writable_next_to_a_placeholder_project(
    projects,
):
    subprocess.run(["git", "init", "-q", str(projects / "xxxx")], check=True)
    domain_mapping._build_registry.cache_clear()
    env = _beta(projects)
    for row in ({"id": 1, "domain": None}, {"id": 2, "domain": "beta"}):
        _write_scope.require_writable_memory(row, "t", env)
        assert _write_scope.memory_writable(row, env) is True


# ── anchor ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anchor_refuses_a_global_scope_with_the_exact_refusal(projects):
    own = await remember_handler({"content": "beta anchor note", "force": True})
    with pytest.raises(ValidationError) as caught:
        await anchor.handler({"memory_id": own["memory_id"], "is_global": True})
    assert str(caught.value) == GLOBAL_REFUSAL.format(tool="anchor")
    assert caught.value.details == {"tool": "anchor", "field": "is_global"}


# ── remember: the exact-duplicate scope and the superseding write ───────────


@pytest.mark.asyncio
async def test_an_explicit_global_replay_is_refused_not_matched_as_a_duplicate(
    projects,
):
    note = "beta release checklist lives in the wiki"
    await remember_handler({"content": note, "force": True})
    with pytest.raises(ValidationError) as caught:
        await remember_handler({"content": note, "is_global": True, "force": True})
    assert str(caught.value) == GLOBAL_REFUSAL.format(tool="remember")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "tags"), [BY_CONTENT, BY_TAGS], ids=["content", "tags"]
)
async def test_a_detected_global_memory_is_its_own_exact_duplicate(
    projects, monkeypatch, content, tags
):
    monkeypatch.setenv(ALLOW, "*")
    first = await remember_handler({"content": content, "tags": tags, "force": True})
    assert first["stored"] is True
    assert first["is_global"] is True
    replay = await remember_handler({"content": content, "tags": tags, "force": True})
    assert replay["reason"] == "exact_duplicate"
    assert replay["memory_id"] == first["memory_id"]


@pytest.mark.asyncio
async def test_an_explicit_global_memory_is_its_own_exact_duplicate(
    projects, monkeypatch
):
    monkeypatch.setenv(ALLOW, "*")
    args = {"content": "beta shares this one", "is_global": True, "force": True}
    first = await remember_handler(dict(args))
    replay = await remember_handler(dict(args))
    assert replay["reason"] == "exact_duplicate"
    assert replay["memory_id"] == first["memory_id"]


@pytest.mark.asyncio
async def test_a_superseding_global_write_is_refused(projects):
    own = await remember_handler({"content": "beta uses port 8080", "force": True})
    with pytest.raises(ValidationError) as caught:
        await remember_handler(
            {
                "content": "beta uses port 9090",
                "supersedes_id": own["memory_id"],
                "is_global": True,
                "force": True,
            }
        )
    assert str(caught.value) == GLOBAL_REFUSAL.format(tool="remember")
    assert caught.value.details == {"tool": "remember", "field": "is_global"}


@pytest.mark.asyncio
async def test_a_write_that_is_not_stored_reports_no_scope(projects, monkeypatch):
    refused = {"stored": False, "action": "superseded_conflict"}
    monkeypatch.setattr(
        remember, "insert_and_post_process", lambda *a, **k: dict(refused)
    )
    content, tags = BY_CONTENT  # kept local: a scope would be reported if stored
    result = await remember_handler({"content": content, "tags": tags, "force": True})
    assert result == refused


# ── curation skips, and does not stop at, a memory it may not change ────────


class _Engine:
    def similarity(self, a, b) -> float:  # noqa: ARG002 — stub contract
        return 0.99  # high enough for the merge branch

    def encode(self, text: str):  # noqa: ARG002 — only hit on merge
        return b"\x00" * 4


class _Store:
    """Two near-identical candidates: alpha's ranked first, then beta's."""

    def __init__(self) -> None:
        self.merged_into: list[int] = []
        row = {"content": "deploy target is server one", "embedding": b"\x01"}
        self._rows = {
            1: {**row, "id": 1, "domain": "alpha", "superseded_by_id": None},
            2: {**row, "id": 2, "domain": "beta", "superseded_by_id": None},
        }
        for r in self._rows.values():
            r.update(compression_level=0, heat=0.5, is_global=False)

    def search_vectors(self, embedding, top_k=3, min_heat=0.0):  # noqa: ARG002
        return [(1, 0.01), (2, 0.02)]

    def get_memories_by_ids(self, ids):
        return {mid: self._rows[mid] for mid in ids if mid in self._rows}

    def update_memory_compression(self, mid, *args, **kwargs):  # noqa: ARG002
        self.merged_into.append(mid)

    def update_memory_heat(self, mid, heat):  # noqa: ARG002
        pass


def test_curation_skips_another_projects_candidate_and_merges_the_next(projects):
    store = _Store()
    action, target = try_curation(
        "deploy target is server one", b"\x01", False, store, _Engine(), [], 0.5
    )
    assert (action, target) == ("merge", 2)
    assert store.merged_into == [2]
