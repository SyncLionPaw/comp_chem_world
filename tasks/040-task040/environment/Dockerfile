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
COPY assets/2K_CO2/ /app/environment/assets/2K_CO2/
COPY assets/IS_budget.json assets/IS_native.tar.gz assets/IS_native_manifest.json \
     assets/IS_seed_panel.extxyz assets/IS_seed_provenance.json assets/methods.json \
     assets/output-contract.json /app/environment/assets/
LABEL org.compchembench.bench06.case="case-05-inner-sphere-budgeted" org.compchembench.bench06.wrapper="shared-ccbench-public-base"
