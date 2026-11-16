FROM comp-chem-world-base
WORKDIR /app
COPY assets/ /app/assets/
COPY assets/_runtime/trajectory-manifest.json /app/trajectory-manifest.json
COPY assets/_runtime/restore-trajectories.py /app/environment/restore-trajectories.py
RUN BENCH06_ENV_ROOT=/app python3 /app/environment/restore-trajectories.py
LABEL org.compchembench.bench06.case="case-04-outer-sphere-budgeted" org.compchembench.bench06.wrapper="shared-ccbench-public-base"
