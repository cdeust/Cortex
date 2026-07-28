"""Cross-backend connection type for shared query modules.

The wiki / memory query modules (``pg_store_wiki_*``, ``pg_store_memory_*``,
``pg_store_near_dup``, ``pg_store_lesson_promotion``) take a ``conn``
parameter that at runtime is either a psycopg connection (PostgreSQL) or a
``PsycopgCompatConnection`` (SQLite, issue #206). Annotating those parameters
as psycopg's ``Connection`` alone was a type lie: it switched checking off
for every SQLite call path — the class of blindness behind the silent
wiki-pipeline failure of issue #220. ``StoreConnection`` names the real
contract once, so both halves are checked at every call site.

TYPE_CHECKING-only: this module is imported for annotations, never at
runtime, so it stays importable on installs without the ``[postgresql]``
extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TypeAlias

    from psycopg import Connection
    from psycopg.rows import DictRow

    from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection

    StoreConnection: TypeAlias = Connection[DictRow] | PsycopgCompatConnection
