"""Static scope of the release credentials in the workflows."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from tests_py.scripts._release_step_fixture import step_section

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
ENGINES = ("pipeline.yml", "pipeline-post-merge.yml")
KEY = "${{ secrets.RELEASE_TAG_SSH_KEY }}"


class ReleaseCredentialScope(unittest.TestCase):
    def test_release_key_is_scoped_to_publication(self):
        for name in ENGINES:
            tag = yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]["tag"]
            with self.subTest(engine=name):
                recipients = [
                    step.get("id") for step in tag["steps"] if KEY in str(step)
                ]
                self.assertEqual(recipients, ["publish"])
                self.assertEqual(tag["permissions"], {"contents": "read"})

    def test_both_engines_publish_with_the_same_step(self):
        first, second = (step_section((WORKFLOWS / n).read_text()) for n in ENGINES)
        self.assertEqual(first, second)

    def test_repository_checkouts_discard_credentials(self):
        for path in WORKFLOWS.glob("*.yml"):
            jobs = yaml.safe_load(path.read_text())["jobs"]
            for job, body in jobs.items():
                for step in body.get("steps", []):
                    if step.get("uses", "").startswith("actions/checkout@"):
                        with self.subTest(workflow=path.name, job=job):
                            self.assertIs(
                                step.get("with", {}).get("persist-credentials"), False
                            )

    def test_catalog_pushes_authenticate_only_for_their_git_command(self):
        workflow = yaml.safe_load((WORKFLOWS / "publish-ccplugins.yml").read_text())
        steps = workflow["jobs"]["sync"]["steps"]
        pushes = [s for s in steps if "${{ secrets.CCPLUGINS_PAT }}" in str(s)]
        self.assertEqual(
            [s["name"] for s in pushes],
            ["Sync fork with upstream", "Push + open (or update) PR"],
        )
        for step in pushes:
            self.assertEqual(step["env"]["GH_TOKEN"], "${{ secrets.CCPLUGINS_PAT }}")
            self.assertIn(
                "git -c credential.helper= "
                "-c 'credential.helper=!gh auth git-credential' push",
                step["run"],
            )


if __name__ == "__main__":
    unittest.main()
