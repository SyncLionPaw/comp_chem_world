FROM comp-chem-world-base

# Harbor Terminus requires terminal tools before the Agent phase begins.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*
ARG CASE_BUILD_TAG=20261024-case03-decision-revision
LABEL org.compchemworld.case="case03-force-trust-audit" \
      org.compchemworld.revision="20261024-case02-03-decision-revision"
COPY assets/requirements.lock.txt /tmp/case03-requirements.lock.txt
RUN python3 -m venv /opt/case03-venv \
    && /opt/case03-venv/bin/pip install --no-cache-dir -r /tmp/case03-requirements.lock.txt \
    && rm /tmp/case03-requirements.lock.txt
ENV PATH=/opt/case03-venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1
WORKDIR /app
COPY assets/inputs/ /app/inputs/
