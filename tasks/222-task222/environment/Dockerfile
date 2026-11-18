FROM comp-chem-world-base

WORKDIR /app

COPY assets/ /app/environment/assets/

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

RUN python3 -m venv /opt/cphmd-analysis \
 && /opt/cphmd-analysis/bin/python -m pip install --no-index --only-binary=:all: --find-links=/app/environment/assets/wheels --require-hashes -r /app/environment/assets/requirements.lock.txt \
 && /opt/cphmd-analysis/bin/python -m pip check \
 && /opt/cphmd-analysis/bin/python -c "import numpy, scipy" \
 && mkdir -p /app/environment \
 && test -x /usr/local/bin/claude \
 && ln -s /app/environment/assets /app/inputs

ENV PATH="/opt/cphmd-analysis/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1
