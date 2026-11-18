FROM comp-chem-world-base

WORKDIR /app

COPY assets/method-card.json assets/panel.json assets/core-ddec-geometry-index.json assets/mapped-panel-charges.csv assets/ddec-panel-charges.csv assets/charge-ambiguity-case05.json assets/assignment_bounds.py assets/potential-model.json /opt/qeq-public/inputs/
COPY assets/runtime/ /opt/qeq-public/

COPY assets/wheels/ /tmp/qeq-wheels/
COPY assets/requirements.lock.txt /tmp/qeq-requirements.lock.txt

RUN --mount=type=cache,target=/root/.cache/pip python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "CPython 3.12 wheels required"' \
 && python3 -m venv /opt/qeq-science \
 && /opt/qeq-science/bin/pip install --no-index --only-binary=:all: --find-links=/tmp/qeq-wheels --require-hashes -r /tmp/qeq-requirements.lock.txt \
 && /opt/qeq-science/bin/pip check \
 && /opt/qeq-science/bin/python -c 'import numpy, scipy, yaml'

ENV PATH="/opt/qeq-science/bin:${PATH}" \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
