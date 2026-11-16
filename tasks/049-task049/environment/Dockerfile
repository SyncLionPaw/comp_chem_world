FROM comp-chem-world-base
LABEL org.opencontainers.image.revision="bench08-local-01-06-20261024-r5"
WORKDIR /app
COPY assets/ /app/environment/assets/
RUN python3 -m pip install --break-system-packages --no-cache-dir numpy==2.2.6 scipy==1.15.3 \
    && python3 -c 'import numpy, scipy; print(numpy.__version__, scipy.__version__)'
# Harbor Terminus2 needs tmux inside the offline candidate environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux=3.4-1build1 \
    && rm -rf /var/lib/apt/lists/* \
    && tmux -V
