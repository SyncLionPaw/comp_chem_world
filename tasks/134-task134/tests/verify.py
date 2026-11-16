#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: TNEP Polarizability and Blind Validation on QM7B.
"""Scorer for case-02: TNEP polarizability blind validation (Table 2 + QM7B).

Exit codes: 0 = PASS, 1 = FAIL, 2 = environment error.
"""
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
PUBLISHED = None
QM7B_PUBLISHED = None
LOG_RATIO_TOL = None
MOLECULAR = None
INPUT_HASHES = None
REFERENCE_SHA256 = '956a65dcbcfa5866735eaf383806aeb2c9ff6a3ca0a1445654786c6b4145b75e'
REFERENCE_LABELS_SHA256 = 'be7fc818b673c5918e095574dfe9e6b59e7183e6fcc82028d560db07b2984376'


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


def precision_bits(value, *, missing=False):
    if missing:
        return 64
    if not isinstance(value, str) or not value.strip():
        fail("engine.precision must explicitly name a supported precision")
    words = declaration_words(value, "engine.precision")
    aliases = {
        32: {"float32", "float 32", "32 bit float", "single", "single precision", "fp32",
             "ieee 754 single", "ieee 754 single precision", "ieee754 single"},
        64: {"float64", "float 64", "64 bit float", "double", "double precision", "fp64",
             "ieee 754 double", "ieee 754 double precision", "ieee754 double"},
    }
    matches = [bits for bits, names in aliases.items() if words in names]
    if len(matches) != 1:
        fail("engine.precision must be a single/double 32/64-bit precision declaration")
    return matches[0]


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


def load_results(final):
    meta = final / "results.json"
    if not meta.is_file():
        fail("missing results.json")
    results = val.object_json(meta, fail)
    for key in ("engine", "conventions", "predictions"):
        val.mapping(results.get(key), f"results.json.{key}", fail)
    if "metrics" in results:
        val.mapping(results["metrics"], "results.json.metrics", fail)
    precision = precision_bits(results["engine"].get("precision"),
                               missing="precision" not in results["engine"])
    val.engine_logs(final, results["engine"], fail)
    for key in ("molecular_polarizability", "offdiag", "qm7b"):
        val.text(results["conventions"].get(key), f"conventions.{key}", fail)
    return results


def load_array(final, results, system, key, shape):
    pred_rel = results["predictions"].get(system)
    if not pred_rel:
        fail(f"no prediction file declared for {system}")
    pred_path = val.inside(final, pred_rel, fail)
    if not pred_path.is_file():
        fail(f"prediction file missing: {pred_rel}")
    try:
        arr = np.asarray(np.load(pred_path)[key], dtype=float)
    except Exception as exc:
        fail(f"cannot load {pred_rel}: {exc}")
    if arr.shape != shape:
        fail(f"{system} '{key}' shape {arr.shape} != {shape}")
    if not np.isfinite(arr).all():
        fail(f"{system} '{key}' contains non-finite values")
    if key == "polarizability":
        tensor = arr.reshape(-1, 3, 3)
        tol = 1e-4 if precision_bits(results["engine"].get("precision"),
                                     missing="precision" not in results["engine"]) == 32 else 1e-6
        if not np.allclose(tensor, tensor.transpose(0, 2, 1), rtol=tol, atol=tol):
            fail(f"{system}: rank-2 polarizability must be symmetric (rtol=atol={tol})")
    return arr


def tensor_rmse(pred, labels):
    pred = pred.reshape(len(pred), 3, 3)
    labels = labels.reshape(len(labels), 3, 3)
    diag_idx = [0, 1, 2]
    off_idx = [(0, 1), (0, 2), (1, 2)]
    d = np.concatenate([ (pred[:, i, i] - labels[:, i, i])[:, None] for i in diag_idx], axis=1)
    o = np.concatenate([ (pred[:, i, j] - labels[:, i, j])[:, None] for i, j in off_idx], axis=1)
    return (float(np.sqrt(np.mean(d ** 2))), float(np.sqrt(np.mean(o ** 2))))


def check_copy(pred, labels, what):
    if pred.shape == labels.shape:
        frac = float(np.mean(np.all(np.isclose(pred, labels, rtol=0, atol=1e-12), axis=1)))
        if frac > 0.01:
            fail(f"{what}: {frac:.0%} of predictions bitwise-match hidden labels")


