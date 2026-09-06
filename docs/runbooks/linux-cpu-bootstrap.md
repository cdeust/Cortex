# Verify the Linux bootstrap's CPU torch resolution

On Linux, the ML pin set includes `torch==2.13.0+cpu`, from the Linux entry in
`requirements/setup.txt`. The added pin invalidates stamps from the previous
ML pin set. Failed installs do not receive a new success stamp, even when the
previous SentenceTransformers and FlashRank packages remain importable.

Every Linux ML resolution, including a partial repair, first downloads only
the CPU torch wheel with `pip download --no-deps --only-binary=:all:` and
`--require-hashes`. The allowed hashes are reconciled against the lock export
and `uv.lock` in tests. Pip then resolves the requested packages and that local
wheel together, with the base pins and CPU pin as constraints, using PyPI.
An unavailable wheel or failed hash check aborts; no PyPI torch fallback is
attempted. macOS and Windows retain their existing ML pin sets and PyPI source.

This expresses the package-specific source policy of the repository's
[`explicit = true` uv index](https://docs.astral.sh/uv/concepts/indexes/#pinning-a-package-to-an-index).
Adding a pip extra index would search both indexes for other packages;
[pip does not prioritize those sources](https://pip.pypa.io/en/stable/cli/pip_install/#finding-packages).
`PIP_CONFIG_FILE=os.devnull` disables external pip configuration files, as
[documented by pip](https://pip.pypa.io/en/stable/topics/configuration/#pip-config-file).
Inherited source and requirement-file overrides are removed; transport settings
such as certificate and proxy environment variables remain available.

The change prevents future CUDA dependency resolution. It does not purge
already-installed `nvidia-*` directories. Existing commit rollback and recovery
behavior remains in place. No model is loaded during the verification below.

## Owner or CI verification

`launcher_deps_install.py` is an imported helper, not a CLI with `--dry-run`.
The following command invokes pip's real `--dry-run --ignore-installed --report`
resolution in Linux. It downloads the CPU wheel and dependency metadata. This
container command was not executed during fixture tests. The image is the pinned Python
image already used in `docker/Dockerfile`. The report is written outside the
read-only source mount and no dependencies are installed. If Docker runs in a
VM that does not share the host temporary directory, set `CORTEX_CPU_REPORT_DIR`
to an existing directory shared with that VM before running the command.

```bash
CORTEX_CPU_REPORT_DIR="${CORTEX_CPU_REPORT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/cortex-cpu-report.XXXXXX")}"
docker run --rm -i --platform linux/amd64 \
  --mount "type=bind,src=$PWD,dst=/repo,readonly" \
  --mount "type=bind,src=$CORTEX_CPU_REPORT_DIR,dst=/evidence" \
  -w /repo \
  python:3.14-slim-bookworm@sha256:416f0db2a2b561945630cef9877a7ea0581b27449eb9fd9df42f03e1b74b5b63 \
  python - <<'PY'
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, "/repo/scripts")
import launcher_deps_install as install
import launcher_pins as pins
import launcher_pip as pip
import launcher_torch_cpu as cpu

root = Path("/evidence")
deps = root / "unused-install-target"
packages = [spec for _, spec in pins.ml_packages(sys.platform)]
constraints = [install.constraint_without_extras(spec) for _, spec in pins.BASE_PACKAGES]
constraints.append(pins.TORCH_CPU_SPEC)
(root / "constraints-used.txt").write_text("\n".join(constraints) + "\n")
environment = pip.clean_environment()
report_path = root / "pip-report.json"
with pip.constraint_args(str(deps), constraints) as arguments:
    with cpu.local_targets(str(deps), packages, environment) as targets:
        command = [sys.executable, "-m", "pip", "install", "--dry-run",
                   "--ignore-installed", "--report", str(report_path),
                   "--index-url", "https://pypi.org/simple/", *arguments, *targets]
        subprocess.run(command, env=environment, check=True)
        report = json.loads(report_path.read_text())
        entries = report["install"]
        names = {item["metadata"]["name"].lower().replace("_", "-") for item in entries}
        assert not any(name.startswith("nvidia-") for name in names), names
        torch, = [item for item in entries if item["metadata"]["name"].lower() == "torch"]
        assert torch["metadata"]["version"] == pins.TORCH_CPU_SPEC.split("==")[1]
        digest = torch["download_info"]["archive_info"]["hashes"]["sha256"]
        assert digest in pins.TORCH_CPU_HASHES, digest
        assert urlsplit(torch["download_info"]["url"]).scheme == "file"
        for item in entries:
            if item is not torch:
                assert urlsplit(item["download_info"]["url"]).hostname in {
                    "files.pythonhosted.org", "pypi.org"
                }, item["download_info"]
        (root / "cpu-source.json").write_text(json.dumps({
            "index": pins.TORCH_CPU_INDEX, "sha256": digest,
            "version": torch["metadata"]["version"], "nvidia_packages": [],
        }, indent=2))
print(report_path)
PY
```

The wheel staging directory is removed after resolution; the report retains
its hash and the explicit CPU source. Repeat with the target architecture
instead of `linux/amd64` when validating another Linux deployment. A successful
report validates resolution, not model runtime or a measured energy reduction.
