FROM comp-chem-world-base AS numpy-build
COPY assets/runtime-deps/*.whl /opt/case-wheels/
COPY assets/runtime-deps/grader-requirements.lock.txt /opt/case-requirements.lock.txt
RUN python3 -m venv /opt/case-venv \
    && /opt/case-venv/bin/pip install --no-index --find-links=/opt/case-wheels --require-hashes -r /opt/case-requirements.lock.txt

FROM comp-chem-world-base
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=numpy-build /opt/case-venv /opt/case-venv
ENV PATH=/opt/case-venv/bin:$PATH
COPY assets/public-inputs-v2/ /app/environment/assets/public-inputs-v2/
COPY assets/public-docs-v2/ /app/environment/assets/public-docs-v2/
RUN ln -s /app/environment /environment && ln -s /app/environment/assets/public-inputs-v2 /app/public-inputs-v2
