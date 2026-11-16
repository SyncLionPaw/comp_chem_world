FROM comp-chem-world-base

WORKDIR /app
RUN mkdir -p /app/assets
COPY assets/S5_model_benchmark.csv /app/assets/S5_model_benchmark.csv
COPY assets/SC-012-D0SC04896H-s090.ipynb /app/assets/SC-012-D0SC04896H-s090.ipynb
COPY assets/SC-012-D0SC04896H-s115.csv /app/assets/SC-012-D0SC04896H-s115.csv
COPY assets/SC-012-D0SC04896H-s118.npy /app/assets/SC-012-D0SC04896H-s118.npy
COPY assets/SC-012-D0SC04896H-s119.npy /app/assets/SC-012-D0SC04896H-s119.npy
COPY assets/SC-012-D0SC04896H-s120.csv /app/assets/SC-012-D0SC04896H-s120.csv
COPY assets/SC-012-D0SC04896H-s121.csv /app/assets/SC-012-D0SC04896H-s121.csv
COPY assets/SC-012-D0SC04896H-s131.csv /app/assets/SC-012-D0SC04896H-s131.csv
COPY assets/SC-012-D0SC04896H-s138.csv /app/assets/SC-012-D0SC04896H-s138.csv
COPY assets/fig8a_learning_curve.csv /app/assets/fig8a_learning_curve.csv
COPY assets/dependencies/vendor/wheels/ /tmp/case03-wheelhouse/
COPY assets/dependencies/vendor/requirements.lock.txt /tmp/case03-requirements.lock.txt
RUN python3 -m venv /opt/case03-python \
    && /opt/case03-python/bin/python3 -m pip install --no-index \
         --find-links=/tmp/case03-wheelhouse --require-hashes \
         -r /tmp/case03-requirements.lock.txt \
    && /opt/case03-python/bin/python3 -m pip check \
    && rm -rf /tmp/case03-wheelhouse /tmp/case03-requirements.lock.txt
ENV PATH="/opt/case03-python/bin:${PATH}" \
    MPLBACKEND=Agg \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    BLIS_NUM_THREADS=1
