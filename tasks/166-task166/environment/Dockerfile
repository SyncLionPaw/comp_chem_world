FROM compchembench-connectivity:hpc

LABEL org.compchemworld.bench="25_SPaiNN-Nonadiabatic-Dynamics" \
      org.compchemworld.case="case-05" \
      org.compchemworld.runtime="hpc-case-image" \
      org.compchemworld.dependencies="pinned-local-pyscf-runtime"

WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux asciinema nodejs npm ripgrep \
    && rm -rf /var/lib/apt/lists/*
COPY assets/build/requirements.in assets/build/requirements.lock.txt /tmp/case05-runtime/
COPY wheels/ /opt/wheels/
RUN uv venv /opt/case05-runtime \
    && uv pip install --python /opt/case05-runtime/bin/python --no-cache --no-index --find-links=/opt/wheels --require-hashes -r /tmp/case05-runtime/requirements.lock.txt \
    && uv pip check --python /opt/case05-runtime/bin/python \
    && rm -rf /opt/wheels \
    && /opt/case05-runtime/bin/python -c 'import numpy, pyscf' \
    && rm -rf /root/.ssh \
    && install -d -m 0700 /root/.ssh

ENV PATH="/opt/case05-runtime/bin:${PATH}"
COPY assets/output-contract.md assets/casscf_reference_spec.md /app/inputs/
COPY assets/geometries/ /app/inputs/geometries/
COPY assets/build/input-hashes.sha256 /tmp/case05-input-hashes.sha256
RUN cd /app && sha256sum -c /tmp/case05-input-hashes.sha256

COPY assets/harbor/bench25_capture.py /opt/bench25/bench25_capture.py
COPY assets/harbor/case05_domain.py assets/harbor/case05_producer.py assets/harbor/case05_runtime.py assets/harbor/case05_audit.py assets/harbor/case_domain_state.py assets/harbor/runtime_snapshot.py assets/harbor/standard_guard.py assets/harbor/identity-pins.json /opt/bench25/
COPY assets/harbor/run_point.py /opt/bench25/run_point.py
COPY assets/harbor/entrypoint.py /opt/bench25/entrypoint.py
COPY assets/harbor/ccb-capture /usr/local/bin/ccb-capture
COPY assets/harbor/trusted-readers/case25_case05_scoring_reader.py /scoring-code/case25_case05_scoring_reader.py
COPY assets/harbor/trusted-readers/case25_case05_rejection_reader.py /scoring-code/case25_case05_rejection_reader.py
RUN groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && groupadd --gid 10003 case05worker \
    && useradd --uid 10003 --gid 10003 --no-create-home --shell /usr/sbin/nologin case05worker \
    && install -d -o researcher -g researcher -m 0750 /app/outputs \
    && install -d -o researcher -g researcher -m 0711 /app/workspace \
    && install -d -o researcher -g researcher -m 0700 /run/ccb-hpc \
    && install -d -o root -g root -m 0711 /run/bench25-worker \
    && install -d -o root -g root -m 0700 /trusted /app/bench25-artifacts \
    && install -d -o root -g root -m 0755 /logs/verifier \
    && install -d -o root -g root -m 0500 /scoring-code \
    && chmod 0755 /app /app/inputs \
    && chmod 0444 /opt/bench25/bench25_capture.py /opt/bench25/case05_domain.py /opt/bench25/case05_producer.py /opt/bench25/case05_runtime.py /opt/bench25/case05_audit.py /opt/bench25/case_domain_state.py /opt/bench25/runtime_snapshot.py /opt/bench25/standard_guard.py /opt/bench25/identity-pins.json /opt/bench25/run_point.py /opt/bench25/entrypoint.py \
    && chmod 0400 /scoring-code/case25_case05_scoring_reader.py /scoring-code/case25_case05_rejection_reader.py \
    && chmod 0400 /opt/bench25/run_point.py \
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
trusted = ['/usr/local/bin', '/usr/bin', '/opt/case05-runtime', '/opt/bench25',
          '/opt/bench25/bench25_capture.py', '/opt/bench25/case05_runtime.py',
          '/opt/bench25/case05_domain.py', '/opt/bench25/case05_producer.py',
          '/opt/bench25/case05_audit.py', '/opt/bench25/runtime_snapshot.py', '/opt/bench25/standard_guard.py',
          '/opt/bench25/run_point.py', '/opt/bench25/identity-pins.json',
          '/scoring-code', '/app/inputs']
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
