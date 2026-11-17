FROM --platform=linux/amd64 compchembench-base:2.1.267

WORKDIR /app

COPY assets/ /opt/task-inputs/

RUN test "$(dpkg --print-architecture)" = amd64 \
 && python3 -m venv --system-site-packages /opt/wpd-science \
 && /opt/wpd-science/bin/python -c "import math,tarfile,tomllib,json" \
 && ln -s /opt/task-inputs /inputs \
 && ln -s /opt/task-inputs /app/inputs

ENV PATH="/opt/wpd-science/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1
