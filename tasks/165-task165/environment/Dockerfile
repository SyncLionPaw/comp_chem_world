FROM compchembench-connectivity:hpc

LABEL org.compchemworld.bench="25_SPaiNN-Nonadiabatic-Dynamics" \
      org.compchemworld.case="case-04" \
      org.compchemworld.runtime="hpc-case-image" \
      org.compchemworld.dependencies="case03-reviewed-python312-arm64-model-lock"

WORKDIR /app
COPY assets/build/requirements.in assets/build/requirements.lock.txt /tmp/case04-runtime/
COPY assets/build/sources/SPaiNN-461b414a.tar.gz /tmp/case04-runtime/sources/SPaiNN-461b414a.tar.gz
COPY assets/build/wheels/schnetpack-2.0.4-py3-none-any.whl /tmp/case04-runtime/wheels/schnetpack-2.0.4-py3-none-any.whl
RUN uv venv /opt/case04-runtime \
    && cd /tmp/case04-runtime \
    && uv pip install --python /opt/case04-runtime/bin/python --no-cache --require-hashes -r requirements.lock.txt \
    && uv pip check --python /opt/case04-runtime/bin/python \
    && /opt/case04-runtime/bin/python -c 'import ase, h5py, numpy, scipy, schnetpack, spainn, torch, yaml' \
    && rm -rf /root/.ssh \
    && install -d -m 0700 /root/.ssh
ENV PATH="/opt/case04-runtime/bin:${PATH}"
COPY assets/output-contract.md assets/sharc-v3.0.0.zip /app/inputs/
COPY assets/databases/ /app/inputs/databases/
COPY assets/pilot-baseline/ /app/inputs/pilot-baseline/
COPY assets/build/input-hashes.sha256 /tmp/case04-input-hashes.sha256
RUN cd /app && sha256sum -c /tmp/case04-input-hashes.sha256

