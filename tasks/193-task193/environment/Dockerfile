FROM --platform=linux/amd64 compchembench-base:2.1.267

WORKDIR /app

COPY assets/inputs/ /opt/zeolite-public/inputs/
COPY assets/public/ /opt/zeolite-public/public/

COPY assets/wheels/python312/ /tmp/zeolite-wheels/

RUN cd /tmp/zeolite-wheels && sha256sum -c SHA256SUMS

RUN test "$(dpkg --print-architecture)" = amd64 \
 && python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
 && python3 -m venv /opt/zeolite-science \
 && /opt/zeolite-science/bin/pip install --no-index --only-binary=:all: --find-links=/tmp/zeolite-wheels ase==3.22.1 contourpy==1.3.3 cycler==0.12.1 fonttools==4.67.0 iniconfig==2.3.1 kiwisolver==1.5.1 matplotlib==3.10.7 numpy==1.26.4 packaging==26.3 pillow==13.0.0 pluggy==1.7.0 pygments==2.21.0 pyparsing==3.3.3 pytest==9.1.1 python-dateutil==3.0.0 pyyaml==6.0.3 scipy==1.13.1 six==1.17.0 tzdata==2026.5 \
 && /opt/zeolite-science/bin/pip check \
 && rm -rf /tmp/zeolite-wheels \
 && cp -r /opt/zeolite-public/inputs /app/inputs \
 && cp -r /opt/zeolite-public/public /app/public

ENV PATH="/opt/zeolite-science/bin:${PATH}" \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
