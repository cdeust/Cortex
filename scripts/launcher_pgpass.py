"""The credentials libpq would have used for the pre-ADR-1104 local URL.

The old default ``postgresql://localhost:5432/cortex`` carried no user and no
password, so libpq filled them in: the user from ``PGUSER`` or the OS login,
the password from ``PGPASSWORD`` or the password file. The first-launch probe
(launcher_backend) must see a user's earlier store the way that URL did.

source: PostgreSQL docs, libpq-envars (PGUSER, PGPASSWORD, PGPASSFILE)
source: PostgreSQL docs, libpq-pgpass (format, wildcards, escapes, permissions)
"""

from __future__ import annotations

import getpass
import os
import stat
from pathlib import Path

# source: PostgreSQL docs, libpq-pgpass (group/world access makes libpq ignore it)
_PRIVATE_MODE_MASK = stat.S_IRWXG | stat.S_IRWXO


def login_user(environ: dict) -> str:
    """``PGUSER``, else the OS login name; raises ``LookupError`` when none."""
    user = environ.get("PGUSER", "")
    if user:
        return user
    try:
        return getpass.getuser()
    except (KeyError, OSError) as exc:  # no passwd entry, no LOGNAME/USER
        raise LookupError(f"no PostgreSQL user name ({exc})") from exc


def _password_file(environ: dict) -> Path:
    if environ.get("PGPASSFILE"):
        return Path(environ["PGPASSFILE"])
    if os.name == "nt":
        return Path(environ.get("APPDATA", "")) / "postgresql" / "pgpass.conf"
    return Path.home() / ".pgpass"


def _field_matches(line: str, at: int, want: str):
    """Index past ``want`` and its ':' when the field at ``at`` matches it, else
    None. ``*`` alone is a wildcard; a backslash takes the next character
    literally (libpq ``pwdfMatchesString``)."""
    if line[at : at + 2] == "*:":
        return at + 2
    got = ""
    while at < len(line) and line[at] != ":":
        if line[at] == "\\" and at + 1 < len(line):
            at += 1
        got += line[at]
        at += 1
    return at + 1 if at < len(line) and got == want else None


def _password(rest: str) -> str:
    """The password: backslash escapes undone, cut at an unescaped ':'."""
    out, escaped = "", False
    for char in rest:
        if escaped:
            out, escaped = out + char, False
        elif char == "\\":
            escaped = True
        elif char == ":":
            break
        else:
            out += char
    return out


def _file_has_entry(path: Path, wanted: tuple) -> bool:
    """libpq ``passwordFromFile``: the first line whose four fields match wins."""
    if not path.is_file():
        return False
    if os.name != "nt" and path.stat().st_mode & _PRIVATE_MODE_MASK:
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        at = 0
        for want in wanted:
            at = _field_matches(line, at, want)
            if at is None:
                break
        if at is not None:
            return bool(_password(line[at:]))
    return False


def has_credentials(
    environ: dict, host: str, port: int, database: str, user: str
) -> bool:
    """Whether libpq would send a password for this connection."""
    if environ.get("PGPASSWORD"):
        return True
    return _file_has_entry(_password_file(environ), (host, str(port), database, user))
