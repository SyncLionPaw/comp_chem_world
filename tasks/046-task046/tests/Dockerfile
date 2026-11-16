FROM comp-chem-world-base
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TF_CPP_MIN_LOG_LEVEL=2
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv util-linux libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/verify && /opt/verify/bin/pip install --no-cache-dir numpy==1.26.4
ENV PATH="/opt/verify/bin:${PATH}"
WORKDIR /app
COPY environment/assets/inputs/ /app/inputs/
COPY environment/assets/output-contract.json /app/output-contract.json
COPY task.toml instruction.md /opt/bench07-task/
COPY environment/assets/ /opt/bench07-task/environment/assets/
COPY tests/ /opt/bench07-task/tests/
RUN python3 -I /opt/bench07-task/tests/harbor_runtime/prepare.py
RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts && chmod 0700 /logs
COPY environment/assets/compute-budget.yaml /app/compute-budget.yaml
