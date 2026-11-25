FROM compchembench-connectivity:hpc
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
COPY assets/dependencies/wheels/ /tmp/bench12-wheelhouse/
COPY assets/dependencies/requirements.lock.txt /tmp/bench12-requirements.lock.txt
RUN python3 -m venv /opt/bench12-science \
    && /opt/bench12-science/bin/python -m pip install --no-index \
         --find-links=/tmp/bench12-wheelhouse --require-hashes -r /tmp/bench12-requirements.lock.txt \
    && /opt/bench12-science/bin/python -m pip check \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /tmp/bench12-wheelhouse /tmp/bench12-requirements.lock.txt
ENV PATH="/opt/bench12-science/bin:${PATH}"
COPY assets/inputs/ /app/inputs/
RUN mkdir -p /app/final
LABEL org.compchembench.release_rev="20261024-r6.1"
