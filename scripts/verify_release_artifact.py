#!/usr/bin/env python3
"""Verify a downloaded release artifact against its published SHA-256.

Standard library only: this may run before the plugin's own dependencies exist
on ``sys.path`` (same constraint as the ``launcher_deps_*`` modules).

source: ADR-0789"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# source: ADR-0789
_SHA256_HEX_LEN = 64
# source: ADR-0789
_CHUNK_BYTES = 1024 * 1024


class ArtifactIntegrityError(Exception):
    """Raised when an artifact's actual SHA-256 does not match the expected one.

    Carries both digests so the caller's error message can name the exact
    mismatch (§F1: an integrity failure must be actionable, not just "bad").
    """

    def __init__(self, artifact: Path, expected: str, actual: str) -> None:
        self.artifact = artifact
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"integrity check FAILED for {artifact}: "
            f"expected sha256={expected}, computed sha256={actual}"
        )


def sha256_of(artifact: Path) -> str:
    """Return the lowercase hex SHA-256 of the file at ``artifact``.

    Precondition: ``artifact`` is a readable regular file.
    Postcondition: returns a 64-char lowercase hex string that is the SHA-256
    of the file's exact bytes; the file is read in bounded chunks.
    """
    digest = hashlib.sha256()
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_expected(expected: str) -> str:
    """Return the bare hex digest from a raw or ``sha256sum``-formatted value.

    Precondition: ``expected`` contains a 64-char hex digest, optionally
    followed by whitespace and a filename (the ``sha256sum`` / ``shasum -a 256``
    line format ``<hex>  <name>``).
    Postcondition: returns the lowercase 64-char hex digest.
    Raises ``ValueError`` if no valid digest is present — a malformed checksum
    file must fail loudly, never silently pass verification.
    """
    token = expected.strip().split()[0] if expected.strip() else ""
    token = token.lower()
    if len(token) != _SHA256_HEX_LEN or any(c not in "0123456789abcdef" for c in token):
        raise ValueError(
            f"expected a {_SHA256_HEX_LEN}-char hex SHA-256, got: {expected!r}"
        )
    return token


def verify_artifact(artifact: Path, expected: str) -> None:
    """Verify ``artifact`` has SHA-256 ``expected``; raise on any mismatch.

    Precondition: ``artifact`` is a readable file; ``expected`` is a hex digest
    (optionally in ``sha256sum`` line format).
    Postcondition: returns ``None`` iff the file's digest equals ``expected``.
    Raises ``ArtifactIntegrityError`` on mismatch and ``ValueError`` if
    ``expected`` is not a well-formed digest. There is no return value that
    means "probably fine": the function either returns cleanly or raises.
    """
    want = _normalize_expected(expected)
    got = sha256_of(artifact)
    if got != want:
        raise ArtifactIntegrityError(artifact, want, got)


def verify_from_checksum_file(artifact: Path, checksum_file: Path) -> None:
    """Verify ``artifact`` against the digest recorded in ``checksum_file``.

    Precondition: ``checksum_file`` is the ``<asset>.sha256`` companion the
    release workflow publishes, whose first line is ``<hex>  <name>``.
    Postcondition: returns ``None`` iff ``artifact`` matches; otherwise raises
    ``ArtifactIntegrityError`` (mismatch) or ``ValueError`` (unreadable/empty
    checksum file).
    """
    contents = checksum_file.read_text(encoding="utf-8").strip()
    if not contents:
        raise ValueError(f"checksum file is empty: {checksum_file}")
    verify_artifact(artifact, contents)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``verify_release_artifact.py <artifact>
    (<sha256-hex> | --checksum-file FILE)``.

    Returns 0 on a verified match, 1 on integrity failure, 2 on usage/IO error.
    Exit codes are the contract callers (install scripts) branch on.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="path to the downloaded asset")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("expected", nargs="?", help="expected SHA-256 hex digest")
    group.add_argument(
        "--checksum-file",
        type=Path,
        help="path to the published <asset>.sha256 companion",
    )
    args = parser.parse_args(argv)

    try:
        if args.checksum_file is not None:
            verify_from_checksum_file(args.artifact, args.checksum_file)
        else:
            verify_artifact(args.artifact, args.expected)
    except ArtifactIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"verification could not run: {exc}", file=sys.stderr)
        return 2

    print(f"OK: {args.artifact} matches the expected SHA-256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
