FROM comp-chem-world-base
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TF_CPP_MIN_LOG_LEVEL=2
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv util-linux libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY environment/assets/requirements.lock.txt /tmp/science-requirements.txt
RUN python3 -m venv /opt/deepmd && /opt/deepmd/bin/pip install --no-cache-dir --require-hashes -r /tmp/science-requirements.txt && rm /tmp/science-requirements.txt
ENV PATH="/opt/deepmd/bin:${PATH}"
WORKDIR /app
COPY environment/assets/inputs/ /app/inputs/
COPY environment/assets/output-contract.json /app/output-contract.json
COPY task.toml instruction.md /opt/bench07-task/
COPY environment/assets/ /opt/bench07-task/environment/assets/
COPY tests/ /opt/bench07-task/tests/
# Host umask (e.g. 0002) can leave refs.json group-writable; prepare rejects that.
RUN chmod go-w /opt/bench07-task/tests/refs.json \
 && python3 -I /opt/bench07-task/tests/harbor_runtime/prepare.py
RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts && chmod 0700 /logs
