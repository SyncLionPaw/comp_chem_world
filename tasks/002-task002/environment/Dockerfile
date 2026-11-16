FROM comp-chem-world-base

WORKDIR /app
RUN mkdir -p /app/assets
COPY assets/S5_model_benchmark.csv /app/assets/S5_model_benchmark.csv
COPY assets/SC-012-D0SC04896H-s007.py /app/assets/SC-012-D0SC04896H-s007.py
COPY assets/SC-012-D0SC04896H-s112.csv /app/assets/SC-012-D0SC04896H-s112.csv
COPY assets/SC-012-D0SC04896H-s115.csv /app/assets/SC-012-D0SC04896H-s115.csv
COPY assets/SC-012-D0SC04896H-s118.npy /app/assets/SC-012-D0SC04896H-s118.npy
COPY assets/SC-012-D0SC04896H-s119.npy /app/assets/SC-012-D0SC04896H-s119.npy
COPY assets/SC-012-D0SC04896H-s120.csv /app/assets/SC-012-D0SC04896H-s120.csv
COPY assets/SC-012-D0SC04896H-s138.csv /app/assets/SC-012-D0SC04896H-s138.csv
COPY assets/SC-012-D0SC04896H-s140.csv /app/assets/SC-012-D0SC04896H-s140.csv
COPY assets/SC-012-D0SC04896H-s141.csv /app/assets/SC-012-D0SC04896H-s141.csv
COPY assets/SC-012-D0SC04896H-s142.csv /app/assets/SC-012-D0SC04896H-s142.csv
COPY assets/SC-012-D0SC04896H-s143.csv /app/assets/SC-012-D0SC04896H-s143.csv
COPY assets/SC-012-D0SC04896H-s144.csv /app/assets/SC-012-D0SC04896H-s144.csv
COPY assets/dependencies/vendor/wheels/ /tmp/case02-wheelhouse/
COPY assets/dependencies/vendor/requirements.lock.txt /tmp/case02-requirements.lock.txt
RUN python3 -m venv /opt/case02-python \
    && /opt/case02-python/bin/python3 -m pip install --no-index \
         --find-links=/tmp/case02-wheelhouse --require-hashes \
         -r /tmp/case02-requirements.lock.txt \
    && /opt/case02-python/bin/python3 -m pip check \
    && rm -rf /tmp/case02-wheelhouse /tmp/case02-requirements.lock.txt
ENV PATH="/opt/case02-python/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    BLIS_NUM_THREADS=1
