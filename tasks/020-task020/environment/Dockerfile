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
    && /opt/autosolvate/bin/python -c 'import numpy, scipy, parmed, openmm, netCDF4, cftime, certifi' \
    && LD_LIBRARY_PATH=/opt/autosolvate/lib /opt/autosolvate/bin/python -c 'import ctypes, ctypes.util; name=ctypes.util.find_library("netcdf"); assert name; ctypes.CDLL(name)'

FROM comp-chem-world-base
COPY --from=dependencies /opt/autosolvate/ /opt/autosolvate/
ENV PATH="/opt/autosolvate/bin:${PATH}" LD_LIBRARY_PATH="/opt/autosolvate/lib" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY assets/data/ /app/inputs/
COPY assets/config/output-contract.yaml /app/output-contract.yaml
RUN mkdir -p /app/final && chmod 1777 /app/final
