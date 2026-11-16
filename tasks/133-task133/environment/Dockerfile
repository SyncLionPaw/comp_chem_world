FROM comp-chem-world-base
WORKDIR /app
RUN for tool in python3 pytest uv; do command -v "$tool" >/dev/null || exit 1; done
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv=3.12.3-0ubuntu2.1 g++=4:13.2.0-7ubuntu1 \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/case-python
ENV PATH="/opt/case-python/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
COPY assets/requirements.lock.txt /tmp/requirements.lock.txt
RUN python3 -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt \
    && python3 -m pip check
COPY assets/vendor/nep-runtime/ /opt/nep-cpu/
RUN g++ -O2 -std=c++14 -I/opt/nep-cpu/src -o /usr/local/bin/nep_predict \
    /opt/nep-cpu/predict.cpp /opt/nep-cpu/src/nep.cpp \
    /opt/nep-cpu/src/neighbor_nep.cpp /opt/nep-cpu/src/ewald_nep.cpp
COPY assets/inputs/ /app/environment/inputs/
ENV INPUT_ROOT=/app/environment/inputs
RUN ln -s /app/environment/inputs /app/inputs

RUN rm -rf /root/.ssh /root/.claude /root/.codex /root/.claude.json \
    && mkdir -p /root/.claude /root/.codex
RUN test ! -e /root/.ssh && test ! -e /root/.claude/skills \
    && test ! -e /root/.codex/skills
