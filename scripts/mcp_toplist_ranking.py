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

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable

SERVER_ID = "io.github.cdeust/hypermnesia-mcp"
LEADERBOARD_URL = "https://mcptoplist.com/data/leaderboard.json"
SERVER_PAGE_URL = "https://mcptoplist.com/server/io.github.cdeust%2Fhypermnesia-mcp"

# source: measured 2026-07-28 — /data/leaderboard.json takes 8-14s to return
# its 503, so a timeout below ~20s cannot distinguish "slow" from "broken".
TIMEOUT_S = 45

# The site renders this sentence in the server page body. Anchored on both
# numbers so a reworded page fails the match instead of yielding a rank
# paired with a stale or unrelated total.
_PROSE_ANCHOR = re.compile(
    r"ranks\s*#\s*([\d,]+)\s*of\s*([\d,]+)\s*servers\s*tracked",
    re.IGNORECASE,
)

# Not a tuned threshold: it is the resolution of the "{:.1f}" format the
# tier text itself uses. A percentile finer than this rounds to "Top 0.0%",
# which reads as a bug rather than as a top-of-field result.
_MIN_PRINTABLE_PCT = 0.1


class UpstreamError(RuntimeError):
    """Upstream data could not be fetched or trusted."""


@dataclass(frozen=True)
class Ranking:
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

    rank: int
    total: int
    source: str


def ranking_percentile(ranking: Ranking) -> float:
    """Share of the field this server sits within, to one decimal."""
    return round(ranking.rank / ranking.total * 100, 1)


def ranking_tier_text(ranking: Ranking) -> str:
    pct = ranking_percentile(ranking)
    # Ranks near the very top round to 0.0%, which reads as an error
    # rather than as an achievement. Report the bound instead.
    if pct < _MIN_PRINTABLE_PCT:
        return f"Top <{_MIN_PRINTABLE_PCT}%"
    return f"Top {pct:.1f}%"


def validate(rank: object, total: object, source: str) -> Ranking:
    """Coerce and bounds-check a candidate figure, or raise.

    Guards the arithmetic in Ranking.percentile (total of zero) and the
    semantics of the claim (a rank outside the field is not a rank).
    """
    try:
        rank_i = int(str(rank).replace(",", "").strip())
        total_i = int(str(total).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise UpstreamError(
            f"{source}: non-numeric rank/total: {rank!r}/{total!r}"
        ) from exc
    if rank_i < 1:
        raise UpstreamError(f"{source}: rank {rank_i} is not a positive position")
    if total_i < 1:
        raise UpstreamError(f"{source}: total {total_i} is not a positive field size")
    if rank_i > total_i:
        raise UpstreamError(f"{source}: rank {rank_i} exceeds field size {total_i}")
    return Ranking(rank=rank_i, total=total_i, source=source)


def _leaderboard_total(doc: object, entries: list) -> int:
    """The field size the document declares, or the entry count if silent."""
    if isinstance(doc, dict):
        for key in ("total", "totalServers", "count"):
            if isinstance(doc.get(key), int):
                return doc[key]
    return len(entries)


def _find_leaderboard_entry(entries: list, server_id: str) -> dict | None:
    """The entry naming server_id under any of the documented identity keys."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identity = next(
            (entry[k] for k in ("id", "name", "serverId", "slug") if k in entry),
            None,
        )
        if identity == server_id:
            return entry
    return None


def parse_leaderboard(payload: bytes, server_id: str = SERVER_ID) -> Ranking:
    """Extract our figure from the structured export.

    PROVISIONAL — see module docstring. Accepts only shapes explicitly
    listed here; an unrecognised document raises rather than guessing, so
    the caller falls back to a path whose format has been observed.
    """
    try:
        # "UTF-8" is equivalent to "utf-8" (codecs.lookup is
        # case-insensitive) — issue #281, same class as
        # generate_repo_badges.py's own utf-8 read.
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamError(f"leaderboard.json: not valid JSON: {exc}") from exc

    entries = doc.get("servers") if isinstance(doc, dict) else doc
    if not isinstance(entries, list) or not entries:
        raise UpstreamError("leaderboard.json: no server list in document")
    total = _leaderboard_total(doc, entries)

    entry = _find_leaderboard_entry(entries, server_id)
    if entry is None:
        raise UpstreamError(
            f"leaderboard.json: {server_id} not present in {len(entries)} entries"
        )
    rank = next(
        (entry[k] for k in ("rank", "position", "place") if k in entry),
        None,
    )
    if rank is None:
        raise UpstreamError(f"leaderboard.json: entry for {server_id} carries no rank")
    return validate(rank, total, "leaderboard.json")


def parse_server_page(html: str) -> Ranking:
    """Extract our figure from the rendered server page."""
    match = _PROSE_ANCHOR.search(html)
    if match is None:
        raise UpstreamError(
            "server page: the 'ranks #N of M servers tracked' sentence is absent "
            "— the page was reworded and this parser needs updating"
        )
    return validate(match.group(1), match.group(2), "server page")


def fetch(  # noqa: S310 — every production caller (resolve_ranking) passes one of the two hardcoded module https:// constants (LEADERBOARD_URL/SERVER_PAGE_URL); tests pass fixed https:// literals
    url: str, opener: Callable = urllib.request.urlopen
) -> bytes:
    """Retrieve a URL, or raise UpstreamError naming the failure."""
    # Header KEY casing is equivalent here: Request normalises every header
    # key via str.capitalize() before storing it, so "User-Agent"/
    # "user-agent"/"USER-AGENT" (and "Accept"'s equivalent) are
    # indistinguishable at the wire — issue #281.
    request = urllib.request.Request(  # noqa: S310 — see fetch()'s own noqa above: url is always one of the two hardcoded https:// module constants in production, a fixed https:// literal in tests
        url,
        headers={
            "User-Agent": "cortex-badge-refresh (+https://github.com/cdeust/Cortex)",
            "Accept": "application/json, text/html;q=0.9",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpstreamError(f"{url}: unreachable: {exc}") from exc


def resolve_ranking(
    fetch_fn: Callable[[str], bytes] = fetch,
) -> tuple[Ranking, list[str]]:
    """Try each extraction path in order; return the first trusted figure.

    Returns the figure and the notices raised along the way, so a silent
    fallback is impossible: the caller reports every path that failed even
    when a later one succeeded.
    """
    notices: list[str] = []
    # "UTF-8" below is equivalent to "utf-8" (codecs.lookup is
    # case-insensitive) — same class as parse_leaderboard's decode, #281.
    attempts: Iterable[tuple[str, Callable[[bytes], Ranking]]] = (
        (LEADERBOARD_URL, parse_leaderboard),
        (
            SERVER_PAGE_URL,
            lambda raw: parse_server_page(raw.decode("utf-8", "replace")),
        ),
    )
    for url, parser in attempts:
        try:
            return parser(fetch_fn(url)), notices
        except UpstreamError as exc:
            notices.append(str(exc))
    raise UpstreamError(
        "no trusted figure from any source; badge left untouched:\n  - "
        + "\n  - ".join(notices)
    )
