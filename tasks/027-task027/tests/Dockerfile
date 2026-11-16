# Credential-free, offline verifier. It is built directly from the base image,
# never from the candidate HPC image that contains SSH material.
FROM comp-chem-world-base
RUN pip3 install --break-system-packages --no-cache-dir \
        cryptography==50.0.2 cffi==2.1.1 pycparser==3.12 \
    && rm -rf /root/.ssh
WORKDIR /app
COPY protected/public-inputs/assets/ /app/assets/
COPY . /tests/
ENV APP=/app \
    TESTS=/tests \
    LOGS=/logs/verifier \
    SSH_AUTH_SOCK= \
    SSH_AGENT_PID= \
    PYTHONDONTWRITEBYTECODE=1
