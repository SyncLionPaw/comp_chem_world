FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_UPDATES=1 \
    PATH="/root/.local/bin:/usr/local/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y ca-certificates curl python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

COPY uv /usr/local/bin/uv

RUN pip3 install --break-system-packages pytest pytest-json-ctrf

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

WORKDIR /app
