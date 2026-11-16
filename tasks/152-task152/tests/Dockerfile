FROM comp-chem-world-base

# Credential-free, offline verifier image for Bench23 task 152. It deliberately does
# not inherit the candidate image's SSH configuration or the connectivity parent.
# The public inputs are copied because the task's verifier preflight hash-checks them;
# no test, reference value or solution is baked into the candidate image instead.
WORKDIR /tests
COPY tests/ /tests/
COPY environment/assets/ /app/assets/
