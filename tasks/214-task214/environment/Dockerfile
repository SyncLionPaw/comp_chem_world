FROM --platform=linux/amd64 compchembench-base:2.1.267

ARG TARGETARCH
# Retain original scientific package sources.
ARG CONDA_FORGE_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
WORKDIR /app

COPY assets/ /opt/task-inputs/

COPY assets/dependencies/conda-linux-64.explicit.lock /tmp/conda-linux-64.explicit.lock
# Pin and authenticate the bootstrap; scientific packages are version-pinned.

COPY assets/wheels/ /tmp/propka-wheels/
COPY assets/wheels/conda-packages/ /tmp/conda-packages/
COPY assets/wheels/conda-local.lock /tmp/conda-local.lock
COPY assets/wheels/micromamba-2.3.3-0.tar.bz2 /tmp/micromamba.tar.bz2
COPY assets/requirements.lock.txt /tmp/propka-requirements.lock.txt

RUN --network=none if ! command -v bzip2; then apt-get update && apt-get install -y --no-install-recommends bzip2 && rm -rf /var/lib/apt/lists/*; fi \
 && digest=e7274528ceb9c20d048a428d6c22d7e02e268f8ffb762c4c365422347c8b8ba2 \
 && echo "${digest}  /tmp/micromamba.tar.bz2" | sha256sum -c - \
 && tar -xjf /tmp/micromamba.tar.bz2 -C /usr/local/bin --strip-components=1 bin/micromamba \
 && rm /tmp/micromamba.tar.bz2 \
 && cd /tmp/conda-packages && sha256sum -c SHA256SUMS && cd /app \
 && micromamba create -y -p /opt/ambertools --file /tmp/conda-local.lock \
 && /opt/ambertools/bin/python -m pip install --no-index --find-links=/tmp/propka-wheels --require-hashes -r /tmp/propka-requirements.lock.txt \
 && mkdir -p /opt/task-inputs \
 && micromamba list -p /opt/ambertools --explicit > /opt/task-inputs/conda-explicit.txt \
 && /opt/ambertools/bin/python -m pip freeze > /opt/task-inputs/pip-freeze.txt \
 && micromamba clean -a -y && rm -rf /tmp/conda-linux-64.explicit.lock /tmp/conda-local.lock /tmp/conda-packages /tmp/propka-wheels /tmp/propka-requirements.lock.txt /opt/task-inputs/wheels

RUN ln -s /opt/task-inputs /inputs \
 && ln -s /opt/task-inputs /app/inputs \
 && for tool in tleap cpptraj propka3; do test -x "/opt/ambertools/bin/$tool" || exit 1; done \
 && /opt/ambertools/bin/python -m pip check \
 && test -x /usr/local/bin/claude \
 && claude --version | grep -F '2.1.267'

ENV AMBERHOME=/opt/ambertools \
    PATH="/opt/ambertools/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    CCW_CLAUDE_CODE_VERSION=2.1.267
