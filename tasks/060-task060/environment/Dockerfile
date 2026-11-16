FROM comp-chem-world-base

ENV CASE06_RUNTIME=/opt/case06-runtime
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.10ubuntu1 cmake=3.28.3-1build7 libeigen3-dev=3.4.0-4build0.1 libfftw3-dev=3.3.10-1ubuntu3 libhdf5-dev=1.10.10+repack-3.1ubuntu4 libopenblas-dev=0.3.26+ds-1ubuntu0.1 liblapack-dev=3.12.0-3build1.1 && rm -rf /var/lib/apt/lists/*

RUN uv python install 3.11.11 \
    && mkdir -p /app "${CASE06_RUNTIME}" \
    && uv venv --python 3.11.11 "${CASE06_RUNTIME}"
RUN <<'CASE61_BUILD'
set -eu
cat <<'CASE61_REQUIREMENTS' > /tmp/case06-requirements.lock
amset==0.5.1
ase==3.29.0
castepxbin==0.3.1
certifi==2026.7.22
cftime==1.6.6
charset-normalizer==3.5.2
click==8.5.0
cloudpickle==3.1.2
cmake==3.31.10
colormath==3.0.0
contourpy==1.3.3
cycler==0.12.1
cython==3.3.0
fonttools==4.66.1
h5py==3.16.0
idna==3.20
interpolation==2.2.7
joblib==1.6.0
kiwisolver==1.5.1
latexcodec==3.0.1
llvmlite==0.42.0
matplotlib==3.11.2
memory-profiler==0.61.0
monty==2026.7.16
mpmath==1.3.0
narwhals==2.26.0
netcdf4==1.7.4
networkx==3.6.1
numba==0.59.1
numpy==1.26.4
packaging==26.3
palettable==3.3.3
pandas==3.0.6
pathspec==1.1.1
phonopy==2.23.1
pillow==12.3.0
plotly==7.1.0
psutil==7.2.2
pybtex==0.26.1
pyfftw==0.15.1
pymatgen==2024.5.1
pyparsing==3.3.3
python-dateutil==2.9.0.post0
pyyaml==6.0.3
requests==2.34.2
ruamel-yaml==0.19.1
scikit-build-core==0.9.10
scipy==1.13.1
seekpath==2.2.2
setuptools==70.3.0
setuptools-scm==8.1.0
six==1.17.0
spglib==2.3.1
sumo==2.3.6
sympy==1.14.0
tabulate==0.10.0
tempita==0.5.2
tqdm==4.70.1
typing-extensions==4.16.0
uncertainties==3.2.3
urllib3==2.8.0
wheel==0.48.0
BoltzTraP2==24.7.2
CASE61_REQUIREMENTS
uv pip install --python "${CASE06_RUNTIME}/bin/python" pip==26.0.1
"${CASE06_RUNTIME}/bin/python" -m pip install --report /app/case06-linux-bootstrap-report.json pip==26.0.1
"${CASE06_RUNTIME}/bin/python" -m pip install --report /app/case06-linux-build-tools-report.json numpy==1.26.4 scipy==1.13.1 setuptools==70.3.0 wheel==0.48.0 Cython==3.3.0 cmake==3.31.10 packaging==26.3 scikit-build-core==0.9.10 setuptools-scm==8.1.0
"${CASE06_RUNTIME}/bin/python" -m pip install --no-build-isolation --report /app/case06-linux-install-report.json -r /tmp/case06-requirements.lock
"${CASE06_RUNTIME}/bin/python" -m pip check
"${CASE06_RUNTIME}/bin/python" -c 'import amset, h5py, numpy, scipy, psutil, yaml; import BoltzTraP2.bandlib'
"${CASE06_RUNTIME}/bin/python" -m pip freeze --all > /app/case06-linux-freeze.txt
sha256sum /tmp/case06-requirements.lock > /app/case06-linux-inputs.sha256
rm /tmp/case06-requirements.lock
CASE61_BUILD
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 \
    && rm -rf /var/lib/apt/lists/*

# The venv runtime links to uv's immutable CPython tree. Let the unprivileged
# agent execute/read that runtime while keeping root's other home files private.
RUN chmod o+x /root /root/.local /root/.local/share /root/.local/share/uv /root/.local/share/uv/python \
    && find /root/.local/share/uv/python -maxdepth 1 -type d -name 'cpython-3.11.11-*' -exec chmod -R o+rX {} +

ENV CCB_CASE06_ATTEMPT=container CCB_CASE06_NONCE=native-api HOME=/home/benchagent XDG_CACHE_HOME=/home/benchagent/.cache

COPY assets/ /app/environment/assets/
COPY assets/tools/case06_rpc.py /app/environment/case06_rpc.py
COPY assets/tools/controller.py /app/environment/assets/tools/controller.py
COPY assets/tools/entrypoint.sh /usr/local/bin/case06-entrypoint
RUN useradd --create-home --shell /bin/bash benchagent \
    && mkdir -p /app/final /var/lib/case06-controller /app/controller-seal /home/benchagent/.cache /home/benchagent/.codex \
    && chown -R benchagent:benchagent /app/final /home/benchagent \
    && chown root:root /app/controller-seal /var/lib/case06-controller \
    && chmod 700 /app/controller-seal /var/lib/case06-controller \
    && chown -R root:root /app/environment/assets/science/case06/author /app/environment/assets/tools/controller.py \
    && chmod -R go-rwx /app/environment/assets/science/case06/author \
    && chmod 600 /app/environment/assets/tools/controller.py \
    && chmod 755 /usr/local/bin/case06-entrypoint
ENTRYPOINT ["/usr/local/bin/case06-entrypoint"]


WORKDIR /app
ENV PATH=/opt/case06-runtime/bin:${PATH}
CMD ["sleep", "infinity"]
LABEL org.opencontainers.image.title="CompChemWorld Bench09 case-06-scattering-convergence" org.opencontainers.image.version="20261024-v4"
