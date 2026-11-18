FROM comp-chem-world-base

WORKDIR /app

USER 0:0

COPY --chown=0:0 assets/ /app/inputs/
COPY --chown=0:0 assets/ /opt/co2-public/inputs/
COPY --chown=0:0 assets/contracts/ /opt/co2-public/
COPY --chown=0:0 assets/wheels/python312/ /tmp/co2-wheels/

RUN cd /tmp/co2-wheels && sha256sum -c SHA256SUMS

RUN rm -rf /app/inputs/wheels /opt/co2-public/inputs/wheels /app/inputs/dependencies /opt/co2-public/inputs/dependencies /app/inputs/contracts /opt/co2-public/inputs/contracts \
 && apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && UV_PYTHON_INSTALL_DIR=/opt/co2-python uv python install --no-bin 3.12.14 \
 && CO2_PYTHON="$(UV_PYTHON_INSTALL_DIR=/opt/co2-python uv python find --no-project --managed-python --no-python-downloads 3.12.14)" \
 && "$CO2_PYTHON" -c 'import sys; assert sys.version_info[:3] == (3, 12, 14), sys.version' \
 && "$CO2_PYTHON" -m venv /opt/co2-science \
 && /opt/co2-science/bin/python -c 'import sys; assert sys.version_info[:3] == (3, 12, 14), sys.version' \
 && chmod -R a+rX /opt/co2-python \
 && /opt/co2-science/bin/pip install --no-index --find-links=/tmp/co2-wheels mpmath==1.3.0 numpy==2.2.6 pymupdf==1.26.5 scipy==1.15.3 \
 && /opt/co2-science/bin/pip check \
 && rm -f /usr/local/bin/python \
 && printf '#!/bin/sh\nexec /opt/co2-science/bin/python "$@"\n' > /usr/local/bin/python \
 && chmod 755 /usr/local/bin/python \
 && rm -rf /tmp/co2-wheels

ARG PUBLIC_SPEC
LABEL co2dl17.case_id="case-02-charge-energy-response" co2dl17.public_spec="${PUBLIC_SPEC}"

RUN rm -rf /opt/co2-public/inputs/contracts \
 && chmod -R a-w /opt/co2-public \
 && chmod -R a+rX /opt/co2-public /app/inputs

RUN test -x /usr/local/bin/claude && claude --version

ENV PATH="/opt/co2-science/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    CCW_CLAUDE_CODE_VERSION=2.1.317
