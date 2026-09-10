"""Badge field specifications for scripts/generate_repo_badges.py.

source: ADR-0780"""

from __future__ import annotations

# source: ADR-0780
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
