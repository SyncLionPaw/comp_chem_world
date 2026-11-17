FROM --platform=linux/amd64 compchembench-base:2.1.267

WORKDIR /app

COPY assets/ /app/environment/assets/

COPY assets/wheels/python312/ /tmp/vendor-wheels/

RUN cd /tmp/vendor-wheels && sha256sum -c SHA256SUMS

RUN rm -rf /app/environment/assets/wheels /app/environment/assets/dependencies \
 && test "$(dpkg --print-architecture)" = amd64 \
 && python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
 && python3 -m venv /opt/science \
 && /opt/science/bin/pip install --no-index --find-links=/tmp/vendor-wheels --only-binary=:all: networkx==3.7 \
 && /opt/science/bin/pip check \
 && rm -rf /tmp/vendor-wheels

RUN ln -s environment/assets /app/inputs

ENV PATH="/opt/science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1
