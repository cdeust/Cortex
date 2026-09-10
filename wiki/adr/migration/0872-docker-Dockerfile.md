---
title: "ADR-0872 — docker/Dockerfile rationale"
status: accepted
source: docker/Dockerfile
---

# ADR-0872 — docker/Dockerfile

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## docker/Dockerfile — original line 21

````text
# Base image pinned by digest so a rebuild cannot silently pick up a
# different python:3.14-slim-bookworm. Digest resolved from the multi-arch manifest
# list, so it stays correct on both amd64 and arm64.
#   source: registry-1.docker.io/v2/library/python/manifests/3.14-slim-bookworm,
#           docker-content-digest header, fetched 2026-08-10.
# Refresh: Dependabot's `docker` ecosystem (.github/dependabot.yml) opens a
# PR when the tag moves; do not hand-edit without re-fetching the header.
````

## docker/Dockerfile — original line 32

````text
# This used to be `curl -fsSL https://deb.nodesource.com/setup_22.x | bash -`,
# which executes an unreviewed remote script as root at build time — whatever
# that URL serves, whenever it is fetched. It is the single largest piece of
# trust this image extended to a third party, and it cannot be pinned: there
# is no hash to check a pipe against. (OpenSSF Scorecard reports it as
# `downloadThenRun not pinned by hash`.)
````

## docker/Dockerfile — original line 44

````text
# source: https://github.com/nodesource/distributions#installation-instructions
#         (the manual instructions the setup script automates)
````

## docker/Dockerfile — original line 58

````text
# Claude Code CLI, installed with `npm ci` against a committed lockfile
# instead of `npm install -g @anthropic-ai/claude-code`.
````

## docker/Dockerfile — original line 61

````text
# The old form was unversioned, so the image tracked whatever the registry
# served that minute — no way to reproduce a build, and no integrity check.
# `npm ci` is also the only install form Scorecard accepts as pinned (the
# other being a git URL at a commit SHA); an exact version on the command
# line is NOT enough. The lockfile additionally records a sha512 integrity
# hash for every transitive package, which npm verifies on extract.
````

## docker/Dockerfile — original line 68

````text
# Bumping the CLI is `npm install --package-lock-only` in that directory,
# which is a reviewable diff rather than a silent change of image contents.
````

## docker/Dockerfile — original line 80

````text
# Installed into a virtualenv at a version-free path so the runtime stage
# copies one directory and no COPY names the Python version. See the root
# Dockerfile for the incident that rule comes from: a literal
# .../python3.13/site-packages path broke on every base-image bump.
# --no-deps: the file is the complete, uv-resolved dependency graph — pip
# must install it as-is rather than re-deriving it from metadata, which
# breaks the moment pyproject.toml's [tool.uv] override-dependencies
# steers a package past a bound another package's metadata still declares
# (issue: PR #332, mpmath 1.4.1 vs sympy's `mpmath<1.4`).
````

## docker/Dockerfile — original line 94

````text
# Cortex itself: --no-deps because every dependency was just installed from
# the hashed file above, and re-resolving here would reintroduce unpinned
# installs. An editable install of a local path with --no-deps is the form
# Scorecard recognises as pinned.
````

## docker/Dockerfile — original line 101

````text
# Pre-cache embedding model. Retry-with-backoff, fail-loudly: same shape and
# same attempt/backoff constants as ci.yml's "Pre-download embedding model"
# step, for the same reason — a transient huggingface.co blip must not decide
# whether the image builds. The bare single-shot form failed this build on PR
# #337 (CI run 30749502167, 2026-08-02) with "We couldn't connect to
# 'https://huggingface.co'" after 73s, on a commit touching neither this file
# nor anything it depends on; the same job had passed on its parent commit.
# No BuildKit cache mount here on purpose: the runtime stage COPYs this cache
# out of the builder layer, and a cache mount is not part of the layer.
# source: .github/workflows/ci.yml:131-139 (5 attempts, attempt*10s backoff)
````

## docker/Dockerfile — original line 155

````text
# This was `COPY --from=builder /usr/local/lib/python3.12/site-packages ...`
# against a python:3.14 base — a path that has not existed in either stage
# since the base image moved off 3.12, so this image could not build at all.
# It went unnoticed because nothing in CI builds this Dockerfile; the job
# added in .github/workflows/ci.yml alongside this change is what makes the
# next such breakage visible. The venv path carries no version, so a future
# base bump cannot reintroduce the same class of failure.
````

## docker/Dockerfile — original line 186

````text
# Fix ownership of cached models
````

## Final non-Python residual audit

### docker/Dockerfile — pre-cleanup line 5

````text
# Claude Code runs INSIDE the container with Cortex MCP pre-configured via
# stdio. No HTTP bridge needed — same architecture as ai-architect-feedback-loop.
````

### docker/Dockerfile — pre-cleanup line 39

````text
# Replaced by what the script itself does, spelled out: fetch the signing
# key, register the signed apt source, install the signed package. curl now
# feeds `gpg --dearmor`, which is not an interpreter — nothing is executed.
# apt then verifies the package signature against that key.
````

### docker/Dockerfile — pre-cleanup line 73

````text
# Python dependencies, hash-pinned. Every requirement in this file carries a
# hash from uv.lock (scripts/generate_pip_constraints.py), including the
# CPU-only torch build that keeps ~2GB of nvidia-cu13-* wheels out of the
# image — that used to be a bare `--index-url` flag whose artifact no
# lockfile described. `--require-hashes` makes pip refuse anything whose
# bytes do not match.
````

### docker/Dockerfile — pre-cleanup line 135

````text
# Copy Node.js + Claude CLI from builder. The CLI now lives in the project
# directory `npm ci` installed it into, not in the global prefix.
````
