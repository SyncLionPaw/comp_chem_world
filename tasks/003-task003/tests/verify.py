#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Low-data model and representation comparison.
"""Canonical Case 03 verifier entrypoint for revision 6."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

SUPPORT = Path(__file__).resolve().parent / "_support"
sys.path.insert(0, str(SUPPORT))
runpy.run_path(str(SUPPORT / "verify_v6.py"), run_name="__main__")
