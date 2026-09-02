"""Tests for scripts/check_version_surfaces.py — the version-coherence gate.

The gate's own failure mode is silence: a JSON key that stops being read, a
regex that stops matching a badge occurrence, or a canonical source it
cannot read would let a version site drift unnoticed. Each test below
desynchronises exactly ONE of the 14 version sites and asserts the gate
names it — the point of the exercise, since a gate that reports "something,
somewhere disagrees" is barely better than no gate.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

# Dotted, path-derived module name — see test_check_doc_claims.py's own
# header comment for why (mutmut trampoline keys on this exact name).
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location(
    "scripts.check_version_surfaces", _SCRIPTS / "check_version_surfaces.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class _FakeRepo:
    """Minimal stand-in for the repository files the gate reads.

    Raises FileNotFoundError (not KeyError) on a missing path, matching what
    the real read()'s Path.read_text raises — the same contract
    test_check_doc_claims.py's own double honours.
    """

    def __init__(self, **files: str):
        self.files = files

    def read(self, relative_path: str) -> str:
        try:
            return self.files[relative_path]
        except KeyError:
            raise FileNotFoundError(relative_path) from None


# One consistent version, "4.16.0", stated identically at all 14 sites.
_V = "4.16.0"
_BADGE_SVG_OK = (
    f'<svg aria-label="Version {_V}">'
    f"<title>Version {_V}</title>"
    f'<text fill-opacity="0.25">{_V}</text>'
    f'<text fill="#fff">{_V}</text>'
    "</svg>"
)
_MARKETPLACE_OK = (
    '{"metadata": {"version": "%s"}, "plugins": ['
    '{"name": "hypermnesia-mcp", "source": "./", "version": "%s"}, '
    '{"name": "other", "source": {"source": "github", "repo": "x/y"}, '
    '"version": "9.9.9"}]}'
) % (_V, _V)
_UV_LOCK_OK = f"""version = 1
revision = 1

[[package]]
name = "other-package"
version = "1.2.3"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "hypermnesia-mcp"
version = "{_V}"
source = {{ editable = "." }}
dependencies = [
    {{ name = "other-package" }},
]

