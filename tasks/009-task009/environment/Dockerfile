FROM comp-chem-world-base
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY assets/ /app/assets/
RUN python3 -m venv --system-site-packages /opt/case-science
ENV PATH="/opt/case-science/bin:${PATH}"
RUN printf '%s\n' \
      'numpy==2.5.3 --hash=sha256:b7e18c623bb5c95acb3b3328861272816ba199fb531921c5d6d0b675f1fde9e3 --hash=sha256:76c2c1e6bfa5c84adc6434dfbf013aa92096a7985221762c8f11fedfd20fff58' \
    | python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /dev/stdin \
    && python -m pip check
