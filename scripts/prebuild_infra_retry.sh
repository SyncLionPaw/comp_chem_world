#!/usr/bin/env bash
# Prebuild Harbor task images for infra-failure retries.
# Clash on this host listens on 127.0.0.1 only, so builds use --network=host
# and http(s)_proxy. Optional local uv python mirror avoids GitHub stalls.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 1; }
docker info >/dev/null

PROXY="${CCW_BUILD_PROXY:-http://127.0.0.1:7890}"
MIRROR_DIR="${CCW_PYTHON_MIRROR_DIR:-/tmp/ccw-py-mirror}"
MIRROR_PORT="${CCW_PYTHON_MIRROR_PORT:-8765}"
LOG_DIR="${CCW_PREBUILD_LOG_DIR:-/tmp/ccw-eval-logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/prebuild-infra-retry.log"

# Use decimal ints (no leading zeros — bash treats 042 as octal).
tasks=(
  42 60 91 109 111 112 113 121 122
  138 140 141 142 143
  195 197 204
  240 241 242 243 244 245
)

if [[ "${1:-}" == "--tasks" ]]; then
  shift
  tasks=("$@")
fi

mirror_pid=""
cleanup() {
  if [[ -n "$mirror_pid" ]] && kill -0 "$mirror_pid" 2>/dev/null; then
    kill "$mirror_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ -d "$MIRROR_DIR" ]] && compgen -G "$MIRROR_DIR/*/*.tar.gz" >/dev/null; then
  python3 -m http.server "$MIRROR_PORT" --bind 127.0.0.1 --directory "$MIRROR_DIR" \
    >/tmp/ccw-py-mirror-http.log 2>&1 &
  mirror_pid=$!
  sleep 0.5
  export UV_PYTHON_INSTALL_MIRROR="http://127.0.0.1:${MIRROR_PORT}"
  echo "python mirror: $UV_PYTHON_INSTALL_MIRROR (dir=$MIRROR_DIR)" | tee -a "$LOG"
else
  echo "python mirror missing under $MIRROR_DIR; builds will use proxy only" | tee -a "$LOG"
fi

export http_proxy="$PROXY" https_proxy="$PROXY"
export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" ALL_PROXY="$PROXY"

echo "START $(date -Is) proxy=$PROXY tasks=${#tasks[@]}" | tee -a "$LOG"

ok=0
fail=0
for task in "${tasks[@]}"; do
  id=$(printf '%03d' "$task")
  context="tasks/${id}-task${id}/environment"
  image="ccw-prebuild/${id}-task${id}:latest"
  if [[ ! -f "$context/Dockerfile" ]]; then
    echo "SKIP $id (no Dockerfile)" | tee -a "$LOG"
    continue
  fi
  echo "==== BUILD $id $(date -Is) ====" | tee -a "$LOG"
  build_args=(
    --network=host
    --progress=plain
    --tag "$image"
    --build-arg "http_proxy=$PROXY"
    --build-arg "https_proxy=$PROXY"
    --build-arg "HTTP_PROXY=$PROXY"
    --build-arg "HTTPS_PROXY=$PROXY"
  )
  tmp_df=""
  if [[ -n "${UV_PYTHON_INSTALL_MIRROR:-}" ]]; then
    # Inject mirror after every FROM so multi-stage Dockerfiles see it too.
    tmp_df=$(mktemp)
    awk '
      BEGIN { inj = "ARG UV_PYTHON_INSTALL_MIRROR\nENV UV_PYTHON_INSTALL_MIRROR=${UV_PYTHON_INSTALL_MIRROR}" }
      /^FROM / { print; print inj; next }
      { print }
    ' "$context/Dockerfile" >"$tmp_df"
    build_args+=(--build-arg "UV_PYTHON_INSTALL_MIRROR=$UV_PYTHON_INSTALL_MIRROR" -f "$tmp_df")
  fi
  if docker build "${build_args[@]}" "$context" >>"$LOG" 2>&1; then
    echo "OK $id" | tee -a "$LOG"
    ok=$((ok + 1))
  else
    echo "FAIL $id" | tee -a "$LOG"
    fail=$((fail + 1))
  fi
  [[ -n "$tmp_df" ]] && rm -f "$tmp_df"
done

echo "DONE $(date -Is) ok=$ok fail=$fail" | tee -a "$LOG"
[[ "$fail" -eq 0 ]]
