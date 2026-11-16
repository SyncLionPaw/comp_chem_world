FROM --platform=linux/amd64 compchembench-connectivity:hpc
WORKDIR /app

COPY assets/wheels/nnp/ /tmp/nnp-wheels/
COPY assets/wheels/nnp-requirements.lock.txt /tmp/nnp-requirements.lock.txt

# This identical layer precedes case-specific assets so both case images reuse it.
RUN UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install 3.9.25 \
 && UV_PYTHON_INSTALL_DIR=/opt/uv-python uv venv --python 3.9.25 /opt/zeolite-nnp \
 && uv pip install --python /opt/zeolite-nnp/bin/python --no-index --find-links=/tmp/nnp-wheels --require-hashes -r /tmp/nnp-requirements.lock.txt \
 && /opt/zeolite-nnp/bin/python -c 'import sys,ase,numpy,scipy,torch,schnetpack,importlib.metadata; assert sys.version_info[:3]==(3,9,25) and ase.__version__=="3.22.1" and numpy.__version__=="1.21.5" and scipy.__version__=="1.10.1" and torch.__version__.split("+")[0]=="1.13.1" and importlib.metadata.version("schnetpack")=="1.0.1"'

COPY assets/inputs/ /opt/zeolite-public/inputs/
COPY assets/public/ /opt/zeolite-public/public/
COPY assets/runtime/ /app/runtime/

COPY assets/wheels/python312/ /tmp/zeolite-wheels/

RUN cd /tmp/zeolite-wheels && sha256sum -c SHA256SUMS

RUN test "$(dpkg --print-architecture)" = amd64 \
 && python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
 && python3 -m venv /opt/zeolite-science \
 && /opt/zeolite-science/bin/pip install --no-index --only-binary=:all: --find-links=/tmp/zeolite-wheels ase==3.22.1 contourpy==1.3.3 cycler==0.12.1 fonttools==4.67.0 iniconfig==2.3.1 kiwisolver==1.5.1 matplotlib==3.10.7 numpy==1.26.4 packaging==26.3 pillow==13.0.0 pluggy==1.7.0 pygments==2.21.0 pyparsing==3.3.3 pytest==9.1.1 python-dateutil==3.0.0 pyyaml==6.0.3 scipy==1.13.1 six==1.17.0 tzdata==2026.5 \
 && /opt/zeolite-science/bin/pip check \
 && rm -rf /tmp/zeolite-wheels \
 && ln -s /opt/zeolite-public/inputs /app/inputs \
 && ln -s /opt/zeolite-public/public /app/public

ENV PATH="/opt/zeolite-science/bin:${PATH}" \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