[[package]]
name = "zzz-package"
version = "9.9.9"
source = {{ registry = "https://pypi.org/simple" }}
"""

OK_FILES: dict[str, str] = {
    "pyproject.toml": f'[project]\nname = "hypermnesia-mcp"\nversion = "{_V}"\n',
    "package.json": f'{{"version": "{_V}"}}',
    "package-lock.json": (
        f'{{"version": "{_V}", "packages": {{"": {{"version": "{_V}"}}}}}}'
    ),
    "server.json": (f'{{"version": "{_V}", "packages": [{{"version": "{_V}"}}]}}'),
    "manifest.json": f'{{"version": "{_V}"}}',
    "gemini-extension.json": f'{{"version": "{_V}"}}',
    ".claude-plugin/plugin.json": f'{{"version": "{_V}"}}',
    ".claude-plugin/marketplace.json": _MARKETPLACE_OK,
    "plugins/hypermnesia-mcp-codex/.codex-plugin/plugin.json": f'{{"version": "{_V}"}}',
    "assets/badge-version.svg": _BADGE_SVG_OK,
    "uv.lock": _UV_LOCK_OK,
}


class _GateTestCase(unittest.TestCase):
    def setUp(self):
        self._real_read = gate.read

    def tearDown(self):
        gate.read = self._real_read

    def _install(self, **overrides: str) -> None:
        files = dict(OK_FILES)
        files.update(overrides)
        gate.read = _FakeRepo(**files).read

    def _failures(self) -> list[str]:
        return gate.check_version_surfaces(gate.read)

    def _assert_single_failure_about(self, path_fragment: str) -> str:
        failures = self._failures()
        self.assertEqual(len(failures), 1, failures)
        self.assertIn(path_fragment, failures[0])
        return failures[0]


class NominalTests(_GateTestCase):
    def test_a_fully_consistent_repository_reports_nothing(self):
        self._install()
        self.assertEqual(self._failures(), [])

    def test_sixteen_surfaces_are_registered(self):
        # source: the task's own site inventory — 12 files, 3 of them (server.json,
        # marketplace.json, package-lock.json) carrying 2 keys each, plus the
        # badge's 4 occurrences: 10 JSON/uv.lock sites - 3 double-counted files
        # + 3 extra keys + 3 extra badge occurrences = 16.
        self.assertEqual(len(gate.SURFACES), 16)


class PerSurfaceDesyncTests(_GateTestCase):
    """Each test desyncs exactly one surface and names it in the failure."""

    def test_package_json_version_desync_is_reported(self):
        self._install(**{"package.json": '{"version": "9.9.9"}'})
        self._assert_single_failure_about("package.json")

    def test_package_lock_root_version_desync_is_reported(self):
        stale = f'{{"version": "9.9.9", "packages": {{"": {{"version": "{_V}"}}}}}}'
        self._install(**{"package-lock.json": stale})
        failure = self._assert_single_failure_about("package-lock.json")
        self.assertNotIn("packages", failure)

    def test_package_lock_root_package_entry_desync_is_reported(self):
        stale = f'{{"version": "{_V}", "packages": {{"": {{"version": "9.9.9"}}}}}}'
        self._install(**{"package-lock.json": stale})
        failure = self._assert_single_failure_about("package-lock.json")
        self.assertIn('packages[""].version', failure)

    def test_server_json_version_desync_is_reported(self):
        stale = f'{{"version": "9.9.9", "packages": [{{"version": "{_V}"}}]}}'
        self._install(**{"server.json": stale})
        failure = self._assert_single_failure_about("server.json")
        self.assertIn("version", failure)
        self.assertNotIn("packages[0]", failure)

    def test_server_json_packages_0_version_desync_is_reported(self):
        """Explicit, dedicated test: this site was covered by NOTHING before."""
        stale = f'{{"version": "{_V}", "packages": [{{"version": "9.9.9"}}]}}'
        self._install(**{"server.json": stale})
        failure = self._assert_single_failure_about("server.json")
        self.assertIn("packages[0].version", failure)

    def test_manifest_json_version_desync_is_reported(self):
        self._install(**{"manifest.json": '{"version": "9.9.9"}'})
        self._assert_single_failure_about("manifest.json")

    def test_gemini_extension_json_version_desync_is_reported(self):
        self._install(**{"gemini-extension.json": '{"version": "9.9.9"}'})
        self._assert_single_failure_about("gemini-extension.json")

    def test_plugin_json_version_desync_is_reported(self):
        self._install(**{".claude-plugin/plugin.json": '{"version": "9.9.9"}'})
        self._assert_single_failure_about(".claude-plugin/plugin.json")

    def test_marketplace_metadata_version_desync_is_reported(self):
        """Explicit, dedicated test: this site was covered by NOTHING before."""
        stale = (
            '{"metadata": {"version": "9.9.9"}, "plugins": ['
            f'{{"name": "hypermnesia-mcp", "source": "./", "version": "{_V}"}}]}}'
        )
        self._install(**{".claude-plugin/marketplace.json": stale})
        failure = self._assert_single_failure_about(".claude-plugin/marketplace.json")
        self.assertIn("metadata.version", failure)

    def test_marketplace_primary_plugin_entry_version_desync_is_reported(self):
        stale = (
            '{"metadata": {"version": "%s"}, "plugins": ['
            '{"name": "hypermnesia-mcp", "source": "./", "version": "9.9.9"}, '
            '{"name": "other", "source": {"source": "github", "repo": "x/y"}, '
            '"version": "%s"}]}'
        ) % (_V, _V)
        self._install(**{".claude-plugin/marketplace.json": stale})
        failure = self._assert_single_failure_about(".claude-plugin/marketplace.json")
        self.assertIn("primary plugin entry version", failure)

    def test_marketplace_with_no_self_hosted_entry_fails_closed(self):
        no_primary = (
            '{"metadata": {"version": "%s"}, "plugins": ['
            '{"name": "other", "source": {"source": "github", "repo": "x/y"}, '
            '"version": "%s"}]}'
        ) % (_V, _V)
        self._install(**{".claude-plugin/marketplace.json": no_primary})
        failure = self._assert_single_failure_about(".claude-plugin/marketplace.json")
        self.assertIn("expected exactly one self-hosted plugin entry, found 0", failure)

    def test_codex_plugin_json_version_desync_is_reported(self):
        self._install(
            **{
                "plugins/hypermnesia-mcp-codex/.codex-plugin/plugin.json": (
                    '{"version": "9.9.9"}'
                )
            }
        )
        self._assert_single_failure_about(
            "plugins/hypermnesia-mcp-codex/.codex-plugin/plugin.json"
        )

    def test_badge_aria_label_desync_is_reported(self):
        self._install(
            **{
                "assets/badge-version.svg": (
                    '<svg aria-label="Version 9.9.9">'
                    f"<title>Version {_V}</title>"
                    f'<text fill-opacity="0.25">{_V}</text>'
                    f'<text fill="#fff">{_V}</text>'
                    "</svg>"
                )
            }
        )
        failure = self._assert_single_failure_about("assets/badge-version.svg")
        self.assertIn("aria-label", failure)

    def test_badge_title_desync_is_reported(self):
        self._install(
            **{
                "assets/badge-version.svg": (
                    f'<svg aria-label="Version {_V}">'
                    "<title>Version 9.9.9</title>"
                    f'<text fill-opacity="0.25">{_V}</text>'
                    f'<text fill="#fff">{_V}</text>'
                    "</svg>"
                )
            }
        )
        failure = self._assert_single_failure_about("assets/badge-version.svg")
        self.assertIn("<title>", failure)

    def test_badge_shadow_text_desync_is_reported(self):
        self._install(
            **{
                "assets/badge-version.svg": (
                    f'<svg aria-label="Version {_V}">'
                    f"<title>Version {_V}</title>"
                    '<text fill-opacity="0.25">9.9.9</text>'
                    f'<text fill="#fff">{_V}</text>'
                    "</svg>"
                )
            }
        )
        failure = self._assert_single_failure_about("assets/badge-version.svg")
        self.assertIn("shadow <text>", failure)

    def test_badge_solid_text_desync_is_reported(self):
        self._install(
            **{
                "assets/badge-version.svg": (
                    f'<svg aria-label="Version {_V}">'
                    f"<title>Version {_V}</title>"
                    f'<text fill-opacity="0.25">{_V}</text>'
                    '<text fill="#fff">9.9.9</text>'
                    "</svg>"
                )
            }
        )
        failure = self._assert_single_failure_about("assets/badge-version.svg")
        self.assertIn("solid <text>", failure)

    def test_uv_lock_root_package_version_desync_is_reported(self):
        stale = _UV_LOCK_OK.replace(
            f'name = "hypermnesia-mcp"\nversion = "{_V}"',
            'name = "hypermnesia-mcp"\nversion = "9.9.9"',
        )
        self._install(**{"uv.lock": stale})
        failure = self._assert_single_failure_about("uv.lock")
        self.assertIn("hypermnesia-mcp", failure)

    def test_uv_lock_missing_the_root_package_fails_closed(self):
        """A block-scan bug could silently compare the WRONG package's version."""
        root_block = (
            f'name = "hypermnesia-mcp"\nversion = "{_V}"\n'
            'source = { editable = "." }\n'
            'dependencies = [\n    { name = "other-package" },\n]\n\n'
        )
        without_root = _UV_LOCK_OK.replace(root_block, "")
        self._install(**{"uv.lock": without_root})
        failure = self._assert_single_failure_about("uv.lock")
        self.assertIn("no version found for", failure)


