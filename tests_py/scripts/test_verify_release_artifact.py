"""Tests for scripts/verify_release_artifact.py — release-asset integrity (#178).

Issue #178 criterion 4 (with §13 A3, G4): the point of a checksum is that a
TAMPERED artifact is REJECTED. Asserting only that a good file passes would
miss the entire reason the code exists, so the tamper-rejection cases are the
load-bearing ones here.

unittest-style to match the sibling scripts tests; Cortex's pytest collects
unittest classes natively.
"""

from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.verify_release_artifact.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.verify_release_artifact",
    Path(__file__).resolve().parents[2] / "scripts" / "verify_release_artifact.py",
)
assert _spec is not None and _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class VerifyArtifactTest(unittest.TestCase):
    def test_matching_digest_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            good = _write(art, b"authentic release bytes")
            # No exception == verified. verify_artifact returns None on success.
            self.assertIsNone(verify.verify_artifact(art, good))

    def test_tampered_artifact_is_rejected(self) -> None:
        """The core case: bytes changed after the digest was published."""
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            published = _write(art, b"authentic release bytes")
            # Attacker swaps the file contents; the published digest is stale.
            art.write_bytes(b"authentic release bytes + keylogger")
            with self.assertRaises(verify.ArtifactIntegrityError) as ctx:
                verify.verify_artifact(art, published)
            # The error must name both digests so the failure is actionable.
            self.assertEqual(ctx.exception.expected, published)
            self.assertNotEqual(ctx.exception.actual, published)

    def test_single_bit_flip_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "sdist.tar.gz"
            good = _write(art, b"\x00" * 4096)
            art.write_bytes(b"\x01" + b"\x00" * 4095)
            with self.assertRaises(verify.ArtifactIntegrityError):
                verify.verify_artifact(art, good)

    def test_checksum_file_line_format_accepted(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            good = _write(art, b"payload")
            checksum = Path(tmp) / "wheel.whl.sha256"
            # sha256sum / shasum -a 256 line format: "<hex>  <name>".
            checksum.write_text(f"{good}  wheel.whl\n", encoding="utf-8")
            self.assertIsNone(verify.verify_from_checksum_file(art, checksum))

    def test_checksum_file_tamper_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            good = _write(art, b"payload")
            art.write_bytes(b"payload-modified")
            checksum = Path(tmp) / "wheel.whl.sha256"
            checksum.write_text(f"{good}  wheel.whl\n", encoding="utf-8")
            with self.assertRaises(verify.ArtifactIntegrityError):
                verify.verify_from_checksum_file(art, checksum)

    def test_malformed_digest_raises_value_error(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            _write(art, b"payload")
            # A too-short / non-hex value must fail loudly, never silently pass.
            with self.assertRaises(ValueError):
                verify.verify_artifact(art, "not-a-real-digest")

    def test_empty_checksum_file_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            _write(art, b"payload")
            checksum = Path(tmp) / "wheel.whl.sha256"
            checksum.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify.verify_from_checksum_file(art, checksum)

    def test_cli_returns_1_on_tamper(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            published = _write(art, b"authentic")
            art.write_bytes(b"tampered")
            rc = verify.main([str(art), published])
            self.assertEqual(rc, 1)

    def test_cli_returns_0_on_match(self) -> None:
        with TemporaryDirectory() as tmp:
            art = Path(tmp) / "wheel.whl"
            good = _write(art, b"authentic")
            rc = verify.main([str(art), good])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
