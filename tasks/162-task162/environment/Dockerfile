FROM comp-chem-world-base

LABEL org.compchemworld.bench="25_SPaiNN-Nonadiabatic-Dynamics" \
      org.compchemworld.case="case-01" \
      org.compchemworld.runtime="local-case-image" \
      org.compchemworld.dependencies="bench25-local-python312-hash-lock"

WORKDIR /app
COPY assets/build/requirements.in assets/build/requirements.lock.txt /tmp/case01-runtime/
RUN uv venv /opt/case01-runtime \
    && uv pip install --python /opt/case01-runtime/bin/python --no-cache --require-hashes -r /tmp/case01-runtime/requirements.lock.txt \
    && uv pip check --python /opt/case01-runtime/bin/python \
    && /opt/case01-runtime/bin/python -c 'import ase, numpy' \
    && rm -rf /root/.ssh \
    && install -d -m 0700 /root/.ssh
ENV PATH="/opt/case01-runtime/bin:${PATH}"
COPY assets/README.md assets/output-contract.md /app/inputs/
COPY assets/databases/ /app/inputs/databases/
COPY assets/build/input-hashes.sha256 /tmp/case01-input-hashes.sha256
RUN cd /app && sha256sum -c /tmp/case01-input-hashes.sha256

ARG BENCH25_CONTEXT_SHA256
ARG BENCH25_PARENT_IMAGE_ID
LABEL org.compchemworld.build-context-sha256="${BENCH25_CONTEXT_SHA256}" \
      org.compchemworld.standard-parent-image-id="${BENCH25_PARENT_IMAGE_ID}"
