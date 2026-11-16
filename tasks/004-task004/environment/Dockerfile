FROM comp-chem-world-base

WORKDIR /app
RUN mkdir -p /app/assets

COPY assets/master_s115_blindarm.csv /app/assets/master_s115_blindarm.csv
COPY assets/SC-012-D0SC04896H-s120.csv /app/assets/SC-012-D0SC04896H-s120.csv
COPY assets/SC-012-D0SC04896H-s113.npy /app/assets/SC-012-D0SC04896H-s113.npy
COPY assets/SC-012-D0SC04896H-s114.npy /app/assets/SC-012-D0SC04896H-s114.npy
COPY assets/SC-012-D0SC04896H-s117.npy /app/assets/SC-012-D0SC04896H-s117.npy
COPY assets/SC-012-D0SC04896H-s118.npy /app/assets/SC-012-D0SC04896H-s118.npy
COPY assets/SC-012-D0SC04896H-s119.npy /app/assets/SC-012-D0SC04896H-s119.npy
COPY assets/S12_replicate_barrier_pairs.csv /app/assets/S12_replicate_barrier_pairs.csv

COPY assets/dependencies/vendor/wheels/ /tmp/case04-wheelhouse/
COPY assets/dependencies/vendor/requirements.lock.txt /tmp/case04-requirements.lock.txt
RUN python3 -m venv /opt/case04-python \
    && /opt/case04-python/bin/python3 -m pip install --no-index \
         --find-links=/tmp/case04-wheelhouse --require-hashes \
         -r /tmp/case04-requirements.lock.txt \
    && /opt/case04-python/bin/python3 -m pip check \
    && rm -rf /tmp/case04-wheelhouse /tmp/case04-requirements.lock.txt

ENV PATH="/opt/case04-python/bin:${PATH}" \
    MPLBACKEND=Agg \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    BLIS_NUM_THREADS=1
