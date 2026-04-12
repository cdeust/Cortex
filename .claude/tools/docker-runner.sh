#!/usr/bin/env bash
# docker-runner.sh — Run research experiments in isolated Docker containers
#
# Usage:
#   tools/docker-runner.sh build [<dockerfile|directory>]
#   tools/docker-runner.sh run <image> <command>
#   tools/docker-runner.sh shell <image>
#   tools/docker-runner.sh list
#   tools/docker-runner.sh clean
#
# Containers mount CWD at /workspace and results/ for output persistence.
# Images tagged with zetetic-research- prefix for easy cleanup.
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"
IMAGE_PREFIX="zetetic-research"
RESULTS_DIR="$REPO_ROOT/results"
NOTEBOOK_TOOL="$REPO_ROOT/tools/lab-notebook-manager.sh"
SESSION_FILE="$REPO_ROOT/research/.session.json"

[[ -z "$ACTION" ]] && { echo "usage: $0 <build|run|shell|list|clean> [args]" >&2; exit 2; }

require_docker() {
  if ! command -v docker &>/dev/null; then
    echo "error: docker is not installed or not in PATH." >&2
    exit 1
  fi
  if ! docker info &>/dev/null 2>&1; then
    echo "error: docker daemon is not running." >&2
    exit 1
  fi
}

has_gpu() {
  command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1
}

gpu_flag() {
  if has_gpu; then
    echo "--gpus all"
  fi
}

log_to_notebook() {
  local entry="$1"
  if [[ -f "$SESSION_FILE" && -x "$NOTEBOOK_TOOL" ]]; then
    "$NOTEBOOK_TOOL" add "$entry" --tag "docker" 2>/dev/null || true
  fi
}

image_exists() {
  docker image inspect "$1" &>/dev/null 2>&1
}

case "$ACTION" in
  build)
    require_docker
    SOURCE="${2:-}"
    TAG="${IMAGE_PREFIX}-$(date +%Y%m%d-%H%M%S)"

    if [[ -n "$SOURCE" && -f "$SOURCE" ]]; then
      # Build from explicit Dockerfile
      echo "Building from Dockerfile: $SOURCE"
      docker build -t "$TAG" -f "$SOURCE" "$(dirname "$SOURCE")"
    elif [[ -n "$SOURCE" && -d "$SOURCE" ]]; then
      if [[ -f "$SOURCE/Dockerfile" ]]; then
        echo "Building from directory: $SOURCE"
        docker build -t "$TAG" "$SOURCE"
      else
        echo "No Dockerfile found in $SOURCE. Generating default research environment..."
        TMPFILE="$(mktemp)"
        trap 'rm -f "$TMPFILE"' EXIT
        cat > "$TMPFILE" <<'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir \
    numpy scipy pandas matplotlib scikit-learn \
    torch --index-url https://download.pytorch.org/whl/cpu
WORKDIR /workspace
DOCKERFILE
        docker build -t "$TAG" -f "$TMPFILE" "$SOURCE"
      fi
    else
      # No source given — generate default Dockerfile in temp
      echo "No Dockerfile specified. Generating default research environment..."
      TMPDIR="$(mktemp -d)"
      trap 'rm -rf "$TMPDIR"' EXIT
      cat > "$TMPDIR/Dockerfile" <<'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir \
    numpy scipy pandas matplotlib scikit-learn \
    torch --index-url https://download.pytorch.org/whl/cpu
WORKDIR /workspace
DOCKERFILE
      docker build -t "$TAG" -f "$TMPDIR/Dockerfile" "$TMPDIR"
    fi

    echo "Image built: $TAG"
    log_to_notebook "Docker image built: $TAG" ;;

  run)
    require_docker
    IMAGE="${2:-}"
    shift 2 2>/dev/null || true
    COMMAND="$*"
    [[ -z "$IMAGE" ]] && { echo "usage: $0 run <image> <command>" >&2; exit 2; }
    [[ -z "$COMMAND" ]] && { echo "usage: $0 run <image> <command>" >&2; exit 2; }

    if ! image_exists "$IMAGE"; then
      echo "error: image '$IMAGE' not found. Build it first with: $0 build" >&2
      exit 1
    fi

    mkdir -p "$RESULTS_DIR"

    echo "Running in container: $COMMAND"
    log_to_notebook "Docker run: image=$IMAGE command=$COMMAND"

    # shellcheck disable=SC2046
    docker run --rm \
      --network=host \
      $(gpu_flag) \
      -v "$(pwd):/workspace" \
      -v "$RESULTS_DIR:/results" \
      -w /workspace \
      "$IMAGE" \
      sh -c "$COMMAND"

    log_to_notebook "Docker run completed: image=$IMAGE" ;;

  shell)
    require_docker
    IMAGE="${2:-}"
    [[ -z "$IMAGE" ]] && { echo "usage: $0 shell <image>" >&2; exit 2; }

    if ! image_exists "$IMAGE"; then
      echo "error: image '$IMAGE' not found. Build it first with: $0 build" >&2
      exit 1
    fi

    mkdir -p "$RESULTS_DIR"

    echo "Starting interactive shell in: $IMAGE"
    log_to_notebook "Docker shell started: image=$IMAGE"

    # shellcheck disable=SC2046
    docker run --rm -it \
      --network=host \
      $(gpu_flag) \
      -v "$(pwd):/workspace" \
      -v "$RESULTS_DIR:/results" \
      -w /workspace \
      "$IMAGE" \
      /bin/bash ;;

  list)
    require_docker
    echo "=== Active Research Containers ==="
    docker ps --filter "ancestor=${IMAGE_PREFIX}*" --format "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.CreatedAt}}" 2>/dev/null || true
    echo ""
    echo "=== Research Images ==="
    docker images --filter "reference=${IMAGE_PREFIX}-*" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" 2>/dev/null || true ;;

  clean)
    require_docker
    echo "Removing stopped research containers..."
    stopped=$(docker ps -a --filter "status=exited" --format "{{.ID}} {{.Image}}" 2>/dev/null \
      | grep "$IMAGE_PREFIX" | awk '{print $1}' || true)
    if [[ -n "$stopped" ]]; then
      echo "$stopped" | xargs docker rm
      echo "Removed stopped containers."
    else
      echo "No stopped research containers found."
    fi

    echo ""
    echo "Removing dangling images..."
    docker image prune -f 2>/dev/null || true

    echo ""
    echo "Research images (use 'docker rmi <image>' to remove):"
    docker images --filter "reference=${IMAGE_PREFIX}-*" --format "  {{.Repository}}:{{.Tag}} ({{.Size}})" 2>/dev/null || true

    log_to_notebook "Docker cleanup performed" ;;

  *) echo "usage: $0 <build|run|shell|list|clean> [args]" >&2; exit 2 ;;
esac
