"""Acquire and validate our MCP Toplist rank: fetch, parse, and bounds-check.

Two extraction paths, tried in order by `resolve_ranking`:

source: ADR-0760"""

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

# source: ADR-0760
TIMEOUT_S = 45

# source: ADR-0760
_PROSE_ANCHOR = re.compile(
    r"ranks\s*#\s*([\d,]+)\s*of\s*([\d,]+)\s*servers\s*tracked",
    re.IGNORECASE,
)

# source: ADR-0760
_MIN_PRINTABLE_PCT = 0.1


class UpstreamError(RuntimeError):
    """Upstream data could not be fetched or trusted."""


@dataclass(frozen=True)
class Ranking:
    """A validated rank-out-of-total, and where it came from.

    source: ADR-0760"""

    rank: int
    total: int
    source: str


def ranking_percentile(ranking: Ranking) -> float:
    """Share of the field this server sits within, to one decimal."""
    return round(ranking.rank / ranking.total * 100, 1)


def ranking_tier_text(ranking: Ranking) -> str:
    pct = ranking_percentile(ranking)
    # source: ADR-0760
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

    source: ADR-0760"""
    try:
        # source: ADR-0760
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


def fetch(url: str, opener: Callable = urllib.request.urlopen) -> bytes:
    """Retrieve a URL, or raise UpstreamError naming the failure."""
    # source: ADR-0760
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
