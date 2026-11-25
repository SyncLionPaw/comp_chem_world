# HPC connectivity image: baked cluster SSH + workspace AGENTS.md.
# Task Dockerfiles FROM this tag (or COPY /root/.ssh from it).
# Tag must stay compchembench-connectivity:hpc (and optionally :hpc-amd64).
ARG BASE_IMAGE=comp-chem-world-base
FROM ${BASE_IMAGE}

ARG PARENT_IMAGE_ID=unverified
LABEL org.compchemworld.connectivity.parent-image-id="${PARENT_IMAGE_ID}"

WORKDIR /app

# Base is credential-free and has no SSH client. Connectivity owns both.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync \
    && rm -rf /var/lib/apt/lists/*

# Cluster SSH material is baked in (no runtime injection from the runner).
COPY ssh/ /root/.ssh/
RUN chmod 700 /root/.ssh \
    && chmod 600 /root/.ssh/config /root/.ssh/hpc_id_rsa \
    && if [ -f /root/.ssh/vasp-site.json ]; then chmod 600 /root/.ssh/vasp-site.json; fi

# Agent-facing cluster rules (stay-in-lane + job dir naming).
COPY AGENTS.md /app/AGENTS.md
