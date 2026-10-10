"""The one place a hook process decides how it writes stdout and stderr.

Claude Code and Codex read hook stdout as UTF-8 bytes (the same contract
``stdin_event`` applies to the input side, issue #664). A text-mode
``sys.stdout`` encodes with the system encoding instead: per CPython's
``Doc/library/sys.rst`` (``sys.stdout``), on Windows a pipe uses the system
locale encoding (the ANSI code page, cp1252 in Western locales), so the
first character with no cp1252 mapping, such as the ``U+27E6`` that opens
every injection receipt, raised ``UnicodeEncodeError`` and discarded the
whole injection (issues #96 and #688).

Why not Python's UTF-8 mode (``-X utf8`` / ``PYTHONUTF8``): the Codex
``hypermnesia-mcp-hook`` console script and a bare ``python -m`` run cannot
carry it, and setting it in CI would hide the defect it papers over. The
explicit reconfiguration below covers every entry point.

Every hook ``__main__`` block and every hook console entry point calls
``use_utf8_output`` before it writes. A guard test
(``tests_py/hooks/test_output_streams_guard.py``) fails any hook entry point
that prints without calling it.

source: ADR-1098 (supersedes the output half of ADR-0742); CPython
Doc/library/sys.rst (``sys.stdout``, ``sys.stderr``) and Doc/library/io.rst
(``TextIOWrapper.reconfigure``); issues #96, #688.
"""

from __future__ import annotations

import io
import sys


class HookOutputStreamError(Exception):
    """A standard stream cannot be set to UTF-8."""


def _reconfigure(stream: object, name: str, errors: str) -> None:
    if not isinstance(stream, io.TextIOWrapper):
        raise HookOutputStreamError(
            f"sys.{name} is {type(stream).__name__}, not a reconfigurable "
            "text stream: cannot guarantee UTF-8 hook output"
        )
    stream.reconfigure(encoding="utf-8", errors=errors)


def use_utf8_output() -> None:
    """Make ``sys.stdout`` and ``sys.stderr`` write UTF-8.

    Precondition: both are ``io.TextIOWrapper`` streams (the real process
    streams, a pipe or a file).
    Postcondition: ``sys.stdout`` encodes UTF-8 with ``errors="strict"``, so
    a lone surrogate fails loudly instead of being replaced; ``sys.stderr``
    encodes UTF-8 with ``errors="backslashreplace"``, which is the error
    handler CPython gives stderr by default (``Doc/library/sys.rst``), kept
    so a diagnostic about a bad character can never raise in turn. Raises
    ``HookOutputStreamError`` when a stream cannot be reconfigured; calling
    it again is harmless.
    """
    _reconfigure(sys.stdout, "stdout", "strict")
    _reconfigure(sys.stderr, "stderr", "backslashreplace")
