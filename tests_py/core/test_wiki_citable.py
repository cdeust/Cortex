"""A wiki pointer memory is never a source a page may cite.

source: issue #715 (slice 1, acceptance criterion 4)
"""

from __future__ import annotations

from mcp_server.core.wiki_citable import WIKI_POINTER, split_citable


def test_pointers_are_refused_once_and_the_rest_keeps_its_order():
    memories = {
        1: {"source": "session"},
        2: {"source": "wiki://notes/a.md"},
        3: {"source": None},
        4: {"source": "  wiki://notes/b.md "},
    }
    citable, refused = split_citable([3, 2, 1, 2, 4, 99], memories)
    assert citable == [3, 1, 99]
    assert refused == [
        {"memory_id": 2, "reason": WIKI_POINTER},
        {"memory_id": 4, "reason": WIKI_POINTER},
    ]


def test_a_bare_scheme_names_no_page_and_stays_citable():
    citable, refused = split_citable([5], {5: {"source": "wiki://"}})
    assert (citable, refused) == ([5], [])


def test_no_ids_gives_two_empty_lists():
    assert split_citable([], {}) == ([], [])
