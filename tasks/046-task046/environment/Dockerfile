FROM compchembench-connectivity:hpc


COPY wheels/ /opt/wheels/
COPY requirements.lock.txt /tmp/requirements.lock
RUN python3 -m venv /opt/ccb-venv \
 && /opt/ccb-venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && rm -rf /opt/wheels
ENV PATH="/opt/ccb-venv/bin:${PATH}"

WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
COPY assets/inputs/ /app/inputs/
COPY assets/output-contract.json /app/output-contract.json
COPY assets/runtime-resource-endpoints.json /app/runtime-resource-endpoints.json
COPY assets/compute-budget.yaml /app/compute-budget.yaml

# Harbor Terminus requires terminal tools before the Agent phase begins.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*
