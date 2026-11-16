FROM compchembench-connectivity:hpc
WORKDIR /app
RUN mkdir -p /app/final
COPY assets/6L_MoS2_origin /app/assets/6L_MoS2_origin
COPY assets/potentials/MoS.rebomos /app/assets/potentials/MoS.rebomos
COPY assets/potentials/MoS.rebomos.rebo-only /app/assets/potentials/MoS.rebomos.rebo-only
COPY assets/potentials/TMD.ILP /app/assets/potentials/TMD.ILP
COPY assets/licenses/ /app/assets/licenses/
COPY assets/n2-seed24101/ /app/assets/n2-seed24101/
COPY assets/tools/md/ /app/packages/case-05-few-layer-md-mode-assignment/md/
COPY assets/tools/generic-mode-evidence.schema.json /app/packages/case-05-few-layer-md-mode-assignment/analysis/generic-mode-evidence.schema.json
COPY assets/requirements.lock.txt /tmp/bench15-requirements.lock.txt
COPY assets/wheels/ /tmp/bench15-wheels/
COPY assets/verification.md /app/verification.md
RUN python3 -m venv /opt/bench15-science \
 && /opt/bench15-science/bin/pip install --no-index --find-links=/tmp/bench15-wheels --require-hashes -r /tmp/bench15-requirements.lock.txt \
 && /opt/bench15-science/bin/pip check \
 && cp /tmp/bench15-requirements.lock.txt /opt/bench15-science/requirements.lock.txt \
 && rm -rf /tmp/bench15-wheels /tmp/bench15-requirements.lock.txt \
 && mkdir -p /app/packages/case-05-few-layer-md-mode-assignment /app/acceptance/hpc/case-05-few-layer-md-mode-assignment \
 && ln -s /app/assets /app/packages/case-05-few-layer-md-mode-assignment/environment \
 && ln -s /app/assets/potentials /app/acceptance/hpc/case-05-few-layer-md-mode-assignment/potentials
ENV PATH="/opt/bench15-science/bin:${PATH}" \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
