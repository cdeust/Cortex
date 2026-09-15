#!/usr/bin/env python3
"""Owners of each top-level deps-dir entry, read from RECORD — stdlib only.

Like its siblings, this module runs before the plugin's own
dependencies exist on ``sys.path`` and may import only the Python
standard library.

An entry's name does not identify its distribution: ``yaml`` is PyYAML's,
``google`` is every distribution shipping a ``google.*`` namespace, ``bin``
is every distribution with a console script. The ``RECORD`` of each
``*.dist-info`` lists every file that distribution installed.

source: https://packaging.python.org/en/latest/specifications/recording-installed-packages/#the-record-file
source: ADR-1064"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_deps_fs as _fs  # noqa: E402

# `pip --target` records paths relative to <home>/lib/python, then moves every
# child of <home> into the target: `../../bin/tqdm` lands in the `bin` entry.
# source: pip 26.0.1 commands/install.py `_handle_target_dir`; sysconfig
#   posix_home purelib = {base}/lib/python; measured 2026-09-15 on the 4.22.0
#   deps (29 `../../bin`, 1 `../../include`, 1 `../../share` rows); ADR-1064
_TARGET_HOME_PREFIX = "../../"


def record_top_level(path: str) -> str | None:
    """The top-level target entry a ``RECORD`` path lands in.

    Precondition: ``path`` is the first column of a ``RECORD`` row written
    by a ``--target`` install. Postcondition: the entry name, or None when
    the path lands outside the target (absolute, or climbing past it).
    """
    if path.startswith(_TARGET_HOME_PREFIX):
        path = path[len(_TARGET_HOME_PREFIX) :]
    head = path.split("/", 1)[0]
    if not head or head.startswith(".."):
        return None
    return head


def _record_paths(dist_info_path: str) -> list[str]:
    """The installed paths a ``*.dist-info``'s ``RECORD`` lists.

    Postcondition: an empty list when ``RECORD`` is missing, unreadable or
    not CSV, so every entry that distribution installed stays unowned.
    """
    try:
        with open(
            os.path.join(dist_info_path, "RECORD"), encoding="utf-8", newline=""
        ) as fh:
            return [row[0] for row in csv.reader(fh) if row]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def entry_owners(dir_path: str) -> dict[str, frozenset[str]]:
    """Map each top-level entry to the dist keys whose ``RECORD`` lists it.

    Precondition: none; a missing or unreadable directory yields an empty map.
    Postcondition: read-only. Keys are ``normalize_dist_key`` forms, the same
    as ``dist_info_versions``. An entry no readable ``RECORD`` lists is
    absent, so no caller can treat it as satisfied.

    source: ADR-1064"""
    try:
        children = os.listdir(dir_path)
    except OSError:
        return {}
    owners: dict[str, set[str]] = {}
    for name in children:
        if not name.endswith(".dist-info"):
            continue
        dist_key = _fs.entry_dist_key(name)
        for path in _record_paths(os.path.join(dir_path, name)):
            entry = record_top_level(path)
            if entry is not None:
                owners.setdefault(entry, set()).add(dist_key)
    return {entry: frozenset(keys) for entry, keys in owners.items()}
