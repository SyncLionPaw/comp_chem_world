FROM comp-chem-world-base

LABEL org.compchembench.bench="21_newtonnet-hessian-transition-states"
LABEL org.compchembench.newtonnet_commit="7057a029367a8f5b4ef55601ac3c51e542ad7014"

RUN uv python install 3.12.14 \
    && uv venv /opt/newtonnet-local --python 3.12.14

ENV VIRTUAL_ENV=/opt/newtonnet-local
ENV PATH="/opt/newtonnet-local/bin:${PATH}"
ENV PYTHONPATH="/opt/compchembench"
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

RUN sed -i 's#http://ports.ubuntu.com/ubuntu-ports/#https://ports.ubuntu.com/ubuntu-ports/#g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential openbabel \
    && rm -rf /var/lib/apt/lists/*

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

COPY assets/newtonnet_evaluator.py /opt/compchembench/newtonnet_evaluator.py
WORKDIR /app
COPY assets/ /app/assets/
CMD ["/bin/bash"]
