FROM comp-chem-world-base
WORKDIR /app
RUN python3.12 -m venv /opt/case-python
ENV PATH="/opt/case-python/bin:${PATH}"
COPY assets/runtime/requirements.lock.txt /tmp/requirements.lock.txt
COPY assets/scripts/build-candidate-rootfs.py /usr/local/libexec/ccb-build-candidate-rootfs.py
RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ \
 && /opt/case-python/bin/python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt \
 && /opt/case-python/bin/python -m pip check \
 && python3 /usr/local/libexec/ccb-build-candidate-rootfs.py --python /opt/case-python/bin/python --site-packages /opt/case-python/lib/python3.12/site-packages --destination /opt/ccb-python-rootfs \
 && rm /tmp/requirements.lock.txt \
 && apt-get purge -y g++ gcc cpp \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
ENV CCB_PYTHON_ROOTFS=/opt/ccb-python-rootfs
COPY assets/README_residue_numbering assets/corrmat_c0_WT.dat assets/corrmat_c0_V72I.dat assets/distmat_c0_WT.dat assets/distmat_c0_V72I.dat /app/assets/
RUN mkdir -p /app/final
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools
