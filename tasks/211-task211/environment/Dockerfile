FROM comp-chem-world-base

ARG TARGETARCH
# Retain original scientific package sources.
ARG CONDA_FORGE_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
WORKDIR /app

COPY assets/ /opt/task-inputs/

COPY assets/dependencies/conda-linux-64.explicit.lock /tmp/conda-linux-64.explicit.lock
COPY assets/dependencies/conda-linux-aarch64.explicit.lock /tmp/conda-linux-aarch64.explicit.lock
# Pin and authenticate the bootstrap; scientific packages are version-pinned.

COPY assets/wheels/ /tmp/propka-wheels/
COPY assets/wheels/conda-packages/ /tmp/conda-packages/
COPY assets/wheels/conda-local.lock /tmp/conda-local-amd64.lock
COPY assets/wheels/conda-local-aarch64.lock /tmp/conda-local-arm64.lock
COPY assets/wheels/micromamba-2.3.3-0.tar.bz2 /tmp/micromamba-amd64.tar.bz2
COPY assets/wheels/micromamba-2.3.3-0-linux-aarch64.tar.bz2 /tmp/micromamba-arm64.tar.bz2
COPY assets/requirements.lock.txt /tmp/propka-requirements.lock.txt

RUN --network=none if ! command -v bzip2; then apt-get update && apt-get install -y --no-install-recommends bzip2 && rm -rf /var/lib/apt/lists/*; fi \
 && arch="$(dpkg --print-architecture)" \
 && if [ "$arch" = amd64 ]; then \
      src=/tmp/micromamba-amd64.tar.bz2; \
      digest=e7274528ceb9c20d048a428d6c22d7e02e268f8ffb762c4c365422347c8b8ba2; \
      lock=/tmp/conda-local-amd64.lock; \
    elif [ "$arch" = arm64 ]; then \
      src=/tmp/micromamba-arm64.tar.bz2; \
      digest=02ed4fe982c8ecbf9c5b1759c07ee29063994842b65fdaab439db77b9b00510a; \
      lock=/tmp/conda-local-arm64.lock; \
    else \
      echo "unsupported architecture: ${arch}" >&2; \
      exit 1; \
    fi \
 && echo "${digest}  ${src}" | sha256sum -c - \
 && tar -xjf "${src}" -C /usr/local/bin --strip-components=1 bin/micromamba \
 && rm -f /tmp/micromamba-amd64.tar.bz2 /tmp/micromamba-arm64.tar.bz2 \
 && cd /tmp/conda-packages && sha256sum -c SHA256SUMS && cd /app \
 && micromamba create -y -p /opt/ambertools --file "${lock}" \
 && /opt/ambertools/bin/python -m pip install --no-index --find-links=/tmp/propka-wheels --require-hashes -r /tmp/propka-requirements.lock.txt \
 && mkdir -p /opt/task-inputs \
 && micromamba list -p /opt/ambertools --explicit > /opt/task-inputs/conda-explicit.txt \
 && /opt/ambertools/bin/python -m pip freeze > /opt/task-inputs/pip-freeze.txt \
 && micromamba clean -a -y && rm -rf /tmp/conda-linux-64.explicit.lock /tmp/conda-linux-aarch64.explicit.lock /tmp/conda-local-amd64.lock /tmp/conda-local-arm64.lock /tmp/conda-packages /tmp/propka-wheels /tmp/propka-requirements.lock.txt /opt/task-inputs/wheels

RUN ln -s /opt/task-inputs /inputs \
 && ln -s /opt/task-inputs /app/inputs \
 && for tool in tleap cpptraj propka3; do test -x "/opt/ambertools/bin/$tool" || exit 1; done \
 && /opt/ambertools/bin/python -m pip check \
 && test -x /usr/local/bin/claude \
 && claude --version

ENV AMBERHOME=/opt/ambertools \
    PATH="/opt/ambertools/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    CCW_CLAUDE_CODE_VERSION=2.1.317
