"""Direct unit coverage of tests_py/_pg_safety_guards.py:looks_like_test_db.

Split out of test_conftest_guard.py (issue #276/#287 boy-scout follow-up):
that file, itself already over coding-standards.md §4.1's 300-line cap
before this session's edits (496 lines on origin/main), grew further with
the new tests this session added and needed decomposing along its natural
per-function boundaries — this file covers `looks_like_test_db` on its
own; `test_guard_against_populated_db.py` and its structural-integrity
sibling cover `guard_against_populated_db`.
"""

from __future__ import annotations

from tests_py import _pg_safety_guards as guards


class TestLooksLikeTestDb:
    """Direct unit coverage of the URL -> database-name parser.

    The trailing `_test`/`_bench`/`_test_` checks are suffix/substring
    checks, so what matters is which slice of the URL `looks_like_test_db`
    feeds them — a wrong slice can produce a false positive (a stray
    "_test_" elsewhere in the URL wrongly trusted) or a false negative (the
    real name missed because the query string wasn't stripped).
    """

    def test_simple_test_named_db(self) -> None:
        assert guards.looks_like_test_db("postgresql://localhost/cortex_test")

    def test_plain_db_name_is_not_test_named(self) -> None:
        assert not guards.looks_like_test_db("postgresql://localhost/cortex")

    def test_query_string_is_stripped_before_the_suffix_check(self) -> None:
        """Without stripping "?sslmode=require", the name would end in the
        query string, not "_test", and wrongly report False."""
        assert guards.looks_like_test_db(
            "postgresql://localhost/cortex_test?sslmode=require"
        )

    def test_a_test_looking_host_with_a_real_db_name_is_not_trusted(self) -> None:
        """The database NAME must be checked, never the host: a host that
        happens to contain "_test_" (e.g. a shared test-labeled server used
        for a real database) must not make an unrelated real DB look safe.
        This is exactly what an rsplit-vs-split parsing bug would get wrong
        — split() on the first "/" would fold the host into the checked
        text; rsplit() on the LAST "/" correctly isolates only the name."""
        assert not guards.looks_like_test_db(
            "postgresql://cortex_test_host:5432/production"
        )

    def test_query_string_split_takes_the_first_question_mark_not_the_last(
        self,
    ) -> None:
        """A (malformed but possible) URL with two "?" characters must be
        split at the FIRST one — `split`, not `rsplit` — or "cortex_test"
        gets a stray "?a=1" appended and no longer ends in "_test"."""
        assert guards.looks_like_test_db("postgresql://localhost/cortex_test?a=1?b=2")

    def test_a_url_with_no_slash_at_all_does_not_raise(self) -> None:
        """A bare name with no "postgresql://" prefix is a degenerate but
        valid input for this pure string function; it must resolve `name`
        to the input itself rather than raising (rsplit finds nothing to
        split on and returns a single-element result — indexing that
        result at a position other than 0/-1 would raise `IndexError`)."""
        assert guards.looks_like_test_db("cortex_test")
