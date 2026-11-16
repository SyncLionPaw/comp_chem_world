FROM comp-chem-world-base
RUN apt-get update && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 && python3 -m pip install --break-system-packages --no-cache-dir asciinema==2.4.0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV APP=/app

# The reference solution fits rates with numpy.linalg.lstsq; the shared base does not install numpy.
RUN uv pip install --system --break-system-packages "numpy==2.5.4"

# Copy public deposited inputs only; solution and tests are staged by the standard runner.
COPY assets/ /app/assets/
