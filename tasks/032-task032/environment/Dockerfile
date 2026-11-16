FROM comp-chem-world-base
LABEL org.compchemworld.approved-parent-config-id="sha256:8867729dcdaa6076595d2935d53ad64bfca944171c1f258585a51ead1007852e"
WORKDIR /app
COPY assets/runtime/requirements.lock.txt assets/runtime/package-provenance.json /opt/runtime/netfluids/
COPY assets/runtime/system-packages/ /tmp/netfluids-system-packages/
RUN dpkg -i /tmp/netfluids-system-packages/*_$(dpkg --print-architecture).deb && rm -rf /tmp/netfluids-system-packages
RUN python3 -m venv /opt/netfluids
ENV PATH="/opt/netfluids/bin:${PATH}" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY assets/runtime/wheels/ /tmp/netfluids-wheels/
RUN python -m pip install --no-index --find-links=/tmp/netfluids-wheels --require-hashes -r /opt/runtime/netfluids/requirements.lock.txt \
    && python -m pip check && rm -rf /tmp/netfluids-wheels
COPY assets/RDFs_rpL5_charged_A0Pep.txt assets/RDFs_rpL5_charged_A1Pep.txt assets/RDFs_rpL5_charged_A2Pep.txt assets/rpL5_example_traj.dcd assets/rpL5_init.data assets/selections.json /app/environment/assets/
