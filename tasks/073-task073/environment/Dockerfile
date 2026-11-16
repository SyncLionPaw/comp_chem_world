FROM comp-chem-world-base
WORKDIR /app
RUN python3.12 -m venv /opt/case-python \
 && /opt/case-python/bin/python -m pip install --no-cache-dir numpy==2.2.6 pandas==2.2.3 \
 && /opt/case-python/bin/python -m pip check
ENV PATH="/opt/case-python/bin:${PATH}"
COPY assets/Fig_9a.dat assets/data_dictionary.md /app/assets/
COPY assets/runtime-tools/ /app/assets/runtime-tools/
RUN mkdir -p /app/final
COPY assets/runtime-tools/ /tmp/bench11-runtime-tools/
RUN sh /tmp/bench11-runtime-tools/install.sh \
 && rm -rf /tmp/bench11-runtime-tools
