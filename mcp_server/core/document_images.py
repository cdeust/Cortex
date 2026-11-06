"""Pure image inventory shared by the document parsers (issue #732).

An image is counted once per element that names its bytes (a *leaf*: the
docx ``a:blip`` / ``v:imagedata``, the Confluence ``ri:attachment`` /
``ri:url`` / ``<img>``), plus once per outermost image *container*
(``w:drawing`` / ``w:pict``, ``<ac:image>``) that holds no leaf. A container
nested in another container is part of the outer one, and a leaf is counted
only inside a container unless the markup declares it standalone (``<img>``).

Each reference is read from the leaf's own attribute, so every byte of
output comes from a distinct byte of input: the result stays linear in the
document, whatever the nesting (review 3 of PR #893: N nested containers
around one reference had yielded N copies of it). The walk is iterative, so a
deeply nested document cannot exhaust the interpreter stack.

source: issue #732; ECMA-376 Part 1 §20.1.8.13 (blip), §14.1.2.11 (imagedata)
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from mcp_server.core.document_model import DocumentAttachment


@dataclass(frozen=True)
class ImageMarkup:
    """How one format marks images up.

    ``containers``: local names of image containers. ``leaves``: local name of
    each leaf → the qualified attribute holding its reference.
    ``standalone``: leaf names counted even outside a container.

    source: issue #732"""

    containers: frozenset[str]
    leaves: dict[str, str]
    standalone: frozenset[str] = frozenset()


def _local(tag: str) -> str:
    # source: ElementTree prefixes qualified tags with ``{namespace}``.
    return tag.rsplit("}", 1)[-1]


def _image_references(elem: ET.Element, markup: ImageMarkup) -> list[str]:
    """References of every image under ``elem``, in document order.

    The walk is preorder, so an outermost container's subtree is read in one
    stretch: one ``pending`` slot (its placeholder, until its first leaf
    fills it) is enough.

    source: issue #732"""
    refs: list[str] = []
    pending: int | None = None
    stack: list[tuple[ET.Element, bool]] = [(elem, False)]
    while stack:
        node, inside = stack.pop()
        name = _local(node.tag)
        if not inside and name in markup.containers:
            inside = True
            pending = len(refs)
            refs.append("")
        elif name in markup.leaves and (inside or name in markup.standalone):
            value = node.get(markup.leaves[name], "")
            if inside and pending is not None:
                refs[pending] = value
                pending = None
            else:
                refs.append(value)
        stack.extend((child, inside) for child in reversed(node))
    return refs


def collect_images(
    elem: ET.Element,
    section_index: int,
    markup: ImageMarkup,
    out: list[DocumentAttachment],
) -> None:
    """Append every image under ``elem`` to ``out``, numbered after the ones
    already there and tagged with ``section_index``.

    source: issue #732"""
    for reference in _image_references(elem, markup):
        out.append(
            DocumentAttachment(
                ordinal=len(out) + 1,
                reference=reference,
                section_index=section_index,
            )
        )
