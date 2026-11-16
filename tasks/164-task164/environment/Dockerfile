FROM compchembench-connectivity:hpc

LABEL org.compchemworld.bench="25_SPaiNN-Nonadiabatic-Dynamics" \
      org.compchemworld.case="case-03" \
      org.compchemworld.runtime="hpc-case-image" \
      org.compchemworld.dependencies="reviewed-hpc-shared-python312-arm64-lock"

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux asciinema nodejs npm ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install only the existing pinned candidate/scorer Python stack. The pinned
# lock targets Python 3.12/Linux ARM64; the installed backend still needs post-build validation.
COPY assets/build/requirements.in assets/build/requirements.lock.txt /tmp/case03-runtime/
COPY assets/build/sources/SPaiNN-461b414a.tar.gz /tmp/case03-runtime/sources/SPaiNN-461b414a.tar.gz
COPY assets/build/wheels/schnetpack-2.0.4-py3-none-any.whl /tmp/case03-runtime/wheels/schnetpack-2.0.4-py3-none-any.whl
RUN uv venv /opt/case03-runtime \
    && cd /tmp/case03-runtime \
    && uv pip install --python /opt/case03-runtime/bin/python --no-cache --require-hashes -r requirements.lock.txt \
    && uv pip check --python /opt/case03-runtime/bin/python \
    && /opt/case03-runtime/bin/python -c 'import ase, h5py, numpy, scipy, schnetpack, spainn, torch, yaml' \
    && rm -rf /root/.ssh \
    && install -d -m 0700 /root/.ssh

ENV PATH="/opt/case03-runtime/bin:${PATH}"
COPY assets/output-contract.md assets/public_asset_manifest.json assets/trainval_shifted.db assets/heldout_geometry.db assets/painn_baseline_state_dict.pt /app/inputs/
COPY assets/build/input-hashes.sha256 /tmp/case03-input-hashes.sha256
RUN cd /app && sha256sum -c /tmp/case03-input-hashes.sha256

# Harbor's agent shell runs as researcher while this PID 1 remains root and
# owns the capture broker and its signing key.
COPY assets/harbor/bench25_capture.py /opt/bench25/bench25_capture.py
COPY assets/harbor/case03_producer.py /opt/bench25/case03_producer.py
COPY assets/harbor/current-refs.json /opt/bench25/current-refs.json
COPY assets/harbor/identity-pins.json /opt/bench25/identity-pins.json
COPY assets/harbor/entrypoint.py /opt/bench25/entrypoint.py
COPY assets/harbor/standard_guard.py /opt/bench25/standard_guard.py
COPY assets/harbor/private-case03/ /opt/bench25/private-case03/
COPY assets/harbor/case03_train.py /opt/bench25/case03_train.py
COPY assets/harbor/ccb-capture /usr/local/bin/ccb-capture
RUN groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && groupadd --gid 10002 case03worker \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin case03worker \
    && install -d -o researcher -g researcher -m 0700 /app/outputs \
    && install -d -o researcher -g researcher -m 0750 /app/workspace \
    && install -d -o researcher -g researcher -m 0700 /run/ccb-hpc \
    && install -d -o root -g root -m 0711 /run/bench25-worker \
    && chmod 0755 /app /app/inputs \
    && install -d -m 0555 /opt/bench25/public-case03/environment \
    && ln -s /app/inputs /opt/bench25/public-case03/environment/assets \
    && chown root:case03worker /opt/bench25/case03_train.py \
    && chmod 0440 /opt/bench25/case03_train.py \
    && chmod 0400 /opt/bench25/case03_producer.py \
    && chmod 0444 /opt/bench25/bench25_capture.py /opt/bench25/current-refs.json /opt/bench25/entrypoint.py /opt/bench25/standard_guard.py \
    && chown -R root:root /opt/bench25/private-case03 \
    && find /opt/bench25/private-case03 -type d -exec chmod 0500 {} + \
    && find /opt/bench25/private-case03 -type f -exec chmod 0400 {} + \
    && install -d -o root -g root -m 0700 /trusted /app/bench25-artifacts \
    && install -d -o root -g root -m 0755 /logs/verifier \
    && chmod 0555 /usr/local/bin/ccb-capture \
    && (rm -f /usr/bin/sudo /usr/sbin/sudo /bin/su /usr/bin/su /usr/bin/pkexec /etc/sudoers.d/* || true)

# Match the Bench2 researcher boundary: inherited setuid/setgid executables
# and file capabilities must not give the agent a path back to root.
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
                    if 'security.capability' in os.listxattr(path, follow_symlinks=False):
                        os.removexattr(path, 'security.capability', follow_symlinks=False)
                except OSError as exc:
                    unsupported = (errno.ENODATA, errno.ENOTSUP, getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP))
                    if exc.errno not in unsupported:
                        raise
        except FileNotFoundError:
            continue
trusted = ['/usr/local/bin', '/usr/bin', '/opt/case03-runtime', '/opt/bench25',
          '/opt/bench25/bench25_capture.py', '/opt/bench25/case03_train.py',
          '/opt/bench25/case03_producer.py', '/opt/bench25/current-refs.json',
          '/opt/bench25/identity-pins.json', '/opt/bench25/private-case03', '/app/inputs']
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
