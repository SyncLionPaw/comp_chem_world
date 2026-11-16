FROM comp-chem-world-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY assets/ /app/assets/
RUN python3 --version | grep -F 'Python 3.12.3' \
    && mkdir -p /app/final /logs/verifier \
    && chmod 0755 /app /app/assets /app/final /logs /logs/verifier
