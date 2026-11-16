#!/usr/bin/env python3
"""Unified read-only grader for Case 05."""
import argparse, os
from pathlib import Path
from review_status import run_case

p = argparse.ArgumentParser()
p.add_argument("--runner", action="store_true")
p.add_argument("submission", nargs="?", type=Path)
a = p.parse_args()
if a.runner or a.submission is None:
    raise SystemExit(run_case(Path(os.environ.get("APP", "/app")).resolve(),
                              Path(os.environ.get("TESTS", "/tests")).resolve(),
                              Path(os.environ.get("LOGS", "/logs/verifier")).resolve()))
raise SystemExit("direct submission mode was removed; use APP/TESTS/LOGS through the runner")
