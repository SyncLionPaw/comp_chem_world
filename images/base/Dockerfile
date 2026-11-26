FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_UPDATES=1 \
    PATH="/root/.local/bin:/usr/local/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y ca-certificates curl python3 python3-pip python3-venv ripgrep && \
    rm -rf /var/lib/apt/lists/*

COPY uv /usr/local/bin/uv

RUN pip3 install --default-timeout=120 --retries=5 --break-system-packages pytest pytest-json-ctrf

# Official native binary (not install.sh / apt npm). Version locked via build-arg.
ARG CLAUDE_CODE_VERSION
RUN test -n "${CLAUDE_CODE_VERSION}" \
    && set -eux \
    && arch="$(dpkg --print-architecture)" \
    && case "${arch}" in \
         amd64) pkg="claude-code-linux-x64" ;; \
         arm64) pkg="claude-code-linux-arm64" ;; \
         *) echo "unsupported arch=${arch}"; exit 1 ;; \
       esac \
    && curl -fsSL \
         "https://registry.npmjs.org/@anthropic-ai/${pkg}/-/${pkg}-${CLAUDE_CODE_VERSION}.tgz" \
         -o /tmp/claude.tgz \
    && tar -xzf /tmp/claude.tgz -C /tmp \
    && install -m 0755 /tmp/package/claude /usr/local/bin/claude \
    && mkdir -p /root/.local/bin \
    && ln -sf /usr/local/bin/claude /root/.local/bin/claude \
    && rm -rf /tmp/claude.tgz /tmp/package \
    && claude --version | grep -F "${CLAUDE_CODE_VERSION}"

# Codex CLI native binary (musl). Host download via images/build.sh → COPY.
# Harbor reuses when configs/agent-codex-*.yaml kwargs.version matches.
ARG CODEX_VERSION
COPY codex.tgz /tmp/codex.tgz
RUN test -n "${CODEX_VERSION}" \
    && set -eux \
    && mkdir -p /tmp/codex-extract \
    && tar -xzf /tmp/codex.tgz -C /tmp/codex-extract \
    && bin="$(find /tmp/codex-extract -type f \( -name 'codex' -o -name 'codex-*' \) ! -name '*.md' | head -n 1)" \
    && test -n "${bin}" \
    && install -m 0755 "${bin}" /usr/local/bin/codex \
    && mkdir -p /root/.local/bin \
    && ln -sf /usr/local/bin/codex /root/.local/bin/codex \
    && rm -rf /tmp/codex.tgz /tmp/codex-extract \
    && codex --version | tee /tmp/codex.version \
    && grep -F "${CODEX_VERSION}" /tmp/codex.version \
    && rm -f /tmp/codex.version

WORKDIR /app