COPY assets/harbor/native/ /opt/bench25/case04-native/
RUN sed -i 's@http://ports.ubuntu.com/ubuntu-ports@https://ports.ubuntu.com/ubuntu-ports@g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
       gcc gfortran make libblas-dev libfftw3-dev liblapack-dev libnetcdf-dev \
       libhdf5-dev libhdf4-alt-dev python3.12-dev \
    && /usr/bin/python3 -I -m zipfile -e /app/inputs/sharc-v3.0.0.zip /opt/bench25 \
    && mv /opt/bench25/sharc-md-sharc-c57d6ce /opt/bench25/sharc \
    && /usr/bin/python3 -c 'from pathlib import Path; p=Path("/opt/bench25/sharc/source/input_list.f90"); b=p.read_bytes(); old=b"      keyword=line\n      values=line_postcomment\n      return"; new=b"      keyword=line\n      values=line_postcomment\n      stat=0\n      return"; assert b.count(old)==1, "SHARC input parser patch context must match exactly once"; p.write_bytes(b.replace(old,new,1))' \
    && rm /opt/bench25/sharc/pysharc/include/data.inc \
    && ln -s ../../source/data.inc /opt/bench25/sharc/pysharc/include/data.inc \
    && make -C /opt/bench25/sharc/pysharc/netcdf ANACONDA=/usr \
    && multiarch="$(gcc -print-multiarch)" \
    && make -C /opt/bench25/sharc/source USE_LIBS=gnu ANACONDA=/usr \
       LD="-llapack -lfftw3 -lblas -lgfortran -L/usr/lib/${multiarch}/hdf5/serial -lhdf5 -lhdf5_hl -lmfhdfalt -ldfalt -ljpeg -L../pysharc/lib -lsharcnc -lnetcdf" \
       data_extractor sharc libsharc \
    && PATH="/opt/case04-runtime/bin:${PATH}" make -C /opt/bench25/sharc/pysharc \
       ANACONDA=/usr USE_LIBS=gnu \
    && cp /opt/bench25/sharc/source/data_extractor.x /opt/bench25/sharc/bin/data_extractor.x \
    && cp /opt/bench25/sharc/source/sharc2.x /opt/bench25/sharc/bin/sharc2.x \
    && chmod 0555 /opt/bench25/sharc/bin/data_extractor.x /opt/bench25/sharc/bin/sharc2.x \
    && rm -f /opt/bench25/sharc/bin/sharc.x /opt/bench25/sharc/bin/wfoverlap.x \
    && ln -s sharc2.x /opt/bench25/sharc/bin/sharc.x \
    && ln -s wfoverlap_ascii.x /opt/bench25/sharc/bin/wfoverlap.x \
    && chmod -R a-w /opt/bench25/case04-native /opt/bench25/sharc \
    && DEBIAN_FRONTEND=noninteractive apt-get purge -y gcc gfortran make build-essential \
       libblas-dev libfftw3-dev liblapack-dev libnetcdf-dev libhdf5-dev libhdf4-alt-dev python3.12-dev \
    && rm -rf /var/lib/apt/lists/* \
    && LD_LIBRARY_PATH=/opt/bench25/sharc/pysharc/lib:/usr/lib/${multiarch}/hdf5/serial \
       /opt/case04-runtime/bin/python -c 'import sys; sys.path.insert(0,"/opt/bench25/sharc/pysharc"); import sharc' \
    && ! ldd /opt/bench25/sharc/bin/data_extractor.x | grep -q "not found" \
    && ! ldd /opt/bench25/sharc/bin/sharc2.x | grep -q "not found"

# Standard Harbor agent installers require these native tools. Install them
# after the pinned scientific runtime and SHARC build so they do not invalidate
# or repeat those dependency layers.
RUN apt-get -o Acquire::Retries=3 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
       tmux asciinema nodejs npm ripgrep \
    && rm -rf /var/lib/apt/lists/*
COPY assets/harbor/case04_domain.py assets/harbor/case04_producer.py assets/harbor/case04_runtime.py assets/harbor/case04_audit.py assets/harbor/case_domain_state.py /opt/bench25/
ENV SHARC_ROOT="/opt/bench25/sharc"
COPY assets/harbor/bench25_capture.py /opt/bench25/bench25_capture.py
COPY assets/harbor/entrypoint.py /opt/bench25/entrypoint.py
COPY assets/harbor/standard_guard.py /opt/bench25/standard_guard.py
COPY assets/harbor/identity-pins.json /opt/bench25/identity-pins.json
COPY assets/harbor/runtime_snapshot.py /opt/bench25/runtime_snapshot.py
COPY assets/harbor/ccb-capture /usr/local/bin/ccb-capture
RUN groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && groupadd --gid 10002 case04worker \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin case04worker \
    && install -d -o researcher -g researcher -m 0750 /app/outputs \
    && install -d -o researcher -g researcher -m 0711 /app/workspace \
    && install -d -o researcher -g researcher -m 0700 /run/ccb-hpc \
    && install -d -o root -g root -m 0711 /run/bench25-worker \
    && chmod 0755 /app /app/inputs \
    && chmod 0444 /opt/bench25/bench25_capture.py /opt/bench25/entrypoint.py /opt/bench25/standard_guard.py /opt/bench25/identity-pins.json /opt/bench25/runtime_snapshot.py /opt/bench25/case04_domain.py /opt/bench25/case04_producer.py /opt/bench25/case04_runtime.py /opt/bench25/case04_audit.py /opt/bench25/case_domain_state.py \
    && chmod 0400 /opt/bench25/case04_audit.py /opt/bench25/case04-native/*.py \
    && install -d -o root -g root -m 0711 /run/bench25-worker/case04 \
    && install -d -o root -g root -m 0700 /trusted /app/bench25-artifacts \
    && install -d -o root -g root -m 0755 /logs/verifier \
    && chmod 0555 /usr/local/bin/ccb-capture \
    && (rm -f /usr/bin/sudo /usr/sbin/sudo /bin/su /usr/bin/su /usr/bin/pkexec /etc/sudoers.d/* || true)

RUN /usr/bin/python3 - <<'PY'
import errno, os, stat
skip = {'proc', 'sys', 'dev', 'run'}
for root, dirs, files in os.walk('/', topdown=True, followlinks=False):
    if root == '/':
        dirs[:] = [name for name in dirs if name not in skip]
    for name in [*dirs, *files]:
        path = os.path.join(root, name)
        try:
            info = os.stat(path, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                if info.st_mode & 0o6000:
                    os.chmod(path, stat.S_IMODE(info.st_mode) & ~0o6000, follow_symlinks=False)
                try:
                    attrs = os.listxattr(path, follow_symlinks=False)
                    if 'security.capability' in attrs:
                        os.removexattr(path, 'security.capability', follow_symlinks=False)
                except OSError as exc:
                    unsupported = (errno.ENODATA, errno.ENOTSUP, getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP))
                    if exc.errno not in unsupported:
                        raise
        except FileNotFoundError:
            continue
trusted = ['/usr/local/bin', '/usr/bin', '/opt/case04-runtime', '/opt/bench25',
          '/opt/bench25/bench25_capture.py', '/opt/bench25/case04_runtime.py',
          '/opt/bench25/runtime_snapshot.py',
          '/opt/bench25/case04_domain.py', '/opt/bench25/case04_producer.py',
          '/opt/bench25/case04_audit.py', '/opt/bench25/sharc', '/app/inputs']
for name in trusted:
    info = os.stat(name)
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError(f'untrusted writable runtime path: {name}')
PY

ARG BENCH25_CONTEXT_SHA256
ARG BENCH25_PARENT_IMAGE_ID
LABEL org.compchemworld.build-context-sha256="${BENCH25_CONTEXT_SHA256}" \
      org.compchemworld.standard-parent-image-id="${BENCH25_PARENT_IMAGE_ID}"

ENTRYPOINT ["/usr/bin/python3", "-B", "-I", "/opt/bench25/entrypoint.py"]
