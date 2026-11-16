FROM comp-chem-world-base
WORKDIR /app
RUN for tool in python3 pytest uv; do command -v "$tool" >/dev/null || exit 1; done
RUN python3 -m venv /opt/case-python
ENV PATH="/opt/case-python/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
COPY assets/pdf-requirements.lock.txt /tmp/pdf-requirements.lock.txt
COPY assets/vendor/pypdf-5.9.0-py3-none-any.whl /tmp/pdf-wheels/
RUN python3 -m pip install --no-index --find-links=/tmp/pdf-wheels --require-hashes -r /tmp/pdf-requirements.lock.txt \
    && python3 -m pip check
RUN mkdir -p /app/environment/inputs
ENV INPUT_ROOT=/app/environment/inputs
RUN ln -s /app/environment/inputs /app/inputs

RUN rm -rf /root/.ssh /root/.claude /root/.codex /root/.claude.json \
    && mkdir -p /root/.claude /root/.codex
RUN test ! -e /root/.ssh && test ! -e /root/.claude/skills \
    && test ! -e /root/.codex/skills
