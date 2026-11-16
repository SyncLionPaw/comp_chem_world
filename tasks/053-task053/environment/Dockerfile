FROM comp-chem-world-base
WORKDIR /app
COPY assets/ /app/environment/assets/
RUN python3 -m pip install --break-system-packages --no-cache-dir numpy==2.2.6 \
    && python3 -c 'import numpy; print(numpy.__version__)'
LABEL org.compchemworld.release-revision="archived-four-20261025-r2"
# Harbor Terminus2 needs tmux inside the offline candidate environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux=3.4-1build1 \
    && rm -rf /var/lib/apt/lists/* \
    && tmux -V
