#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
FORCE=false
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.317}"

while getopts "f" opt; do
    case $opt in
        f) FORCE=true ;;
        *) echo "Usage: $0 [-f]" >&2; exit 1 ;;
    esac
done

ensure_uv() {
    local uv_arch
    case "$(uname -m)" in
        x86_64) uv_arch="x86_64" ;;
        arm64 | aarch64) uv_arch="aarch64" ;;
        *) echo "unsupported host arch for uv: $(uname -m)" >&2; exit 1 ;;
    esac
    if [ -x "$DIR/base/uv" ] && [ "$(cat "$DIR/base/uv.arch" 2>/dev/null || true)" = "$uv_arch" ]; then
        return
    fi
    echo "=== Downloading uv (${uv_arch}) into base/ ==="
    tmp="$(mktemp -d)"
    curl -LsSf "https://github.com/astral-sh/uv/releases/latest/download/uv-${uv_arch}-unknown-linux-gnu.tar.gz" \
        | tar -xz -C "$tmp"
    mv "$tmp"/uv-${uv_arch}-unknown-linux-gnu/uv "$DIR/base/uv"
    chmod +x "$DIR/base/uv"
    echo "$uv_arch" > "$DIR/base/uv.arch"
    rm -rf "$tmp"
}

docker_build() {
    local tag="$1"
    local context="$2"
    shift 2
    local args=(--network=host)
    if [ -n "${http_proxy:-}${HTTP_PROXY:-}" ]; then
        local hp="${http_proxy:-$HTTP_PROXY}"
        local hsp="${https_proxy:-${HTTPS_PROXY:-$hp}}"
        # Clash on the host listens on 127.0.0.1; --network=host makes that reachable.
        args+=(--build-arg "HTTP_PROXY=$hp")
        args+=(--build-arg "HTTPS_PROXY=$hsp")
        args+=(--build-arg "http_proxy=$hp")
        args+=(--build-arg "https_proxy=$hsp")
    fi
    args+=("$@")
    docker build "${args[@]}" -t "$tag" "$context"
}

build() {
    ensure_uv

    echo "=== Current comp-chem-world images ==="
    docker images | grep -E "comp-chem-world|REPOSITORY" || true
    echo ""

    if [ "$FORCE" = true ]; then
        echo "=== Removing old images ==="
        docker rmi -f comp-chem-world-base-chem 2>/dev/null || true
        docker rmi -f comp-chem-world-base 2>/dev/null || true
        echo ""
    fi

    echo "=== Building comp-chem-world-base (CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}) ==="
    docker_build comp-chem-world-base "$DIR/base" \
        --build-arg "CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}"

    echo ""
    echo "=== Building comp-chem-world-base-chem ==="
    docker_build comp-chem-world-base-chem "$DIR/chem"

    echo ""
    echo "=== Done ==="
    docker images | grep comp-chem-world-base
}

build
