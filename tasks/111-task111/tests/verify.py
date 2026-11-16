#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Implement RDKit internal-coordinate restraints.
"""Verifier entrypoint for the RDKit internal-coordinate constraint task.

The suite, its fixtures and the trusted worker supervisor live next to this
file; this module only starts pytest so tests/test.sh has the single
``verify.py`` entrypoint the task layout requires.
"""

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["/tests", "-rA"]))
