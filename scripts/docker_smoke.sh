#!/usr/bin/env bash
# source: ADR-0732

set -euo pipefail

# source: ADR-0732
MIN_TOOL_COUNT="${CORTEX_SMOKE_MIN_TOOLS:-52}"
IMAGE="${CORTEX_SMOKE_IMAGE:-cortex-smoke:local}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_BUILD=0

# source: ADR-0732
DOCKER_RUN_TIMEOUT_SECONDS=60

for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    *)
      echo "docker_smoke.sh: unknown argument '$arg'" >&2
      exit 2
      ;;
  esac
done

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "docker_smoke: building ${IMAGE} from ${REPO_ROOT}/Dockerfile ..." >&2
  docker build -t "$IMAGE" -f "${REPO_ROOT}/Dockerfile" "$REPO_ROOT"
fi

# Replace this shell with the Python driver and propagate its exit status.
# source: ADR-0732
exec python3 "${REPO_ROOT}/scripts/docker_smoke_client.py" \
  --image "$IMAGE" \
  --min-tools "$MIN_TOOL_COUNT" \
  --timeout "$DOCKER_RUN_TIMEOUT_SECONDS"
