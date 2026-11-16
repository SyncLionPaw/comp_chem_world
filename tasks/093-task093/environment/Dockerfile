FROM comp-chem-world-base

WORKDIR /app

COPY assets/requirements.lock.txt /tmp/ihf-requirements.lock.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir --require-hashes -r /tmp/ihf-requirements.lock.txt \
    && python3 -m pip check \
    && rm /tmp/ihf-requirements.lock.txt

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tmux asciinema \
    && rm -rf /var/lib/apt/lists/*

COPY assets/ /app/assets/
