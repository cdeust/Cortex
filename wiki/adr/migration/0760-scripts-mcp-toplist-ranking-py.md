# ADR-0760: scripts/mcp_toplist_ranking.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/mcp_toplist_ranking.py`; original SHA-256 `46a7ad2e2ff5131cb70bb053db242e864cc5c5359f22c51f2fdbdbdae8ee2877`.

## Original docstring, lines 1–27

````text
"""Acquire and validate our MCP Toplist rank: fetch, parse, and bounds-check.

Split out of refresh_mcp_toplist_badge.py (issue #281): that file was 404
lines, over this repo's 300-line file cap, once its mutation-survivor gap
was closed with the tests the gap needed — mirroring issue #228's split of
condensers.py for the identical reason. This module is the acquisition
side (network fetch, two parser strategies, shared bounds validation);
refresh_mcp_toplist_badge.py keeps the rendering and CLI orchestration and
re-exports every name here, so no import path changes.

Two extraction paths, tried in order by `resolve_ranking`:

  1. /data/leaderboard.json — the structured export the site links from its
     homepage. PROVISIONAL: as of 2026-07-28 this endpoint returns HTTP 503
     (measured: 3/3 attempts, 8-14s each, browser UA). Its schema has
     therefore never been observed; `parse_leaderboard` accepts only a
     narrow set of documented candidate shapes and refuses anything else
     rather than guessing, so path 2 takes over.

  2. The server page's prose sentence "It ranks #N of M servers tracked",
     verified present 2026-07-28 — the only construct on that page
     carrying both numbers together.

Both paths feed `validate`. A figure that fails validation is never
trusted: the caller (main, in the sibling module) leaves the badge
untouched rather than publish a wrong claim.
"""
````

## Original comment, lines 42–43

````text
# source: measured 2026-07-28 — /data/leaderboard.json takes 8-14s to return
# its 503, so a timeout below ~20s cannot distinguish "slow" from "broken".
````

## Original comment, lines 46–48

````text
# The site renders this sentence in the server page body. Anchored on both
# numbers so a reworded page fails the match instead of yielding a rank
# paired with a stale or unrelated total.
````

## Original comment, lines 54–56

````text
# Not a tuned threshold: it is the resolution of the "{:.1f}" format the
# tier text itself uses. A percentile finer than this rounds to "Top 0.0%",
# which reads as a bug rather than as a top-of-field result.
````

## Original docstring, lines 66–79

````text
"""A validated rank-out-of-total, and where it came from.

    Data only — deliberately no methods. mutmut's mutation generator
    categorically excludes the body of any `@dataclass`-decorated class (it
    must, since copying a decorated class for the trampoline setup can
    re-run the decorator and its side effects), so logic placed on methods
    here would carry zero mutation coverage no matter how the test loader
    names the module — confirmed empirically: 298 mutants for this file, 0
    attributed to `percentile`/`tier_text` while they were methods (same
    defect class as `RepoBadge` in scripts/generate_repo_badges.py and
    `ConstraintSet` in scripts/pip_constraint_sets.py, issue #262).
    `ranking_percentile`/`ranking_tier_text` below carry the same logic as
    free functions instead.
    """
````

## Original comment, lines 93–94

````text
# Ranks near the very top round to 0.0%, which reads as an error
    # rather than as an achievement. Report the bound instead.
````

## Original docstring, lines 146–151

````text
"""Extract our figure from the structured export.

    PROVISIONAL — see module docstring. Accepts only shapes explicitly
    listed here; an unrecognised document raises rather than guessing, so
    the caller falls back to a path whose format has been observed.
    """
````

## Original comment, lines 153–155

````text
# "UTF-8" is equivalent to "utf-8" (codecs.lookup is
        # case-insensitive) — issue #281, same class as
        # generate_repo_badges.py's own utf-8 read.
````

## Original comment, lines 192–195

````text
# Header KEY casing is equivalent here: Request normalises every header
    # key via str.capitalize() before storing it, so "User-Agent"/
    # "user-agent"/"USER-AGENT" (and "Accept"'s equivalent) are
    # indistinguishable at the wire — issue #281.
````

