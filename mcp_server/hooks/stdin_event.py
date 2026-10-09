"""The one place a hook reads its event from stdin.

Claude Code and Codex write the hook event JSON as UTF-8 bytes. A text-mode
``sys.stdin`` decodes with the locale encoding instead, which on Windows is
the ANSI code page (cp1252): ``é`` arrives as ``Ã©`` and bytes with no
cp1252 mapping become lone surrogates that later fail on write (issue #664).
Python's ``-X utf8`` / ``PYTHONUTF8`` would fix this only for a process the
host's environment reaches; a hook the host starts with the system Python
never sees it. Decoding the bytes explicitly depends on neither the locale
nor the environment.

source: https://docs.python.org/3/library/sys.html#sys.stdin ("the encoding
is the locale encoding" for the standard streams) and
https://docs.python.org/3/using/windows.html#python-utf-8-mode; issue #664.
"""

from __future__ import annotations

import io
import sys


class HookStdinDecodeError(Exception):
    """The hook event bytes on stdin are not valid UTF-8."""


def read_event_text() -> str:
    """Read all of stdin as strict UTF-8 text.

    Precondition: ``sys.stdin`` is a text stream backed by a binary
    ``buffer`` (the real process stdin, or ``install_event_stdin``'s).
    Postcondition: returns the exact text the host wrote; raises
    ``HookStdinDecodeError`` (never substituting characters) when the bytes
    are not valid UTF-8, so the hook fails loudly instead of storing damage.
    """
    raw = sys.stdin.buffer.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HookStdinDecodeError(
            f"hook event on stdin is not valid UTF-8: {exc}"
        ) from exc


def install_event_stdin(text: str) -> None:
    """Replace ``sys.stdin`` with a UTF-8 stream carrying ``text``.

    Postcondition: ``read_event_text()`` returns ``text`` unchanged, whatever
    the locale. Used where one reader already decoded the event and a hook
    run in-process must read it again.
    """
    sys.stdin = io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8")
