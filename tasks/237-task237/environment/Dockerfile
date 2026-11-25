FROM --platform=linux/amd64 compchembench-connectivity:hpc

WORKDIR /app

COPY AGENTS.md /app/AGENTS.md
COPY assets/ /app/environment/assets/
COPY assets/runtime/ /app/runtime/

COPY assets/wheels/python312/ /tmp/vendor-wheels/

RUN cd /tmp/vendor-wheels && sha256sum -c SHA256SUMS
COPY assets/dependencies/system-packages/ /tmp/system-packages/

RUN rm -rf /app/environment/assets/wheels /app/environment/assets/dependencies \
 && test "$(dpkg --print-architecture)" = amd64 \
 && python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
 && cd /tmp/system-packages \
 && sha256sum -c SHA256SUMS \
 && dpkg -i ./*.deb \
 && dpkg-query -W libgomp1 libgfortran5 libstdc++6 \
 && cd /app \
 && python3 -m venv /opt/science \
 && /opt/science/bin/pip install --no-index --find-links=/tmp/vendor-wheels --only-binary=:all: numpy==2.5.4 scipy==1.18.1 ase==3.29.0 quippy-ase==0.10.3 matplotlib==3.11.2 networkx==3.7 f90wrap==0.3.0 contourpy==1.4.0 cycler==0.12.1 fonttools==4.67.0 kiwisolver==1.5.1 packaging==26.3 pillow==13.0.0 pyparsing==3.3.3 python-dateutil==2.9.0.post0 pyyaml==6.0.3 six==1.17.0 typing-extensions==4.16.0 \
 && /opt/science/bin/pip check \
 && rm -rf /tmp/vendor-wheels /tmp/system-packages \
 && ln -s environment/assets /app/inputs

ENV PATH="/opt/science/bin:${PATH}" \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY assets/output-contract.md /app/output-contract.md
