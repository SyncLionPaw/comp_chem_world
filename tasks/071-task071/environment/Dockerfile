FROM comp-chem-world-base
WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ \
 && python3.12 -m venv /opt/case-python \
 && /opt/case-python/bin/python -m pip install --no-cache-dir numpy==2.2.6 scipy==1.15.3 ParmEd==4.3.0 propka==3.5.1 \
 && /opt/case-python/bin/python -m pip check \
 && apt-get purge -y g++ gcc cpp \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/case-python/bin:${PATH}"
COPY assets/F_V72I_ASPASP.rst assets/D_V72I_ASPASP.rst assets/S_V72I.top assets/S_V72I.rst /app/assets/
COPY assets/D_V72I_ASPASP.top.gz assets/F_V72I_ASPASP.top.gz /tmp/task72-topologies/
RUN cd /tmp/task72-topologies \
 && printf '%s  %s\n' '41377037385390c56d8d802cd2f75a0aba8a2090104502e1b486d42c34fbf3df' D_V72I_ASPASP.top.gz 'd8aed5fee63a6cd88350d02fc7075af5a709bdb46fadd6778bdfff6a56e439ac' F_V72I_ASPASP.top.gz | sha256sum --check --strict \
 && gzip -t D_V72I_ASPASP.top.gz F_V72I_ASPASP.top.gz \
 && gzip -dc D_V72I_ASPASP.top.gz > /app/assets/D_V72I_ASPASP.top \
 && gzip -dc F_V72I_ASPASP.top.gz > /app/assets/F_V72I_ASPASP.top \
 && test "$(wc -c < /app/assets/D_V72I_ASPASP.top)" -eq 115191865 \
 && test "$(wc -c < /app/assets/F_V72I_ASPASP.top)" -eq 164180209 \
 && printf '%s  %s\n' '331fe0bf7eb306d564a3e4cdc2927d555821919d2a141b17455621ac490b50f9' /app/assets/D_V72I_ASPASP.top '2ad547555c30fd49dc9645689e483c3c6ea26dab4270d65e559a81afcfd1979b' /app/assets/F_V72I_ASPASP.top | sha256sum --check --strict \
 && rm -rf /tmp/task72-topologies
RUN mkdir -p /app/final
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools
