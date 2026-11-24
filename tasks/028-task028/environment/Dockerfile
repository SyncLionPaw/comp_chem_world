FROM compchembench-connectivity:hpc
COPY wheels/ /opt/wheels/
COPY requirements.lock.txt /tmp/requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --break-system-packages --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && rm -rf /opt/wheels
WORKDIR /app
ENV APP=/app
COPY assets/_runtime/output-contract.json /app/output-contract.json
COPY assets/_runtime/README.md /app/research-service.md
RUN mkdir -p /app/final && hpc --help >/dev/null
