FROM comp-chem-world-base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_UPDATES=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl git python3 python3-pip python3-venv \
       libgomp1 libstdc++6 poppler-utils \
    && rm -rf /var/lib/apt/lists/*


ENV VIRTUAL_ENV=/opt/organic-emitter-rate-constants
ENV PATH="/opt/organic-emitter-rate-constants/bin:${PATH}"

COPY assets/requirements.lock.txt /tmp/requirements.lock.txt
RUN uv venv "$VIRTUAL_ENV" --python /usr/bin/python3 \
    && uv pip install --python "$VIRTUAL_ENV/bin/python" \
       --require-hashes -r /tmp/requirements.lock.txt \
    && uv pip check --python "$VIRTUAL_ENV/bin/python"

COPY assets/tools/literature.py /app/tools/literature.py
COPY assets/output-interface.md /app/output-interface.md
RUN chmod 0755 /app/tools/literature.py
WORKDIR /app