def main():
    global PUBLISHED, QM7B_PUBLISHED, LOG_RATIO_TOL, MOLECULAR, INPUT_HASHES
    contract = load_contract()
    PUBLISHED = contract["published_rmse"]
    QM7B_PUBLISHED = contract["qm7b_published_rmse"]
    LOG_RATIO_TOL = contract["log10_ratio_tolerance"]
    MOLECULAR = contract["molecular_frames"]
    INPUT_HASHES = contract["input_sha256"]
    final = Path(os.environ.get("APP", "/app/final"))
    inputs = Path(os.environ.get("INPUT_ROOT", "/app/inputs"))
    for name, expected in INPUT_HASHES.items():
        val.frozen_file(inputs / name, expected, infra)
    private = load_private()
    results = load_results(final)
    details, all_ok = {}, True

    def reported_metric(system, key, actual):
        # The blind candidate cannot compute hidden-label errors. Omission is
        # valid; any statistic it chooses to report is checked independently.
        if system not in results.get("metrics", {}):
            return
        row = val.mapping(results["metrics"][system], f"metrics.{system}", fail)
        if key not in row:
            return
        reported = val.number(row[key], f"metrics.{system}.{key}", fail)
        if not np.isclose(reported, actual, rtol=1e-3, atol=0):
            fail(f"{system}: self-reported {key} {reported} != recomputed {actual}")

    # molecular polarizability
    for system, n_frames in MOLECULAR.items():
        labels = np.asarray(private[system]["labels_cell"], dtype=float)
        pred = load_array(final, results, system, "polarizability", (n_frames, 9))
        check_copy(pred, labels, system)
        rmse_d, rmse_o = tensor_rmse(pred, labels)
        row = {}
        for kind, value, anchor in (("diag", rmse_d, PUBLISHED[system]["diag"]),
                                    ("offdiag", rmse_o, PUBLISHED[system]["offdiag"])):
            reported_metric(system, kind + "_rmse_bohr3", value)
            ratio = abs(np.log10(value / anchor))
            ok = bool(ratio <= LOG_RATIO_TOL)
            all_ok = all_ok and ok
            row[kind] = {"recomputed": value, "published": anchor,
                         "log10_ratio": float(ratio), "within_window": ok}
        details[system] = row

    # QM7B per-atom metrics
    for system, key in (("qm7b_dipole", "dipole"), ("qm7b_polarizability", "polarizability")):
        entry = private[system]
        labels = np.asarray(entry["labels_cell"], dtype=float)
        natoms = np.asarray(entry["n_atoms"], dtype=float)
        shape = (len(natoms), 3 if key == "dipole" else 9)
        pred = load_array(final, results, system, key, shape)
        check_copy(pred / natoms[:, None], labels / natoms[:, None], system)
        resid = (pred - labels) / natoms[:, None]
        rmse = float(np.sqrt(np.mean(resid ** 2)))
        if key == "dipole":
            anchors = {"dipole": rmse}
        else:
            p = pred.reshape(len(pred), 3, 3)
            l = labels.reshape(len(labels), 3, 3)
            rd = (p - l) / natoms[:, None, None]
            diag = float(np.sqrt(np.mean(np.stack([rd[:, i, i] for i in range(3)], axis=1) ** 2)))
            off = float(np.sqrt(np.mean(np.stack(
                [rd[:, i, j] for i, j in [(0, 1), (0, 2), (1, 2)]], axis=1) ** 2)))
            anchors = {"alpha_diag": diag, "alpha_offdiag": off}
            rmse = None
        row = {}
        for kind, value in anchors.items():
            reported_key = {"dipole": "dipole_rmse_per_atom", "alpha_diag": "diag_rmse_per_atom",
                            "alpha_offdiag": "offdiag_rmse_per_atom"}[kind]
            reported_metric(system, reported_key, value)
            anchor = QM7B_PUBLISHED[kind]
            ratio = abs(np.log10(value / anchor))
            ok = bool(ratio <= LOG_RATIO_TOL)
            all_ok = all_ok and ok
            row[kind] = {"recomputed": value, "published": anchor,
                         "log10_ratio": float(ratio), "within_window": ok}
        if key == "dipole":
            details[system] = row
        else:
            details.setdefault(system, {}).update(row)

    engine = results.get("engine", "n/a")
    verdict = {"case_id": "case-02", "status": "PASS" if all_ok else "FAIL",
               "reward": 1 if all_ok else 0, "engine": engine, "metrics": details,
               "tolerance": f"|log10(recomputed/published)| <= {LOG_RATIO_TOL}"}
    print(json.dumps(verdict, indent=1))
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SubmissionError as exc:
        print(json.dumps({"case_id": "case-02", "status": "FAIL", "reward": 0, "reason": str(exc)}))
        sys.exit(1)
    except InfrastructureError as exc:
        print(json.dumps({"case_id": "case-02", "status": "ENVIRONMENT_ERROR", "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"case_id": "case-02", "status": "ENVIRONMENT_ERROR", "reason": f"unexpected verifier error: {type(exc).__name__}: {exc}"}))
        sys.exit(2)
