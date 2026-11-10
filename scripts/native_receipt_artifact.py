#!/usr/bin/env python3
"""Print the ``artifact`` object of a native receipt for the running Cortex.

A ``cortex-native-receipt/1`` receipt (``scripts/native_receipt.py``) binds each
check to the artifact that ran it. Until this script, ``cortex doctor`` stated
that identity only as free text, so a receipt author had to copy the version,
revision and digest by hand (issue #730, remaining slice 2). This script reads
the doctor's identity as data (``mcp_server.doctor_artifact.identify``) and
prints the receipt fields, checked against the receipt schema before output.

It refuses, and prints why, when the identity cannot be stated: git could not
answer, an installed wheel has no RECORD or its files differ from that RECORD,
no installed distribution names the version, or a checkout has no commit to
bind to. A refusal is never a guessed field. An altered wheel is refused because
its ``members_digest`` is computed over its RECORD hashes, not over the files
that run: two differently altered installs would carry the same digest, so
checks run on either could be merged into one receipt (Codex review on #957).
The doctor fails the same install with a reinstall fix.

Run it with the interpreter the host runs, so it imports the same ``mcp_server``.

source: issue #730 (remaining slice 2: a receipt producer that reads the
artifact identity directly); issue #729 (artifact identity)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# source: check_craftsmanship.py (sibling scripts import by their directory).
# The repository root is not added: ``mcp_server`` must be the one the running
# interpreter imports, which is the artifact this script describes.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import native_receipt  # noqa: E402

from mcp_server.doctor_artifact import Identity, identify  # noqa: E402


class UnstatedIdentityError(ValueError):
    """The running artifact has no identity a receipt can carry."""


def receipt_artifact(found: Identity) -> dict:
    """The receipt ``artifact`` object of ``found``.

    Raises ``UnstatedIdentityError`` when ``found`` cannot be stated."""
    if found.unknown:
        raise UnstatedIdentityError(found.unknown)
    if found.altered:
        what = "the installed wheel differs from its RECORD"
        if found.kind != "wheel":
            what = "cached bytecode runs other code than the source tree"
        raise UnstatedIdentityError(
            f"{what} ({found.altered[0]} first): its digest does not name the "
            f"running files; {found.fix}"
        )
    if found.version is None:
        raise UnstatedIdentityError("no installed hypermnesia-mcp names the version")
    if found.in_git and found.revision is None:
        raise UnstatedIdentityError("the checkout has no commit to name as revision")
    artifact = {
        "kind": found.kind,
        "version": found.version,
        "revision": found.revision,
        "modified": found.modified,
        "members_digest": found.digest,
    }
    errors = native_receipt.artifact_errors(artifact)
    if errors:
        raise UnstatedIdentityError("; ".join(errors))
    return artifact


def main() -> int:
    try:
        artifact = receipt_artifact(identify())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cannot state the running artifact: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
