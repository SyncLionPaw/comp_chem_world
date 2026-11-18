FROM comp-chem-world-base
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libgfortran5 liblapack3 libblas3 libgomp1 \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/chemgraph
ENV PATH="/opt/chemgraph/bin:${PATH}" \
    VIRTUAL_ENV=/opt/chemgraph \
    PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    BENCH19_CASE_ID="case-07-smi-coords"
COPY assets/requirements.lock.txt /opt/requirements.lock.txt
COPY assets/wheels/ /opt/wheels/
RUN pip install --no-cache-dir --upgrade pip >/dev/null \
 && pip install --no-cache-dir --no-index --find-links=/opt/wheels --require-hashes -r /opt/requirements.lock.txt \
 && pip check \
 && rm -rf /opt/wheels
COPY assets/inputs.json /app/environment/assets/inputs.json
WORKDIR /app
