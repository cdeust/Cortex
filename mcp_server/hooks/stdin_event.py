"""The one place a hook reads its event from stdin.

Claude Code and Codex write the hook event JSON as UTF-8 bytes. A text-mode
``sys.stdin`` decodes with the system encoding instead: per CPython's
``Doc/library/sys.rst``, on Windows pipes and disk files use the system
locale encoding (the ANSI code page, cp1252 in Western locales), and
``sys.stdin.buffer`` is the documented route to the raw bytes. So ``é``
arrived as ``Ã©``, and bytes with no cp1252 mapping became lone surrogates
that later fail on write (issue #664).

Why not Python's UTF-8 mode (``-X utf8`` / ``PYTHONUTF8``): it does override
the standard-stream encoding, and the Claude hook commands in
``.claude-plugin/plugin.json`` are project-controlled, so it could be added
there; it cannot be added to the Codex ``hypermnesia-mcp-hook`` console
script. More decisively, UTF-8 mode keeps ``surrogateescape`` on stdin, so
undecodable bytes would still become lone surrogates silently. The explicit
strict decode below covers both entry points and fails loudly.

source: CPython Doc/library/sys.rst (``sys.stdin``) and
Doc/using/windows.rst (UTF-8 mode); issue #664.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable


class HookStdinDecodeError(Exception):
    """The hook event bytes on stdin are not valid UTF-8."""


def use_utf8_stdout() -> None:
    """Make ``sys.stdout`` write UTF-8, whatever the locale or code page.

    Hooks print injections that hold non-ASCII text (``⟦``, accented memory
    content). On Windows a piped text-mode ``sys.stdout`` encodes with the
    ANSI code page (cp1252 in Western locales), so ``print`` raised
    ``UnicodeEncodeError`` (issue #688). The host reads hook output as UTF-8,
    the same as the event it writes on stdin.

    Postcondition: a reconfigurable text ``sys.stdout`` encodes as UTF-8
    (``errors`` unchanged); any other stream, such as pytest's capture, is
    left as it is.
    """
    stdout = sys.stdout
    encoding = getattr(stdout, "encoding", None) or ""
    if encoding.lower().replace("_", "-") in {"utf-8", "utf8"}:
        return
    reconfigure = getattr(stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def read_event_text(log: Callable[[str], None] | None = None) -> str:
    """Read all of stdin as strict UTF-8 text.

    Precondition: ``sys.stdin`` is a text stream backed by a binary
    ``buffer`` (the real process stdin, or ``install_event_stdin``'s);
    ``log``, when given, is the calling hook's own ``_log``. Every hook that
    prints to stdout reads its event here first, so this is also where
    ``use_utf8_stdout`` runs.
    Postcondition: returns the exact text the host wrote; raises
    ``HookStdinDecodeError`` (never substituting characters) when the bytes
    are not valid UTF-8, after passing the message to ``log`` the way hooks
    log a JSON parse failure, so the hook fails loudly and leaves a trail.
    """
    use_utf8_stdout()
    raw = sys.stdin.buffer.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        message = f"hook event on stdin is not valid UTF-8: {exc}"
        if log is not None:
            log(f"Failed to decode event: {message}")
        raise HookStdinDecodeError(message) from exc


def install_event_stdin(text: str) -> None:
    """Replace ``sys.stdin`` with a UTF-8 stream carrying ``text``.

    Postcondition: ``read_event_text()`` returns ``text`` unchanged, whatever
    the locale. Used where one reader already decoded the event and a hook
    run in-process must read it again.
    """
    sys.stdin = io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8")
