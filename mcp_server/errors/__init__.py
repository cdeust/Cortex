"""Typed error hierarchy for the methodology-agent system.

Typed errors enable the router to distinguish user errors (validation) from
system errors (storage) and return appropriate MCP error codes.
"""

from __future__ import annotations


class MethodologyError(Exception):
    """Base error for all methodology-agent errors."""

    def __init__(
        self,
        message: str,
        code: int = -32000,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class ValidationError(MethodologyError):
    """Invalid input (user-correctable)."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code=-32602, details=details)


class StorageError(MethodologyError):
    """Filesystem/persistence failures."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code=-32001, details=details)


class AnalysisError(MethodologyError):
    """Core algorithm failures."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code=-32002, details=details)


class McpConnectionError(MethodologyError):
    """MCP client connection failures."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, code=-32003, details=details)
