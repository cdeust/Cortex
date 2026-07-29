"""Shields-style two-panel badge SVG rendering, shared by the badge generators.

Extracted from refresh_mcp_toplist_badge.py when a second generator
(generate_repo_badges.py) needed the same geometry. Both emit the same
anatomy — a dark label panel, a coloured message panel, a drop-shadowed
text run in each — and differ only in their data and provenance.

Two constraints shape every choice here, and neither is negotiable on the
one surface these badges exist for (a README rendered by GitHub):

  * No <style> block and no external font. GitHub's SVG sanitizer strips
    both, so a badge depending on either renders unstyled in production
    while looking correct in every local preview.
  * Every <text> carries textLength + lengthAdjust. That makes width
    estimation a cosmetic concern rather than a correctness one: a bad
    estimate costs letter-spacing, never overflow past the panel edge.

Text and attributes are XML-escaped here rather than at each call site.
A top-of-field MCP Toplist rank renders its tier as "Top <0.1%", and that
unescaped '<' made the badge unparseable XML — caught by a test before it
shipped. Centralising the escape means a new generator cannot reintroduce
that bug by forgetting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree
from xml.sax.saxutils import escape


class BadgeMarkupError(RuntimeError):
    """The rendered badge is not well-formed XML."""


# source: measured 2026-07-28 — the 19-character string "Top 1.2% · Jul 2026"
# renders correctly at textLength=110 in Verdana/DejaVu Sans, i.e.
# 5.79 px/char across this badge set's glyphs (digits, letters, '%', '·',
# '+', '.', '<'). The set is narrow and fixed, so a per-character mean is
# adequate; see the module docstring on why accuracy is cosmetic here.
_PX_PER_CHAR = 5.79

# 7px of padding on each side of the message text, matching the shields.io
# proportions the surrounding badge row already uses.
_SIDE_PADDING = 7

_BADGE_HEIGHT = 20
_FONT_STACK = "Verdana,DejaVu Sans,Geneva,sans-serif"
_FONT_SIZE = 11


def text_width(text: str) -> int:
    """Nominal px width of badge text at font-size 11.

    Never returns 0: a textLength of 0 collapses the glyphs into a point
    rather than rendering nothing, which is harder to spot than a wrong width.
    """
    return max(1, round(_PX_PER_CHAR * len(text)))


@dataclass(frozen=True)
class Panel:
    """One side of a badge: its text, its fill, and where the text sits.

    Geometry is explicit rather than derived because the label panel of a
    badge carrying an icon is not centred on its own midpoint — the icon
    displaces the text. Deriving it would silently move the MCP Toplist
    label when this module changed.
    """

    text: str
    fill: str
    text_fill: str
    width: int
    text_width: int
    text_x: float


def label_panel(text: str, fill: str, text_fill: str) -> Panel:
    """A label panel with no icon, sized to its text and centred in itself."""
    inner = text_width(text)
    width = inner + _SIDE_PADDING * 2
    return Panel(
        text=text,
        fill=fill,
        text_fill=text_fill,
        width=width,
        text_width=inner,
        text_x=width / 2,
    )


@dataclass(frozen=True)
class BadgeSpec:
    """Everything one badge needs, as a parameter object.

    A dataclass rather than a long parameter list: the renderer would
    otherwise take eight arguments, past the four-parameter limit, and the
    call sites would be unreadable positional soup.
    """

    label: Panel
    message: str
    message_fill: str
    message_text_fill: str
    alt: str
    provenance: tuple[str, ...]
    icon: tuple[str, ...] = field(default_factory=tuple)


def _text_pair(x: float, width: int, text: str, fill: str) -> list[str]:
    """The drop-shadow run and the face run for one label.

    Emitted as a pair because they always occur together: the faint offset
    copy is what keeps light text legible on the panel fill.
    """
    shared = (
        f'text-anchor="middle" textLength="{width}" lengthAdjust="spacingAndGlyphs"'
    )
    return [
        (
            f'    <text x="{x:g}" y="15" fill="#000" fill-opacity="0.25" '
            f"{shared}>{text}</text>"
        ),
        f'    <text x="{x:g}" y="14" fill="{fill}" {shared}>{text}</text>',
    ]


def render(spec: BadgeSpec) -> str:
    """Render a badge to SVG source, newline-terminated.

    The caller supplies the provenance comment: every badge in this repo is
    a committed file rather than a hotlinked image, so the file has to carry
    enough for the next maintainer to re-derive its claim without network
    access. A badge with nothing to say for itself is not one of ours.
    """
    message_w = text_width(spec.message)
    right_w = message_w + _SIDE_PADDING * 2
    total_w = spec.label.width + right_w
    message_x = spec.label.width + right_w / 2
    # Escaped once, here, so no generator can forget it: see module docstring.
    message_xml = escape(spec.message)
    label_xml = escape(spec.label.text)
    alt_xml = escape(spec.alt, {'"': "&quot;"})
    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}"'
            f' height="{_BADGE_HEIGHT}" viewBox="0 0 {total_w} {_BADGE_HEIGHT}"'
            f' role="img" aria-label="{alt_xml}">'
        ),
        f"  <title>{alt_xml}</title>",
        *spec.provenance,
        '  <clipPath id="r">',
        f'    <rect width="{total_w}" height="{_BADGE_HEIGHT}" rx="3" fill="#fff"/>',
        "  </clipPath>",
        '  <g clip-path="url(#r)">',
        f'    <rect width="{spec.label.width}" height="{_BADGE_HEIGHT}"'
        f' fill="{spec.label.fill}"/>',
        f'    <rect x="{spec.label.width}" width="{right_w}"'
        f' height="{_BADGE_HEIGHT}" fill="{spec.message_fill}"/>',
        "  </g>",
        *spec.icon,
        f'  <g font-family="{_FONT_STACK}" font-size="{_FONT_SIZE}">',
        *_text_pair(
            spec.label.text_x,
            spec.label.text_width,
            label_xml,
            spec.label.text_fill,
        ),
        *_text_pair(message_x, message_w, message_xml, spec.message_text_fill),
        "  </g>",
        "</svg>",
        "",
    ]
    svg = "\n".join(lines)
    # Parse what we just built, and refuse to return anything that is not
    # well-formed. Escaping the text runs is not sufficient on its own: a
    # provenance comment containing "--" (as "--check" or "--collect-only"
    # readily does) is illegal inside an XML comment and produces a badge
    # that no strict renderer will draw. Both defects have been introduced
    # here in practice, so the guard is on the finished artifact rather than
    # on any one of the ways to break it.
    try:
        ElementTree.fromstring(svg)
    except ElementTree.ParseError as error:
        raise BadgeMarkupError(f"rendered badge is not well-formed XML: {error}")
    return svg
