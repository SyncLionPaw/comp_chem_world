FROM comp-chem-world-base

WORKDIR /app

COPY environment/assets/vendor/requirements.lock.txt /tmp/case05-requirements.lock.txt
RUN python3 -m venv /opt/case05-venv \
    && /opt/case05-venv/bin/python -m pip install --no-cache-dir --require-hashes \
      -r /tmp/case05-requirements.lock.txt \
    && /opt/case05-venv/bin/python -m pip check \
    && /opt/case05-venv/bin/python -c 'import sys, importlib.metadata as m, attrs, iodata, numpy, scipy; from iodata.overlap import compute_overlap; expected={"attrs":"25.4.0","qc-iodata":"1.0.1","numpy":"2.2.6","scipy":"1.16.3"}; actual={name:m.version(name) for name in expected}; assert sys.version_info[:2]==(3,12) and sys.prefix=="/opt/case05-venv" and actual==expected, (sys.version,sys.prefix,actual); print({"python":sys.version.split()[0],"prefix":sys.prefix,"packages":actual})'
ENV PATH="/opt/case05-venv/bin:${PATH}"

COPY environment/assets/data/public/ /app/assets/
COPY environment/assets/config/output-contract.yaml /app/assets/output-contract.yaml
COPY environment/assets/scripts/ /app/assets/tools/
COPY tests/ /tests/
