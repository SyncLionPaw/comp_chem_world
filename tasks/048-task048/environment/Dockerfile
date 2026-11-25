FROM compchembench-connectivity:hpc

WORKDIR /app

COPY AGENTS.md /app/AGENTS.md
# Harbor Terminus requires these terminal tools.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/final
