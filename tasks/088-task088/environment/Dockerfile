FROM compchembench-connectivity:hpc

# This HPC image bakes the cluster SSH material, so the Agent submits its own
# GROMACS job through ssh/ikkem-slurm; no runtime injection from the runner.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gromacs tmux asciinema \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY assets/requirements.lock.txt /tmp/ihf-requirements.lock.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir --require-hashes -r /tmp/ihf-requirements.lock.txt \
    && python3 -m pip check \
    && rm /tmp/ihf-requirements.lock.txt

COPY assets/protocol.json /app/public/protocol.json
COPY assets/output-contract.json /app/public/output-contract.json
COPY assets/runtime-instructions.md /app/public/runtime-instructions.md

ARG CASE01_PROTOCOL_SHA256=d7647d42dc0c3b91a59c3b98836c7487a297f417052ed8b82dd873a8a9b3b73c
ARG CASE01_OUTPUT_CONTRACT_SHA256=8254abe12ec5fda02142a422d1a08a0f8b29923f263150adda175778e79db0d5
ARG CASE01_RUNTIME_INSTRUCTIONS_SHA256=9ee1091df43035c33fd48358593f4876fd11d63ec791dd75ea466b44986c8c19
RUN test -n "$CASE01_PROTOCOL_SHA256" \
    && test -n "$CASE01_OUTPUT_CONTRACT_SHA256" \
    && test -n "$CASE01_RUNTIME_INSTRUCTIONS_SHA256" \
    && echo "$CASE01_PROTOCOL_SHA256  /app/public/protocol.json" | sha256sum -c - \
    && echo "$CASE01_OUTPUT_CONTRACT_SHA256  /app/public/output-contract.json" | sha256sum -c - \
    && echo "$CASE01_RUNTIME_INSTRUCTIONS_SHA256  /app/public/runtime-instructions.md" | sha256sum -c -
