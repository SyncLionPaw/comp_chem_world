FROM compchembench-connectivity:hpc
WORKDIR /app
COPY wheels/ /opt/wheels/
COPY requirements.lock.txt /tmp/requirements.lock
RUN python3.12 -m venv /opt/case-python \
 && /opt/case-python/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && /opt/case-python/bin/python -m pip check \
 && rm -rf /opt/wheels
ENV PATH="/opt/case-python/bin:${PATH}"
COPY assets/M_WT.top assets/M_WT.rst assets/M_V72I.top assets/M_V72I.rst /environment/assets/
COPY assets/md_inputs/ /environment/assets/md_inputs/
COPY assets/M_WT.top assets/M_WT.rst assets/M_V72I.top assets/M_V72I.rst /app/assets/
COPY assets/md_inputs/ /app/assets/md_inputs/
COPY assets/M_WT.top assets/M_WT.rst assets/M_V72I.top assets/M_V72I.rst /app/environment/assets/
COPY assets/md_inputs/ /app/environment/assets/md_inputs/
COPY assets/scripts/submit-hpc.sh assets/scripts/task71-hpc-run.sh /app/environment/
RUN mkdir -p /app/final
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools
