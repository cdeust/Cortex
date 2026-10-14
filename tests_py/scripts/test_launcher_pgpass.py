"""scripts/launcher_pgpass.py: the credentials libpq would have sent
(``passwordFromFile`` / ``pwdfMatchesString`` rules).

source: PostgreSQL docs, libpq-envars and libpq-pgpass
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launcher_pgpass  # noqa: E402

_TARGET = ("localhost", 5432, "cortex", "me")


def _pgpass(tmp_path: Path, text: str, mode: int = 0o600) -> dict:
    path = tmp_path / "pgpass"
    path.write_text(text)
    path.chmod(mode)
    return {"PGPASSFILE": str(path)}


def test_pgpassword_counts():
    assert launcher_pgpass.has_credentials({"PGPASSWORD": "x"}, *_TARGET)


@pytest.mark.parametrize(
    "line",
    ["localhost:5432:cortex:me:pw", "*:*:*:*:pw", "localhost:5432:*:me:pw"],
)
def test_a_matching_line_counts(tmp_path, line):
    env = _pgpass(tmp_path, "# comment\n\n" + line + "\n")
    assert launcher_pgpass.has_credentials(env, *_TARGET)


@pytest.mark.parametrize(
    "line", ["otherhost:5432:cortex:me:pw", "localhost:5433:cortex:me:pw",
             "localhost:5432:other:me:pw", "localhost:5432:cortex:you:pw"],
)  # fmt: skip
def test_a_line_for_another_connection_does_not(tmp_path, line):
    assert not launcher_pgpass.has_credentials(_pgpass(tmp_path, line), *_TARGET)


def test_escaped_colons_are_part_of_a_field(tmp_path):
    env = _pgpass(tmp_path, "localhost:5432:cortex:me:p\\:w\n")
    assert launcher_pgpass.has_credentials(env, *_TARGET)
    assert launcher_pgpass._password("p\\:w:ignored") == "p:w"
    env = _pgpass(tmp_path, "localhost:5432:cortex:m\\:e:pw\n")
    assert launcher_pgpass.has_credentials(env, "localhost", 5432, "cortex", "m:e")


def test_an_escaped_star_is_a_literal_not_a_wildcard(tmp_path):
    env = _pgpass(tmp_path, "localhost:5432:\\*:me:pw\n")
    assert not launcher_pgpass.has_credentials(env, *_TARGET)


def test_only_a_leading_hash_is_a_comment(tmp_path):
    env = _pgpass(tmp_path, " #:*:*:*:pw\n")  # host " #" — a line, not a comment
    assert not launcher_pgpass.has_credentials(env, *_TARGET)
    env = _pgpass(tmp_path, "#localhost:5432:cortex:me:pw\n")
    assert not launcher_pgpass.has_credentials(env, *_TARGET)


def test_the_first_match_decides(tmp_path):
    env = _pgpass(tmp_path, "localhost:5432:cortex:me:\n*:*:*:*:pw\n")
    assert not launcher_pgpass.has_credentials(env, *_TARGET)


@pytest.mark.skipif(os.name == "nt", reason="libpq checks permissions on POSIX only")
def test_a_file_others_can_read_is_ignored_as_libpq_does(tmp_path):
    env = _pgpass(tmp_path, "*:*:*:*:pw\n", mode=0o644)
    assert not launcher_pgpass.has_credentials(env, *_TARGET)


def test_pguser_wins_over_the_login():
    assert launcher_pgpass.login_user({"PGUSER": "owner"}) == "owner"


def test_no_user_name_is_a_lookup_error(monkeypatch):
    def missing():
        raise KeyError("getpwuid(): uid not found: 501")

    monkeypatch.setattr(launcher_pgpass.getpass, "getuser", missing)
    with pytest.raises(LookupError, match="no PostgreSQL user name"):
        launcher_pgpass.login_user({})
