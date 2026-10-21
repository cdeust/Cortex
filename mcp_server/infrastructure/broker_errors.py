"""Errors a broker client raises, and how a remote failure crosses back.

A failure inside the broker travels as its type name and message. A built-in
exception type (``ValueError``, ``KeyError``, ``LookupError``...) is raised
again as that type, so callers that catch it keep working; a schema refusal
is raised as its own ``SchemaError`` subclass, with the broker's message, so
"upgrade Cortex" and "run the migration step" reach the user unchanged
(ADR-1112 decision 7: an explicit error, never a silent fallback). Anything
else (a driver error, an application error) is a ``BrokerRemoteError``
carrying the remote type name.

source: ADR-1112 decisions 6 and 7
"""

from __future__ import annotations

import builtins

from mcp_server.infrastructure import schema_versions


class BrokerUnavailableError(ConnectionError):
    """The broker could not be reached or the channel broke mid-request; a
    write may or may not have happened and is never replayed."""


class BrokerLaunchError(RuntimeError):
    """No broker answered and none could be started; never a direct connection."""


class BrokerRefusedError(RuntimeError):
    """The broker could not open the store and refused the connection."""

    def __init__(self, type_name: str, message: str) -> None:
        super().__init__(
            f"store broker could not open the store: {type_name}: {message}"
        )
        self.type_name = type_name


class BrokerRemoteError(RuntimeError):
    """The broker ran the request and it failed there."""

    def __init__(self, type_name: str, message: str) -> None:
        super().__init__(f"{type_name}: {message}")
        self.type_name = type_name


def _schema_error(type_name: str) -> type[schema_versions.SchemaError] | None:
    candidate = getattr(schema_versions, type_name, None)
    if isinstance(candidate, type) and issubclass(
        candidate, schema_versions.SchemaError
    ):
        return candidate
    return None


def remote_error(type_name: str, message: str) -> Exception:
    """The exception to raise in the client for a failure in the broker."""
    schema = _schema_error(type_name)
    if schema is not None:
        return schema(message)
    builtin = getattr(builtins, type_name, None)
    if (
        isinstance(builtin, type)
        and issubclass(builtin, Exception)
        and not issubclass(
            builtin, (OSError, UnicodeError)
        )  # constructor shapes differ
    ):
        try:
            return builtin(message)
        except TypeError:
            pass
    return BrokerRemoteError(type_name, message)


def refusal_error(type_name: str, message: str) -> Exception:
    """The exception for a broker that refused at the handshake."""
    schema = _schema_error(type_name)
    if schema is not None:
        return schema(message)
    return BrokerRefusedError(type_name, message)
