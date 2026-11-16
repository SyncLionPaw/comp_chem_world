FROM comp-chem-world-base
WORKDIR /app
COPY assets/ /app/assets/
COPY assets/requirements.lock.txt /tmp/bench15-requirements.lock.txt
COPY assets/wheels/ /tmp/bench15-wheels/
COPY assets/verification.md /app/verification.md
RUN python3 -m venv /opt/bench15-science \
 && /opt/bench15-science/bin/pip install --no-index --find-links=/tmp/bench15-wheels --require-hashes -r /tmp/bench15-requirements.lock.txt \
 && /opt/bench15-science/bin/pip check \
 && cp /tmp/bench15-requirements.lock.txt /opt/bench15-science/requirements.lock.txt \
 && rm -rf /tmp/bench15-wheels /tmp/bench15-requirements.lock.txt \
 && rm -rf /app/assets/wheels /app/assets/requirements.lock.txt
ENV PATH="/opt/bench15-science/bin:${PATH}" \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
