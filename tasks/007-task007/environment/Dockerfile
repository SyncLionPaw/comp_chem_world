FROM compchembench-connectivity:hpc
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY assets/ /app/assets/
RUN python3 -m venv --system-site-packages /opt/case-science
ENV PATH="/opt/case-science/bin:${PATH}"
RUN printf '%s\n' \
      'cffi==2.1.1 --hash=sha256:c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf --hash=sha256:68e62fe11f30d5ca8289242866f0a5291402d8529ca2178ab8afc5c9694ae890' \
      'cryptography==50.0.2 --hash=sha256:f21e8a22c8605750c7af886bab299a363721264061b4ac0a30efb73cfd58efc5 --hash=sha256:630ebfea3bf689d075f82316324ff7433dc447fe6bc1bfc76524b74b4a9567d2 --hash=sha256:79def8d059362e7831389ed3be0ecdf58a89386e1271e35dd9f5af84e81bffd0' \
      'pycparser==3.0 --hash=sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992' \
      'typing-extensions==4.16.0 --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8' \
    | python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /dev/stdin \
    && python -m pip check
RUN groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && install -d -o root -g root -m 0755 /opt/task7 /var/lib/compchembench/task7 \
    && install -d -o root -g root -m 0700 /trusted/task7 \
    && install -d -o researcher -g researcher -m 0700 /workspace /app/final /home/researcher/.ssh \
    && test -d /root/.ssh \
    && chown -R root:root /root/.ssh \
    && chmod 0700 /root /root/.ssh \
    && find /root/.ssh -type d -exec chmod 0700 {} + \
    && find /root/.ssh -type f -exec chmod 0600 {} + \
    && cp /opt/skills/ikkem-slurm/scripts/submit.py /opt/skills/ikkem-slurm/scripts/submit_core.py \
    && cp /app/assets/task07_trusted.py /opt/task7/task07_trusted.py \
    && cp /app/assets/task07_submit.py /opt/skills/ikkem-slurm/scripts/submit.py \
    && chmod 0444 /opt/task7/task07_trusted.py /opt/skills/ikkem-slurm/scripts/submit.py /opt/skills/ikkem-slurm/scripts/submit_core.py \
    && chown -R root:root /opt/task7 /opt/skills/ikkem-slurm/scripts /app/assets \
    && chmod 0755 /opt/task7 /opt/skills/ikkem-slurm/scripts /app /app/assets \
    && chmod -R a-w /opt/skills/ikkem-slurm/scripts \
    && chmod -R a-w /app/assets \
    && (rm -f /usr/bin/sudo /usr/sbin/sudo /bin/su /usr/bin/su /usr/bin/pkexec /etc/sudoers.d/* || true)
RUN python3 - <<'PY'
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
trusted_paths = [
    '/usr/local/sbin', '/usr/local/bin', '/usr/sbin', '/usr/bin', '/sbin', '/bin',
    '/opt/case-science', '/opt/case-science/bin', '/opt/task7',
    '/opt/task7/task07_trusted.py', '/opt/skills/ikkem-slurm/scripts',
    '/opt/skills/ikkem-slurm/scripts/submit.py',
    '/opt/skills/ikkem-slurm/scripts/submit_core.py',
    '/usr/bin/python3', '/usr/bin/bash', '/usr/bin/ssh', '/root', '/root/.ssh',
]
for name in trusted_paths:
    info = os.stat(name)
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError(f'untrusted writable runtime path: {name}')
PY
ENV HOME=/home/researcher BASH_ENV= ENV= PATH="/opt/case-science/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENTRYPOINT ["/usr/bin/python3", "-I", "/opt/task7/task07_trusted.py", "entrypoint"]
