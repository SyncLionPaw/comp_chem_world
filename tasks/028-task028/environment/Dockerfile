FROM compchembench-connectivity:hpc
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 && python3 -m pip install --break-system-packages --no-cache-dir asciinema==2.4.0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV APP=/app
COPY assets/_runtime/output-contract.json /app/output-contract.json
COPY assets/_runtime/README.md /app/research-service.md
RUN mkdir -p /app/final && ikkem-slurm --help >/dev/null
