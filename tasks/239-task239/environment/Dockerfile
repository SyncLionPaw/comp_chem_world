FROM comp-chem-world-base

WORKDIR /app

COPY assets/ /app/environment/assets/

RUN python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
 && python3 -m venv /opt/science \
 && /opt/science/bin/pip check

RUN ln -s environment/assets /app/inputs

RUN rm -rf /app/environment/assets/wheels /app/environment/assets/dependencies

ENV PATH="/opt/science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1
