"""Badge field specifications for scripts/generate_repo_badges.py.

Extracted (issue #287, Extract Function/Move Function) to keep
generate_repo_badges.py under the repo's 300-line file cap. Returns plain
field dicts rather than `RepoBadge` instances: `RepoBadge` is a
`@dataclass`-decorated class whose owning module matters to mutmut (see its
docstring in generate_repo_badges.py), and generate_repo_badges.py's own
tests load that module twice under two different dotted names (the direct
`spec_from_file_location` load the test suite drives, plus whatever a bare
`import generate_repo_badges` from a sibling would separately cache) — two
non-identical `RepoBadge` classes existing side by side is a real, if
usually harmless, risk (dataclass `__eq__`/`isinstance` compare by class
identity). Keeping `RepoBadge` construction exclusively in
generate_repo_badges.py and having this module hand back only primitive
data (str/int, dict) sidesteps the question entirely: no class ever
crosses this module boundary.
"""

from __future__ import annotations

# The palette is assets/banner.svg's, shared with the MCP Toplist badge so
# the README's badge row reads as one set rather than as a pile of styles.
_LABEL_FILL = "#3b3129"
_LABEL_TEXT = "#f8f7f2"
_MESSAGE_TEXT = "#fff"

# Message-panel fills. Distinct hues carry the same meaning the shields.io
# originals did (blue = neutral fact, green = healthy, orange = corpus), so
# the row's reading does not change with its hosting.
_NEUTRAL = "#31708f"
_HEALTHY = "#2f6f3e"
_CORPUS = "#a53e00"

TESTS_BADGE_FILENAME = "badge-tests.svg"


def fixed_badge_specs(
    licence: str, floor: str, references: int, version: str
) -> list[dict[str, str]]:
    """The four badges present on every run — none needs a live test count."""
    return [
        {
            "filename": "badge-license.svg",
            "label": "license",
            "message": licence,
            "fill": _NEUTRAL,
            "alt": f"License: {licence}",
            "derivation": "Source: [project].license in pyproject.toml.",
        },
        {
            "filename": "badge-python.svg",
            "label": "python",
            "message": f"{floor}+",
            "fill": _NEUTRAL,
            "alt": f"Python {floor}+",
            "derivation": "Source: [project].requires-python in pyproject.toml.",
        },
        {
            "filename": "badge-references.svg",
            "label": "references",
            "message": f"{references} papers",
            "fill": _CORPUS,
            "alt": f"{references} referenced papers",
            "derivation": (
                "Source: entries under '## References' in docs/papers/bibliography.md."
            ),
        },
        {
            "filename": "badge-version.svg",
            "label": "version",
            "message": version,
            "fill": _HEALTHY,
            "alt": f"Version {version}",
            "derivation": "Source: [project].version in pyproject.toml.",
        },
    ]


def tests_badge_spec(test_count: int) -> dict[str, str]:
    return {
        "filename": TESTS_BADGE_FILENAME,
        "label": "tests",
        "message": f"{test_count} passing",
        "fill": _HEALTHY,
        "alt": f"{test_count} tests passing",
        "derivation": "Source: the count pytest collects on this tree.",
    }
