"""install-plugin.sh unsets a storage setting that names nothing — issue #704.

A blank value or a whole unexpanded ``${name}`` token (the manifest's
``${user_config.database_url}``) sets nothing at launch:
``apply_backend_resolution`` removes such a URL or backend and
``map_database_option`` ignores such an option. The installer unsets them
first by the same rule (``shared/database_url.names_a_setting``). Split from
``test_install_plugin_environment_decides`` (file-size cap) with the tests of
the review of #1053, notes 2 and 3.
"""

from __future__ import annotations

from tests_py.scripts.test_install_plugin_environment_decides import _setup_env
from tests_py.scripts.test_install_plugin_no_implicit_postgres import (
    _MANAGED_MARKER,
    _run,
    _saved_marker,
)


def test_an_unexpanded_url_is_unset_and_the_host_option_reaches_setup(tmp_path):
    # At launch, map_database_option writes the option over a DATABASE_URL
    # left as ${user_config.database_url}, which names no database; the
    # installer's `-n` test kept the token as a URL (review 1 of #1052,
    # note 2). The installer now unsets that token first (install-plugin.sh,
    # UNSET_NAMES), so the option fills the empty URL and decides. On the
    # Windows branch the uname stub forces, Setup (scripts/setup.py) is then
    # named postgresql and not asked to provision the managed server, whose
    # marker stays; Linux and Darwin run setup.sh, which is not passed the
    # decided backend (review of #1053, note 2; review of #1054, notes 2 and
    # 3; review of #1055, notes 1 and 3).
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={
            "CLAUDE_PLUGIN_OPTION_DATABASE_URL": "postgresql://db.example/cortex",
            "DATABASE_URL": "${user_config.database_url}",
        },
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Backend: postgresql" in result.stdout + result.stderr
    setup_env = _setup_env(tmp_path)
    assert setup_env["DATABASE_URL"] == "postgresql://db.example/cortex"
    assert setup_env["CORTEX_MEMORY_STORE_BACKEND"] == "postgresql"
    assert "CORTEX_SETUP_MANAGED_PG" not in setup_env
    assert _saved_marker(tmp_path) == _MANAGED_MARKER


def test_an_unexpanded_named_url_is_unset_before_the_marker_backend_copies_it(
    tmp_path,
):
    # With a postgresql marker, NAMED_URL copies CORTEX_MEMORY_DATABASE_URL
    # into an empty DATABASE_URL for Setup. Only the unset list keeps the
    # token ${user_config.database_url} out of it: no test failed when the
    # name left that list (review of #1053, note 3).
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"CORTEX_MEMORY_DATABASE_URL": "${user_config.database_url}"},
        marker='{"backend": "postgresql"}',
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Backend: postgresql" in result.stdout + result.stderr
    setup_env = _setup_env(tmp_path)
    assert "DATABASE_URL" not in setup_env
    assert "CORTEX_MEMORY_DATABASE_URL" not in setup_env


def test_unexpanded_settings_decide_nothing_and_the_managed_marker_holds(tmp_path):
    result, calls = _run(
        tmp_path,
        earlier_state=True,
        extra_env={
            "CLAUDE_PLUGIN_OPTION_DATABASE_URL": "${user_config.database_url}",
            "CORTEX_MEMORY_STORE_BACKEND": "${user_config.store_backend}",
        },
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Existing managed PostgreSQL kept" in result.stdout + result.stderr
    assert "DATABASE_URL" not in _setup_env(tmp_path)
    assert _saved_marker(tmp_path) == _MANAGED_MARKER
    assert not calls.exists()
