#!/usr/bin/env python3
"""Generate the hash-pinned requirements files every pip install reads.

The table of files and their consumers is scripts/pip_constraint_sets.py.

Usage:
    python3 scripts/generate_pip_constraints.py           # rewrite if changed
    python3 scripts/generate_pip_constraints.py --check   # exit 1 if stale

source: ADR-0737"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pip_constraint_sets import (  # noqa: E402
    SETS,
    ConstraintSet,
    constraint_command,
    constraint_header_lines,
    constraint_path,
)

# source: ADR-0737
PYPI = "https://pypi.org/simple"
_LOCAL_VERSION = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;]*\+[^\s;]+)")
_INDEX_URL = re.compile(r"\[\[tool\.uv\.index\]\][^\[]*?url\s*=\s*\"([^\"]+)\"", re.S)


class ExportError(RuntimeError):
    """uv could not produce a resolved, hashed, installable export."""


def declared_index_urls() -> frozenset[str]:
    """Every url a `[[tool.uv.index]]` entry in pyproject.toml declares.

    source: ADR-0737"""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return frozenset(_INDEX_URL.findall(text))


def lock_registries() -> dict[tuple[str, str], str]:
    """(package, version) -> the registry uv.lock resolved it from."""
    registries: dict[tuple[str, str], str] = {}
    name = version = None
    for line in (REPO_ROOT / "uv.lock").read_text(encoding="utf-8").splitlines():
        # The quote in each prefix matters: uv.lock opens with an unquoted
        # `version = 1` (the lock format's own version), which is not a
        # package's version and must not be read as one.
        if line.startswith("[[package]]"):
            name = version = None
        elif line.startswith('name = "'):
            name = line.split('"')[1]
        elif line.startswith('version = "'):
            version = line.split('"')[1]
        elif line.startswith("source = ") and "registry" in line and name and version:
            registries[(name, version)] = line.split('"')[1]
    return registries


def serving_registries(body: str) -> list[str]:
    """The indexes this export's local-version pins cannot be installed without.

        uv resolves a `+cpu` wheel from a `[[tool.uv.index]]` but emits no index
        directive into the export, and pip defaults to PyPI alone — where that
        version does not exist. Without this, `pip install -r` fails outright
        with `No matching distribution found for torch==2.13.0+cpu`.

    source: ADR-0737"""
    registries = lock_registries()
    declared = declared_index_urls()
    needed: list[str] = []
    for line in body.splitlines():
        match = _LOCAL_VERSION.match(line)
        if match is None:
            continue
        pin = (match.group(1), match.group(2))
        registry = registries.get(pin)
        if registry is None:
            raise ExportError(f"{pin[0]}=={pin[1]} is in no uv.lock registry")
        if registry == PYPI or registry in needed:
            continue
        if registry not in declared:
            raise ExportError(
                f"{pin[0]}=={pin[1]} resolves from {registry}, which"
                " pyproject.toml declares no [[tool.uv.index]] for"
            )
        needed.append(registry)
    return needed


def _index_directive(registries: list[str]) -> str:
    """The `--extra-index-url` block, with the reason it is safe here."""
    if not registries:
        return ""
    reason = (
        "# An extra index widens where pip may look, which is normally how\n"
        "# dependency-confusion attacks land. It is safe HERE and only here\n"
        "# because every requirement in this file carries a hash and the file\n"
        "# is installed with --require-hashes: an artifact served by either\n"
        "# index that is not the locked one fails the hash check before it is\n"
        "# unpacked. Do not copy this directive into an unhashed file.\n"
    )
    urls = "\n".join(f"--extra-index-url {url}" for url in registries)
    return reason + urls + "\n\n"


def export(constraint_set: ConstraintSet) -> str:
    """Run uv and return its raw stdout. The ONLY part that touches the world.

    source: ADR-0737"""
    if shutil.which("uv") is None:
        raise ExportError(
            "uv is not installed — it is the only reader of uv.lock."
            " See https://docs.astral.sh/uv/getting-started/installation/"
        )
    command = constraint_command(constraint_set)
    try:
        done = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
            command, cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise ExportError(f"could not run uv: {error}") from error
    if done.returncode != 0:
        raise ExportError(
            f"`{' '.join(command)}` failed with exit"
            f" {done.returncode}:\n{done.stderr.strip()}"
        )
    return done.stdout


def compose(constraint_set: ConstraintSet, body: str) -> str:
    """Judge an export and assemble the file. Pure: no uv, no I/O, no network.

    Every rule about what makes a requirements file usable lives here, which
    is what makes those rules testable from a string literal.
    """
    _reject_unusable(constraint_set, body)
    header = "\n".join(constraint_header_lines(constraint_set)) + "\n"
    return header + _index_directive(serving_registries(body)) + body


def render(constraint_set: ConstraintSet) -> str:
    """Export from the lock; the result must be fully hashed and installable."""
    return compose(constraint_set, export(constraint_set))


def _reject_unusable(constraint_set: ConstraintSet, body: str) -> None:
    """Fail here, where the cause is visible, not in CI minutes later.

    A requirement that reached `--require-hashes` carrying no hash aborts
    the whole install. An empty export is equally a failure: it would
    install nothing and every check downstream would still pass.
    """
    requirements = [
        line
        for line in body.splitlines()
        if line and not line.startswith((" ", "#", "-"))
    ]
    if not requirements:
        raise ExportError(
            f"{constraint_path(constraint_set)}: export resolved to zero requirements"
        )
    unhashed = [line for line in requirements if not line.rstrip().endswith("\\")]
    if unhashed:
        path = constraint_path(constraint_set)
        raise ExportError(
            f"{path}: {len(unhashed)} requirement(s) carry no hash,"
            f" first is {unhashed[0].strip()!r}"
        )


def write(constraint_set: ConstraintSet) -> bool:
    """Write the file; True when it changed."""
    target = REPO_ROOT / constraint_path(constraint_set)
    rendered = render(constraint_set)
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return True


def stale(constraint_set: ConstraintSet) -> str | None:
    """Why this file is out of date, or None when it matches the lock."""
    target = REPO_ROOT / constraint_path(constraint_set)
    if not target.exists():
        return (
            f"{constraint_path(constraint_set)}: missing"
            " — run scripts/generate_pip_constraints.py"
        )
    if target.read_text(encoding="utf-8") != render(constraint_set):
        return (
            f"{constraint_path(constraint_set)}: disagrees with uv.lock"
            " — run scripts/generate_pip_constraints.py"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any file is missing or disagrees with the lock",
    )
    args = parser.parse_args(argv)

    # source: ADR-0737
    try:
        if args.check:
            failures = [reason for s in SETS if (reason := stale(s))]
            if failures:
                print("Requirements files disagree with uv.lock:", file=sys.stderr)
                for failure in failures:
                    print(f"  {failure}", file=sys.stderr)
                return 1
            print(f"requirements OK ({len(SETS)} checked)")
            return 0

        changed = [constraint_path(s) for s in SETS if write(s)]
        for path in changed:
            print(f"wrote {path}")
        print(f"{len(changed)} of {len(SETS)} file(s) changed")
        return 0
    except ExportError as error:
        print(f"constraint generation could not run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
