#!/usr/bin/env python3
# Load the package grader against the public /app/assets mount.
import argparse, os, sys
from pathlib import Path
APP = Path(os.environ.get("APP", "/app")).resolve()
TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()
sys.path.insert(0, str(TESTS / "_support"))
import case04_protocol
case04_protocol.CASE = APP
case04_protocol.ROOT = APP
case04_protocol.ASSETS = APP / "assets"
import case04_verifier
case04_verifier.CASE = APP
case04_verifier.ROOT = APP
case04_verifier.ASSETS = APP / "assets"
parser = argparse.ArgumentParser()
for name in ("final-dir", "runtime-dir", "gold-path", "report"):
    parser.add_argument("--" + name, required=True, type=Path)
args = parser.parse_args()
raise SystemExit(case04_verifier.main([
    "--final-dir", str(args.final_dir), "--runtime-dir", str(args.runtime_dir),
    "--gold-path", str(args.gold_path), "--report", str(args.report),
]))
