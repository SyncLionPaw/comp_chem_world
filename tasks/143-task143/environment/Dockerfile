FROM comp-chem-world-base

LABEL org.compchembench.bench="21_newtonnet-hessian-transition-states"
LABEL org.compchembench.case="case-06-path-identity"
LABEL org.compchembench.role="local-execution-and-offline-scoring"
LABEL org.compchembench.newtonnet_commit="7057a029367a8f5b4ef55601ac3c51e542ad7014"

# Offline scoring dependencies, pinned by hash to the verified dual-architecture lock.
RUN if [ "$(dpkg --print-architecture)" = "arm64" ]; then sed -i 's#http://ports.ubuntu.com/ubuntu-ports/#https://ports.ubuntu.com/ubuntu-ports/#g' /etc/apt/sources.list.d/ubuntu.sources; fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential openbabel \
    && obabel -V 2>&1 | grep -F 'Open Babel 3.1.1' \
    && rm -rf /var/lib/apt/lists/*

RUN uv python install 3.12.14 \
    && uv venv /opt/case-python --python 3.12.14

ENV VIRTUAL_ENV=/opt/case-python
ENV PATH="/opt/case-python/bin:${PATH}"
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1

COPY assets/requirements.lock.txt /tmp/requirements.lock.txt
RUN uv pip install --require-hashes \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements.lock.txt

RUN curl --retry 2 --retry-all-errors --retry-delay 2 --connect-timeout 15 --max-time 60 -fsSL \
        https://files.pythonhosted.org/packages/6b/c6/80f1dee95cf70de0f13a3f32a8a01c6f942290bc01a401c4315db1206adb/NewtonNet-1.1.1.tar.gz \
        -o /tmp/NewtonNet-1.1.1.tar.gz \
    && echo "f68e3c1cafbf08d84d11be9fdd9f58d920a5b9156557a0ab9fe834640ebd82a1  /tmp/NewtonNet-1.1.1.tar.gz" | sha256sum -c - \
    && uv pip install --no-deps --no-build-isolation /tmp/NewtonNet-1.1.1.tar.gz \
    && rm /tmp/NewtonNet-1.1.1.tar.gz \
    && uv pip check

# Evaluator module used by the reference generator (copied from the runtime, no solution material).
COPY assets/newtonnet_evaluator.py /opt/compchembench/newtonnet_evaluator.py

WORKDIR /app
COPY assets/ /app/assets/
