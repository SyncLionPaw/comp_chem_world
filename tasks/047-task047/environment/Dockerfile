FROM comp-chem-world-base

# Harbor Terminus requires terminal tools before the Agent phase begins.
RUN apt-get update && apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY assets/inputs/ /app/inputs/
COPY assets/output-contract.json /app/output-contract.json
