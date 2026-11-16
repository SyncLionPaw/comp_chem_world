# Separate offline grader image with the task's pinned scientific libraries.
FROM comp-chem-world-base
WORKDIR /app
COPY environment/assets/dependencies/wheels/ /tmp/bench12-wheelhouse/
COPY environment/assets/dependencies/requirements.lock.txt /tmp/bench12-requirements.lock.txt
RUN python3 -m venv /opt/bench12-grader \
    && /opt/bench12-grader/bin/python -m pip install --no-index \
         --find-links=/tmp/bench12-wheelhouse --require-hashes -r /tmp/bench12-requirements.lock.txt \
    && /opt/bench12-grader/bin/python -m pip check \
    && rm -rf /tmp/bench12-wheelhouse /tmp/bench12-requirements.lock.txt
ENV PATH="/opt/bench12-grader/bin:${PATH}"
RUN mkdir -p /app/final /tests
