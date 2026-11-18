FROM compchembench-connectivity:hpc
WORKDIR /app
RUN sed -i 's#http://ports.ubuntu.com#https://ports.ubuntu.com#g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends build-essential=12.10ubuntu1 python3.12-dev=3.12.3-1ubuntu0.17 cmake \
    && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/case05-venv
ENV PATH="/opt/case05-venv/bin:${PATH}" PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY wheels/ /opt/wheels/
COPY assets/build/spglib-2.3.1.tar.gz /opt/wheels/spglib-2.3.1.tar.gz
COPY requirements.lock.txt /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
    && echo "736e25ec67c220cb20fab7017c4fe6382eedee223076d57f4047342b1bc68ce3  /opt/wheels/spglib-2.3.1.tar.gz" | sha256sum -c - \
    && python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --no-build-isolation --no-deps /opt/wheels/spglib-2.3.1.tar.gz \
    && python -c 'import importlib.metadata as m, numpy, scipy, pymatgen; assert m.version("pymatgen") == "2024.5.1"' \
    && rm -rf /opt/wheels
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 \
    && rm -rf /var/lib/apt/lists/*
COPY assets/ /app/assets/
RUN rm -rf /app/assets/build
