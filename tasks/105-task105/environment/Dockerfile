FROM compchembench-connectivity:hpc
WORKDIR /app
COPY assets/ /app/assets/
USER root

RUN useradd --create-home --uid 1001 --shell /bin/bash researcher \
    && mkdir -p /run/bench16 /trusted /app/final /app/.bench16-trusted \
    && chown root:root /app \
    && chmod 0755 /app \
    && chmod 0700 /run/bench16 /trusted /root /app/.bench16-trusted \
    && chmod 1777 /app/final \
    && for bin in /usr/bin/sudo /bin/sudo /usr/bin/su /bin/su /usr/bin/pkexec /usr/bin/runuser /usr/sbin/runuser /sbin/runuser; do if [ -e "$bin" ]; then chmod u-s "$bin"; fi; done
ENTRYPOINT ["python3", "/app/assets/bench16_runtime.py", "start"]
USER root
