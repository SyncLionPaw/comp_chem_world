FROM comp-chem-world-base

WORKDIR /app

COPY assets/inputs/ /app/inputs/
COPY assets/public/ /app/public/

COPY assets/wheels/python312/ /tmp/batio3-wheels/

RUN cd /tmp/batio3-wheels && sha256sum -c SHA256SUMS

RUN python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
 && python3 -m venv /opt/batio3-science \
 && /opt/batio3-science/bin/pip install --no-index --find-links=/tmp/batio3-wheels --only-binary=:all: \
      ase==3.26.0 cloudpickle==3.1.2 contourpy==1.4.0 cycler==0.12.1 fonttools==4.67.0 \
      joblib==1.6.0 kiwisolver==1.5.1 matplotlib==3.11.2 numpy==2.5.3 packaging==26.3 \
      pillow==13.0.0 pyparsing==3.3.3 python_dateutil==2.9.0.post0 scikit_learn==1.7.2 \
      scipy==1.18.1 six==1.17.0 threadpoolctl==3.7.0 \
 && /opt/batio3-science/bin/pip check \
 && rm -rf /tmp/batio3-wheels

ENV PATH="/opt/batio3-science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1
