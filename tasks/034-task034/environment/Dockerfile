FROM compchembench-connectivity:hpc
LABEL org.compchemworld.approved-parent-config-id="sha256:9da94d543f2356fb47463ba00896e611256921a721c31a3eba2ea48a89aff124"
WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
COPY assets/runtime/requirements.lock.txt assets/runtime/package-provenance.json /opt/runtime/netfluids/
COPY assets/runtime/system-packages/ /tmp/netfluids-system-packages/
RUN dpkg -i /tmp/netfluids-system-packages/*_$(dpkg --print-architecture).deb && rm -rf /tmp/netfluids-system-packages
RUN python3 -m venv /opt/netfluids
ENV PATH="/opt/netfluids/bin:${PATH}" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY assets/runtime/wheels/ /tmp/netfluids-wheels/
RUN python -m pip install --no-index --find-links=/tmp/netfluids-wheels --require-hashes -r /opt/runtime/netfluids/requirements.lock.txt \
    && python -m pip check && rm -rf /tmp/netfluids-wheels
COPY assets/simulation/ /app/environment/assets/simulation/
COPY assets/RPC-PROTOCOL.md /app/environment/RPC-PROTOCOL.md
