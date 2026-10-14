"""Persisted storage-backend selection for the Claude Code plugin path.

The plugin installer (``scripts/install-plugin.sh``) records the backend
it provisioned in a small JSON marker::

    ~/.claude/methodology/backend.json
    {"backend": "sqlite"}        # zero-config default install
    {"backend": "postgresql"}    # --postgres opt-in, or a protected
                                 # pre-existing PostgreSQL install

1. ``CORTEX_MEMORY_STORE_BACKEND`` already set  -> untouched
2. ``CORTEX_BACKEND`` = postgres|postgresql|sqlite -> mapped to (1)
3. ``DATABASE_URL`` / ``CORTEX_MEMORY_DATABASE_URL`` non-empty ->
   untouched (operator configured PostgreSQL; the engine's strict
   no-silent-fallback path in memory_store applies)
4. marker file backend -> applied
5. nothing -> ``default`` when the caller names one (the Claude Code plugin
   launcher names ``sqlite``: an empty ``database_url`` means the local
   SQLite store, and nothing dials a PostgreSQL the user never configured),
   else untouched (engine default: ``auto``)

source: ADR-0505
source: ADR-1104"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Mapping, MutableMapping

from mcp_server.infrastructure.config import METHODOLOGY_DIR

logger = logging.getLogger(__name__)

BACKEND_MARKER_PATH = METHODOLOGY_DIR / "backend.json"

# The two backends the installer can persist — mirrors the explicit
# (non-"auto") values of MemorySettings.STORE_BACKEND.
VALID_BACKENDS = frozenset({"sqlite", "postgresql"})

# CORTEX_BACKEND accepts the colloquial "postgres" too; the engine env
# var only understands "postgresql".
_BACKEND_ALIASES = {
    "sqlite": "sqlite",
    "postgres": "postgresql",
    "postgresql": "postgresql",
}


class BackendMarkerError(ValueError):
    """The marker exists but cannot say which backend: never guess one."""


def read_backend_marker(path: Path | None = None) -> dict | None:
    """Read the installer's backend marker; ``None`` only when it is absent.

    An unreadable or invalid marker raises ``BackendMarkerError`` naming the
    file: treating it as absent would hand a PostgreSQL user the SQLite
    default (ADR-1104).

    source: ADR-0505
    source: ADR-1104"""
    marker_path = path or BACKEND_MARKER_PATH
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackendMarkerError(
            f"backend marker {marker_path} is unreadable ({exc}); fix or delete it"
        ) from exc
    if not isinstance(data, dict) or data.get("backend") not in VALID_BACKENDS:
        raise BackendMarkerError(
            f"backend marker {marker_path} names no backend of {sorted(VALID_BACKENDS)}"
            f" ({data!r}); fix or delete it"
        )
    return data


def write_backend_marker(
    backend: str, written_by: str, path: Path | None = None
) -> Path:
    """Persist ``backend`` as the marker, atomically (no reader sees half a file).

    Pre:  ``backend`` is one of ``VALID_BACKENDS``.
    source: ADR-1104"""
    if backend not in VALID_BACKENDS:
        raise BackendMarkerError(f"refusing to persist unknown backend {backend!r}")
    marker_path = path or BACKEND_MARKER_PATH
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"backend": backend, "written_by": written_by}, indent=2)
    fd, tmp = tempfile.mkstemp(dir=marker_path.parent, prefix=marker_path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.replace(tmp, marker_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return marker_path


def resolve_backend_env(
    environ: Mapping[str, str], marker: dict | None, default: str = ""
) -> dict[str, str]:
    """Pure resolution: env additions implementing the module precedence.

    source: ADR-0505
    source: ADR-1104"""
    if environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip():
        return {}
    requested = _BACKEND_ALIASES.get(environ.get("CORTEX_BACKEND", "").strip().lower())
    if requested:
        return {"CORTEX_MEMORY_STORE_BACKEND": requested}
    if environ.get("DATABASE_URL", "").strip():
        return {}
    if environ.get("CORTEX_MEMORY_DATABASE_URL", "").strip():
        return {}
    if marker is not None:
        return {"CORTEX_MEMORY_STORE_BACKEND": marker["backend"]}
    if default:
        return {"CORTEX_MEMORY_STORE_BACKEND": default}
    return {}


def environment_decides(environ: Mapping[str, str]) -> bool:
    """Steps 1-3 of the precedence: an explicit setting, so no marker is read.

    source: ADR-1104 (an invalid marker must not stop a user it never governs)"""
    return bool(
        environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip()
        or _BACKEND_ALIASES.get(environ.get("CORTEX_BACKEND", "").strip().lower())
        or environ.get("DATABASE_URL", "").strip()
        or environ.get("CORTEX_MEMORY_DATABASE_URL", "").strip()
    )


def _marker_unless_decided(
    environ: Mapping[str, str], marker_path: Path | None
) -> dict | None:
    return None if environment_decides(environ) else read_backend_marker(marker_path)


def apply_backend_resolution(
    environ: MutableMapping[str, str],
    marker_path: Path | None = None,
    default: str = "",
) -> dict[str, str]:
    """Apply the resolved backend to ``environ`` in place.

    Also normalizes a *blank* ``DATABASE_URL`` to absent first: the
    plugin manifest interpolates ``${user_config.database_url}`` whose
    default is now empty, and an empty string must mean "not
    configured" everywhere downstream (psycopg would otherwise read
    libpq defaults from a blank DSN, and
    ``memory_store._database_url_is_explicit`` tests key presence).

    Pre:  ``environ`` is mutable (normally ``os.environ``); ``default`` is
          ``""`` or one of ``VALID_BACKENDS``.
    Post: returns the additions applied (possibly ``{}``).
    """
    url = environ.get("DATABASE_URL")
    if url is not None and not url.strip():
        del environ["DATABASE_URL"]
    additions = resolve_backend_env(
        environ, _marker_unless_decided(environ, marker_path), default
    )
    environ.update(additions)
    return additions


def effective_backend(
    environ: Mapping[str, str], marker_path: Path | None = None
) -> str:
    """The backend the precedence chain selects, without mutating env.

    Post: ``"sqlite"`` / ``"postgresql"`` when the chain resolves one;
          ``""`` when nothing is configured (engine default ``auto``
          applies) or when the operator configured a database URL
          (case 3 — the engine, not this module, owns that path).
    """
    explicit = environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip().lower()
    if explicit in VALID_BACKENDS:
        return explicit
    if explicit:  # "auto" or anything else the engine will interpret
        return ""
    additions = resolve_backend_env(
        environ, _marker_unless_decided(environ, marker_path)
    )
    return additions.get("CORTEX_MEMORY_STORE_BACKEND", "")
