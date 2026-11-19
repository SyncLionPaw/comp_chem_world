FROM comp-chem-world-base
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      gcc g++ python3-dev \
      libgfortran5 liblapack3 libblas3 libgomp1 \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/ccb-venv
COPY assets/wheels/ /opt/wheels/
COPY assets/requirements.lock.txt /tmp/requirements.lock
RUN /opt/ccb-venv/bin/pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && printf '%s\n' \
      'setuptools==84.0.0 \' \
      '    --hash=sha256:51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670' \
      'wheel==0.45.1 \' \
      '    --hash=sha256:708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248' \
      > /tmp/build-tools.lock \
 && /opt/ccb-venv/bin/pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/build-tools.lock \
 && echo "3d0208f56507649b5af91bbb128f650a6f86de1b5a9af780e6479145e5362ea3  /opt/wheels/parmed-4.3.0.tar.gz" | sha256sum -c - \
 && /opt/ccb-venv/bin/pip install --no-cache-dir --no-index --find-links=/opt/wheels --no-build-isolation --no-deps /opt/wheels/parmed-4.3.0.tar.gz \
 && /opt/ccb-venv/bin/pip check \
 && rm -rf /opt/wheels
ENV PATH=/opt/ccb-venv/bin:$PATH
COPY assets/ /tmp/task-assets/
RUN rm -rf /tmp/task-assets/wheels /tmp/task-assets/requirements.lock.txt \
 && mkdir -p /app/inputs \
 && cp -a /tmp/task-assets/. /app/inputs/ \
 && rm -rf /tmp/task-assets
WORKDIR /app
CMD ["python", "--version"]
