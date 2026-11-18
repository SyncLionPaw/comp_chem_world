FROM comp-chem-world-base

ARG CONDA_FORGE_CHANNEL=https://conda.anaconda.org/conda-forge
WORKDIR /app

COPY assets/ /app/environment/assets/
COPY assets/inputs/ /opt/ccw-public/inputs/
COPY assets/native-execution-contract.json /opt/ccw-public/native-execution-contract.json

COPY assets/runtime/ /opt/build/
COPY assets/wheels/conda-packages/ /opt/build/packages/
COPY assets/wheels/conda-packages-linux-aarch64/ /opt/build/packages-linux-aarch64/

RUN --network=none arch="$(dpkg --print-architecture)" \
 && if [ "$arch" = amd64 ]; then \
      install -m 755 /opt/build/micromamba /usr/local/bin/micromamba; \
    elif [ "$arch" = arm64 ]; then \
      install -m 755 /opt/build/micromamba-linux-aarch64 /usr/local/bin/micromamba; \
      cp -f /opt/build/packages-linux-aarch64/* /opt/build/packages/; \
      cp /opt/build/conda-linux-aarch64.lock.json /opt/build/conda-linux64.lock.json; \
    else \
      echo "unsupported architecture: ${arch}" >&2; \
      exit 1; \
    fi \
 && CONDA_FORGE_CHANNEL="${CONDA_FORGE_CHANNEL}" python3 /opt/build/install_locked.py \
 && python3 /opt/build/check_dependencies.py \
 && rm -rf /opt/mamba /opt/build /app/environment/assets/wheels /app/environment/assets/runtime

ENV PATH="/opt/science/bin:${PATH}" \
    CONDA_PREFIX=/opt/science \
    AMBERHOME=/opt/science \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1
