# Credential-free, offline verifier. It is not derived from the candidate HPC
# image and contains no prepared candidate science assets.
FROM comp-chem-world-base
RUN pip3 install --break-system-packages --no-cache-dir \
        cryptography==50.0.2 cffi==2.1.1 pycparser==3.12 \
    && rm -rf /root/.ssh
WORKDIR /app
RUN mkdir -p /tests
COPY . /tests/
ENV APP=/app \
    TESTS=/tests \
    LOGS=/logs/verifier \
    SSH_AUTH_SOCK= \
    SSH_AGENT_PID= \
    PYTHONDONTWRITEBYTECODE=1