class RealRepositoryTests(unittest.TestCase):
    """The gate must pass against the actual, committed repository tree."""

    def test_the_real_repository_agrees_on_every_surface(self):
        self.assertEqual(gate.check_version_surfaces(gate.read), [])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._argv = sys.argv[:]
        self._real_read = gate.read

    def tearDown(self):
        sys.argv = self._argv
        gate.read = self._real_read

    def _run(self):
        sys.argv = ["check_version_surfaces.py"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_consistent_tree_exits_zero(self):
        gate.read = _FakeRepo(**OK_FILES).read
        code, out, err = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("version surfaces OK (16 site(s) checked", out)

    def test_a_diverged_tree_exits_one_and_names_the_surface(self):
        files = dict(OK_FILES)
        files["package.json"] = '{"version": "9.9.9"}'
        gate.read = _FakeRepo(**files).read
        code, out, err = self._run()
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Version surfaces disagree with pyproject.toml:", err)
        self.assertIn("package.json", err)

    def test_an_unreadable_pyproject_aborts_with_exit_code_2(self):
        files = dict(OK_FILES)
        files["pyproject.toml"] = '[project]\nname = "hypermnesia-mcp"\n'
        gate.read = _FakeRepo(**files).read
        code, out, err = self._run()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("version-surfaces gate could not run:", err)


if __name__ == "__main__":
    unittest.main()
