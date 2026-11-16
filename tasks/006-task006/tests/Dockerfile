# Credential-free, offline grader; the candidate environment remains unchanged.
FROM comp-chem-world-base
WORKDIR /app
COPY environment/assets/dependencies/ /tmp/case06-dependencies/
RUN python3 -m venv --system-site-packages /opt/case06-grader \
    && /opt/case06-grader/bin/python3 -m pip install --no-cache-dir --no-index \
         --find-links=/tmp/case06-dependencies --require-hashes \
         -r /tmp/case06-dependencies/requirements.lock.txt \
    && /opt/case06-grader/bin/python3 -m pip check \
    && rm -rf /tmp/case06-dependencies
COPY tests/ /tests/
ENV PATH="/opt/case06-grader/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    BLIS_NUM_THREADS=1
