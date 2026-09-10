# ADR-0706: scripts/badge_render.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/badge_render.py`; original SHA-256 `528184d39b6702a220361250eb0368392b84ad1d52580056fd5ec6e5c2f19e80`.

## Original docstring, lines 1–23

````text
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
````

## Original comment, lines 36–40

````text
# source: measured 2026-07-28 — the 19-character string "Top 1.2% · Jul 2026"
# renders correctly at textLength=110 in Verdana/DejaVu Sans, i.e.
# 5.79 px/char across this badge set's glyphs (digits, letters, '%', '·',
# '+', '.', '<'). The set is narrow and fixed, so a per-character mean is
# adequate; see the module docstring on why accuracy is cosmetic here.
````

## Original docstring, lines 53–57

````text
"""Nominal px width of badge text at font-size 11.

    Never returns 0: a textLength of 0 collapses the glyphs into a point
    rather than rendering nothing, which is harder to spot than a wrong width.
    """
````

## Original docstring, lines 63–69

````text
"""One side of a badge: its text, its fill, and where the text sits.

    Geometry is explicit rather than derived because the label panel of a
    badge carrying an icon is not centred on its own midpoint — the icon
    displaces the text. Deriving it would silently move the MCP Toplist
    label when this module changed.
    """
````

## Original docstring, lines 95–100

````text
"""Everything one badge needs, as a parameter object.

    A dataclass rather than a long parameter list: the renderer would
    otherwise take eight arguments, past the four-parameter limit, and the
    call sites would be unreadable positional soup.
    """
````

## Original docstring, lines 112–116

````text
"""The drop-shadow run and the face run for one label.

    Emitted as a pair because they always occur together: the faint offset
    copy is what keeps light text legible on the panel fill.
    """
````

## Original docstring, lines 130–136

````text
"""Render a badge to SVG source, newline-terminated.

    The caller supplies the provenance comment: every badge in this repo is
    a committed file rather than a hotlinked image, so the file has to carry
    enough for the next maintainer to re-derive its claim without network
    access. A badge with nothing to say for itself is not one of ours.
    """
````

## Original comment, lines 176–182

````text
# Parse what we just built, and refuse to return anything that is not
    # well-formed. Escaping the text runs is not sufficient on its own: a
    # provenance comment containing "--" (as "--check" or "--collect-only"
    # readily does) is illegal inside an XML comment and produces a badge
    # that no strict renderer will draw. Both defects have been introduced
    # here in practice, so the guard is on the finished artifact rather than
    # on any one of the ways to break it.
````

