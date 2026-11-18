FROM comp-chem-world-base

WORKDIR /app

COPY assets/inputs/ /app/inputs/
COPY assets/public/ /app/public/
COPY assets/runtime/ /app/runtime/

RUN python3 -c "import csv, hashlib, json, math, tomllib" \
 && ln -s /usr/bin/python3 /usr/local/bin/python \
 && mkdir -p /app/results

ENV PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
