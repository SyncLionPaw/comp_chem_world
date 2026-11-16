FROM comp-chem-world-base
RUN python3 -m venv /opt/task-python
ENV PATH="/opt/task-python/bin:${PATH}"
COPY assets/wheels/ /tmp/wheels/
RUN echo "76c2c1e6bfa5c84adc6434dfbf013aa92096a7985221762c8f11fedfd20fff58  /tmp/wheels/numpy-2.5.3-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl" | sha256sum -c - \
    && echo "b7e18c623bb5c95acb3b3328861272816ba199fb531921c5d6d0b675f1fde9e3  /tmp/wheels/numpy-2.5.3-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl" | sha256sum -c - \
    && python3 -m pip install --no-index --find-links=/tmp/wheels numpy==2.5.3 \
    && python3 -m pip check \
    && rm -rf /tmp/wheels
WORKDIR /app
COPY assets/ /app/environment/assets/
# Wheels were installed from /tmp; do not leave them agent-visible.
RUN rm -rf /app/environment/assets/wheels
