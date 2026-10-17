"""Build the pgvector archive Setup installs, against the pinned PostgreSQL tree.

Run by ``.github/workflows/pgvector.yml`` once per target triple, on a runner
of that triple; stdlib only, POSIX only. In order:

1. the pinned theseus PostgreSQL archive, sha256-verified
   (``launcher_pg_assets``: one table for Setup and for this build);
2. pgvector's source at the pinned upstream tag, kept only when the tag
   resolves to the pinned commit;
3. ``make`` with PGXS from that tree (``OPTFLAGS=""``: no ``-march=native``,
   so the library runs on any CPU of the triple; on macOS the SDK of this
   runner and the deployment target of the tree's own ``postgres``);
4. a proof that the library loads: ``initdb`` then ``postgres --single``
   creates the extension and computes a distance (single-user mode reads
   stdin and exits: nothing to wait for);
5. on Linux, the glibc symbol versions stay within the tree's own floor;
6. a reproducible archive (sorted members, owner 0, fixed mtime, gzip
   without a timestamp) whose sha256 is printed for the pin.

    python3 -I scripts/pgvector_build.py <target-triple> <work-dir>

source: ADR-1110
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launcher_pg_assets as assets  # noqa: E402

UPSTREAM = "https://github.com/pgvector/pgvector.git"  # source: ADR-1110
# source: theseus 18.6.0 linux gnu bin/postgres requires GLIBC_2.34 at most
# (objdump -T, measured 2026-10-17, ~/.claude/fleet/state/cortex-748.md step2)
GLIBC_FLOOR = (2, 34)
_ARGC = 3  # source: this module's usage line (script, triple, work dir)
# source: ADR-1110 (the extension Cortex creates, its version, one distance)
_PROBE = (
    "CREATE EXTENSION vector;\n"
    "SELECT extversion FROM pg_extension WHERE extname = 'vector';\n"
    "SELECT '[1,2,3]'::vector <-> '[3,2,1]';\n"
)
_DISTANCE = "2.828427"  # source: sqrt(8), the L2 distance _PROBE computes


def _run(argv: list[str], **kwargs) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)
    if done.returncode:
        output = f"{done.stdout}{done.stderr}"
        raise SystemExit(f"{argv[0]} exited {done.returncode}:\n{output}")
    return done.stdout


def postgres_tree(target: str, work: Path) -> Path:
    """The pinned PostgreSQL tree of ``target``, downloaded and verified."""
    name = f"postgresql-{assets.PG_VERSION}-{target}.tar.gz"
    archive = work / name
    url = assets.PG_URL.format(version=assets.PG_VERSION, name=name)
    assets._download(url, archive, assets.SHA256[target][0])
    return assets._extract(archive, work / "pg")


def pgvector_source(work: Path) -> Path:
    """pgvector at the pinned tag, refused unless it is the pinned commit."""
    source = work / "pgvector"
    tag = f"v{assets.PGVECTOR_VERSION}"
    clone = ["git", "clone", "--quiet", "--depth", "1", "--branch", tag]
    _run([*clone, UPSTREAM, str(source)])
    head = _run(["git", "-C", str(source), "rev-parse", "HEAD^{commit}"]).strip()
    if head != assets.PGVECTOR_COMMIT:
        pinned = assets.PGVECTOR_COMMIT
        raise SystemExit(f"{tag} is {head}, pinned {pinned}; refusing it")
    return source


def _macos_flags(tree: Path) -> tuple[list[str], dict[str, str]]:
    sdk = _run(["xcrun", "--show-sdk-path"]).strip()
    load = _run(["otool", "-l", str(tree / "bin" / "postgres")])
    minos = re.search(r"minos (\S+)", load)
    if minos is None:
        raise SystemExit("bin/postgres records no LC_BUILD_VERSION minos")
    # The tree's Makefile.global names its build machine's SDK and Homebrew
    # include/lib paths; this runner's SDK replaces them.
    flags = [f"PG_SYSROOT={sdk}", f"CPPFLAGS=-isysroot {sdk}"]
    flags.append(f"LDFLAGS=-isysroot {sdk} -Wl,-dead_strip_dylibs")
    return flags, {"MACOSX_DEPLOYMENT_TARGET": minos.group(1)}


def build(tree: Path, source: Path) -> None:
    flags, env = _macos_flags(tree) if sys.platform == "darwin" else ([], {})
    argv = ["make", "-C", str(source), f"PG_CONFIG={tree / 'bin' / 'pg_config'}"]
    # The work directory must not reach the library (__FILE__ in elog calls).
    prefix = f"COPT=-ffile-prefix-map={source.parent}=."
    _run([*argv, "OPTFLAGS=", prefix, *flags], env={**os.environ, **env})


def library(source: Path) -> Path:
    suffix = "dylib" if sys.platform == "darwin" else "so"
    return source / f"vector.{suffix}"


def layout(source: Path) -> dict[str, Path]:
    """Archive member name → file, the layout ``launcher_pg_assets._overlay`` reads."""
    files = {f"lib/{library(source).name}": library(source)}
    scripts = sorted((source / "sql").glob("vector--*.sql"))
    extension = [source / "vector.control", *scripts]
    files.update({f"share/extension/{item.name}": item for item in extension})
    return files


def prove_loads(tree: Path, files: dict[str, Path], work: Path) -> None:
    """Overlay the files, create the extension, compute a distance."""
    for member, item in files.items():
        (tree / member).write_bytes(item.read_bytes())
    cluster = work / "cluster"
    _run([str(tree / "bin" / "initdb"), "-D", str(cluster), "-U", "postgres",
          "--auth=trust", "--no-instructions"])  # fmt: skip
    out = _run([str(tree / "bin" / "postgres"), "--single", "-D", str(cluster),
                "postgres"], input=_PROBE)  # fmt: skip
    if _DISTANCE not in out or f'"{assets.PGVECTOR_VERSION}"' not in out:
        raise SystemExit(f"pgvector did not load as expected:\n{out}")


def check_glibc(lib: Path) -> None:
    """No symbol version above the tree's own glibc floor (Linux only)."""
    found = re.findall(r"GLIBC_(\d+)\.(\d+)", _run(["objdump", "-T", str(lib)]))
    highest = max(((int(a), int(b)) for a, b in found), default=(0, 0))
    if highest > GLIBC_FLOOR:
        raise SystemExit(f"{lib.name} needs GLIBC_{highest[0]}.{highest[1]} > floor")


def archive(files: dict[str, Path], target: str, out: Path) -> Path:
    """A byte-reproducible ``pgvector-<target>-pg18.tar.gz``."""
    top = f"pgvector-{target}-pg18"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for member in sorted(files):
            data = files[member].read_bytes()
            info = tarfile.TarInfo(f"{top}/{member}")
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{top}.tar.gz"
    with (
        path.open("wb") as handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as gz,
    ):
        gz.write(raw.getvalue())
    return path


def main(argv: list[str]) -> int:
    if len(argv) != _ARGC:
        raise SystemExit("usage: pgvector_build.py <target-triple> <work-dir>")
    target, work = argv[1], Path(argv[2])
    work.mkdir(parents=True, exist_ok=True)
    tree, source = postgres_tree(target, work), pgvector_source(work)
    build(tree, source)
    files = layout(source)
    prove_loads(tree, files, work)
    if sys.platform != "darwin":
        check_glibc(library(source))
    path = archive(files, target, work / "out")
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
