"""Shields-style two-panel badge SVG rendering, shared by the badge generators.

Two constraints shape every choice here, and neither is negotiable on the
one surface these badges exist for (a README rendered by GitHub):

source: ADR-0706"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree
from xml.sax.saxutils import escape


class BadgeMarkupError(RuntimeError):
    """The rendered badge is not well-formed XML."""


# source: ADR-0706
_PX_PER_CHAR = 5.79

# 7px of padding on each side of the message text, matching the shields.io
# proportions the surrounding badge row already uses.
_SIDE_PADDING = 7

_BADGE_HEIGHT = 20
_FONT_STACK = "Verdana,DejaVu Sans,Geneva,sans-serif"
_FONT_SIZE = 11


def text_width(text: str) -> int:
    """Nominal px width of badge text at font-size 11.

    source: ADR-0706"""
    return max(1, round(_PX_PER_CHAR * len(text)))


@dataclass(frozen=True)
class Panel:
    """One side of a badge: its text, its fill, and where the text sits.

    source: ADR-0706"""

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

    source: ADR-0706"""

    label: Panel
    message: str
    message_fill: str
    message_text_fill: str
    alt: str
    provenance: tuple[str, ...]
    icon: tuple[str, ...] = field(default_factory=tuple)


def _text_pair(x: float, width: int, text: str, fill: str) -> list[str]:
    """The drop-shadow run and the face run for one label.

    source: ADR-0706"""
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

    source: ADR-0706"""
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
    # source: ADR-0706
    try:
        ElementTree.fromstring(svg)
    except ElementTree.ParseError as error:
        raise BadgeMarkupError(
            f"rendered badge is not well-formed XML: {error}"
        ) from error
    return svg
