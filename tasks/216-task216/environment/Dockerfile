FROM comp-chem-world-base

WORKDIR /app

COPY assets/ /opt/task-inputs/

RUN python3 -m venv --system-site-packages /opt/wpd-science \
 && /opt/wpd-science/bin/python -c "import math,tarfile,tomllib,json" \
 && ln -s /opt/task-inputs /inputs \
 && ln -s /opt/task-inputs /app/inputs

ENV PATH="/opt/wpd-science/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1

COPY assets/output-contract.md /app/output-contract.md
