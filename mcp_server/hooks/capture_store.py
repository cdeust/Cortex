"""The one store path for an admitted capture payload, wherever it runs.

The resident worker awaits ``store`` (through ``remember``) on its persistent
loop. A platform the worker does not support (``capture_peer.is_supported()``
is false, e.g. Windows: no ``AF_UNIX``, no ``fcntl``, no ``geteuid``) awaits the
same function from the spool drainer (``capture_drain``). Same validation, same
handler, same payload: only the hosting process differs.
"""

from __future__ import annotations

import logging

from mcp_server.hooks.capture_worker_policy import validate_payload

logger = logging.getLogger(__name__)


async def store(payload: dict[str, object]) -> dict[str, object]:
    """precondition: payload is the hook's unchanged ``remember`` payload.
    postcondition: payload was validated and handed to the remember handler;
    its result is returned. A refused payload or missing dependency raises."""
    validate_payload(payload)
    from mcp_server.hooks.post_tool_capture import _load_remember  # noqa: PLC0415 — reuse the existing composition loader only when a store is needed

    try:
        _, handler = _load_remember()
    except SystemExit as exc:
        raise RuntimeError(
            "capture dependencies unavailable; verify installation"
        ) from exc
    result = await handler(payload)
    if result.get("stored"):
        logger.info(
            "captured %s memory_id=%s", payload["origin_tool"], result.get("memory_id")
        )
    else:
        logger.info(
            "gated %s: %s",
            payload["origin_tool"],
            result.get("reason", "below_threshold"),
        )
    return result


async def remember(payload: dict[str, object]) -> None:
    """The resident worker's callback: store and discard the handler result."""
    await store(payload)
