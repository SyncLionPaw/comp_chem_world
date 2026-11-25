#!/bin/bash
# Build compchembench-connectivity:hpc (or :hpc-amd64) from comp-chem-world-base.
#
# Usage:
#   cp hpc.toml.example hpc.toml   # fill host/user/key
#   bash images/connectivity/build.sh
#   bash images/connectivity/build.sh --platform linux/amd64
#
# Env overrides (optional):
#   CCW_BASE_TAG, CCW_CONNECTIVITY_TAG, CCW_HPC_TOML, CCW_SKIP_SSH_CHECK=1
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DIR/../.." && pwd)"
SSH_DIR="$DIR/ssh"
TOML="${CCW_HPC_TOML:-$DIR/hpc.toml}"
PLATFORM=""
BASE_IMAGE_TAG="${CCW_BASE_TAG:-comp-chem-world-base}"
IMAGE_TAG="${CCW_CONNECTIVITY_TAG:-compchembench-connectivity:hpc}"
SKIP_SSH_CHECK="${CCW_SKIP_SSH_CHECK:-0}"

while (($#)); do
    case "$1" in
        --platform)
            PLATFORM="${2:-}"
            shift 2
            ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -n "$PLATFORM" && "$PLATFORM" != "linux/amd64" && "$PLATFORM" != "linux/arm64" ]]; then
    echo "unsupported platform: $PLATFORM (expected linux/amd64 or linux/arm64)" >&2
    exit 2
fi
if [[ -n "$PLATFORM" && "$IMAGE_TAG" == "compchembench-connectivity:hpc" ]]; then
    case "$PLATFORM" in
        linux/amd64) IMAGE_TAG="compchembench-connectivity:hpc-amd64" ;;
        linux/arm64) IMAGE_TAG="compchembench-connectivity:hpc-arm64" ;;
    esac
    echo "using tag $IMAGE_TAG for --platform $PLATFORM"
fi

if [[ ! -f "$TOML" ]]; then
    echo "missing $TOML — copy hpc.toml.example and fill in host/user/key" >&2
    exit 1
fi

if ! docker image inspect "$BASE_IMAGE_TAG" >/dev/null 2>&1; then
    echo "base image missing: $BASE_IMAGE_TAG (run: bash images/build.sh)" >&2
    exit 1
fi

# Parse hpc.toml → shell exports (stdlib tomllib only).
eval "$(python3 - "$TOML" <<'PY'
import json, sys, tomllib
from pathlib import Path

path = Path(sys.argv[1])
data = tomllib.loads(path.read_text(encoding="utf-8"))
hpc = data.get("hpc") or {}
required = ("host", "user", "identity_file")
missing = [k for k in required if not hpc.get(k)]
if missing:
    raise SystemExit(f"hpc.toml [hpc] missing: {', '.join(missing)}")

host = str(hpc["host"]).strip()
user = str(hpc["user"]).strip()
key = Path(str(hpc["identity_file"]).strip()).expanduser()
port = int(hpc.get("port") or 22)
if not key.is_file():
    raise SystemExit(f"identity_file not found: {key}")

def sh_export(name, value):
    print(f"export {name}={value!r}")

sh_export("HPC_HOST", host)
sh_export("HPC_USER", user)
sh_export("HPC_KEY", str(key.resolve()))
sh_export("HPC_PORT", str(port))

vasp = data.get("vasp") or {}
if vasp:
    site = {k: vasp[k] for k in vasp}
    print(f"export HPC_VASP_SITE={json.dumps(site, ensure_ascii=False)!r}")
else:
    print("export HPC_VASP_SITE=''")
PY
)"

write_container_ssh_config() {
    mkdir -p "$SSH_DIR"
    {
        echo "Host hpc"
        echo "  HostName ${HPC_HOST}"
        echo "  User ${HPC_USER}"
        if [[ "${HPC_PORT}" != "22" ]]; then
            echo "  Port ${HPC_PORT}"
        fi
        echo "  IdentityFile /root/.ssh/hpc_id_rsa"
        echo "  IdentitiesOnly yes"
        echo "  StrictHostKeyChecking accept-new"
        echo "  LogLevel ERROR"
    } > "$SSH_DIR/config"
}

