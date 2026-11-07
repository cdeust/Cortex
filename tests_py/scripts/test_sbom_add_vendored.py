"""The release SBOM lists the vendored gitleaks rule set (ADR-1110)."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts import sbom_add_vendored as sbom


def test_the_gitleaks_rule_set_is_a_component_with_the_committed_hash():
    (component,) = sbom.components()
    vendored = sbom.THIRD_PARTY / "gitleaks" / "v8.30.1" / "gitleaks.toml"
    assert (
        component["purl"] == "pkg:github/gitleaks/gitleaks@v8.30.1#config/gitleaks.toml"
    )
    assert component["version"] == "8.30.1"
    assert component["licenses"] == [{"license": {"id": "MIT"}}]
    assert (
        component["hashes"][0]["content"]
        == hashlib.sha256(vendored.read_bytes()).hexdigest()
    )


def test_add_is_idempotent_and_keeps_lock_components(tmp_path):
    path = tmp_path / "bom.json"
    path.write_text(
        json.dumps({"bomFormat": "CycloneDX", "components": [{"name": "numpy"}]})
    )
    sbom.main([str(path)])
    sbom.main([str(path)])
    names = [c["name"] for c in json.loads(path.read_text())["components"]]
    assert names == ["numpy", "gitleaks default rule set"]


def test_a_vendored_file_that_drifted_from_its_provenance_is_refused(tmp_path):
    vendor = tmp_path / "tool" / "v1"
    vendor.mkdir(parents=True)
    (vendor / "rules.toml").write_text("changed")
    (vendor / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "component": "tool",
                "version": "1",
                "purl": "pkg:generic/tool@1",
                "license": "MIT",
                "url": "https://example.invalid/rules.toml",
                "sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(SystemExit, match="sha256"):
        sbom.components(tmp_path)
