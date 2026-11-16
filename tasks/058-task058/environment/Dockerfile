FROM comp-chem-world-base
RUN python3 -m venv /opt/carrier-local
ENV PATH="/opt/carrier-local/bin:${PATH}"
RUN <<'CASE59_BUILD'
set -eu
cat <<'CASE59_REQUIREMENTS' > /opt/requirements.lock.txt
numpy==2.4.2 --hash=sha256:9e35d3e0144137d9fdae62912e869136164534d64a169f86438bc9561b6ad49f --hash=sha256:6d82351358ffbcdcd7b686b90742a9b86632d6c1c051016484fa0b326a0a1548
CASE59_REQUIREMENTS
python -m pip install --no-cache-dir --require-hashes -r /opt/requirements.lock.txt
python -m pip check
rm /opt/requirements.lock.txt
CASE59_BUILD
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 \
    && rm -rf /var/lib/apt/lists/*
RUN <<'PYPDF_BUILD'
set -eu
cat <<'PYPDF_REQUIREMENTS' > /opt/pypdf-requirements.lock.txt
pypdf==5.9.0 --hash=sha256:be10a4c54202f46d9daceaa8788be07aa8cd5ea8c25c529c50dd509206382c35
PYPDF_REQUIREMENTS
python -m pip install --no-cache-dir --no-deps --require-hashes -r /opt/pypdf-requirements.lock.txt
rm /opt/pypdf-requirements.lock.txt
PYPDF_BUILD
COPY assets/ /app/environment/assets/
ENV TMPDIR=/dev/shm
WORKDIR /app
LABEL org.opencontainers.image.title="CompChemWorld Bench09 case-04-seebeck-validity" org.opencontainers.image.version="20261024-v4"
