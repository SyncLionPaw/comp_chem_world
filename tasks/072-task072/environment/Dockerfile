FROM comp-chem-world-base
WORKDIR /app
RUN python3.12 -m venv /opt/case-python
ENV PATH="/opt/case-python/bin:${PATH}"
COPY assets/runtime/requirements.lock.txt /tmp/requirements.lock.txt
COPY assets/runtime/wheels/ /opt/wheels/
COPY assets/scripts/build-candidate-rootfs.py /usr/local/libexec/ccb-build-candidate-rootfs.py
# scipy.libs short-named .so files have no RPATH; teach ldd to search their directory.
RUN python3 - <<'PY'
from pathlib import Path

path = Path("/usr/local/libexec/ccb-build-candidate-rootfs.py")
text = path.read_text()
if "LD_LIBRARY_PATH" not in text:
    if "import os\n" not in text:
        text = text.replace("import argparse\n", "import argparse\nimport os\n", 1)
    needle = 'proc = subprocess.run(["ldd", str(path)], check=True, capture_output=True, text=True)'
    repl = (
        'env = {**os.environ, "LD_LIBRARY_PATH": '
        'f"{path.parent}:{os.environ.get(\'LD_LIBRARY_PATH\', \'\')}"}\n'
        '    proc = subprocess.run(["ldd", str(path)], check=True, capture_output=True, text=True, env=env)'
    )
    if needle not in text:
        raise SystemExit("ldd() call site not found for LD_LIBRARY_PATH patch")
    text = text.replace(needle, repl, 1)
if "local = path.parent / name" not in text:
    old = (
        '        elif "not found" in line:\n'
        '            raise RuntimeError(f"unresolved dynamic dependency for {path}: {line.strip()}")'
    )
    new = (
        '        elif "not found" in line:\n'
        '            name = line.split("=>", 1)[0].strip().split()[-1]\n'
        '            local = path.parent / name\n'
        '            if local.exists():\n'
        '                found.add(local.resolve())\n'
        '                continue\n'
        '            raise RuntimeError(f"unresolved dynamic dependency for {path}: {line.strip()}")'
    )
    if old not in text:
        raise SystemExit("ldd not-found branch not found for sibling resolve patch")
    text = text.replace(old, new, 1)
path.write_text(text)

# Drop ParmEd from the hashed lock; it is an sdist installed separately below.
src = Path("/tmp/requirements.lock.txt")
out = Path("/tmp/requirements.wheels.lock")
skip = False
kept = []
for line in src.read_text().splitlines():
    if line.startswith("parmed=="):
        skip = True
        continue
    if skip:
        if line.startswith("    --hash=") or not line.strip():
            continue
        if line.startswith("    #"):
            skip = False
            continue
        skip = False
    kept.append(line)
out.write_text("\n".join(kept) + "\n")
PY
# Keep libquadmath0 after purging the g++ toolchain (autoremove would drop it).
RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ libquadmath0 \
 && /opt/case-python/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.wheels.lock \
 && printf '%s\n' \
      'setuptools==84.0.0 \' \
      '    --hash=sha256:51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670' \
      'wheel==0.45.1 \' \
      '    --hash=sha256:708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248' \
      > /tmp/build-tools.lock \
 && /opt/case-python/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/build-tools.lock \
 && echo "3d0208f56507649b5af91bbb128f650a6f86de1b5a9af780e6479145e5362ea3  /opt/wheels/parmed-4.3.0.tar.gz" | sha256sum -c - \
 && /opt/case-python/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/wheels --no-build-isolation --no-deps /opt/wheels/parmed-4.3.0.tar.gz \
 && /opt/case-python/bin/python -m pip check \
 && python3 /usr/local/libexec/ccb-build-candidate-rootfs.py --python /opt/case-python/bin/python --site-packages /opt/case-python/lib/python3.12/site-packages --destination /opt/ccb-python-rootfs \
 && rm -rf /tmp/requirements.lock.txt /tmp/requirements.wheels.lock /tmp/build-tools.lock /opt/wheels \
 && apt-get purge -y g++ gcc cpp \
 && apt-get install -y --no-install-recommends libquadmath0 \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
ENV CCB_PYTHON_ROOTFS=/opt/ccb-python-rootfs
COPY assets/README_residue_numbering assets/corrmat_c0_WT.dat assets/corrmat_c0_V72I.dat assets/distmat_c0_WT.dat assets/distmat_c0_V72I.dat /app/assets/
RUN mkdir -p /app/final
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools
