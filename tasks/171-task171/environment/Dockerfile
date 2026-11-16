FROM comp-chem-world-base
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends bash build-essential ca-certificates coreutils curl git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY assets/ /app/assets/
COPY assets/ /app/environment/assets/
RUN mkdir -p /app/final
