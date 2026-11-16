FROM comp-chem-world-base

LABEL org.compchembench.bench="21_newtonnet-hessian-transition-states"

# This task analyses supplied paired eigenvalues; it has no checkpoint or model
# execution. Python's standard library is sufficient for all required metrics.
WORKDIR /app
COPY assets/hessian_eigenvalues.csv assets/output-contract.json /app/assets/
CMD ["/bin/bash"]
