# ADR-0780: scripts/repo_badge_catalog.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/repo_badge_catalog.py`; original SHA-256 `9c4b761ccf779bad61a0176e7b4ae1f2708316fc0d7cd4ca80090eeda01de092`.

## Original docstring, lines 1–17

````text
"""Badge field specifications for scripts/generate_repo_badges.py.

Extracted (issue #293, Extract Function/Move Function) to keep
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
````

## Original comment, lines 21–22

````text
# The palette is assets/banner.svg's, shared with the MCP Toplist badge so
# the README's badge row reads as one set rather than as a pile of styles.
````

