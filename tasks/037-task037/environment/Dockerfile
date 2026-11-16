FROM comp-chem-world-base
WORKDIR /app
COPY assets/dependencies/vendor/wheels/ /tmp/task-wheelhouse/
COPY assets/dependencies/vendor/requirements.lock.txt /tmp/task-requirements.lock.txt
RUN python3 -m venv /opt/task-science \
    && /opt/task-science/bin/python -m pip install --no-index \
         --find-links=/tmp/task-wheelhouse --require-hashes -r /tmp/task-requirements.lock.txt \
    && /opt/task-science/bin/python -m pip check \
    && rm -rf /tmp/task-wheelhouse /tmp/task-requirements.lock.txt
ENV PATH="/opt/task-science/bin:${PATH}" \
    MPLBACKEND=Agg \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
COPY assets/ /app/environment/assets/
COPY assets/_runtime/trajectory-manifest.json assets/_runtime/restore-trajectories.py /app/environment/
# Build wheels were already installed from /tmp; do not leave them agent-visible.
RUN rm -rf /app/environment/assets/dependencies \
    && python /app/environment/restore-trajectories.py
LABEL org.compchembench.bench06.case="case-02-spectrum" org.compchembench.bench06.wrapper="shared-ccbench-public-base"
