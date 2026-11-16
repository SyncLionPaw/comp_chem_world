FROM comp-chem-world-base AS dependencies
COPY assets/vendor/ /tmp/vendor/
COPY assets/vendor/cache-aarch64/ /tmp/science-cache-aarch64/
COPY assets/vendor/cache-x86_64/ /tmp/science-cache-x86_64/
RUN --network=none mkdir -p /tmp/science-cache \
    && cp -a /tmp/science-cache-$(uname -m)/. /tmp/science-cache/ \
    && python3 /tmp/vendor/fetch-dependencies.py --offline --cache-dir /tmp/science-cache \
    && chmod 0755 /tmp/science-cache/bin/micromamba \
    && ln -s /tmp/science-cache/packages /tmp/science-pkgs \
    && /tmp/science-cache/bin/micromamba create --yes --offline --prefix /opt/autosolvate --file /tmp/vendor/explicit-conda-$(uname -m).txt \
    && /opt/autosolvate/bin/python -m pip install --no-deps --no-index --find-links /tmp/science-cache/packages --require-hashes -r /tmp/vendor/wheels.lock \
    && test -x /opt/autosolvate/bin/packmol \
    && AMBERHOME=/opt/autosolvate PATH=/opt/autosolvate/bin:$PATH /opt/autosolvate/bin/python -c 'import numpy, scipy, parmed, openmm, netCDF4, cftime, certifi' \
    && AMBERHOME=/opt/autosolvate PATH=/opt/autosolvate/bin:$PATH /opt/autosolvate/bin/python -c "from pathlib import Path; assert b'Version 20.14.3' in Path('/opt/autosolvate/bin/packmol').read_bytes()"

FROM comp-chem-world-base
COPY --from=dependencies /opt/autosolvate/ /opt/autosolvate/
ENV PATH="/opt/autosolvate/bin:${PATH}" AMBERHOME=/opt/autosolvate OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY assets/data/ /app/inputs/
COPY assets/config/output-contract.yaml /app/output-contract.yaml
