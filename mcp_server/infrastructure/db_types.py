"""Cross-backend connection type for shared query modules.

source: ADR-0515"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TypeAlias

    from psycopg import Connection
    from psycopg.rows import DictRow

    from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection

    StoreConnection: TypeAlias = Connection[DictRow] | PsycopgCompatConnection
