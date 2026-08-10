"""Direct unit test for `wiki_registry_known_kind_names` (issue #282).

`WikiRegistry` is a plain `@dataclass(frozen=True)`; mutmut categorically
skips the body of any `@dataclass`-decorated class
(`mutmut/mutation/file_mutation.py:236`), so the logic that used to live on
`WikiRegistry.known_kind_names` carries zero mutation coverage unless
exercised directly against the extracted free function. No dedicated test
module for `wiki_schema_loader.py`'s parsers existed prior to this file.
"""

from __future__ import annotations

from mcp_server.shared.wiki_schema_loader import (
    KindDefinition,
    WikiRegistry,
    wiki_registry_known_kind_names,
)


def test_known_kind_names_returns_kind_keys():
    registry = WikiRegistry(
        kinds={
            "adr": KindDefinition(name="adr", display_name="ADR", dir_name="adr"),
            "rfc": KindDefinition(name="rfc", display_name="RFC", dir_name="rfc"),
        },
        rules=[],
        views={},
        triggers={},
    )
    assert wiki_registry_known_kind_names(registry) == {"adr", "rfc"}


def test_known_kind_names_empty_registry():
    registry = WikiRegistry(kinds={}, rules=[], views={}, triggers={})
    assert wiki_registry_known_kind_names(registry) == set()
