"""``claude -p`` subprocess invocation for the headless authoring worker.

Split out of ``headless_authoring`` (Fowler: Move Function, issue #276)
to keep that module under the size limit. The public import surface
stays ``headless_authoring``, which re-exports ``_claude_invoke``.

Import-cycle note (issue #237 family): ``headless_authoring`` defines
``InvokeResult``/``CLAUDE_CALL_TIMEOUT_SEC`` and imports
``_claude_invoke`` back at its own module top, so a module-top ``from .
import headless_authoring as _root`` here would deadlock a fresh
interpreter importing ``claude_invoke`` first. ``_root`` is resolved
lazily inside ``_claude_invoke`` instead, exactly like the other four
siblings in this package.
"""

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


def _parse_invoke_response(
    returncode: int, stdout_bytes: bytes, stderr_bytes: bytes, _root: Any
) -> Any:
    """Decode the subprocess output and parse ``--output-format json``.

    Documented fields (source: code.claude.com/docs/en/headless):
    ``result`` (str, assistant text), ``total_cost_usd`` (float, client-side
    cost estimate). ``usage``/``is_error`` are NOT guaranteed — returncode only.
    """
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if returncode != 0:
        logger.warning(
            "headless-authoring: claude -p exit %d stderr=%r", returncode, stderr[:300]
        )
        return _root.InvokeResult(text=None, cost_usd=0.0)

    stdout = stdout.strip()
    if not stdout:
        return _root.InvokeResult(text=None, cost_usd=0.0)

    try:
        data = json.loads(stdout)
        text: str | None = data.get("result") or None
        cost_usd = float(data.get("total_cost_usd") or 0.0)
    except (json.JSONDecodeError, ValueError):
        # Defensive: returncode==0 but JSON parse failed. Can happen if
        # --output-format json isn't supported by an older claude CLI build.
        # Treat raw stdout as the text to degrade gracefully rather than
        # losing a successful response.
        logger.debug(
            "headless-authoring: JSON parse failed (returncode=0); "
            "treating raw stdout as text (cost unknown)"
        )
        text = stdout or None
        cost_usd = 0.0

    return _root.InvokeResult(text=text, cost_usd=cost_usd)


async def _claude_invoke(
    prompt: str,
    *,
    cwd: str | None = None,
    source_root: str | None = None,
    timeout: float | None = None,
) -> Any:
    """Run ``claude -p`` asynchronously and return an InvokeResult.

    Non-blocking on the event loop; on timeout the subprocess is killed
    and an empty InvokeResult is returned. The argv/child environment —
    including the audit-B-1 security argument and auth mode — are built
    by ``claude_cli``. The prompt is fed via STDIN, not a positional argv
    element: the variadic ``--add-dir`` would otherwise swallow a
    trailing prompt (see ``claude_cli._build_argv``).
    """
    # Deferred import (issue #237 family): see module docstring's note.
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
        return _root.InvokeResult(text=None, cost_usd=0.0)

    comm = await _communicate_with_timeout(proc, prompt, call_timeout)
    if comm is None:
        return _root.InvokeResult(text=None, cost_usd=0.0)
    stdout_bytes, stderr_bytes = comm

    return _parse_invoke_response(proc.returncode, stdout_bytes, stderr_bytes, _root)
