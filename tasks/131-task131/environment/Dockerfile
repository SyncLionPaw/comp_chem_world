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
    BENCH19_CASE_ID="case-12-react-enthalpy"
COPY assets/requirements.lock.txt /opt/requirements.lock.txt
COPY assets/vendor/ /opt/vendor/
RUN pip install --no-cache-dir --upgrade pip >/dev/null \
 && pip install --no-cache-dir --find-links=/opt/vendor -r /opt/requirements.lock.txt tblite==0.7.0 \
 && pip check
COPY assets/inputs.json /app/environment/assets/inputs.json
WORKDIR /app
