FROM compchembench-connectivity:hpc
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN mkdir -p /app/submission
