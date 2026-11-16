FROM --platform=linux/amd64 compchembench-connectivity:hpc

WORKDIR /app

COPY assets/wheels/ /tmp/suite29-wheels/
COPY assets/requirements.lock.txt /tmp/suite29-requirements.lock.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,id=suite29-apt-lists-amd64,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,id=suite29-apt-archives-amd64,target=/var/cache/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends g++ libgomp1 python3-dev \
 && python3 -m venv /opt/suite29-science \
 && /opt/suite29-science/bin/pip install --no-index --find-links=/tmp/suite29-wheels --require-hashes -r /tmp/suite29-requirements.lock.txt \
 && /opt/suite29-science/bin/pip check

FROM --platform=linux/amd64 compchembench-connectivity:hpc

WORKDIR /app

COPY assets/ /app/assets/

COPY --from=0 /opt/suite29-science/ /opt/suite29-science/

RUN --mount=type=cache,id=suite29-apt-lists-amd64,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,id=suite29-apt-archives-amd64,target=/var/cache/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
 && mkdir -p /app/results \
 && rm -rf /app/assets/wheels /app/assets/requirements.lock.txt \
 && ln -s /app/assets/inputs /app/inputs \
 && /opt/suite29-science/bin/python -c "import numpy,scipy,ase,calorine,phonopy"

ENV PATH="/opt/suite29-science/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1
