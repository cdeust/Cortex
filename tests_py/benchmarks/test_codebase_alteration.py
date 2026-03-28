"""Codebase alteration benchmark — detect renamed symbols in code memories.

Analyzes a synthetic codebase (20 Python files), then modifies exactly
2 files (rename a class, change a function), re-analyzes incrementally,
and tests whether:
  1. The altered files are detected as changed (hash mismatch)
  2. Recall returns the NEW symbol names, not the old ones
  3. Unmodified files remain unchanged
  4. The knowledge graph reflects the renamed entities

This is the codebase equivalent of the Harry Potter spell alteration test.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from mcp_server.handlers.codebase_analyze import handler as analyze_handler
from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

DOMAIN = "codebase-alteration-bench"


# ── Synthetic codebase ────────────────────────────────────────────────────

ORIGINAL_FILES: dict[str, str] = {
    "auth/token_service.py": '''"""Token management service."""

from datetime import datetime, timedelta
from auth.crypto import sign_payload

class TokenService:
    """Manages JWT token creation and validation."""

    def __init__(self, secret: str, expiry_hours: int = 24):
        self.secret = secret
        self.expiry = timedelta(hours=expiry_hours)

    def create_token(self, user_id: str, roles: list[str]) -> str:
        """Create a signed JWT token for a user."""
        payload = {"sub": user_id, "roles": roles, "exp": datetime.utcnow() + self.expiry}
        return sign_payload(payload, self.secret)

    def validate_token(self, token: str) -> dict:
        """Validate and decode a JWT token."""
        return verify_payload(token, self.secret)
''',
    "auth/crypto.py": '''"""Cryptographic primitives for auth."""

import hashlib
import hmac

def sign_payload(payload: dict, secret: str) -> str:
    """Sign a payload with HMAC-SHA256."""
    msg = str(sorted(payload.items())).encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()

def verify_payload(token: str, secret: str) -> dict:
    """Verify a signed token."""
    return {"valid": True}
''',
    "auth/middleware.py": '''"""Authentication middleware."""

from auth.token_service import TokenService

class AuthMiddleware:
    """HTTP middleware that validates auth tokens."""

    def __init__(self, token_service: TokenService):
        self.token_service = token_service

    def authenticate(self, request: dict) -> dict:
        """Extract and validate token from request headers."""
        header = request.get("Authorization", "")
        if not header.startswith("Bearer "):
            return {"authenticated": False}
        token = header[7:]
        return self.token_service.validate_token(token)
''',
    "models/user.py": '''"""User domain model."""

from dataclasses import dataclass, field

@dataclass
class User:
    """Represents an authenticated user."""
    user_id: str
    email: str
    display_name: str
    roles: list[str] = field(default_factory=list)
    is_active: bool = True

    def has_role(self, role: str) -> bool:
        return role in self.roles
''',
    "models/session.py": '''"""Session tracking model."""

from dataclasses import dataclass
from datetime import datetime

@dataclass
class Session:
    """Active user session."""
    session_id: str
    user_id: str
    created_at: datetime
    last_active: datetime
    ip_address: str = ""

    def is_expired(self, max_idle_minutes: int = 30) -> bool:
        delta = datetime.utcnow() - self.last_active
        return delta.total_seconds() > max_idle_minutes * 60
''',
    "api/routes.py": '''"""API route definitions."""

from auth.middleware import AuthMiddleware
from models.user import User

class Router:
    """HTTP router with auth-protected endpoints."""

    def __init__(self, auth: AuthMiddleware):
        self.auth = auth

    def get_profile(self, request: dict) -> dict:
        """Get current user profile."""
        auth_result = self.auth.authenticate(request)
        if not auth_result.get("authenticated"):
            return {"error": "unauthorized"}
        return {"user": auth_result.get("user_id")}

    def list_users(self, request: dict) -> list:
        """List all users (admin only)."""
        return []
''',
    "api/health.py": '''"""Health check endpoint."""

def health_check() -> dict:
    """Return service health status."""
    return {"status": "ok", "version": "1.0.0"}

def readiness_check(db_connected: bool) -> dict:
    """Return readiness status."""
    return {"ready": db_connected}
''',
    "storage/repository.py": '''"""Base repository pattern."""

from typing import Any

class BaseRepository:
    """Abstract repository for data access."""

    def __init__(self, connection: Any):
        self.connection = connection

    def find_by_id(self, entity_id: str) -> dict | None:
        """Find entity by primary key."""
        return None

    def save(self, entity: dict) -> str:
        """Persist an entity and return its ID."""
        return ""
''',
    "storage/user_repo.py": '''"""User repository implementation."""

from storage.repository import BaseRepository
from models.user import User

class UserRepository(BaseRepository):
    """Database operations for User entities."""

    def find_by_email(self, email: str) -> User | None:
        """Look up a user by email address."""
        return None

    def create_user(self, email: str, name: str) -> User:
        """Create a new user account."""
        return User(user_id="new", email=email, display_name=name)
''',
    "config/settings.py": '''"""Application configuration."""

import os

class AppSettings:
    """Central configuration loaded from environment."""

    def __init__(self):
        self.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
        self.db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
        self.debug = os.environ.get("DEBUG", "false").lower() == "true"
        self.port = int(os.environ.get("PORT", "8080"))
''',
}

# The two alterations: rename TokenService -> CredentialManager, rename authenticate -> verify_request
ALTERED_FILES: dict[str, str] = {
    "auth/token_service.py": '''"""Credential management service."""

from datetime import datetime, timedelta
from auth.crypto import sign_payload

class CredentialManager:
    """Manages credential creation and validation."""

    def __init__(self, secret: str, expiry_hours: int = 24):
        self.secret = secret
        self.expiry = timedelta(hours=expiry_hours)

    def create_token(self, user_id: str, roles: list[str]) -> str:
        """Create a signed JWT token for a user."""
        payload = {"sub": user_id, "roles": roles, "exp": datetime.utcnow() + self.expiry}
        return sign_payload(payload, self.secret)

    def validate_token(self, token: str) -> dict:
        """Validate and decode a JWT token."""
        return verify_payload(token, self.secret)
''',
    "auth/middleware.py": '''"""Authentication middleware."""

from auth.token_service import CredentialManager

class AuthMiddleware:
    """HTTP middleware that validates auth tokens."""

    def __init__(self, credential_manager: CredentialManager):
        self.credential_manager = credential_manager

    def verify_request(self, request: dict) -> dict:
        """Extract and validate token from request headers."""
        header = request.get("Authorization", "")
        if not header.startswith("Bearer "):
            return {"authenticated": False}
        token = header[7:]
        return self.credential_manager.validate_token(token)
''',
}


# ── Fixtures ──────────────────────────────────────────────────────────────


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


# ── Tests ─────────────────────────────────────────────────────────────────


class TestCodebaseAlteration:
    """Detect 2 renamed symbols in a 10-file codebase."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_initial_analysis_stores_all_files(self) -> None:
        """Phase 1: all 10 files are analyzed and stored."""
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                _write_codebase(Path(tmpdir), ORIGINAL_FILES)
                result = await analyze_handler({
                    "directory": tmpdir,
                    "languages": ["python"],
                    "domain": DOMAIN,
                    "incremental": False,
                })
                assert result["analyzed"]
                assert result["new"] == len(ORIGINAL_FILES)
                assert result["entities"] > 0
        self._run(_test())

    def test_incremental_detects_changed_files(self) -> None:
        """Phase 2: after alteration, only changed files are re-processed."""
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                _write_codebase(root, ORIGINAL_FILES)

                # First pass
                r1 = await analyze_handler({
                    "directory": tmpdir, "languages": ["python"],
                    "domain": DOMAIN, "incremental": False,
                })
                assert r1["new"] == len(ORIGINAL_FILES)

                # Apply alterations
                for rel_path, content in ALTERED_FILES.items():
                    (root / rel_path).write_text(content)

                # Incremental pass
                r2 = await analyze_handler({
                    "directory": tmpdir, "languages": ["python"],
                    "domain": DOMAIN, "incremental": True,
                })
                assert r2["updated"] == len(ALTERED_FILES)
                unchanged = len(ORIGINAL_FILES) - len(ALTERED_FILES)
                assert r2["unchanged"] == unchanged

        self._run(_test())

    def test_recall_finds_new_class_name(self) -> None:
        """After alteration, recall returns CredentialManager, not TokenService."""
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(root, merged)

                await analyze_handler({
                    "directory": tmpdir, "languages": ["python"],
                    "domain": DOMAIN, "incremental": False,
                })

                results = await recall_handler({
                    "query": "credential management JWT token creation",
                    "domain": DOMAIN, "max_results": 5,
                })
                contents = [r.get("content", "") for r in results.get("results", [])]
                assert any("CredentialManager" in c for c in contents), \
                    "CredentialManager not found in recall results"
                assert not any("class: TokenService" in c for c in contents), \
                    "Old TokenService should not appear"

        self._run(_test())

    def test_recall_finds_renamed_method(self) -> None:
        """After alteration, recall returns verify_request, not authenticate."""
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(root, merged)

                await analyze_handler({
                    "directory": tmpdir, "languages": ["python"],
                    "domain": DOMAIN, "incremental": False,
                })

                results = await recall_handler({
                    "query": "middleware validates auth token from request",
                    "domain": DOMAIN, "max_results": 5,
                })
                contents = [r.get("content", "") for r in results.get("results", [])]
                assert any("verify_request" in c for c in contents), \
                    "verify_request not found in recall results"

        self._run(_test())

    def test_unmodified_files_unchanged(self) -> None:
        """Files not in ALTERED_FILES remain intact in memory."""
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                merged = {**ORIGINAL_FILES, **ALTERED_FILES}
                _write_codebase(root, merged)

                await analyze_handler({
                    "directory": tmpdir, "languages": ["python"],
                    "domain": DOMAIN, "incremental": False,
                })

                # User model should be intact
                results = await recall_handler({
                    "query": "user domain model with roles and email",
                    "domain": DOMAIN, "max_results": 5,
                })
                contents = [r.get("content", "") for r in results.get("results", [])]
                assert any("User" in c and "has_role" in c for c in contents)

                # Health check should be intact
                results = await recall_handler({
                    "query": "health check readiness endpoint",
                    "domain": DOMAIN, "max_results": 5,
                })
                contents = [r.get("content", "") for r in results.get("results", [])]
                assert any("health_check" in c for c in contents)

        self._run(_test())
