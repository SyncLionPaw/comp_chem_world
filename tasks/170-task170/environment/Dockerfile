FROM comp-chem-world-base
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
ENV VIRTUAL_ENV=/opt/w2n3-venv PATH="/opt/w2n3-venv/bin:${PATH}"
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends bash build-essential ca-certificates coreutils curl git \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv "$VIRTUAL_ENV"
WORKDIR /app
COPY requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.lock.txt \
    && python -m pip check \
    && rm /tmp/requirements.lock.txt
COPY assets/ /app/assets/
COPY assets/ /app/environment/assets/
RUN mkdir -p /app/final
