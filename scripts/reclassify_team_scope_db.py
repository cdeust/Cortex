"""Explicit database boundary for the scope repair. source: ADR-1083"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Self


def verify_backup(path: Path | None) -> None:
    if path is None or not path.is_file():
        raise ValueError("PostgreSQL apply requires an existing --backup archive")
    with path.open("rb") as stream:
        if stream.read(len(b"PGDMP")) != b"PGDMP":
            raise ValueError("backup must be a pg_dump custom-format archive")
    catalog = subprocess.run(
        ["pg_restore", "--list", str(path)], check=True, capture_output=True, text=True
    ).stdout
    if "TABLE DATA public memories " not in catalog:
        raise ValueError("backup must contain public.memories table data")
    subprocess.run(["pg_restore", "--file", os.devnull, str(path)], check=True)


class ScopeDatabase:
    def __init__(self, database_url: str | None, sqlite_path: Path | None) -> None:
        self.postgres = database_url is not None
        if self.postgres:
            import psycopg  # noqa: PLC0415 -- optional PostgreSQL adapter
            from psycopg.rows import dict_row  # noqa: PLC0415 -- optional PostgreSQL adapter

            self.connection = psycopg.connect(database_url, row_factory=dict_row)
        else:
            if sqlite_path is None or not sqlite_path.is_file():
                raise ValueError("SQLite target must be an existing database")
            self.connection = sqlite3.connect(sqlite_path)
            self.connection.row_factory = sqlite3.Row
        self.columns: set[str] = set()

    def __enter__(self) -> Self:
        if self.postgres:
            self.connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            rows = self.connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'memories'"
            ).fetchall()
            self.columns = {row["column_name"] for row in rows}
        else:
            self.connection.execute("BEGIN IMMEDIATE")
            self.columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(memories)")
            }
        return self

    def __exit__(self, *_exc: object) -> None:
        self.connection.rollback()
        self.connection.close()

    def fetch_rows(self, *, require_marker: bool) -> list[dict]:
        marker = "is_team_decision" in self.columns
        if require_marker and not marker:
            raise ValueError(
                "install the is_team_decision schema migration before apply"
            )
        team_column = "m.is_team_decision" if marker else "FALSE AS is_team_decision"
        query = (
            "SELECT m.id, m.content, m.tags, m.domain, m.directory_context, "  # noqa: S608 -- fixed column choice, no user SQL
            "m.agent_context, m.is_global, " + team_column + " FROM memories m "
            "JOIN current_memories cm ON cm.id = m.id "
            "WHERE m.is_global = TRUE AND m.is_benchmark = FALSE ORDER BY m.id"
        )
        if self.postgres and require_marker:
            query += " FOR UPDATE OF m"
        rows = self.connection.execute(query).fetchall()
        return [self._normalize(dict(row)) for row in rows]

    @staticmethod
    def _normalize(row: dict) -> dict:
        tags = row["tags"] or []
        row["tags"] = json.loads(tags) if isinstance(tags, str) else tags
        for key in ("domain", "directory_context", "agent_context"):
            row[key] = row[key] or ""
        for key in ("is_global", "is_team_decision"):
            row[key] = bool(row[key])
        return row

    def apply_changes(self, changes: list[dict]) -> None:
        query = (
            "UPDATE memories SET directory_context = ?, is_global = ?, "
            "is_team_decision = ? WHERE id = ?"
        )
        if self.postgres:
            query = query.replace("?", "%s")
        for change in changes:
            cursor = self.connection.execute(
                query,
                (
                    change["directory_context"],
                    change["is_global"],
                    change["is_team_decision"],
                    change["id"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"scope update did not affect exactly row {change['id']}"
                )
        self.connection.commit()
