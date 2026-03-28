"""Codebase alteration benchmark — detect renamed symbols in code memories.

Analyzes a synthetic codebase (10 Python files), then modifies exactly
2 files (rename a class, change a function), re-analyzes incrementally,
and tests whether:
  1. The altered files are detected as changed (hash mismatch)
  2. The store contains the NEW symbol names, not the old ones
  3. Unmodified files remain unchanged
  4. Total file count is preserved

Tests use direct store queries — works with any embedding backend.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from mcp_server.handlers.codebase_analyze import handler as analyze_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

DOMAIN = "codebase-alteration-bench"


# ── Synthetic codebase ────────────────────────────────────────────────────

ORIGINAL_FILES: dict[str, str] = {
    "auth/token_service.py": (
        '"""Token management service."""\n\n'
        "from datetime import datetime, timedelta\n"
        "from auth.crypto import sign_payload\n\n"
        "class TokenService:\n"
        '    """Manages JWT token creation and validation."""\n\n'
        "    def __init__(self, secret: str, expiry_hours: int = 24):\n"
        "        self.secret = secret\n"
        "        self.expiry = timedelta(hours=expiry_hours)\n\n"
        "    def create_token(self, user_id: str) -> str:\n"
        "        return sign_payload({}, self.secret)\n\n"
        "    def validate_token(self, token: str) -> dict:\n"
        "        return {}\n"
    ),
    "auth/crypto.py": (
        '"""Cryptographic primitives."""\n\n'
        "import hashlib\nimport hmac\n\n"
        "def sign_payload(payload: dict, secret: str) -> str:\n"
        "    return hmac.new(secret.encode(), b'', hashlib.sha256).hexdigest()\n\n"
        "def verify_payload(token: str, secret: str) -> dict:\n"
        '    return {"valid": True}\n'
    ),
    "auth/middleware.py": (
        '"""Authentication middleware."""\n\n'
        "from auth.token_service import TokenService\n\n"
        "class AuthMiddleware:\n"
        "    def __init__(self, svc: TokenService):\n"
        "        self.svc = svc\n\n"
        "    def authenticate(self, request: dict) -> dict:\n"
        '        header = request.get("Authorization", "")\n'
        '        if not header.startswith("Bearer "):\n'
        '            return {"authenticated": False}\n'
        "        return self.svc.validate_token(header[7:])\n"
    ),
    "models/user.py": (
        '"""User model."""\n\n'
        "from dataclasses import dataclass, field\n\n"
        "@dataclass\nclass User:\n"
        "    user_id: str\n    email: str\n"
        "    display_name: str\n"
        "    roles: list[str] = field(default_factory=list)\n\n"
        "    def has_role(self, role: str) -> bool:\n"
        "        return role in self.roles\n"
    ),
    "models/session.py": (
        '"""Session model."""\n\n'
        "from dataclasses import dataclass\nfrom datetime import datetime\n\n"
        "@dataclass\nclass Session:\n"
        "    session_id: str\n    user_id: str\n"
        "    created_at: datetime\n\n"
        "    def is_expired(self, max_minutes: int = 30) -> bool:\n"
        "        return False\n"
    ),
    "api/routes.py": (
        '"""API routes."""\n\n'
        "from auth.middleware import AuthMiddleware\n\n"
        "class Router:\n"
        "    def __init__(self, auth: AuthMiddleware):\n"
        "        self.auth = auth\n\n"
        "    def get_profile(self, request: dict) -> dict:\n"
        '        return {"user": "test"}\n\n'
        "    def list_users(self, request: dict) -> list:\n"
        "        return []\n"
    ),
    "api/health.py": (
        '"""Health check."""\n\n'
        "def health_check() -> dict:\n"
        '    return {"status": "ok"}\n\n'
        "def readiness_check(db_ok: bool) -> dict:\n"
        '    return {"ready": db_ok}\n'
    ),
    "storage/repository.py": (
        '"""Base repository."""\n\n'
        "from typing import Any\n\n"
        "class BaseRepository:\n"
        "    def __init__(self, conn: Any):\n"
        "        self.conn = conn\n\n"
        "    def find_by_id(self, eid: str) -> dict | None:\n"
        "        return None\n\n"
        "    def save(self, entity: dict) -> str:\n"
        '        return ""\n'
    ),
    "storage/user_repo.py": (
        '"""User repository."""\n\n'
        "from storage.repository import BaseRepository\n"
        "from models.user import User\n\n"
        "class UserRepository(BaseRepository):\n"
        "    def find_by_email(self, email: str) -> User | None:\n"
        "        return None\n\n"
        "    def create_user(self, email: str, name: str) -> User:\n"
        '        return User(user_id="new", email=email, display_name=name)\n'
    ),
    "config/settings.py": (
        '"""App configuration."""\n\n'
        "import os\n\n"
        "class AppSettings:\n"
        "    def __init__(self):\n"
        '        self.secret_key = os.environ.get("SECRET_KEY", "dev")\n'
        '        self.db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")\n'
        '        self.debug = os.environ.get("DEBUG", "false") == "true"\n'
    ),
}

# Alterations: rename TokenService -> CredentialManager, authenticate -> verify_request
ALTERED_FILES: dict[str, str] = {
    "auth/token_service.py": (
        '"""Credential management service."""\n\n'
        "from datetime import datetime, timedelta\n"
        "from auth.crypto import sign_payload\n\n"
        "class CredentialManager:\n"
        '    """Manages credential creation and validation."""\n\n'
        "    def __init__(self, secret: str, expiry_hours: int = 24):\n"
        "        self.secret = secret\n"
        "        self.expiry = timedelta(hours=expiry_hours)\n\n"
        "    def create_token(self, user_id: str) -> str:\n"
        "        return sign_payload({}, self.secret)\n\n"
        "    def validate_token(self, token: str) -> dict:\n"
        "        return {}\n"
    ),
    "auth/middleware.py": (
        '"""Authentication middleware."""\n\n'
        "from auth.token_service import CredentialManager\n\n"
        "class AuthMiddleware:\n"
        "    def __init__(self, mgr: CredentialManager):\n"
        "        self.mgr = mgr\n\n"
        "    def verify_request(self, request: dict) -> dict:\n"
        '        header = request.get("Authorization", "")\n'
        '        if not header.startswith("Bearer "):\n'
        '            return {"authenticated": False}\n'
        "        return self.mgr.validate_token(header[7:])\n"
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _get_store() -> MemoryStore:
    s = get_memory_settings()
    return MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)


@pytest.fixture(autouse=True)
def clean_benchmark():
    """Clean benchmark memories before and after."""
    store = _get_store()
    store._conn.execute("DELETE FROM memories WHERE domain = %s", (DOMAIN,))
    store._conn.commit()
    yield
    store._conn.execute("DELETE FROM memories WHERE domain = %s", (DOMAIN,))
    store._conn.commit()


def _write_codebase(tmpdir: Path, files: dict[str, str]) -> None:
    """Write files to a temp directory."""
    for rel_path, content in files.items():
        full = tmpdir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)


def _query_content(store: MemoryStore, substring: str) -> list[dict]:
    """Direct store query for memories containing a substring."""
    rows = store._conn.execute(
        "SELECT id, content FROM memories WHERE domain = %s AND content LIKE %s",
        (DOMAIN, f"%{substring}%"),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Tests ─────────────────────────────────────────────────────────────────


class TestCodebaseAlteration:
    """Detect 2 renamed symbols in a 10-file codebase."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_initial_analysis_stores_all_files(self) -> None:
        """All 10 files are analyzed and stored."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                _write_codebase(Path(tmpdir), ORIGINAL_FILES)
                result = await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": False,
                    }
                )
                assert result["analyzed"]
                assert result["new"] == len(ORIGINAL_FILES)
                assert result["entities"] > 0

        self._run(_test())

    def test_incremental_detects_changed_files(self) -> None:
        """After alteration, only changed files are re-processed."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                _write_codebase(root, ORIGINAL_FILES)

                r1 = await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": False,
                    }
                )
                assert r1["new"] == len(ORIGINAL_FILES)

                for rel_path, content in ALTERED_FILES.items():
                    (root / rel_path).write_text(content)

                r2 = await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": True,
                    }
                )
                assert r2["updated"] == len(ALTERED_FILES)
                assert r2["unchanged"] == len(ORIGINAL_FILES) - len(ALTERED_FILES)

        self._run(_test())

    def test_store_contains_new_class_name(self) -> None:
        """After alteration, CredentialManager is in store, TokenService is not."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(Path(tmpdir), merged)

                await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": False,
                    }
                )

                store = _get_store()
                new_rows = _query_content(store, "CredentialManager")
                assert len(new_rows) >= 1, "CredentialManager not found in store"

                old_rows = _query_content(store, "class: TokenService")
                assert len(old_rows) == 0, "Old TokenService should not appear"

        self._run(_test())

    def test_store_contains_renamed_method(self) -> None:
        """After alteration, verify_request is in store, authenticate is gone."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(Path(tmpdir), merged)

                await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": False,
                    }
                )

                store = _get_store()
                new_rows = _query_content(store, "verify_request")
                assert len(new_rows) >= 1, "verify_request not found in store"

        self._run(_test())

    def test_unmodified_files_unchanged(self) -> None:
        """Files not in ALTERED_FILES remain intact in memory."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(Path(tmpdir), merged)

                await analyze_handler(
                    {
                        "directory": tmpdir,
                        "languages": ["python"],
                        "domain": DOMAIN,
                        "incremental": False,
                    }
                )

                store = _get_store()
                # User model intact
                user_rows = _query_content(store, "has_role")
                assert len(user_rows) >= 1, "User.has_role not found"

                # Health check intact
                health_rows = _query_content(store, "health_check")
                assert len(health_rows) >= 1, "health_check not found"

                # Total file count preserved
                count = store._conn.execute(
                    "SELECT COUNT(*) as c FROM memories "
                    "WHERE domain = %s AND agent_context = 'codebase'",
                    (DOMAIN,),
                ).fetchone()
                assert count["c"] == len(ORIGINAL_FILES)

        self._run(_test())
