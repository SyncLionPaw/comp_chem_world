FROM comp-chem-world-base
LABEL org.opencontainers.image.revision="bench08-local-01-06-20261024-r5"
WORKDIR /app
RUN python3 -m pip install --break-system-packages --no-cache-dir \
    --only-binary=:all: --retries 3 --timeout 20 numpy==2.2.6 \
    && python3 -c 'import numpy; assert numpy.__version__ == "2.2.6", numpy.__version__'
COPY assets/ /app/environment/assets/
# Harbor Terminus2 needs tmux inside the offline candidate environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux=3.4-1build1 \
    && rm -rf /var/lib/apt/lists/* \
    && tmux -V
