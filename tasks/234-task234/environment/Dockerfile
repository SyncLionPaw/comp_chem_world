FROM --platform=linux/amd64 compchembench-base:2.1.267

WORKDIR /app

COPY assets/ /app/environment/assets/

RUN test "$(dpkg --print-architecture)" = amd64 \
 && python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
 && python3 -m venv /opt/science \
 && /opt/science/bin/pip check

RUN rm -rf /app/environment/assets/wheels /app/environment/assets/dependencies

ENV PATH="/opt/science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1
