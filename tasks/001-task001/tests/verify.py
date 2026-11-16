#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: SNAr reaction and transition-state evidence audit.
"""Canonical Case01 verifier entrypoint."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_support"))
from case01_checker import main

if __name__ == "__main__":
    raise SystemExit(main())
