"""Add the vendored third-party files to a CycloneDX SBOM built from uv.lock.

``release.yml`` builds the SBOM from the lock, which knows only Python
packages. Files vendored under ``third_party/<name>/<version>/`` carry a
``PROVENANCE.json`` (component, version, purl, license, upstream sha256);
each becomes one ``file`` component, its hash recomputed from the committed
bytes so the SBOM states what ships, not what the provenance file claims.

Usage: ``python scripts/sbom_add_vendored.py <sbom.cdx.json>`` (in place).

source: ADR-1110"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY = REPO_ROOT / "third_party"


def _vendored_file(directory: Path, provenance: dict) -> Path:
    name = provenance["url"].rsplit("/", 1)[-1]
    return directory / name


def components(root: Path = THIRD_PARTY) -> list[dict]:
    """One CycloneDX component per vendored file, in path order."""
    found = []
    for record in sorted(root.glob("*/*/PROVENANCE.json")):
        provenance = json.loads(record.read_text(encoding="utf-8"))
        payload = _vendored_file(record.parent, provenance)
        digest = hashlib.sha256(payload.read_bytes()).hexdigest()
        if digest != provenance["sha256"]:
            raise SystemExit(f"{payload}: sha256 {digest} != provenance")
        found.append(
            {
                "type": "file",
                "bom-ref": provenance["purl"],
                "name": provenance["component"],
                "version": provenance["version"],
                "purl": provenance["purl"],
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "licenses": [{"license": {"id": provenance["license"]}}],
                "externalReferences": [
                    {"type": "distribution", "url": provenance["url"]}
                ],
            }
        )
    return found


def add(sbom: dict, extra: list[dict]) -> dict:
    """Return ``sbom`` with ``extra`` appended once (idempotent by bom-ref)."""
    present = {c.get("bom-ref") for c in sbom.get("components", [])}
    sbom.setdefault("components", []).extend(
        c for c in extra if c["bom-ref"] not in present
    )
    return sbom


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0])
    sbom = add(json.loads(path.read_text(encoding="utf-8")), components())
    path.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print(f"{path}: {len(components())} vendored component(s) recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
