# Verify the Linux bootstrap's CPU torch resolution

On Linux, `uv.lock` resolves torch to the `+cpu` wheels of the PyTorch CPU
index, declared once in `pyproject.toml` (`[[tool.uv.index]]` with
`explicit = true` and the Linux marker in `[tool.uv.sources]`). The launcher
installs its `launcher-ml` group by exporting it from `uv.lock` as a
`pylock.toml` (`uv export --format pylock.toml`): every wheel URL and sha256
comes from the lock, and `uv pip install --require-hashes` refuses any other
bytes. There is no second CPU pin to keep in step and no PyPI torch
fallback. macOS and Windows receive the PyPI torch wheels the lock records
for them.

Stamps are keyed on the sha256 of `uv.lock`: any lock change re-runs the
install once, and a failed install never receives a success stamp, even when
an older SentenceTransformers and FlashRank remain importable. The change
does not purge `nvidia-*` directories an older install left behind; commit
rollback and recovery behave as before. No model is loaded during the
verification below.

## Owner or CI verification

The command runs the real launcher in a clean Linux container that has no
uv: the launcher bootstraps its pinned uv with pip (hash-checked), installs
the base and ML sets into a throwaway directory, and the script then checks
that torch is a `+cpu` build and that no `nvidia-*` distribution landed. The
repository is mounted read-only. Docker must be able to bind-mount the
current directory (Colima shares only `$HOME` by default).

```bash
docker run --rm -i --mount "type=bind,src=$PWD,dst=/repo,readonly" \
  python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 \
  python3 - <<'PY'
import importlib.metadata as md, json, os, sys
sys.path.insert(0, "/repo/scripts")
import launcher_deps, launcher_site
deps = "/tmp/data/deps"
launcher_site.isolate_deps(deps)  # what scripts/launcher.py does first
launcher_deps.ensure_all_deps(deps)
dists = {d.metadata["Name"].lower(): d.version for d in md.distributions(path=[deps])}
assert dists["torch"].endswith("+cpu"), dists["torch"]
assert not [n for n in dists if n.startswith("nvidia")], sorted(dists)
stamps = sorted(p for p in os.listdir(deps) if p.startswith(".cortex-deps-stamp"))
print(json.dumps({"torch": dists["torch"], "packages": len(dists), "stamps": stamps}))
PY
```

Measured 2026-10-01 on Colima (linux/aarch64): `torch 2.13.0+cpu`, 78
distributions, both stamps written, no `nvidia-*`. Add `--platform
linux/amd64` to validate the x86-64 wheels. A successful run validates
resolution and installation, not model runtime or a measured energy
reduction.