verify_hpc_ssh() {
    local ssh_args=(-o BatchMode=yes -o ConnectTimeout=15 -i "$HPC_KEY")
    if [[ "${HPC_PORT}" != "22" ]]; then
        ssh_args+=(-p "$HPC_PORT")
    fi
    echo "checking cluster SSH (${HPC_USER}@${HPC_HOST})..."
    ssh "${ssh_args[@]}" "${HPC_USER}@${HPC_HOST}" hostname
}

if [[ "$SKIP_SSH_CHECK" != "1" ]]; then
    verify_hpc_ssh
else
    echo "CCW_SKIP_SSH_CHECK=1 — skipping live SSH probe"
fi

mkdir -p "$SSH_DIR"
rm -f -- "$SSH_DIR/"*_id_rsa "$SSH_DIR/vasp-site.json"
write_container_ssh_config
install -m 600 "$HPC_KEY" "$SSH_DIR/hpc_id_rsa"
if [[ -n "${HPC_VASP_SITE}" ]]; then
    (umask 077; printf '%s\n' "$HPC_VASP_SITE" > "$SSH_DIR/vasp-site.json")
fi

BASE_ID="$(docker image inspect "$BASE_IMAGE_TAG" --format '{{.Id}}')"
if [[ -n "$PLATFORM" ]]; then
    EXPECTED_ARCH="${PLATFORM#linux/}"
    BASE_ARCH="$(docker image inspect "$BASE_IMAGE_TAG" --format '{{.Os}}/{{.Architecture}}')"
    [[ "$BASE_ARCH" == "linux/$EXPECTED_ARCH" ]] || {
        echo "base image architecture mismatch: expected linux/$EXPECTED_ARCH for $BASE_IMAGE_TAG, got $BASE_ARCH" >&2
        exit 1
    }
fi

PARENT="compchembench-connectivity-parent:${BASE_ID#sha256:}"
docker tag "$BASE_ID" "$PARENT"

# Network needed for apt (openssh-client/rsync); credentials still only from local COPY.
BUILD_ARGS=(build --network=host)
if [[ -n "${http_proxy:-}${HTTP_PROXY:-}" ]]; then
    hp="${http_proxy:-$HTTP_PROXY}"
    hsp="${https_proxy:-${HTTPS_PROXY:-$hp}}"
    BUILD_ARGS+=(--build-arg "HTTP_PROXY=$hp" --build-arg "HTTPS_PROXY=$hsp"
                 --build-arg "http_proxy=$hp" --build-arg "https_proxy=$hsp")
fi
if [[ -n "$PLATFORM" ]]; then
    BUILD_ARGS+=(--platform "$PLATFORM")
fi
BUILD_ARGS+=(
    --build-arg "BASE_IMAGE=$PARENT"
    --build-arg "PARENT_IMAGE_ID=$BASE_ID"
    -f "$DIR/Dockerfile"
    -t "$IMAGE_TAG"
    "$DIR"
)
echo "=== Building $IMAGE_TAG ==="
docker "${BUILD_ARGS[@]}"

RUN_ARGS=(run --rm)
if [[ -n "$PLATFORM" ]]; then
    RUN_ARGS+=(--platform "$PLATFORM")
fi
docker "${RUN_ARGS[@]}" "$IMAGE_TAG" test -f /app/AGENTS.md
echo "/app/AGENTS.md ok"

if [[ "$SKIP_SSH_CHECK" != "1" ]]; then
    echo "=== verifying baked SSH inside image (needs network) ==="
    VERIFY=(run --rm)
    if [[ -n "$PLATFORM" ]]; then
        VERIFY+=(--platform "$PLATFORM")
    fi
    docker "${VERIFY[@]}" "$IMAGE_TAG" \
        bash -lc 'ls -l /root/.ssh; ssh -o BatchMode=yes -o ConnectTimeout=15 hpc hostname'
fi

echo "=== Done: $IMAGE_TAG ==="
docker image inspect "$IMAGE_TAG" --format '{{.RepoTags}} {{.Id}} {{.Architecture}}'
