FROM compchembench-connectivity:hpc
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
COPY assets/ /app/environment/assets/
COPY assets/runtime/harbor_remote_lifecycle.py /usr/local/bin/bench28-remote-lifecycle.py
RUN ln -s /app/environment /environment
