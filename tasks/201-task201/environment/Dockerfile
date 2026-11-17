FROM --platform=linux/amd64 compchembench-base:2.1.267

ARG CONDA_FORGE_CHANNEL=https://conda.anaconda.org/conda-forge
WORKDIR /app

COPY assets/ /app/environment/assets/
COPY assets/inputs/ /opt/ccw-public/inputs/
COPY assets/native-execution-contract.json /opt/ccw-public/native-execution-contract.json

COPY assets/runtime/micromamba /usr/local/bin/micromamba
COPY assets/runtime/ /opt/build/
COPY assets/wheels/conda-packages/ /opt/build/packages/

RUN --network=none test "$(uname -m)" = x86_64 \
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
