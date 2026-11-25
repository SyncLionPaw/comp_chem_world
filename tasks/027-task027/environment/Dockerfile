# Reuse baked cluster SSH from the connectivity image. Submission uses
# ssh hpc + AGENTS.md stay-in-lane rules (no runtime injection from the runner).
FROM compchembench-connectivity:hpc AS hpc_tools
FROM comp-chem-world-base
COPY wheels/ /opt/wheels/
COPY requirements.lock.txt /tmp/requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 openssh-client rsync && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --break-system-packages --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && rm -rf /opt/wheels
COPY --from=hpc_tools /root/.ssh/ /root/.ssh/
RUN chmod 700 /root/.ssh && chmod 600 /root/.ssh/config /root/.ssh/hpc_id_rsa
WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
ENV APP=/app
COPY assets/ /app/assets/
COPY assets/_runtime/output-contract.json /app/output-contract.json
COPY assets/_runtime/README.md /app/research-service.md
COPY assets/_runtime/README.md /app/environment/README.md
RUN mkdir -p /app/final
