FROM comp-chem-world-base
WORKDIR /app
COPY environment/assets/runtime/requirements.lock.txt environment/assets/runtime/package-provenance.json /opt/runtime/netfluids/
COPY environment/assets/runtime/system-packages/ /tmp/netfluids-system-packages/
RUN dpkg -i /tmp/netfluids-system-packages/*.deb && rm -rf /tmp/netfluids-system-packages
RUN python3 -m venv /opt/netfluids
ENV PATH="/opt/netfluids/bin:${PATH}" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY environment/assets/runtime/wheels/ /tmp/netfluids-wheels/
RUN python -m pip install --no-index --find-links=/tmp/netfluids-wheels --require-hashes -r /opt/runtime/netfluids/requirements.lock.txt \
    && python -m pip check && rm -rf /tmp/netfluids-wheels
COPY environment/assets/simulation/ /app/environment/assets/simulation/
COPY environment/assets/RPC-PROTOCOL.md /app/environment/RPC-PROTOCOL.md
COPY tests/ /tests/
ENV APP=/app TESTS=/tests LOGS=/logs/verifier
