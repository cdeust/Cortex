"""Tests for delete_memories_by_tag — domain scoping (issue #16).

Background: PSGSupport reported `seed_project` purging memories globally
across repos. Root cause: `delete_memories_by_tag("seeded")` was unscoped
and authority leaked past the project boundary. Fix: optional `domain`
parameter scopes the delete; default (None) preserves legacy behavior
for callers that intentionally want a global purge.
"""

from __future__ import annotations

from mcp_server.infrastructure.memory_store import get_shared_store


def _insert(store, *, content: str, tag: str, domain: str) -> int:
    return store.insert_memory(
        {
            "content": content,
            "tags": [tag],
            "domain": domain,
            "source": "test",
            "is_protected": False,
        }
    )


def test_delete_by_tag_with_domain_scopes_to_that_domain() -> None:
    """domain=X removes only memories with tag AND domain=X."""
    store = get_shared_store()

    a1 = _insert(store, content="repo-a memory 1", tag="seeded", domain="repo-a")
    a2 = _insert(store, content="repo-a memory 2", tag="seeded", domain="repo-a")
    b1 = _insert(store, content="repo-b memory 1", tag="seeded", domain="repo-b")

    deleted = store.delete_memories_by_tag("seeded", domain="repo-a")

    assert deleted == 2, "must remove exactly the two repo-a rows"
    # repo-b survives
    surviving = [
        m for m in store.get_memories_for_domain("repo-b", min_heat=0.0, limit=100)
    ]
    surviving_ids = {m["id"] for m in surviving}
    assert b1 in surviving_ids, "repo-b memory must survive a repo-a-scoped purge"
    # repo-a is gone
    surviving_a = [
        m for m in store.get_memories_for_domain("repo-a", min_heat=0.0, limit=100)
    ]
    surviving_a_ids = {m["id"] for m in surviving_a}
    assert a1 not in surviving_a_ids
    assert a2 not in surviving_a_ids


def test_delete_by_tag_without_domain_purges_globally() -> None:
    """domain=None preserves legacy global-purge behavior."""
    store = get_shared_store()

    _insert(store, content="repo-a memory", tag="seeded", domain="repo-a")
    _insert(store, content="repo-b memory", tag="seeded", domain="repo-b")
    _insert(store, content="other tag memory", tag="kept", domain="repo-a")

    deleted = store.delete_memories_by_tag("seeded")

    assert deleted == 2, "must remove both seeded rows globally"
    # The differently-tagged memory survives
    a_remaining = store.get_memories_for_domain("repo-a", min_heat=0.0, limit=100)
    assert any("other tag" in m["content"] for m in a_remaining)


def test_delete_by_tag_with_domain_does_not_touch_other_tags() -> None:
    """Scoped delete must not remove rows that lack the tag, even in-domain."""
    store = get_shared_store()

    _insert(store, content="seeded one", tag="seeded", domain="repo-a")
    _insert(store, content="manual one", tag="manual", domain="repo-a")

    deleted = store.delete_memories_by_tag("seeded", domain="repo-a")

    assert deleted == 1
    remaining = store.get_memories_for_domain("repo-a", min_heat=0.0, limit=100)
    contents = [m["content"] for m in remaining]
    assert "manual one" in contents
    assert "seeded one" not in contents


def test_delete_by_tag_with_unknown_domain_is_noop() -> None:
    """Domain that has no rows returns 0 and removes nothing."""
    store = get_shared_store()

    _insert(store, content="real memory", tag="seeded", domain="repo-a")

    deleted = store.delete_memories_by_tag("seeded", domain="nonexistent")

    assert deleted == 0
    remaining = store.get_memories_for_domain("repo-a", min_heat=0.0, limit=100)
    assert len(remaining) == 1
