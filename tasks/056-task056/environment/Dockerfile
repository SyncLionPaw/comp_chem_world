FROM comp-chem-world-base
RUN python3 -m venv /opt/carrier-local
ENV PATH="/opt/carrier-local/bin:${PATH}"
RUN <<'CASE57_BUILD'
set -eu
cat <<'CASE57_REQUIREMENTS' > /opt/requirements.lock.txt
numpy==2.4.2 --hash=sha256:9e35d3e0144137d9fdae62912e869136164534d64a169f86438bc9561b6ad49f --hash=sha256:6d82351358ffbcdcd7b686b90742a9b86632d6c1c051016484fa0b326a0a1548
CASE57_REQUIREMENTS
python -m pip install --no-cache-dir --require-hashes -r /opt/requirements.lock.txt
python -m pip check
rm /opt/requirements.lock.txt
CASE57_BUILD
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 \
    && rm -rf /var/lib/apt/lists/*
COPY assets/ /app/environment/assets/
ENV TMPDIR=/dev/shm
WORKDIR /app
LABEL org.opencontainers.image.title="CompChemWorld Bench09 case-02-mechanism-diagnosis" org.opencontainers.image.version="20261024-v4"
