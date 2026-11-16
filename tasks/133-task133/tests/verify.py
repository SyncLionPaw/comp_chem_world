#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Blind Validation of the TNEP Dipole Model (Source Table 1).
"""Scorer for case-01: TNEP dipole blind validation (paper Table 1).

Exit codes: 0 = PASS (reward 1), 1 = FAIL (reward 0), 2 = environment error.
Reads agent submission from $APP (default /app/final) and private labels from
$NEP_REFERENCE_ROOT (default: this package's tests/refs.json).
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import math

# --- inlined from the former tests/validation.py ------------------------------
import hashlib
import json
import math
from pathlib import Path


def object_json(path, on_error):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    try:
        obj = json.loads(path.read_text(), object_pairs_hook=pairs,
                         parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {s}")))
        if not isinstance(obj, dict):
            raise ValueError("JSON root must be an object")
        return obj
    except Exception as exc:
        on_error(f"{path.name} unreadable or malformed: {exc}")


def mapping(value, what, on_error):
    if not isinstance(value, dict):
        on_error(f"{what} must be an object")
    return value


def text(value, what, on_error):
    if not isinstance(value, str) or not value.strip():
        on_error(f"{what} must be a nonempty string")
    return value


def number(value, what, on_error):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        on_error(f"{what} must be a finite number")
    return float(value)


def inside(final, rel, on_error):
    text(rel, "artifact path", on_error)
    path = final / rel
    if path.is_symlink():
        on_error(f"symbolic-link artifact is not allowed: {rel}")
    resolved = path.resolve()
    if not resolved.is_relative_to(final.resolve()) or resolved == final.resolve():
        on_error(f"artifact path escapes submission dir: {rel}")
    return resolved


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_file(path, expected, on_error):
    try:
        if not path.is_file() or digest(path) != expected:
            on_error(f"frozen evaluation asset missing or SHA-256 mismatch: {path.name}")
    except OSError as exc:
        on_error(f"frozen evaluation asset unreadable: {path.name}: {exc}")


def engine_logs(final, engine, on_error):
    mapping(engine, "engine", on_error)
    for key in ("name", "version", "build_command"):
        text(engine.get(key), f"engine.{key}", on_error)
    hashes = mapping(engine.get("log_sha256"), "engine.log_sha256", on_error)
    for name in ("build.log", "run.log"):
        path = inside(final, name, on_error)
        try:
            if not path.is_file() or not path.read_text().strip():
                on_error(f"missing or empty {name}")
            if hashes.get(name) != digest(path):
                on_error(f"engine.log_sha256 does not match {name}")
        except (OSError, UnicodeError) as exc:
            on_error(f"cannot read {name}: {exc}")

val = sys.modules[__name__]  # the helpers above, addressed as before

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
PUBLISHED_RMSE = None
LOG_RATIO_TOL = None
N_FRAMES = None
N_ATOMS = None
INPUT_HASHES = None
REFERENCE_SHA256 = 'ef6214986483713baace07d79504e1df72fd48ce4af61d2a0c6820e6213abf7a'
REFERENCE_LABELS_SHA256 = '7fb464d84c9b1ab2774a93890a540a16194aef2607acc9baf170e9b8e8dc21c4'


class SubmissionError(Exception):
    pass


class InfrastructureError(Exception):
    pass


def fail(msg):
    raise SubmissionError(msg)


def infra(msg):
    raise InfrastructureError(msg)


def declaration_words(value, field):
    if not isinstance(value, str) or not value.strip():
        fail(f"{field} must be a non-empty convention declaration")
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def load_contract():
    path = Path(__file__).resolve().parent / "refs.json"
    val.frozen_file(path, REFERENCE_SHA256, infra)
    ref = val.object_json(path, infra)
    labels = {key: value for key, value in ref.items() if key != "_scoring_contract"}
    canonical = json.dumps(labels, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != REFERENCE_LABELS_SHA256:
        infra("private reference labels do not match the frozen label digest")
    contract = ref.get("_scoring_contract")
    if not isinstance(contract, dict):
        infra("private scoring contract is missing or malformed")
    return contract


def load_private():
    path = Path(os.environ.get(
        "NEP_REFERENCE_ROOT",
        Path(__file__).resolve().parent / "refs.json"))
    if not path.is_file() or path.stat().st_size == 0:
        infra(f"private reference missing: {path}")
    val.frozen_file(path, REFERENCE_SHA256, infra)
    ref = val.object_json(path, infra)
    labels = {key: value for key, value in ref.items() if key != "_scoring_contract"}
    canonical = json.dumps(labels, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != REFERENCE_LABELS_SHA256:
        infra("private reference labels do not match the frozen label digest")
    if not isinstance(ref.get("_scoring_contract"), dict):
        infra("private scoring contract is missing or malformed")
    return ref


def read_xyz_frames(path, n_atoms):
    frames = []
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        n = int(lines[i].strip())
        if n != n_atoms:
            infra(f"unexpected atom count in {path.name}: {n} != {n_atoms}")
        frames.append(lines[i + 2:i + 2 + n])
        i += n + 2
    return frames


def load_predictions(final, system):
    meta = final / "results.json"
    if not meta.is_file():
        fail("missing results.json")
    results = val.object_json(meta, fail)
    for key in ("engine", "conventions", "predictions"):
        val.mapping(results.get(key), f"results.json.{key}", fail)
    if "metrics" in results:
        val.mapping(results["metrics"], "results.json.metrics", fail)
    pred_rel = results["predictions"].get(system)
    if not pred_rel:
        fail(f"no prediction file declared for {system}")
    pred_path = val.inside(final, pred_rel, fail)
    if not pred_path.is_file():
        fail(f"prediction file missing: {pred_rel}")
    try:
        data = np.load(pred_path)
    except Exception as exc:
        fail(f"cannot load {pred_rel}: {exc}")
    if "dipole" not in data:
        fail(f"{pred_rel} missing 'dipole' array")
    try:
        arr = np.asarray(data["dipole"], dtype=float)
    except Exception as exc:
        fail(f"invalid dipole array: {exc}")
    if arr.shape != (N_FRAMES, 3):
        fail(f"{system} predictions shape {arr.shape} != ({N_FRAMES}, 3)")
    if not np.isfinite(arr).all():
        fail(f"{system} predictions contain non-finite values")
    return results, arr


def metrics(pred, labels):
    resid = pred - labels
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    denom = float(np.mean(labels.std(axis=0)))
    rrmse = rmse / denom if denom > 0 else float("inf")
    r2 = float(np.mean([
        1.0 - np.sum((labels[:, k] - pred[:, k]) ** 2) / np.sum((labels[:, k] - labels[:, k].mean()) ** 2)
        for k in range(3)]))
    return rmse, rrmse, r2


def main():
    global PUBLISHED_RMSE, LOG_RATIO_TOL, N_FRAMES, N_ATOMS, INPUT_HASHES
    contract = load_contract()
    PUBLISHED_RMSE = {k: v["published_rmse"] for k, v in contract["systems"].items()}
    LOG_RATIO_TOL = contract["log10_ratio_tolerance"]
    N_FRAMES = contract["n_frames"]
    N_ATOMS = {k: v["n_atoms"] for k, v in contract["systems"].items()}
    INPUT_HASHES = contract["input_sha256"]
    final = Path(os.environ.get("APP", "/app/final"))
    inputs = Path(os.environ.get("INPUT_ROOT", "/app/inputs"))
    for name, expected in INPUT_HASHES.items():
        val.frozen_file(inputs / name, expected, infra)
    private = load_private()
    for s in ("h2o", "h2o_dimer", "h5o2plus", "liquid_water"):
        if s not in private or len(private[s]["labels_cell"]) != N_FRAMES:
            infra(f"private reference incomplete for {s}")

    details, all_ok = {}, True
    for system in ("h2o", "h2o_dimer", "h5o2plus", "liquid_water"):
        results, pred = load_predictions(final, system)
        labels = np.asarray(private[system]["labels_cell"], dtype=float)
        n_mol = private[system]["n_molecules_per_frame"]
        if system == "liquid_water":
            labels = labels / n_mol
            raw_conv = results["conventions"].get("liquid_water")
            conv = declaration_words(raw_conv, "conventions.liquid_water")
            legacy_cell_form = (isinstance(raw_conv, str) and re.fullmatch(
                r"\s*per[\s_-]*molecule\s*\(\s*cell\s+dipole\s*/\s*32\s*\)\s*",
                raw_conv, flags=re.IGNORECASE))
            if conv != "per molecule" and not legacy_cell_form:
                fail("liquid_water convention must declare per-molecule (divide by 32)")
        if system == "h5o2plus":
            conv = declaration_words(results["conventions"].get("h5o2plus"),
                                     "conventions.h5o2plus")
            if conv not in {"relative to com", "relative to center of mass", "com relative",
                            "relative to com mu r"}:
                fail("h5o2plus convention must declare relative-to-COM (mu_r)")

        # copy detection: exact bitwise duplication of labels is cheating
        frac_equal = float(np.mean(np.all(np.isclose(pred, labels, rtol=0, atol=1e-12), axis=1)))
        if frac_equal > 0.01:
            fail(f"{system}: {frac_equal:.0%} of predictions bitwise-match hidden labels")

        rmse, rrmse, r2 = metrics(pred, labels)
        # Hidden-label statistics are grader-owned: a blind candidate may omit
        # metrics. Any provided statistic must still be honest and finite.
        if system in results.get("metrics", {}):
            row = val.mapping(results["metrics"][system], f"metrics.{system}", fail)
            for key, actual in (("rmse_ebohr", rmse), ("rrmse", rrmse), ("r2", r2)):
                if key not in row:
                    continue
                reported = val.number(row[key], f"metrics.{system}.{key}", fail)
                if not np.isclose(reported, actual, rtol=1e-3, atol=0):
                    fail(f"{system}: self-reported {key} {reported} != recomputed {actual}")
        ratio = abs(np.log10(rmse / PUBLISHED_RMSE[system]))
        window_ok = bool(ratio <= LOG_RATIO_TOL)
        all_ok = all_ok and window_ok
        details[system] = {"rmse_recomputed": rmse, "rmse_published": PUBLISHED_RMSE[system],
                           "log10_ratio": float(ratio), "rrmse": rrmse, "r2": r2,
                           "within_window": window_ok}

    val.engine_logs(final, results["engine"], fail)
    engine = "n/a"
    try:
        engine = json.loads((final / "results.json").read_text())["engine"]
    except Exception:
        pass
    verdict = {
        "case_id": "case-01",
        "status": "PASS" if all_ok else "FAIL",
        "reward": 1 if all_ok else 0,
        "engine": engine,
        "metrics": details,
        "tolerance": f"|log10(recomputed/published)| <= {LOG_RATIO_TOL}",
    }
    print(json.dumps(verdict, indent=1))
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SubmissionError as exc:
        print(json.dumps({"case_id": "case-01", "status": "FAIL", "reward": 0,
                          "reason": str(exc)}))
        sys.exit(1)
    except InfrastructureError as exc:
        print(json.dumps({"case_id": "case-01", "status": "ENVIRONMENT_ERROR",
                          "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"case_id": "case-01", "status": "ENVIRONMENT_ERROR", "reason": f"unexpected verifier error: {type(exc).__name__}: {exc}"}))
        sys.exit(2)
