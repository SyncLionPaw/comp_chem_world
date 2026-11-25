# This case needs x86_64: the pinned PySCF/geomeTRIC wheelhouse ships linux-x86_64 wheels only.
# The amd64 connectivity base must be prepared as compchembench-connectivity:hpc-amd64.
FROM compchembench-connectivity:hpc-amd64
COPY AGENTS.md /app/AGENTS.md

# The fresh solver requires the locked PySCF/geomeTRIC runtime.
COPY assets/qm_task.md /app/environment/assets/qm_task.md
COPY assets/config/hpc.md assets/config/hpc-submit.md assets/scripts/submit-hpc.sh assets/scripts/run-hpc-job.sh /app/environment/
COPY assets/runtime/ /app/environment/runtime/
RUN chmod 755 /app/environment/submit-hpc.sh /app/environment/run-hpc-job.sh
RUN test "$(uname -m)" = "x86_64" || { echo "case 06 pinned PySCF wheelhouse requires linux/amd64 (x86_64)" >&2; exit 1; }
RUN /app/environment/runtime/bootstrap-runtime.sh
ENV PATH="/app/environment/runtime/.case06-venv/bin:${PATH}"
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools

ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
