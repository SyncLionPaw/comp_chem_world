# HPC connectivity image: cluster SSH + hpc CLI + docs-only skill.
# Task Dockerfiles either FROM this tag directly, or COPY the skill/ssh/CLI
# bits out of it (see tasks/*/environment/Dockerfile). Tag must stay
#   compchembench-connectivity:hpc
# (and optionally :hpc-amd64) so existing task Dockerfiles resolve.
ARG BASE_IMAGE=comp-chem-world-base
FROM ${BASE_IMAGE}

ARG PARENT_IMAGE_ID=unverified
LABEL org.compchemworld.connectivity.parent-image-id="${PARENT_IMAGE_ID}"

# Base is credential-free and has no SSH client. Connectivity owns both.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync \
    && rm -rf /var/lib/apt/lists/*

# Cluster SSH material is baked in so job submission depends only on the
# container's own ssh/hpc (no runtime injection from the runner).
COPY ssh/ /root/.ssh/
RUN chmod 700 /root/.ssh \
    && chmod 600 /root/.ssh/config /root/.ssh/hpc_id_rsa \
    && if [ -f /root/.ssh/vasp-site.json ]; then chmod 600 /root/.ssh/vasp-site.json; fi

# Runtime CLI lives outside the skill tree.
COPY cli/submit.py /opt/hpc/submit.py
COPY cli/hpc /usr/local/bin/hpc
RUN chmod 755 /opt/hpc/submit.py /usr/local/bin/hpc \
    && hpc --help >/dev/null

# Skill = documentation only (SKILL.md + references).
COPY hpc/ /opt/skills/hpc/
RUN mkdir -p /root/.claude/skills /root/.codex/skills \
    && ln -sfn /opt/skills/hpc /root/.claude/skills/hpc \
    && ln -sfn /opt/skills/hpc /root/.codex/skills/hpc
