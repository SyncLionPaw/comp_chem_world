FROM compchembench-connectivity:hpc

# Harbor Terminus requires terminal tools before the Agent phase begins.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/ccb-venv \
 && /opt/ccb-venv/bin/python -m pip install --no-cache-dir numpy==1.26.4
ENV PATH="/opt/ccb-venv/bin:${PATH}"

WORKDIR /app
COPY assets/inputs/ /app/inputs/
COPY assets/output-contract.json /app/output-contract.json
COPY assets/runtime-resource-endpoints.json /app/runtime-resource-endpoints.json
COPY assets/compute-budget.yaml /app/compute-budget.yaml
