FROM --platform=linux/amd64 compchembench-base:2.1.267

WORKDIR /app

COPY assets/ /app/inputs/
COPY assets/runtime/claude-gateway.py /tmp/ccw35-claude-gateway.py
COPY assets/runtime/build_dns.py /tmp/ccw35-build-dns.py

COPY assets/wheels/ /tmp/ccw35-wheels/
COPY assets/requirements.lock.txt /tmp/ccw35-requirements.lock.txt

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/var/cache/apt \
    python3 /tmp/ccw35-build-dns.py > /tmp/ccw35-build-network.log 2>&1 & \
    NETWORK_PID=$!; \
    export https_proxy=http://127.0.0.1:18080 \
 && sleep 1 \
 && rm -f /etc/apt/apt.conf.d/docker-clean \
 && sed -i 's/^Components:.*/Components: main/' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get -o Acquire::Languages=none -o Acquire::https::Timeout=30 update \
 && apt-get install -y --no-install-recommends g++ \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/ccw35-science \
 && /opt/ccw35-science/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
 && /opt/ccw35-science/bin/pip install --no-index --find-links=/tmp/ccw35-wheels --require-hashes -r /tmp/ccw35-requirements.lock.txt \
 && /opt/ccw35-science/bin/pip check \
 && ln -s /app/inputs /inputs \
 && test -x /usr/local/bin/claude \
 && claude --version | grep -F '2.1.267' \
 && kill "$NETWORK_PID" \
 && install -m 755 /tmp/ccw35-claude-gateway.py /opt/ccw35-science/bin/claude \
 && rm /tmp/ccw35-claude-gateway.py

RUN rm -rf /app/inputs/wheels /app/inputs/runtime /app/inputs/requirements.lock.txt

ENV PATH="/opt/ccw35-science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENMM_CPU_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
