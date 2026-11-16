FROM compchembench-connectivity:hpc
WORKDIR /app
RUN sed -i 's#http://ports.ubuntu.com#https://ports.ubuntu.com#g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends build-essential=12.10ubuntu1 python3.12-dev=3.12.3-1ubuntu0.17 \
    && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/case05-venv
ENV PATH="/opt/case05-venv/bin:${PATH}" PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN python -m pip install --no-cache-dir pip==26.0.1 \
    && cat > /tmp/case05-build-constraints.txt <<'EOF'
scikit-build-core==0.9.10
setuptools-scm==8.1.0
numpy==1.26.4
EOF
RUN python -m pip install --no-cache-dir --build-constraint /tmp/case05-build-constraints.txt \
    numpy==1.26.4 scipy==1.13.1 monty==2026.7.16 networkx==3.6.1 \
    palettable==3.3.3 pandas==2.2.2 plotly==5.22.0 pymatgen==2024.5.1 \
    requests==2.32.3 ruamel.yaml==0.18.6 spglib==2.3.1 uncertainties==3.2.2 \
    sympy==1.13.1 tabulate==0.9.0 tqdm==4.66.4 matplotlib==3.8.4 lxml==5.2.2 \
    && python -c 'import importlib.metadata as m, numpy, scipy, pymatgen; assert m.version("pymatgen") == "2024.5.1"' \
    && rm -f /tmp/case05-build-constraints.txt
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends tmux=3.4-1ubuntu0.2 \
    && rm -rf /var/lib/apt/lists/*
COPY assets/ /app/assets/
