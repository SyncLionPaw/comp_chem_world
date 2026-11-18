FROM comp-chem-world-base

WORKDIR /app

COPY assets/method-card.json assets/family-proxy-method.md assets/archive-schema.json /opt/qeq-public/inputs/
COPY assets/original/ /opt/qeq-public/inputs/original/
COPY assets/runtime/ /opt/qeq-public/

COPY assets/wheels/ /tmp/qeq-wheels/
COPY assets/requirements.lock.txt /tmp/qeq-requirements.lock.txt

RUN python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "CPython 3.12 wheels required"' \
 && python3 -m venv /opt/qeq-science \
 && /opt/qeq-science/bin/pip install --no-index --only-binary=:all: --find-links=/tmp/qeq-wheels --require-hashes -r /tmp/qeq-requirements.lock.txt \
 && /opt/qeq-science/bin/pip check \
 && /opt/qeq-science/bin/python -c 'import numpy, scipy, yaml'

ENV PATH="/opt/qeq-science/bin:${PATH}" \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
