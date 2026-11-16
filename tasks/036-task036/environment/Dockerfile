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
COPY assets/water_CO2/ /app/environment/assets/water_CO2/
COPY assets/water_CO2anion/ /app/environment/assets/water_CO2anion/
COPY assets/2K_CO2/ /app/environment/assets/2K_CO2/
COPY assets/2K_CO2anion/ /app/environment/assets/2K_CO2anion/
COPY assets/_runtime/trajectory-manifest.json assets/_runtime/restore-trajectories.py /app/environment/
RUN BENCH06_ENV_ROOT=/app/environment python /app/environment/restore-trajectories.py \
    && find /app/environment/assets -type f -name '10ps.traj.gz.*' -delete \
    && rm -f /app/environment/trajectory-manifest.json /app/environment/restore-trajectories.py
LABEL org.compchembench.bench06.case="case-01-geometry" org.compchembench.bench06.wrapper="shared-ccbench-public-base"
