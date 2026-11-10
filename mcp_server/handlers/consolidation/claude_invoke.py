"""``claude -p`` subprocess invocation for the headless authoring worker.

source: ADR-0350"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .claude_cli import _build_argv, _subprocess_env

logger = logging.getLogger(__name__)


async def _spawn_claude_process(
    argv: list[str], cwd: str | None, child_env: dict[str, str]
) -> Any:
    """Start the claude subprocess; return None (logged) on spawn failure."""
    try:
        return await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=child_env,
        )
    except FileNotFoundError:
        logger.warning("headless-authoring: claude binary not found on PATH")
        return None
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("headless-authoring: failed to start claude subprocess: %s", exc)
        return None


async def _communicate_with_timeout(
    proc: Any, prompt: str, call_timeout: float
) -> tuple[bytes, bytes] | None:
    """Send the prompt and await the response, killing the process on
    timeout/failure/cancellation. Returns None (logged) on no response.
    """
    try:
        return await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=call_timeout
        )
    except asyncio.TimeoutError:
        logger.warning(
            "headless-authoring: claude -p timed out after %.0fs", call_timeout
        )
        return None
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("headless-authoring: claude -p communicate failed: %s", exc)
        return None
    finally:
        # CancelledError is a BaseException — it escapes the except clauses
        # above. Without this finally, a cancelled drain leaves a zombie
        # subprocess. Covers the timeout path too (returncode is None after
        # wait_for cancels communicate), so the kill lives in one place.
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


def _reported_cost(raw: Any) -> float | None:
    """The CLI's ``total_cost_usd`` as a float, or None when it reported none.

    A reported ``0.0`` stays ``0.0``; an absent or null field is unknown,
    never free (#733: an unknown cost must not read as a free call).
    Raises ValueError on a value that is not a number."""
    if raw is None:
        return None
    return float(raw)


def _parse_invoke_response(
    returncode: int, stdout_bytes: bytes, stderr_bytes: bytes, _root: Any
) -> Any:
    """Decode the subprocess output and parse ``--output-format json``.

    source: ADR-0350"""
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if returncode != 0:
        logger.warning(
            "headless-authoring: claude -p exit %d stderr=%r", returncode, stderr[:300]
        )
        return _root.InvokeResult(text=None, cost_usd=None)

    stdout = stdout.strip()
    if not stdout:
        return _root.InvokeResult(text=None, cost_usd=None)

    cost_usd: float | None
    try:
        data = json.loads(stdout)
        text: str | None = data.get("result") or None
        cost_usd = _reported_cost(data.get("total_cost_usd"))
    except (json.JSONDecodeError, ValueError):
        # source: ADR-0350
        logger.debug(
            "headless-authoring: JSON parse failed (returncode=0); "
            "treating raw stdout as text (cost unknown)"
        )
        text = stdout or None
        cost_usd = None

    return _root.InvokeResult(text=text, cost_usd=cost_usd)


async def _claude_invoke(
    prompt: str,
    *,
    cwd: str | None = None,
    source_root: str | None = None,
    timeout: float | None = None,
) -> Any:
    """Run ``claude -p`` asynchronously and return an InvokeResult.

    source: ADR-0350"""
    # source: ADR-0350
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    argv = _build_argv(source_root)
    # Stays inline: _root's concrete type here is what lets pyright resolve
    # CLAUDE_CALL_TIMEOUT_SEC's real type (see cycle_orchestration.py's
    # commit note on the same narrowing behavior).
    call_timeout = (
        timeout if timeout is not None else float(_root.CLAUDE_CALL_TIMEOUT_SEC)
    )
    # Subscription by default + hook-neutralising child flag; API key passes
    # through only on CORTEX_HEADLESS_AUTH=api opt-in. See claude_cli.
    child_env = _subprocess_env()

    proc = await _spawn_claude_process(argv, cwd, child_env)
    if proc is None:
        # No child process started, so nothing was spent: a known 0.0.
        return _root.InvokeResult(text=None, cost_usd=0.0)

    comm = await _communicate_with_timeout(proc, prompt, call_timeout)
    if comm is None:
        # The child ran and may have spent before it was killed: unknown.
        return _root.InvokeResult(text=None, cost_usd=None)
    stdout_bytes, stderr_bytes = comm

    return _parse_invoke_response(proc.returncode, stdout_bytes, stderr_bytes, _root)
