FROM compchembench-connectivity:hpc

LABEL org.compchemworld.case="case-06-hybrid-end-to-end-barrier" \
      org.compchemworld.scope="environment-only-hpc-scoped-science-replay-v6"

COPY assets/dependencies/ /tmp/case06-dependencies/
COPY assets/submit-job.json /app/assets/submit-job.json
RUN mkdir -p /app/final \
    && python3 -m venv --system-site-packages /opt/case06-python \
    && /opt/case06-python/bin/python3 -m pip install --no-cache-dir --no-index \
         --find-links=/tmp/case06-dependencies --require-hashes \
         -r /tmp/case06-dependencies/requirements.lock.txt \
    && /opt/case06-python/bin/python3 -m pip check \
    && rm -rf /tmp/case06-dependencies

ENV PATH="/opt/case06-python/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    BLIS_NUM_THREADS=1
