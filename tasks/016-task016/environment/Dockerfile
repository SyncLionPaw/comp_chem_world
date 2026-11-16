FROM comp-chem-world-base AS dependencies
COPY assets/vendor/ /tmp/vendor/
COPY assets/vendor/cache-aarch64/ /tmp/science-cache-aarch64/
COPY assets/vendor/cache-x86_64/ /tmp/science-cache-x86_64/
RUN mkdir -p /tmp/science-cache \
    && cp -a /tmp/science-cache-$(uname -m)/. /tmp/science-cache/ \
    && python3 /tmp/vendor/fetch-dependencies.py --cache-dir /tmp/science-cache \
    && chmod 0755 /tmp/science-cache/bin/micromamba \
    && ln -s /tmp/science-cache/packages /tmp/science-pkgs \
    && /tmp/science-cache/bin/micromamba create --yes --offline --prefix /opt/autosolvate --file /tmp/vendor/explicit-conda-$(uname -m).txt \
    && AMBERHOME=/opt/autosolvate PATH=/opt/autosolvate/bin:$PATH /opt/autosolvate/bin/python -c 'import numpy, scipy, parmed, openmm'

FROM comp-chem-world-base
COPY --from=dependencies /opt/autosolvate/ /opt/autosolvate/
ENV PATH="/opt/autosolvate/bin:${PATH}" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY assets/data/ /app/inputs/
COPY assets/config/output-contract.yaml /app/output-contract.yaml
