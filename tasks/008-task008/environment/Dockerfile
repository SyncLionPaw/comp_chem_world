FROM comp-chem-world-base
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY assets/ /app/assets/
