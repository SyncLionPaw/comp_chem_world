FROM --platform=linux/amd64 compchembench-connectivity:hpc

WORKDIR /app

COPY assets/runtime/native-config-export.patch /tmp/native-config-export.patch
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cmake g++ make ca-certificates git libfftw3-dev \
 && rm -rf /var/lib/apt/lists/*

RUN git init /tmp/cphmd-src \
 && git -C /tmp/cphmd-src remote add origin https://gitlab.com/gromacs-constantph/constantph.git \
 && git -C /tmp/cphmd-src fetch --depth 1 origin 28807b1162cacd9dc797520bc509d12edca13d1a \
 && git -C /tmp/cphmd-src checkout --detach FETCH_HEAD \
 && test "$(git -C /tmp/cphmd-src rev-parse HEAD)" = 28807b1162cacd9dc797520bc509d12edca13d1a \
 && test "$(sha256sum /tmp/native-config-export.patch | cut -d' ' -f1)" = ba32035583449038fab848e71458f68cc7036c51bfaac634db0149aa446a75e1 \
 && cd /tmp/cphmd-src/gromacs-constantph \
 && grep -Fq 'int residueNStates() { return residueNStates_; }' src/gromacs/mdtypes/lambda_dynamics_params.h \
 && git apply --check /tmp/native-config-export.patch \
 && git apply /tmp/native-config-export.patch \
 && sed -i 's/int residueNStates() { return residueNStates_; }/int residueNStates() const { return residueNStates_; }/' src/gromacs/mdtypes/lambda_dynamics_params.h \
 && cmake -S . -B /tmp/cphmd-build -DCMAKE_INSTALL_PREFIX=/opt/cphmd-reader -DGMX_MPI=OFF -DGMX_OPENMP=ON -DGMX_GPU=OFF -DGMX_BUILD_OWN_FFTW=OFF -DGMX_BUILD_MDRUN_ONLY=OFF -DGMX_SIMD=NONE -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /tmp/cphmd-build --parallel 6 \
 && cmake --install /tmp/cphmd-build \
 && mkdir -p /opt/cphmd-reader \
 && python3 -c "import hashlib,json,pathlib,subprocess; b=pathlib.Path('/opt/cphmd-reader/bin/gmx'); v=subprocess.check_output([str(b),'--version'],text=True); version=next(x.split(':',1)[1].strip() for x in v.splitlines() if x.startswith('GROMACS version:')); d={'name':'GROMACS CpHMD','version':version,'source_commit':'28807b1162cacd9dc797520bc509d12edca13d1a','binary_sha256':hashlib.sha256(b.read_bytes()).hexdigest(),'source_patch_sha256':'ba32035583449038fab848e71458f68cc7036c51bfaac634db0149aa446a75e1'}; pathlib.Path('/opt/cphmd-reader/identity.json').write_text(json.dumps(d,sort_keys=True)+'\n')" \
 && rm -rf /tmp/cphmd-src /tmp/cphmd-build /tmp/native-config-export.patch

COPY assets/ /app/environment/assets/
COPY assets/runtime/ /app/tools/

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

RUN python3 -m venv /opt/cphmd-analysis \
 && /opt/cphmd-analysis/bin/python -m pip install --no-index --only-binary=:all: --find-links=/app/environment/assets/wheels --require-hashes -r /app/environment/assets/requirements.lock.txt \
 && /opt/cphmd-analysis/bin/python -m pip check \
 && /opt/cphmd-analysis/bin/python -c "import numpy, scipy" \
 && mkdir -p /app/environment \
 && test -x /usr/local/bin/claude \
 && ln -s /app/environment/assets /app/inputs

ENV PATH="/opt/cphmd-analysis/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1
