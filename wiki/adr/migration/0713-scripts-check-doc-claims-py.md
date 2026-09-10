# ADR-0713: scripts/check_doc_claims.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/check_doc_claims.py`; original SHA-256 `c7d45ee822f05ab49b2810d0cf5fb6cf69123ea0da4eceecf99c5028c1aa093b`.

## Original docstring, lines 1–67

````text
"""Doc-claim gate: the numbers the docs advertise must match the repository.

Cortex advertises counts in prose — tools, references, mechanisms,
tests. Each one is a claim a reader can check, and each one drifts silently:
between 2026-07-12 and 2026-07-27 the tool count moved from 49 to 52 while
README, CONTRIBUTING and the MCPB manifest still said 50, 43 and 49, and
CONTRIBUTING advertised a ``mypy --strict`` gate the project has never run.
Nothing failed, because nothing checked.

This gate closes that at the point where the drift is introduced (every push
and pull request), not at release time. It compares every advertised count
against the one place that owns it:

===================  =====================================================
Claim                Owner
===================  =====================================================
tool counts          ``docs/mcp-tools.md`` header, itself pinned to the live
                     registry by ``tests_py/test_main.py::
                     test_standalone_baseline_is_52_tools``
reference count      entries counted in ``docs/papers/bibliography.md``
mechanism count      the count declared in that bibliography's header
test count           ``assets/badge-tests.svg`` alone (issue #293) — the
                     one artifact that still states an absolute figure. No
                     prose file (nor ``.bestpractices.json``) states this
                     count any more: a PR that adds tests would otherwise
                     have to hand-edit six files to the same new number,
                     and any two such PRs conflict on every one of them BY
                     CONSTRUCTION. The badge is also not an exact fact —
                     it is checked as a monotone FLOOR (``committed <=
                     live``), because the true count is a property of the
                     post-merge tree that no single branch can compute in
                     advance; only an OVER-claim is reported. See
                     ``doc_claim_structural.check_badge_floor``.
===================  =====================================================

Version-site coherence (``[project].version`` in ``pyproject.toml`` against
every manifest, plugin, and badge occurrence that restates it) is NOT this
gate's job any more — it moved to ``scripts/check_version_surfaces.py``,
which is a strict superset of what this gate's own ``check_versions`` used
to compare (issue #392).

Release history is exempt: a line describing v4.13.0 may legitimately say
"49 memory tools". Lines carrying a ``**vX.Y.Z`` marker, and files that are
history by nature (CHANGELOG, docs/release-notes/), are skipped.

A line may also state a number that counts something *other* than the
advertised total, in a wording the claim patterns cannot tell apart ("12
tests skipped locally"). Such a line declares
``[not-a-count-claim: <label>]`` and is skipped for that one family only —
see ``NOT_A_CLAIM``. The declared set is a registry: it is printed on every
successful run and pinned by a test naming each member, so an exemption is
added deliberately or not at all.

Usage::

    python scripts/check_doc_claims.py                 # static claims
    python scripts/check_doc_claims.py --test-count 5571

Split across scripts/doc_claim_sources.py (canonical readers),
scripts/doc_claim_scan.py (claim scanning/comparison) and
scripts/doc_claim_structural.py (badge + structural-integrity checks) —
issue #293, Extract Function/Move Function — to stay under the repo's
300-line file cap (docs/agent-guidance.md, Code Style); this module is the thin
orchestrator each of those forwards through, and the only place ``read``/
``SCANNED_FILES`` are defined (tests patch them here; see each sibling
module's docstring for why they take these as parameters instead).
"""
````

## Original comment, lines 78–80

````text
# Sibling modules, path-imported for the same reason generate_repo_badges.py
# does it: resolves identically whether this runs as a script or is loaded
# via importlib.util.spec_from_file_location from a test.
````

## Original comment, lines 89–90

````text
# Files whose numbers describe the present. Release history lives elsewhere
# (CHANGELOG.md, docs/release-notes/) and is deliberately not scanned.
````

## Original comment, lines 96–97

````text
# The former CLAUDE.md body (moved 2026-09-08 so it is read on demand);
    # its tool and module counts describe the present exactly as before.
````

## Original comment, lines 107–110

````text
# The OpenSSF Best Practices answers are claims about the present too: they
    # are transcribed into the questionnaire, so a stale number here is
    # published to the badge. Three of its test counts had drifted two
    # corrections behind the repository before it was scanned (2026-07-27).
````

## Original comment, lines 112–116

````text
# The MCP registry serves server.json's description verbatim, so a stale
    # number here is published to every registry client. Only its `version`
    # was asserted (check_versions) until its description was found still
    # advertising "72 references" — two corrections behind the 97-reference
    # bibliography — and shipped that way to the registry (2026-08-02).
````

## Original comment, lines 123–128

````text
# `cited` is optional because the claim is written both ways ("36
# neuroscience-grounded mechanisms" in CONTRIBUTING, "36 cited brain
# mechanisms" in the README lede and "36 cited neuroscience mechanisms" in
# server.json). Without it the qualified phrasings parsed as no claim at
# all, so the README lede and the registry description were never asserted
# against the canonical count (found 2026-08-02).
````

## Original comment, lines 133–140

````text
# Both the "N tests" and the "N-test suite" phrasings state the count. No
# scanned file states this claim in prose any more (issue #293 — see the
# module docstring's "test count" row); the pattern stays defined because
# it is still the generic worked example scan_claims/check_counts's own
# tests exercise, and tests_py/scripts/test_check_doc_claims.py asserts its
# absence from the real tree as a standing regression guard (a re-added
# hardcoded prose count would fail
# RepositoryTests.test_no_prose_file_states_the_suite_size).
````

## Original comment, lines 146–152

````text
# every scanned Markdown file uses non-ASCII prose (em dashes, arrows),
    # and a locale-dependent default can mis-decode them on a non-UTF-8-
    # default platform (Windows is in this project's own CI matrix) — see
    # test_read_pins_utf8. "UTF-8" (verbatim uppercase) is a documented-
    # equivalent spelling: codecs.lookup is case-insensitive (CPython
    # Lib/encodings/aliases.py normalizes via .lower()), so it is the SAME
    # codec, not a different one a wrong-encoding bug could reach.
````

## Original comment, lines 212–214

````text
# The tests badge is the ONLY test-count claim left (issue #293);
        # see check_badge_floor's docstring for why it is a floor, not an
        # exact match.
````

## Original comment, lines 230–234

````text
# Explicit, not load-bearing: argparse already defaults an unset
        # optional argument with no `default` kwarg at all to None, so a
        # mutant dropping this line is a documented equivalent (issue #235;
        # rationale + verification in MainTests.test_the_parser_declares_
        # the_modules_docstring_and_flag_help's docstring).
````

