FROM compchembench-connectivity:hpc

WORKDIR /app
COPY AGENTS.md /app/AGENTS.md
COPY assets/ /app/assets/
COPY assets/verification.md /app/verification.md
# Root-owned observer consumed by the task's [[verifier.collect]] hook. The image
# also carries it under /app/assets, where the candidate may read it; the copy at
# /opt/task152 is root-owned and non-writable so the sealed run cannot be edited.
COPY assets/task152_trusted.py /opt/task152/task152_trusted.py
RUN chmod 0444 /opt/task152/task152_trusted.py \
    && chown root:root /opt/task152 /opt/task152/task152_trusted.py
