#!/usr/bin/env python3
"""Isolate the vendored ``deps/`` directory from user site-packages.

``scripts/launcher.py`` and ``scripts/setup.py`` both put ``deps/`` at the
front of ``sys.path``. Issue #621 showed that this is not isolation, and
that a plain ``sys.path`` entry leaks in two directions at once:

* ``sys.path.insert`` does not process a directory's ``.pth`` files; only
  ``site.addsitedir`` does. ``deps/pywin32.pth`` is the only route to
  ``pywintypes`` on Windows, so a ``deps/`` that is merely *on* the path
  ships a pywin32 nothing can import.
* the interpreter's user site-packages stays on ``sys.path`` behind
  ``deps/``, so every package ``deps/`` does not vendor keeps resolving
  from there. A user site-packages holding a coherent CUDA
  torch/torchvision/torchaudio set then pairs its ``torchvision`` with the
  CPU ``torch`` that ``deps/`` vendors, and importing the two together
  aborts the process with ``RuntimeError: operator torchvision::nms does
  not exist`` — which ``transformers`` re-raises as a misleading
  ``ModuleNotFoundError: Could not import module 'PreTrainedModel'``.

Both halves are needed, and in this order: cutting user site-packages
without ``addsitedir`` first removes the only importable pywin32, which is
how the reporter's second attempted workaround failed.

Stdlib only — this runs before any dependency is guaranteed installed.

source: issue #621"""

from __future__ import annotations

import os
import site
import sys


def user_site_dir() -> str | None:
    """The interpreter's user site-packages directory, or None.

    Precondition: none.
    Postcondition: returns whatever ``site.getusersitepackages()``
    resolves. Inside a virtualenv the value still resolves but is absent
    from ``sys.path`` (``site.ENABLE_USER_SITE`` is False there), so
    dropping it is a measured no-op for dev clones and CI.

    A launch must survive a ``sysconfig`` that cannot resolve the user
    base, so a raising ``getusersitepackages()`` yields None instead of
    propagating — but never silently: returning None leaves user
    site-packages on ``sys.path``, which is issue #621's symptom exactly,
    so the cause goes to stderr the way ``scripts/launcher.py`` reports a
    failed backend resolution.
    """
    try:
        return site.getusersitepackages()
    except Exception as exc:  # noqa: BLE001 — a launch must survive any sysconfig failure
        print(
            f"[cortex-launcher] user site-packages not resolved, deps/ is "
            f"not isolated from it: {exc}",
            file=sys.stderr,
        )
        return None


def _normalized(entry: str) -> str:
    """Absolute, case-normalized form used to compare two path strings."""
    return os.path.normcase(os.path.abspath(entry))


def without_user_site(path: list[str], user_site: str | None) -> list[str]:
    """``path`` with every entry inside ``user_site`` removed.

    Precondition: ``path`` is a list of ``sys.path`` entries.
    Postcondition: returns a new list in the same order, minus the entries
    whose absolute, case-normalized form is ``user_site``'s or sits under
    it. An empty or None ``user_site`` removes nothing.

    Normalizing matters on Windows, where the same directory reaches
    ``sys.path`` under a different case or separator than ``site`` reports
    it. Matching subdirectories matters because ``site`` processes user
    site-packages' own ``.pth`` files at interpreter start: a pywin32
    installed there has already appended ``<user-site>/win32`` and
    ``<user-site>/win32/lib``, and leaving those behind would keep exactly
    the packages this cut exists to displace.
    """
    if not user_site:
        return list(path)
    dropped = _normalized(user_site)
    prefix = dropped + os.sep
    return [
        entry
        for entry in path
        if not _normalized(entry).startswith(prefix) and _normalized(entry) != dropped
    ]


def isolate_deps(deps_dir: str) -> None:
    """Put ``deps_dir`` first on ``sys.path`` as a *site* directory, then
    cut user site-packages.

    Precondition: none. ``deps_dir`` need not exist and need not already
    be on ``sys.path``.
    Postcondition: ``deps_dir`` is on ``sys.path`` exactly once, at index
    0 unless a caller had already placed it elsewhere; its ``.pth`` files
    have been processed, so the directories they name (pywin32's
    ``win32``, ``win32/lib``, ``pythonwin``) are importable; and no
    ``sys.path`` entry points at the user site-packages directory any
    more. A ``.pth`` line that raises is reported by ``site`` on stderr
    rather than propagating.

    The insert belongs here rather than at each call site: the two
    operations are only correct in this order (``site.addsitedir``
    appends a directory ``sys.path`` does not already carry, which would
    put ``deps/`` *behind* system site-packages), and a contract kept by
    prose at each call site is one a third call site can drop.
    """
    if deps_dir not in sys.path:
        sys.path.insert(0, deps_dir)
    site.addsitedir(deps_dir)
    sys.path[:] = without_user_site(sys.path, user_site_dir())
