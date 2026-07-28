#!/usr/bin/env python3
"""Regenerate assets/badge-mcp-toplist.svg from upstream MCP Toplist data.

The badge is a committed static file, not a hotlinked remote image, so it
cannot restate itself without a commit in our history. The cost of that
choice is that it cannot self-update: the date it carries is part of the
claim, and goes stale by INACTION. Inaction never opens a PR, so this
script exists to be run on a cron and propose the refresh.

Two extraction paths, tried in order:

  1. /data/leaderboard.json — the structured export the site links from its
     homepage. PROVISIONAL: as of 2026-07-28 this endpoint returns HTTP 503
     (measured: 3/3 attempts, 8-14s each, browser UA, so a server-side
     generation timeout rather than UA gating or rate limiting). Its schema
     has therefore never been observed. The parser below accepts a narrow
     set of documented candidate shapes under strict validation; anything
     else is refused rather than guessed at, and path 2 takes over.

  2. The server page's prose sentence "It ranks #N of M servers tracked",
     verified present 2026-07-28. This is the ONLY construct on that page
     carrying both numbers — the <title>, og/twitter meta tags and JSON-LD
     blocks all carry the rank without the total, so none of them can yield
     a percentile on their own.

Both paths feed the same validator. A figure that fails validation is never
written: the script exits non-zero and leaves the badge untouched. A wrong
badge is worse than a stale one, and far worse than a red run.

Usage:
    python3 scripts/refresh_mcp_toplist_badge.py           # rewrite if changed
    python3 scripts/refresh_mcp_toplist_badge.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timezone, datetime
from pathlib import Path
from typing import Callable, Iterable

# badge_render.py is a stdlib-only sibling module (the shields-style SVG
# geometry, shared with generate_repo_badges.py). Path-based import for the
# same reason the launcher family path-imports its siblings: resolves
# identically whether this file is run as a script (script dir already on
# sys.path) or loaded directly via importlib.util.spec_from_file_location
# from a test.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import badge_render  # noqa: E402

SERVER_ID = "io.github.cdeust/hypermnesia-mcp"
LEADERBOARD_URL = "https://mcptoplist.com/data/leaderboard.json"
SERVER_PAGE_URL = "https://mcptoplist.com/server/io.github.cdeust%2Fhypermnesia-mcp"
BADGE_PATH = Path("assets/badge-mcp-toplist.svg")

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

# The left panel carries the fixed string "MCP Toplist", so unlike the right
# panel its geometry never varies with the data. Both measured 2026-07-28 by
# rendering: 64px of text inside a 92px panel (icon + padding).
_LABEL_TEXT_W = 64
_LABEL_PANEL_W = 92

# Locale-independent: strftime("%b") follows the runner's locale, which is
# not pinned across GitHub-hosted images.
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class UpstreamError(RuntimeError):
    """Upstream data could not be fetched or trusted."""


@dataclass(frozen=True)
class Ranking:
    """A validated rank-out-of-total, and where it came from."""

    rank: int
    total: int
    source: str

    def percentile(self) -> float:
        """Share of the field this server sits within, to one decimal."""
        return round(self.rank / self.total * 100, 1)

    def tier_text(self) -> str:
        pct = self.percentile()
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


def parse_leaderboard(payload: bytes, server_id: str = SERVER_ID) -> Ranking:
    """Extract our figure from the structured export.

    PROVISIONAL — see module docstring. Accepts only shapes explicitly
    listed here; an unrecognised document raises rather than guessing, so
    the caller falls back to a path whose format has been observed.
    """
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamError(f"leaderboard.json: not valid JSON: {exc}") from exc

    entries = doc.get("servers") if isinstance(doc, dict) else doc
    if not isinstance(entries, list) or not entries:
        raise UpstreamError("leaderboard.json: no server list in document")

    total = None
    if isinstance(doc, dict):
        for key in ("total", "totalServers", "count"):
            if isinstance(doc.get(key), int):
                total = doc[key]
                break
    if total is None:
        total = len(entries)

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identity = next(
            (entry[k] for k in ("id", "name", "serverId", "slug") if k in entry),
            None,
        )
        if identity != server_id:
            continue
        rank = next(
            (entry[k] for k in ("rank", "position", "place") if k in entry),
            None,
        )
        if rank is None:
            raise UpstreamError(
                f"leaderboard.json: entry for {server_id} carries no rank"
            )
        return validate(rank, total, "leaderboard.json")

    raise UpstreamError(
        f"leaderboard.json: {server_id} not present in {len(entries)} entries"
    )


def parse_server_page(html: str) -> Ranking:
    """Extract our figure from the rendered server page."""
    match = _PROSE_ANCHOR.search(html)
    if match is None:
        raise UpstreamError(
            "server page: the 'ranks #N of M servers tracked' sentence is absent "
            "— the page was reworded and this parser needs updating"
        )
    return validate(match.group(1), match.group(2), "server page")


def _provenance_comment(ranking: Ranking, as_of: date) -> list[str]:
    """The audit trail the badge carries in its own source.

    Whoever next bumps this file must be able to re-derive the claim from
    the file alone: where the figure came from, the raw inputs, the
    arithmetic, and what the number does NOT assert.
    """
    pct = ranking.rank / ranking.total * 100
    return [
        "  <!-- GENERATED by scripts/refresh_mcp_toplist_badge.py — do not hand-edit.",
        f"       Source: {ranking.source} reported rank {ranking.rank:,}"
        f" of {ranking.total:,}",
        f"       tracked MCP servers, read {as_of.isoformat()}",
        f"       ({ranking.rank}/{ranking.total} = {pct:.2f}%"
        f' -> "{ranking.tier_text()}").',
        f"       Verify: {SERVER_PAGE_URL}",
        "       Upstream's score is a popularity and activity signal, not a quality",
        "       assessment, and ~25% of its weighting is undisclosed — so this badge",
        "       says Cortex is RANKED in this tier by MCP Toplist, never that"
        " it IS. -->",
    ]


def render_badge(ranking: Ranking, as_of: date) -> str:
    """Render the badge SVG.

    Geometry, escaping and the no-<style>/no-external-font constraints live
    in badge_render; what stays here is what makes this badge THIS badge —
    the bar icon, the banner palette, and the wording of the claim.
    """
    tier = ranking.tier_text()
    stamp = f"{_MONTHS[as_of.month - 1]} {as_of.year}"
    alt = f"MCP Toplist: {tier} of {ranking.total:,} tracked MCP servers, {stamp}"
    label = badge_render.Panel(
        text="MCP Toplist",
        fill="#3b3129",
        text_fill="#f8f7f2",
        # Explicit, not derived: the bar icon displaces the label text, so
        # this panel is not centred on its own midpoint.
        width=_LABEL_PANEL_W,
        text_width=_LABEL_TEXT_W,
        text_x=54,
    )
    spec = badge_render.BadgeSpec(
        label=label,
        message=f"{tier} · {stamp}",
        message_fill="#a53e00",
        message_text_fill="#fff",
        alt=alt,
        provenance=tuple(_provenance_comment(ranking, as_of)),
        icon=(
            '  <g fill="#f1eee7">',
            '    <rect x="7" y="10" width="2.6" height="5" rx="0.6"/>',
            '    <rect x="11.2" y="6.5" width="2.6" height="8.5" rx="0.6"/>',
            '    <rect x="15.4" y="8.4" width="2.6" height="6.6" rx="0.6"/>',
            "  </g>",
        ),
    )
    return badge_render.render(spec)


def fetch(url: str, opener: Callable = urllib.request.urlopen) -> bytes:
    """Retrieve a URL, or raise UpstreamError naming the failure."""
    request = urllib.request.Request(
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


def _today() -> date:
    return datetime.now(timezone.utc).date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the badge is out of date; never write",
    )
    parser.add_argument("--badge", type=Path, default=BADGE_PATH)
    args = parser.parse_args(argv)

    try:
        ranking, notices = resolve_ranking()
    except UpstreamError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for notice in notices:
        print(f"notice: fell back after: {notice}", file=sys.stderr)

    rendered = render_badge(ranking, _today())
    current = args.badge.read_text() if args.badge.exists() else None

    if current == rendered:
        print(
            f"current: {ranking.tier_text()} "
            f"(#{ranking.rank:,} of {ranking.total:,}, via {ranking.source})"
        )
        return 0

    if args.check:
        print(
            f"STALE: badge does not match upstream "
            f"({ranking.tier_text()}, #{ranking.rank:,} of {ranking.total:,})",
            file=sys.stderr,
        )
        return 1

    args.badge.write_text(rendered)
    print(
        f"updated: {ranking.tier_text()} "
        f"(#{ranking.rank:,} of {ranking.total:,}, via {ranking.source})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
