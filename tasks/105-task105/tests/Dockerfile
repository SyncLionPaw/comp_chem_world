# Independent verifier image: task assets only; Harbor uploads tests at runtime.
FROM comp-chem-world-base
WORKDIR /app
COPY environment/assets/ /app/assets/
COPY tests/ /tests/
RUN mkdir -p /app/final /logs/verifier /trusted \
    && chmod 0755 /app /app/assets /app/final /logs /logs/verifier /trusted
