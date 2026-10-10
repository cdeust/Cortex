"""The wiki reindex reads and writes README.md and INDEX.md as UTF-8 (#688).

A bare ``read_text()`` / ``write_text()`` uses the locale code page (cp1252 on
Windows): a hand-written UTF-8 README with no generated marker was misread, an
undecodable one decoded to mojibake instead of being refused, and a page name
outside cp1252 could not be written at all (the reindex is best-effort, so the
failure was swallowed). ``-X warn_default_encoding`` turns each default-encoding
file open into an ``EncodingWarning``, made an error here, so the proof holds on
any platform.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = "journal/réunion-日本語.md"
CHILD = f"""
import sys
from pathlib import Path
from mcp_server.infrastructure.wiki_reindex_io import try_reindex

root = Path(sys.argv[1])
page = root / {PAGE!r}
page.parent.mkdir(parents=True)
page.write_bytes("# réunion\\n".encode("utf-8"))
try_reindex(root)
"""


def test_reindex_does_no_default_encoding_io_and_writes_utf8(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            "-c",
            CHILD,
            str(tmp_path),
        ],
        capture_output=True,
        env={"CORTEX_CLAUDE_DIR": str(tmp_path / "claude"), "PYTHONPATH": str(ROOT)},
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "backslashreplace")
    readme = (tmp_path / "README.md").read_bytes().decode("utf-8")
    index = (tmp_path / ".generated" / "INDEX.md").read_bytes().decode("utf-8")
    assert "réunion" in readme + index


def test_a_readme_written_in_cp1252_is_left_untouched(tmp_path: Path) -> None:
    """A README an older run wrote in the locale code page is not valid UTF-8.
    The reindex keeps it byte for byte (it reports through its existing except
    branch) rather than rewriting or garbling it; ADR-1098 records that this is
    a documented refusal and not yet a hard failure, and this pins it."""
    old = "# café — notes\n".encode("cp1252")
    (tmp_path / "README.md").write_bytes(old)
    child = (
        "import sys\n"
        "from pathlib import Path\n"
        "from mcp_server.infrastructure.wiki_reindex_io import try_reindex\n"
        "try_reindex(Path(sys.argv[1]))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path)],
        capture_output=True,
        env={"CORTEX_CLAUDE_DIR": str(tmp_path / "claude"), "PYTHONPATH": str(ROOT)},
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "backslashreplace")
    assert (tmp_path / "README.md").read_bytes() == old
