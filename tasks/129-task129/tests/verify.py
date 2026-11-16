#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including thermo.json).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Compute thermochemistry for SMILES-specified molecules.
"""Trusted verifier for case-10-smi-gibbs.

The reference value lives in tests/refs.json and is never recomputed from
candidate-writable files. A missing or malformed artifact is FAIL; an
infrastructure problem is ENVIRONMENT_ERROR (exit 2), never a scientific FAIL.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path(os.environ.get("APP", "/app"))
TESTS = Path(os.environ.get("TESTS", Path(__file__).resolve().parent))
LOGS = Path(os.environ.get("LOGS", "/logs/verifier"))


class Failure(Exception):
    """A scientific or contractual failure of the submission."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def read_xyz(path: Path):
    import numpy as np

    lines = path.read_text(encoding="utf-8").splitlines()
    require(len(lines) >= 2, f"{path.name}: needs an atom count and a comment line")
    try:
        count = int(lines[0].split()[0])
    except (ValueError, IndexError) as exc:
        raise Failure(f"{path.name}: first line is not an atom count") from exc
    require(len(lines) - 2 >= count, f"{path.name}: declares {count} atoms but has fewer")
    symbols, positions = [], []
    for line in lines[2:2 + count]:
        parts = line.split()
        require(len(parts) >= 4, f"{path.name}: malformed atom line {line!r}")
        symbols.append(parts[0])
        positions.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return symbols, np.asarray(positions, dtype=float)


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        refs = json.loads((TESTS / "refs.json").read_text(encoding="utf-8"))
        artifact = APP / refs["artifact"]
        require(artifact.is_file(), f"missing declared artifact: {refs['artifact']}")
        try:
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except (ValueError, RecursionError) as exc:
            raise Failure(f"Malformed JSON artifact: {exc}") from exc
        key = refs["key"]
        want = refs["value"][key]
        require(isinstance(data, dict), "thermo.json must be a JSON object")
        require(key in data, f"thermo.json must contain {key!r}")
        got = data[key]
        require(isinstance(got, (int, float)) and not isinstance(got, bool),
                f"{key} must be a number")
        require(abs(float(got) - float(want)) < 0.01, f"{key}={got} differs from the reference by at least 0.01 eV")  # B2: thermo_value
        result = {"status": "PASS", "reward": 1.0, "case_id": refs["case_id"],
                  "kind": refs["kind"]}
        rc = 0
    except Failure as exc:
        result = {"status": "FAIL", "reward": 0.0, "error": str(exc)}
        rc = 1
    except Exception as exc:  # infrastructure problem, never a scientific FAIL
        print(json.dumps({"status": "ENVIRONMENT_ERROR",
                           "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    (LOGS / "reward.txt").write_text(f"{result['reward']}\n", encoding="utf-8")
    (LOGS / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
