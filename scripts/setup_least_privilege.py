#!/usr/bin/env python3
"""Provision the two PostgreSQL roles of ADR-1112, one command, as an administrator.

    python scripts/setup_least_privilege.py \
        --admin-url postgresql://postgres@127.0.0.1/postgres \
        [--database cortex] [--migrate-role cortex_migrate] \
        [--runtime-role cortex_runtime]

Creates (idempotently) a migration role that owns the database and a runtime
role with CONNECT only, and the extensions the schema needs. The store broker
then migrates as the first and serves as the second, granting the runtime role
data access after each migration:

    DATABASE_URL=postgresql://cortex_runtime@HOST/cortex
    CORTEX_MIGRATION_DATABASE_URL=postgresql://cortex_migrate@HOST/cortex

No password is set or printed: use ``ALTER ROLE ... PASSWORD`` or ``.pgpass``.

source: ADR-1112 (least privilege); three-pillar audit Track 0.3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.infrastructure.pg_roles import provision  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--database", default="cortex")
    parser.add_argument("--migrate-role", default="cortex_migrate")
    parser.add_argument("--runtime-role", default="cortex_runtime")
    args = parser.parse_args()
    provision(args.admin_url, args.database, args.migrate_role, args.runtime_role)
    roles = f"{args.migrate_role} (owner) and {args.runtime_role} (runtime)"
    print(f"roles {roles} ready on {args.database}")
    print(f"DATABASE_URL=postgresql://{args.runtime_role}@HOST/{args.database}")
    print(
        f"CORTEX_MIGRATION_DATABASE_URL=postgresql://{args.migrate_role}@HOST/{args.database}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
