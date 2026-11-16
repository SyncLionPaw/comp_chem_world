FROM comp-chem-world-base

LABEL org.compchemworld.bench="25_SPaiNN-Nonadiabatic-Dynamics" \
      org.compchemworld.case="case-02" \
      org.compchemworld.runtime="local-case-image" \
      org.compchemworld.dependencies="bench25-local-python312-hash-lock"

WORKDIR /app
COPY assets/build/requirements.in assets/build/requirements.lock.txt /tmp/case02-runtime/
RUN uv venv /opt/case02-runtime \
    && uv pip install --python /opt/case02-runtime/bin/python --no-cache --require-hashes -r /tmp/case02-runtime/requirements.lock.txt \
    && uv pip check --python /opt/case02-runtime/bin/python \
    && /opt/case02-runtime/bin/python -c 'import ase, matplotlib, numpy; from PIL import Image' \
    && rm -rf /root/.ssh \
    && install -d -m 0700 /root/.ssh
ENV PATH="/opt/case02-runtime/bin:${PATH}"
COPY assets/README.md assets/output-contract.md /app/inputs/
COPY assets/databases/ /app/inputs/databases/
COPY assets/build/input-hashes.sha256 /tmp/case02-input-hashes.sha256
RUN cd /app && sha256sum -c /tmp/case02-input-hashes.sha256

ARG BENCH25_CONTEXT_SHA256
ARG BENCH25_PARENT_IMAGE_ID
LABEL org.compchemworld.build-context-sha256="${BENCH25_CONTEXT_SHA256}" \
      org.compchemworld.standard-parent-image-id="${BENCH25_PARENT_IMAGE_ID}"
