FROM comp-chem-world-base
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' 'numpy==2.5.3 --hash=sha256:b7e18c623bb5c95acb3b3328861272816ba199fb531921c5d6d0b675f1fde9e3 \' '    --hash=sha256:76c2c1e6bfa5c84adc6434dfbf013aa92096a7985221762c8f11fedfd20fff58' > /tmp/requirements.lock.txt \
    && python3 -m pip install --break-system-packages --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt \
    && python3 -m pip check \
    && rm /tmp/requirements.lock.txt

WORKDIR /app
COPY assets/ /app/environment/assets/
