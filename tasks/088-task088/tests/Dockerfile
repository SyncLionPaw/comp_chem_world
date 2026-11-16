# Credential-free offline verifier for the remote HPC candidate task.
FROM comp-chem-world-base
WORKDIR /app
COPY environment/assets/requirements.lock.txt /tmp/bench14-requirements.lock.txt
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gromacs \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --break-system-packages --no-cache-dir --require-hashes -r /tmp/bench14-requirements.lock.txt \
    && python3 -m pip check \
    && rm /tmp/bench14-requirements.lock.txt
