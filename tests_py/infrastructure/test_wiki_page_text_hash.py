"""``page_text_hash`` is the one fingerprint every wiki writer records.

source: issue #715 (one fingerprint for every writer)
"""

from __future__ import annotations

import hashlib

import pytest

from mcp_server.infrastructure.pg_store_wiki_common import body_hash, page_text_hash

_PAGE = "---\ntitle: A\n---\n# A\n\nBody.\n"


def test_the_fingerprint_is_the_redacted_hash_of_the_whole_page():
    assert page_text_hash(_PAGE) == body_hash(_PAGE)
    assert page_text_hash(_PAGE) == hashlib.sha256(_PAGE.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "other",
    [
        "---\ntitle: A\nstatus: mature\n---\n# A\n\nBody.\n",  # frontmatter only
        "---\ntitle: A\n---\n# A\n\nOther.\n",  # body only
    ],
)
def test_the_fingerprint_changes_with_the_frontmatter_and_with_the_body(other):
    # a fingerprint blind to the frontmatter let upsert_page skip a rewrite
    # that changed only tags or status
    assert page_text_hash(_PAGE) != page_text_hash(other)
