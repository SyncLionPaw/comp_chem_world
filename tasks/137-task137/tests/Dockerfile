FROM comp-chem-world-base
WORKDIR /app
COPY requirements.lock.txt /tmp/requirements.lock.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir --only-binary=:all: \
        --require-hashes -r /tmp/requirements.lock.txt \
    && rm /tmp/requirements.lock.txt
COPY test.sh verify.py refs.json /tests/
RUN mkdir -p /app/final
