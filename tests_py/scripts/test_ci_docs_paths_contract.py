"""ci.json may list documentation paths, and the validator both workflows embed
refuses an entry that can hold code or leave the repository (ADR-1133)."""

import json
from pathlib import Path
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
# source: the heredoc opener of the ci.json validator in pipeline.yml.
VALIDATOR = "          python3 - \"$GITHUB_WORKSPACE\" --github-output <<'PY'\n"
DOCS = ["docs/", "wiki/", "CHANGELOG.md"]


def load(workflow, opener):
    text = (WORKFLOWS / workflow).read_text()
    source = text.split(opener, 1)[1].split("\n          PY", 1)[0]
    namespace = {"__name__": "embedded_test"}
    exec(compile(textwrap.dedent(source), workflow, "exec"), namespace)
    return namespace


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.ns = load("pipeline.yml", VALIDATOR)

    def faults(self, *listed):
        document = {key: "true" for key in self.ns["KEYS"]}
        document.update(version_file="v.json", low_risk_files=[])
        if listed:
            document["docs_paths"] = listed[0]
        with tempfile.TemporaryDirectory() as root:
            Path(root, "v.json").write_text('{"version": "1.0.0"}')
            Path(root, "ci.json").write_text(json.dumps(document))
            return self.ns["faults"](Path(root))

    def test_the_key_is_optional_and_takes_directories_and_files(self):
        self.assertEqual(self.faults(), [])
        self.assertEqual(self.faults([]), [])
        self.assertEqual(self.faults(["docs/", "a/b/", "CHANGELOG.md"]), [])

    def test_a_path_that_can_hold_code_or_leave_the_repository_fails(self):
        for value in (
            "docs/", [""], [" docs/"], ["/docs/"], [".github/"], ["./docs/"],
            ["a/../b/"], ["ci.json"], [7], None,
        ):  # fmt: skip
            with self.subTest(value=value):
                self.assertEqual(
                    self.faults(value),
                    ["docs_paths: must be a list of paths inside the repository"],
                )

    def test_this_repository_s_ci_json_honours_the_contract(self):
        self.assertEqual(self.ns["faults"](ROOT), [])
        self.assertEqual(json.loads((ROOT / "ci.json").read_text())["docs_paths"], DOCS)


if __name__ == "__main__":
    unittest.main()
