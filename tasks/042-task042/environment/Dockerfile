FROM comp-chem-world-base


ENV DEBIAN_FRONTEND=noninteractive \
    UV_HTTP_TIMEOUT=300 \
    UV_HTTP_RETRIES=5 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VIRTUAL_ENV=/opt/deepmd \
    PATH="/opt/deepmd/bin:${PATH}"

COPY assets/requirements.lock.txt /tmp/requirements.lock.txt
RUN --mount=type=cache,target=/root/.cache/uv uv venv /opt/deepmd --python /usr/bin/python3 \
    && uv pip install --python /opt/deepmd/bin/python --require-hashes -r /tmp/requirements.lock.txt \
    && rm /tmp/requirements.lock.txt \
    && uv pip check --python /opt/deepmd/bin/python

ENV LAMMPS_PLUGIN_PATH=/opt/deepmd/lib/python3.12/site-packages/deepmd/lib
WORKDIR /app
COPY assets/inputs/ /app/inputs/
COPY assets/output-contract.json /app/output-contract.json
CMD ["/bin/bash"]

# Harbor Terminus requires terminal tools before the Agent phase begins.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*
