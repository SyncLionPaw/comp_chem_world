#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Rotational Equivariance Check for the TNEP Tensor Model.
"""Scorer for case-03: rotational equivariance of TNEP tensor models (SI S9).

Exit codes: 0 = PASS, 1 = FAIL, 2 = environment error.

The residual check is the rank-1/rank-2 identity. It is accepted only together
with geometry-bound inference dumps: rotated coordinates must equal the
declared rotation acting on the package coordinates, and both orientations
must have an extended XYZ whose coordinates and μ/α match the submission.
The scorer does not re-execute NEP.
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
PUBLISHED_MU_RMSE = None
PUBLISHED_ALPHA_RMSE_DIAG = None
LOG_RATIO_TOL = None
N_FRAMES = None
N_ATOMS = None
MIN_ANGLE_RAD = None
COORD_ATOL = None
MASSES = None
INPUT_XYZ = Path(os.environ.get("INPUT_ROOT", "/app/inputs")) / "test-positions-h2o-200.xyz"

INPUT_HASHES = None
REFERENCE_SHA256 = 'eb8a922b73a82802e2a2604fea4f4f23699448ac628b39f1fb0346cb5d5a7c9c'
REFERENCE_LABELS_SHA256 = '2bd15d9bc74e639df091e768e0918171f8ae80f4b827869cc340e3a050e1b36c'


class SubmissionError(Exception):
    pass


class InfrastructureError(Exception):
    pass


def fail(msg):
    raise SubmissionError(msg)


def infra(msg):
    raise InfrastructureError(msg)


def precision_bits(value):
    if not isinstance(value, str) or not value.strip():
        fail("engine.precision must explicitly name a supported precision")
    words = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
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


def sha256_file(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


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
    if len(ref.get("dipole_labels", [])) != N_FRAMES or \
       len(ref.get("polarizability_labels", [])) != N_FRAMES:
        infra("private reference does not contain 200-frame labels")
    return ref


def read_extxyz(path, on_error=fail):
    if not path.is_file() or path.stat().st_size == 0:
        on_error(f"missing or empty coordinate file: {path.name}")
    lines = path.read_text().splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            n = int(lines[i].strip())
        except ValueError:
            on_error(f"{path.name}: expected atom count at line {i + 1}")
        if n != N_ATOMS:
            on_error(f"{path.name}: frame {len(frames)} has {n} atoms, expected {N_ATOMS}")
        if i + 1 + n >= len(lines):
            on_error(f"{path.name}: truncated frame {len(frames)}")
        comment = lines[i + 1]
        atoms = []
        for j in range(n):
            parts = lines[i + 2 + j].split()
            if len(parts) < 4:
                on_error(f"{path.name}: frame {len(frames)} atom line is incomplete")
            try:
                xyz = np.asarray(parts[1:4], dtype=float)
            except ValueError:
                on_error(f"{path.name}: frame {len(frames)} has invalid coordinates")
            if not np.isfinite(xyz).all():
                on_error(f"{path.name}: frame {len(frames)} has non-finite coordinates")
            atoms.append((parts[0], *xyz))
        frames.append({"comment": comment, "atoms": atoms})
        i += n + 2
    if len(frames) != N_FRAMES:
        on_error(f"{path.name}: expected {N_FRAMES} frames, found {len(frames)}")
    return frames


def quoted_floats(comment, key, n):
    attributes = {}
    i = 0
    while i < len(comment):
        while i < len(comment) and comment[i].isspace():
            i += 1
        if i == len(comment):
            break

        start = i
        while i < len(comment) and not comment[i].isspace() and comment[i] != "=":
            i += 1
        name = comment[start:i]
        while i < len(comment) and comment[i].isspace():
            i += 1
        if not name or i == len(comment) or comment[i] != "=":
            # Consume one free-text token, respecting quotes so text inside a
            # different attribute cannot masquerade as a required attribute.
            i = start
            quote = comment[i] if comment[i] in "\"'" else None
            if quote:
                i += 1
                while i < len(comment) and comment[i] != quote:
                    i += 1
                if i < len(comment):
                    i += 1
            else:
                while i < len(comment) and not comment[i].isspace():
                    i += 1
            continue

        i += 1
        while i < len(comment) and comment[i].isspace():
            i += 1
        if i == len(comment) or comment[i] not in "\"'":
            quote = None
            value_start = i
            if i < len(comment) and comment[i] == "[":
                closing = comment.find("]", i + 1)
                i = len(comment) if closing == -1 else closing + 1
            else:
                while i < len(comment) and not comment[i].isspace():
                    i += 1
            value = comment[value_start:i]
        else:
            quote = comment[i]
            i += 1
            value_start = i
            while i < len(comment) and comment[i] != quote:
                i += 1
            if i == len(comment):
                fail(f"{name} attribute has an unterminated quoted value")
            value = comment[value_start:i]
            i += 1
        if i < len(comment) and not comment[i].isspace():
            fail(f"{name} attribute must be followed by whitespace or end of comment")

        if name == key:
            if name in attributes:
                fail(f"{key} attribute must appear exactly once")
            if quote is None and not value.startswith("["):
                fail(f'{key} attribute must use a quoted value or bracketed JSON list ({n} floats)')
            attributes[name] = value

    if key not in attributes:
        fail(f'{key} attribute missing an array value ({n} floats)')
    raw_values = attributes[key].strip()
    bracketed = raw_values.startswith("[") or raw_values.endswith("]")
    if bracketed:
        if not (raw_values.startswith("[") and raw_values.endswith("]")):
            fail(f"{key} array has mismatched brackets")
        try:
            vals = json.loads(raw_values, parse_constant=lambda token: fail(
                f"{key} contains non-finite JSON number {token}"))
        except (ValueError, TypeError):
            fail(f"{key} quoted array is not a JSON numeric list")
        if not isinstance(vals, list) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) for value in vals):
            fail(f"{key} JSON array must contain only numeric values")
    else:
        if not raw_values or re.search(r"(?:^\s*,|,\s*(?:,|$))", raw_values):
            fail(f"{key} contains an empty numeric item")
        tokens = re.split(r"(?:\s*,\s*|\s+)", raw_values)
        try:
            vals = [float(token) for token in tokens]
        except ValueError:
            fail(f"{key} contains an invalid float token")
    if len(vals) != n:
        fail(f"{key} must contain {n} floats, found {len(vals)}")
    try:
        vals = np.asarray(vals, dtype=float)
    except (TypeError, ValueError, OverflowError):
        fail(f"{key} values cannot be represented as finite floats")
    if not np.isfinite(vals).all():
        fail(f"{key} contains non-finite values")
    return vals


def frame_geometry(frame):
    species = [a[0] for a in frame["atoms"]]
    coords = np.array([[a[1], a[2], a[3]] for a in frame["atoms"]], dtype=float)
    return species, coords


def center_of(coords, species, mode):
    if mode == "origin":
        return np.zeros(3)
    if mode != "com":
        fail("rotation_protocol.center must be 'origin' or 'com'")
    masses = []
    for sym in species:
        if sym not in MASSES:
            fail(f"unsupported element for COM rotation: {sym}")
        masses.append(MASSES[sym])
    w = np.asarray(masses, dtype=float)
    return (coords * w[:, None]).sum(axis=0) / w.sum()


def rotation_angle(rot):
    cos_theta = float(np.clip((np.trace(rot) - 1.0) / 2.0, -1.0, 1.0))
    return float(np.arccos(cos_theta))


def inside(final, rel):
    path = (final / rel).resolve()
    if not str(path).startswith(str(final.resolve()) + os.sep) and path != final.resolve():
        fail(f"path escapes submission dir: {rel}")
    return path


def main():
    global PUBLISHED_MU_RMSE, PUBLISHED_ALPHA_RMSE_DIAG, LOG_RATIO_TOL
    global N_FRAMES, N_ATOMS, MIN_ANGLE_RAD, COORD_ATOL, MASSES, INPUT_HASHES
    contract = load_contract()
    PUBLISHED_MU_RMSE = contract["published_rmse"]["dipole"]
    PUBLISHED_ALPHA_RMSE_DIAG = contract["published_rmse"]["polarizability_diagonal"]
    LOG_RATIO_TOL = contract["log10_ratio_tolerance"]
    N_FRAMES = contract["n_frames"]
    N_ATOMS = contract["n_atoms"]
    MIN_ANGLE_RAD = contract["minimum_rotation_angle_rad"]
    COORD_ATOL = contract["coordinate_absolute_tolerance"]
    MASSES = contract["masses"]
    INPUT_HASHES = contract["input_sha256"]
    final = Path(os.environ.get("APP", "/app/final"))
    val.frozen_file(INPUT_XYZ, INPUT_HASHES[INPUT_XYZ.name], infra)
    source_frames = read_extxyz(INPUT_XYZ, on_error=infra)

    path = final / "equivariance.json"
    if not path.is_file():
        fail("missing equivariance.json")
    sub = val.object_json(path, fail)

    for key in ("engine", "rotation_protocol", "residual_summary", "frames"):
        if key not in sub:
            fail(f"missing key: {key}")
    val.mapping(sub["engine"], "engine", fail)
    for key in ("name", "version", "precision"):
        val.text(sub["engine"].get(key), f"engine.{key}", fail)
    val.mapping(sub["residual_summary"], "residual_summary", fail)
    protocol = val.mapping(sub["rotation_protocol"], "rotation_protocol", fail)
    for key in ("seed", "distribution", "n_rotations", "center"):
        if key not in protocol:
            fail(f"rotation_protocol missing {key}")
    if val.number(protocol["n_rotations"], "rotation_protocol.n_rotations", fail) != N_FRAMES:
        fail(f"rotation_protocol.n_rotations must be {N_FRAMES}")
    seed = val.number(protocol["seed"], "rotation_protocol.seed", fail)
    if seed != int(seed):
        fail("rotation_protocol.seed must be an integer")
    val.text(protocol["distribution"], "rotation_protocol.distribution", fail)
    center_mode = str(protocol["center"])
    frames = sub["frames"]
    if not isinstance(frames, list) or len(frames) != N_FRAMES:
        fail(f"frames must be a list of {N_FRAMES} frames")

    precision = precision_bits(sub["engine"]["precision"])
    mu_tol, alpha_tol = (1e-4, 1e-4) if precision == 32 else (1e-6, 1e-6)
    log_hash = sub["engine"].get("log_sha256")
    if not isinstance(log_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", log_hash):
        fail("engine.log_sha256 must be the SHA-256 of inference.log")

    rotated_xyz = inside(final, "rotated-positions.xyz")
    raw_u = inside(final, "inference-unrotated.xyz")
    raw_r = inside(final, "inference-rotated.xyz")
    log_path = inside(final, "inference.log")
    rotated_frames = read_extxyz(rotated_xyz)
    dump_u = read_extxyz(raw_u)
    dump_r = read_extxyz(raw_r)

    mu_lab = np.asarray(load_private()["dipole_labels"], dtype=float)
    al_lab = np.asarray(load_private()["polarizability_labels"], dtype=float)

    mu_u, mu_r, al_u, al_r, rots = [], [], [], [], []

    def as_vec(v, n, what):
        try:
            arr = np.asarray(v, dtype=float)
        except (TypeError, ValueError) as exc:
            fail(f"{what} invalid array: {exc}")
        if arr.size != n:
            fail(f"{what} must contain {n} numbers (flat or 3x3)")
        return arr.reshape(n)

    for k, fr in enumerate(frames):
        val.mapping(fr, f"frame {k}", fail)
        if val.number(fr.get("frame"), f"frame {k}.frame", fail) != k:
            fail(f"frame {k}: frame identifier must preserve input order")
        for key, n in (("mu_unrotated", 3), ("mu_rotated", 3), ("alpha_unrotated", 9),
                       ("alpha_rotated", 9)):
            if key not in fr:
                fail(f"frame {k}: missing {key}")
        if not isinstance(fr.get("R"), list) or len(fr["R"]) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in fr["R"]):
            fail(f"frame {k}: R must be 3x3")
        rots.append(as_vec(fr["R"], 9, f"frame {k} R").reshape(3, 3))
        mu_u.append(as_vec(fr["mu_unrotated"], 3, f"frame {k} mu_unrotated"))
        mu_r.append(as_vec(fr["mu_rotated"], 3, f"frame {k} mu_rotated"))
        al_u.append(as_vec(fr["alpha_unrotated"], 9, f"frame {k} alpha_unrotated"))
        al_r.append(as_vec(fr["alpha_rotated"], 9, f"frame {k} alpha_rotated"))
    mu_u, mu_r = np.asarray(mu_u), np.asarray(mu_r)
    al_u, al_r = np.asarray(al_u).reshape(-1, 3, 3), np.asarray(al_r).reshape(-1, 3, 3)
    rots = np.asarray(rots)
    if not (np.isfinite(mu_u).all() and np.isfinite(mu_r).all()
            and np.isfinite(al_u).all() and np.isfinite(al_r).all() and np.isfinite(rots).all()):
        fail("non-finite values in submission")

    eye = np.stack([np.eye(3)] * N_FRAMES)
    if np.abs(np.einsum("fki,fkj->fij", rots, rots) - eye).max() > 1e-10:
        fail("rotation matrices are not orthogonal (|R^T R - I| > 1e-10)")
    if np.max(np.abs(np.linalg.det(rots) - 1.0)) > 1e-10:
        fail("R must be a proper rotation: det(R)=+1; reflections are not rotations")
    angles = np.array([rotation_angle(rots[k]) for k in range(N_FRAMES)])
    if float(angles.min()) < MIN_ANGLE_RAD:
        fail(f"rotation angle {angles.min():.3f} rad is below {MIN_ANGLE_RAD} rad; "
             "identity or near-identity rotations do not test a rotated geometry")

    coord_err = 0.0
    for k in range(N_FRAMES):
        src_species, src = frame_geometry(source_frames[k])
        rot_species, rot_xyz = frame_geometry(rotated_frames[k])
        du_species, du_xyz = frame_geometry(dump_u[k])
        dr_species, dr_xyz = frame_geometry(dump_r[k])
        if src_species != rot_species or src_species != du_species or src_species != dr_species:
            fail(f"frame {k}: species order changed under rotation")
        if np.max(np.abs(du_xyz - src)) > COORD_ATOL:
            fail(f"frame {k}: inference-unrotated.xyz does not match the package coordinates")
        center = center_of(src, src_species, center_mode)
        expected = (rots[k] @ (src - center).T).T + center
        err = float(np.max(np.abs(rot_xyz - expected)))
        coord_err = max(coord_err, err)
        if err > COORD_ATOL:
            fail(f"frame {k}: rotated coordinates differ from R (x-c)+c by {err:.3e} Å")
        if float(np.sqrt(np.mean((rot_xyz - src) ** 2))) < 1e-3:
            fail(f"frame {k}: rotated coordinates are indistinguishable from the original")
        if np.max(np.abs(dr_xyz - rot_xyz)) > COORD_ATOL:
            fail(f"frame {k}: inference-rotated.xyz coordinates differ from rotated-positions.xyz")
        dump_mu_u = quoted_floats(dump_u[k]["comment"], "dipole", 3)
        dump_al_u = quoted_floats(dump_u[k]["comment"], "polarizability", 9)
        dump_mu_r = quoted_floats(dump_r[k]["comment"], "dipole", 3)
        dump_al_r = quoted_floats(dump_r[k]["comment"], "polarizability", 9)
        if np.max(np.abs(dump_mu_u - mu_u[k])) > mu_tol or \
           np.max(np.abs(dump_al_u - al_u[k].reshape(-1))) > alpha_tol:
            fail(f"frame {k}: unrotated dump μ/α does not match equivariance.json")
        if np.max(np.abs(dump_mu_r - mu_r[k])) > mu_tol or \
           np.max(np.abs(dump_al_r - al_r[k].reshape(-1))) > alpha_tol:
            fail(f"frame {k}: rotated dump μ/α does not match equivariance.json")

    log_text = log_path.read_text() if log_path.is_file() else ""
    if not log_text.strip():
        fail("inference.log is missing or empty")
    if sha256_file(log_path) != log_hash:
        fail("engine.log_sha256 does not match inference.log")
    required_hashes = {
        "input_sha256": sha256_file(INPUT_XYZ),
        "rotated_xyz_sha256": sha256_file(rotated_xyz),
        "inference_unrotated_sha256": sha256_file(raw_u),
        "inference_rotated_sha256": sha256_file(raw_r),
    }
    for key, digest in required_hashes.items():
        if f"{key}={digest}" not in log_text:
            fail(f"inference.log does not record {key} of the submitted file")
    if "run=unrotated" not in log_text or "run=rotated" not in log_text:
        fail("inference.log must record both run=unrotated and run=rotated")

    mu_rmse = float(np.sqrt(np.mean((mu_u - mu_lab) ** 2)))
    al_d = np.stack([al_u[:, i, i] for i in range(3)], axis=1)
    ld = np.stack([al_lab.reshape(-1, 3, 3)[:, i, i] for i in range(3)], axis=1)
    al_rmse = float(np.sqrt(np.mean((al_d - ld) ** 2)))
    mu_ok = abs(np.log10(mu_rmse / PUBLISHED_MU_RMSE)) <= LOG_RATIO_TOL
    al_ok = abs(np.log10(al_rmse / PUBLISHED_ALPHA_RMSE_DIAG)) <= LOG_RATIO_TOL
    if not mu_ok:
        fail(f"unrotated dipole RMSE {mu_rmse:.3e} outside anchor window "
             f"({PUBLISHED_MU_RMSE:.1e}, factor 10^{LOG_RATIO_TOL})")
    if not al_ok:
        fail(f"unrotated diagonal polarizability RMSE {al_rmse:.3e} outside anchor window")

    mu_expect = np.einsum("fij,fj->fi", rots, mu_u)
    al_expect = np.einsum("fij,fjk,flk->fil", rots, al_u, rots)  # R alpha R^T
    dmu = np.abs(mu_expect - mu_r)
    dal = np.abs(al_expect - al_r) / (np.abs(al_expect) + 1e-12)
    max_mu, rms_mu = float(dmu.max()), float(np.sqrt(np.mean(dmu ** 2)))
    max_al, rms_al = float(dal.max()), float(np.sqrt(np.mean(dal ** 2)))
    if max_mu > mu_tol:
        fail(f"dipole equivariance residual {max_mu:.3e} > {mu_tol:.0e}")
    if max_al > alpha_tol:
        fail(f"polarizability equivariance residual {max_al:.3e} > {alpha_tol:.0e}")

    for key, actual in (("max_abs_mu", max_mu), ("rms_mu", rms_mu),
                        ("max_rel_alpha", max_al), ("rms_alpha", rms_al)):
        reported = val.number(sub["residual_summary"].get(key), f"residual_summary.{key}", fail)
        if not np.isclose(reported, actual, rtol=1e-3, atol=1e-12):
            fail(f"self-reported {key} {reported} != recomputed {actual}")

    verdict = {"case_id": "case-03", "status": "PASS", "reward": 1,
               "unrotated": {"mu_rmse": mu_rmse, "alpha_diag_rmse": al_rmse},
               "equivariance": {"max_abs_mu": max_mu, "rms_mu": rms_mu,
                                "max_rel_alpha": max_al, "rms_alpha": rms_al,
                                "thresholds": {"mu": mu_tol, "alpha_rel": alpha_tol}},
               "rotated_inference": {
                   "coordinate_max_abs_error_A": coord_err,
                   "min_rotation_angle_rad": float(angles.min()),
                   "center": center_mode,
                   "geometry_bound_dumps": True,
                   "engine_reexecuted": False,
               },
               "protocol": protocol}
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SubmissionError as exc:
        print(json.dumps({"case_id": "case-03", "status": "FAIL", "reward": 0, "reason": str(exc)}))
        sys.exit(1)
    except InfrastructureError as exc:
        print(json.dumps({"case_id": "case-03", "status": "ENVIRONMENT_ERROR", "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"case_id": "case-03", "status": "ENVIRONMENT_ERROR", "reason": f"unexpected verifier error: {type(exc).__name__}: {exc}"}))
        sys.exit(2)
