#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Hsp60 V72I Monomer Dynamics: Flexibility and Allosteric Communication.
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import re
import sys

import numpy as np

CASE = "case-01-monomer-dynamics"
REFS_SHA256 = "504553a5a39e1d7818ca0d8eb0cde7f42c47c867b443af8909bae5a642ec221d"
INPUT_HASHES = {}
FEATURE_ATOMS = {}
TOLERANCES = {}
REQUIRED = ("run_manifest.json", "native-artifacts.json", "convergence.json", "descriptors.csv",
            "pca.json", "df_delta.npy", "rmsf.csv", "conclusions.json", "report.md")


class CandidateFail(Exception):
    pass


class EnvironmentInvalid(Exception):
    pass


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_refs() -> dict:
    path = pathlib.Path(__file__).with_name("refs.json")
    if path.is_symlink() or not path.is_file() or sha(path) != REFS_SHA256:
        raise EnvironmentInvalid("case-01-monomer-dynamics refs.json is missing, redirected, or changed")
    try:
        refs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"case-01-monomer-dynamics refs.json cannot be parsed: {exc}") from exc
    if not isinstance(refs, dict) or refs.get("schema_version") != "case01-verifier-reference/v1":
        raise EnvironmentInvalid("case-01-monomer-dynamics refs.json has an unsupported schema")
    hashes, features, tolerances = refs.get("input_sha256"), refs.get("feature_atom_indices"), refs.get("tolerances")
    if (not isinstance(hashes, dict) or set(hashes) != {"M_WT.top", "M_WT.rst", "M_V72I.top", "M_V72I.rst", "minimisation_stage1.in"}
            or any(not isinstance(value, str) or len(value) != 64 for value in hashes.values())):
        raise EnvironmentInvalid("case-01-monomer-dynamics refs.json input hash map is malformed")
    if not isinstance(features, dict) or set(features) != {"M_WT", "M_V72I"} or any(
            not isinstance(value, list) or len(value) != 5 or any(type(index) is not int or index < 0 for index in value)
            for value in features.values()):
        raise EnvironmentInvalid("case-01-monomer-dynamics refs.json feature atom map is malformed")
    if not isinstance(tolerances, dict) or not tolerances or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            for value in tolerances.values()):
        raise EnvironmentInvalid("case-01-monomer-dynamics refs.json numeric tolerances are malformed")
    return refs


def prmtop_atom_indices(path: pathlib.Path):
    sections = {}
    current = None
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("%FLAG "):
            current = line[6:].strip()
            sections[current] = []
        elif current is not None and not line.startswith(("%FORMAT", "%COMMENT")):
            sections[current].append(line)
    def fields(flag, width, cast):
        return [cast(row[i:i + width].strip()) for row in sections[flag]
                for i in range(0, len(row), width) if row[i:i + width].strip()]
    atoms = fields("ATOM_NAME", 4, str)
    labels = fields("RESIDUE_LABEL", 4, str)
    starts = fields("RESIDUE_POINTER", 8, int)
    pointers = fields("POINTERS", 8, int)
    masses = fields("MASS", 16, float)
    if len(atoms) != pointers[0] or len(masses) != len(atoms) or len(labels) != pointers[11] or len(starts) != len(labels):
        raise EnvironmentInvalid(f"PRMTOP pointer sections are inconsistent: {path.name}")
    atom_residue = [None] * len(atoms)
    for residue, start1 in enumerate(starts):
        end1 = starts[residue + 1] if residue + 1 < len(starts) else len(atoms) + 1
        atom_residue[start1 - 1:end1 - 1] = [residue] * (end1 - start1)
    return atoms, labels, atom_residue, float(sum(masses))


def topology_mapping(assets, variant):
    atoms, labels, residue_for_atom, total_mass_da = prmtop_atom_indices(assets / f"{variant}.top")
    ca = {}
    for index, (name, residue) in enumerate(zip(atoms, residue_for_atom)):
        if residue < 526 and name.upper() == "CA":
            if residue in ca:
                raise EnvironmentInvalid(f"duplicate C-alpha in {variant} topology residue {residue}")
            ca[residue] = index
    if set(ca) != set(range(526)):
        raise EnvironmentInvalid(f"{variant} topology does not map mature residues 0..525 exactly")
    mapping = [(232, "VAL", "CA"), (404, "ALA", "CA"), (513, "LEU", "CA"),
               (50, "ASP", "CG"), (397, "ASP", "CG")]
    feature = []
    for residue, label, atom in mapping:
        if labels[residue].upper() != label:
            raise EnvironmentInvalid(f"{variant} topology residue {residue} expected {label}")
        found = [i for i, (name, res) in enumerate(zip(atoms, residue_for_atom))
                 if res == residue and name.upper() == atom]
        if len(found) != 1:
            raise EnvironmentInvalid(f"{variant} topology residue {residue} expected one {atom}")
        feature.append(found[0])
    excluded = [i for i, (name, residue) in enumerate(zip(atoms, residue_for_atom))
                if name.upper() in {"H", "H1"} and labels[residue].upper() != "WAT"]
    return ca, feature, len(atoms), excluded, total_mass_da


def wt_replica_one(entries):
    matches = [entry for entry in entries if int(entry[0]["replica"]) == 1]
    if len(matches) != 1:
        raise CandidateFail("exactly one WT replica 1 is required as the PCA fitting reference")
    return matches[0]


def dcd_selected_coordinates(path, expected_frames, atom_count, ca_indices, feature_indices):
    """Read standard Fortran-record DCD frames and extract native atom coordinates."""
    selected = np.asarray(list(ca_indices) + list(feature_indices), dtype=np.int64)
    if selected.max(initial=-1) >= atom_count:
        raise CandidateFail("DCD atom count is smaller than the PRMTOP atom selections")
    result = []
    volumes_nm3 = []
    with path.open("rb") as stream:
        first = stream.read(4)
        if len(first) != 4:
            raise CandidateFail("DCD header is truncated")
        little = int.from_bytes(first, "little", signed=True)
        big = int.from_bytes(first, "big", signed=True)
        if little == 84:
            endian = "<"
        elif big == 84:
            endian = ">"
        else:
            raise CandidateFail("DCD header does not use the standard 84-byte CORD record")
        def read_int():
            raw = stream.read(4)
            if len(raw) != 4:
                raise CandidateFail("DCD record is truncated")
            return int(np.frombuffer(raw, dtype=endian + "i4")[0])
        stream.seek(0)
        if read_int() != 84:
            raise CandidateFail("DCD control record is malformed")
        control = stream.read(84)
        if len(control) != 84 or control[:4] != b"CORD" or read_int() != 84:
            raise CandidateFail("DCD control record is malformed")
        nsets = int(np.frombuffer(control[4:8], dtype=endian + "i4")[0])
        if nsets != expected_frames:
            raise CandidateFail("DCD frame count does not match extracted analysis coordinates")
        for _ in range(2):  # title and atom-count records
            length = read_int()
            if length <= 0 or length > 1_000_000:
                raise CandidateFail("DCD title/atom record length is invalid")
            data = stream.read(length)
            if len(data) != length or read_int() != length:
                raise CandidateFail("DCD title/atom record is truncated")
            if length == 4:
                parsed_atoms = int(np.frombuffer(data, dtype=endian + "i4")[0])
                if parsed_atoms != atom_count:
                    raise CandidateFail("DCD atom count does not match the pinned PRMTOP")
        for _ in range(expected_frames):
            length = read_int()
            if length != 48:
                raise CandidateFail("periodic DCD frame lacks its six-double unit-cell record")
            cell_data = stream.read(48)
            if len(cell_data) != 48 or read_int() != 48:
                raise CandidateFail("DCD periodic unit-cell record is malformed")
            cell = np.frombuffer(cell_data, dtype=endian + "f8")
            if not np.isfinite(cell).all() or min(cell[0], cell[2], cell[5]) <= 0:
                raise CandidateFail("DCD periodic unit-cell values are invalid")
            # OpenMM DCD cell layout: a, cos(gamma), b, cos(beta), cos(alpha), c.
            a, cos_gamma, b, cos_beta, cos_alpha, c = map(float, cell)
            volume_angstrom3 = a * b * c * math.sqrt(max(0.0, 1 + 2*cos_alpha*cos_beta*cos_gamma
                - cos_alpha**2 - cos_beta**2 - cos_gamma**2))
            volumes_nm3.append(volume_angstrom3 / 1000.0)
            length = read_int()
            expected_coord_bytes = atom_count * 4
            if length != expected_coord_bytes:
                raise CandidateFail("DCD coordinate record has an unexpected precision or atom count")
            axes = []
            for axis_index in range(3):
                if axis_index:
                    length = read_int()
                if length != expected_coord_bytes:
                    raise CandidateFail("DCD coordinate axis record length is invalid")
                data = stream.read(length)
                if len(data) != length or read_int() != length:
                    raise CandidateFail("DCD coordinate axis record is truncated")
                axis = np.frombuffer(data, dtype=endian + "f4")
                if not np.isfinite(axis).all():
                    raise CandidateFail("DCD coordinate record contains non-finite values")
                axes.append(axis[selected].astype(np.float64))
            result.append(np.stack(axes, axis=1))
    return np.asarray(result, dtype=np.float64), np.asarray(volumes_nm3, dtype=np.float64)


def emit(logs: pathlib.Path, status: str, message: str, details=None):
    logs.mkdir(parents=True, exist_ok=True)
    if status in {"PASS", "FAIL"}:
        (logs / "reward.txt").write_text(("1" if status == "PASS" else "0") + "\n")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    report = {"case_id": CASE, "status": status, "message": message}
    if details:
        report["details"] = details
    (logs / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return {"PASS": 0, "FAIL": 1, "ENV_INVALID": 2}.get(status, 2)


def read_json(path: pathlib.Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFail(f"{path.name} must contain a JSON object")
    return value


def read_csv(path, columns):
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not set(columns).issubset(reader.fieldnames):
                raise CandidateFail(f"{path.name} is missing columns {sorted(set(columns)-set(reader.fieldnames or []))}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot read {path.name}: {exc}") from exc
    if not rows:
        raise CandidateFail(f"{path.name} contains no rows")
    return rows


def num(value, label):
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label} must be numeric") from exc
    if not math.isfinite(x):
        raise CandidateFail(f"{label} must be finite")
    return x


def json_int(value, label):
    """Read an integer-valued JSON field without coercing strings, floats, or booleans."""
    if type(value) is not int:
        raise CandidateFail(f"{label} must be a JSON integer")
    return value


def json_num(value, label):
    """Read a finite JSON number; bool is not a numeric measurement here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateFail(f"{label} must be a finite JSON number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFail(f"{label} must be a finite JSON number") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be a finite JSON number")
    return result


def validate_report_text(text: str) -> None:
    """Keep report prose readable; scientific status is scored from structured evidence."""
    if not isinstance(text, str) or not text.strip():
        raise CandidateFail("report.md must contain a scientific analysis")


def gamma_angle(points):
    u, v = points[0] - points[1], points[2] - points[1]
    den = np.linalg.norm(u) * np.linalg.norm(v)
    if den == 0:
        raise CandidateFail("gamma coordinate has coincident atoms")
    return float(np.degrees(np.arccos(np.clip(np.dot(u, v) / den, -1, 1))))


def align_frames(frames, reference):
    aligned = np.empty_like(frames, dtype=np.float64)
    q0 = reference.mean(axis=0)
    q = reference - q0
    for i, frame in enumerate(frames):
        p0 = frame.mean(axis=0)
        p = frame - p0
        u, _, vt = np.linalg.svd(p.T @ q)
        d = np.eye(3); d[2, 2] = np.linalg.det(u @ vt)
        aligned[i] = p @ (u @ d @ vt) + q0
    return aligned


def df_matrix(frames):
    mean = None
    m2 = None
    n = 0
    for frame in frames:
        distances = np.linalg.norm(frame[:, None, :] - frame[None, :, :], axis=2)
        if mean is None:
            mean = np.zeros_like(distances)
            m2 = np.zeros_like(distances)
        n += 1
        delta = distances - mean
        mean += delta / n
        m2 += delta * (distances - mean)
    if n < 2:
        raise CandidateFail("at least two production frames per variant are required for DF")
    result = m2 / n  # author's population variance of pair-distance deviations
    idx = np.arange(result.shape[0])
    result[np.abs(idx[:, None] - idx[None, :]) < 2] = 0.0
    return result


def secure_file(root: pathlib.Path, relative: str):
    rel = pathlib.PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise CandidateFail("artifact path must remain inside final/")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise CandidateFail(f"native artifact is missing or redirected: {relative}")
    resolved = path.resolve(strict=True)
    if root.resolve() not in resolved.parents:
        raise CandidateFail("native artifact path escapes final/")
    return path


def verify(app: pathlib.Path, assets: pathlib.Path):
    global INPUT_HASHES, FEATURE_ATOMS, TOLERANCES
    refs = load_refs()
    INPUT_HASHES = refs["input_sha256"]
    FEATURE_ATOMS = refs["feature_atom_indices"]
    TOLERANCES = refs["tolerances"]
    final = app / "final"
    if app.is_symlink() or final.is_symlink() or not final.is_dir():
        raise CandidateFail("APP/final must be a real directory")
    for name in REQUIRED:
        p = final / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size == 0:
            raise CandidateFail(f"required deliverable is missing, empty, or redirected: final/{name}")
    if assets.is_symlink() or not assets.is_dir():
        raise EnvironmentInvalid("public author-input directory is missing")
    for name, expected in INPUT_HASHES.items():
        p = assets / ("md_inputs" / pathlib.Path(name) if name == "minimisation_stage1.in" else name)
        if p.is_symlink() or not p.is_file() or sha(p) != expected:
            raise EnvironmentInvalid(f"pinned author input is absent, redirected, or changed: {name}")

    manifest = read_json(final / "run_manifest.json")
    if manifest.get("schema") != "hsp60-case01-run-manifest/v1":
        raise CandidateFail("run_manifest.json schema is unsupported")
    if manifest.get("input_sha256") != INPUT_HASHES:
        raise CandidateFail("run_manifest input hashes do not match the supplied author systems")
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise CandidateFail("run_manifest.runs must be a list")
    by_variant = {"M_WT": [], "M_V72I": []}
    topology_maps = {variant: topology_mapping(assets, variant) for variant in by_variant}
    seeds = set()
    files_from_runs = set()
    loaded = {}
    for r in runs:
        if not isinstance(r, dict) or r.get("variant") not in by_variant:
            raise CandidateFail("run record must identify M_WT or M_V72I")
        variant = r["variant"]
        try:
            replica = json_int(r["replica"], "replica")
            seed = json_int(r["seed"], "seed")
            nframes = json_int(r["production_frames"], "production_frames")
            steps = json_int(r["production_steps"], "production_steps")
        except KeyError as exc:
            raise CandidateFail("run record is missing integer replica, seed, frame, or step metadata") from exc
        if replica < 1 or seed <= 0 or nframes < 2 or steps <= 0:
            raise CandidateFail("each native run needs a positive seed, production steps, and at least two frames")
        if seed in seeds:
            raise CandidateFail("independent replicas must use distinct velocity seeds")
        seeds.add(seed)
        if r.get("input_topology_sha256") != INPUT_HASHES[f"{variant}.top"] or r.get("input_restart_sha256") != INPUT_HASHES[f"{variant}.rst"]:
            raise CandidateFail("run metadata does not bind to the correct variant inputs")
        selection = r.get("restraint_selection")
        if selection is not None:
            if not isinstance(selection, dict):
                raise CandidateFail("restraint_selection must be an object")
            _, _, atom_count, excluded, _ = topology_maps[variant]
            expected_excluded_hash = hashlib.sha256(",".join(map(str, excluded)).encode()).hexdigest()
            if (selection.get("restrained_count") != atom_count - len(excluded) or
                    selection.get("excluded_count") != len(excluded) or
                    selection.get("excluded_indices_sha256") != expected_excluded_hash):
                raise CandidateFail("declared stage-1 restraint audit does not match the variant-specific frozen PRMTOP selection")
        if not isinstance(r.get("artifacts"), list):
            raise CandidateFail("each run must list native artifacts")
        for relative in r["artifacts"]:
            if not isinstance(relative, str):
                raise CandidateFail("native artifact paths must be strings")
            p = secure_file(final, relative)
            files_from_runs.add(relative)
        arrays_rel = next((x for x in r["artifacts"] if x.endswith("-analysis-coordinates.npz")), None)
        dcd_rel = next((x for x in r["artifacts"] if x.endswith(".dcd")), None)
        state_rel = next((x for x in r["artifacts"] if x.endswith("-state.csv")), None)
        log_rel = next((x for x in r["artifacts"] if x.endswith("-engine.log")), None)
        restart_rel = next((x for x in r["artifacts"] if x.endswith(("-final-state.xml", ".rst7", ".nc"))), None)
        if not all((arrays_rel, dcd_rel, state_rel, log_rel, restart_rel)):
            raise CandidateFail("run record must include DCD, state series, engine log, restart state, and coordinate arrays")
        with np.load(secure_file(final, arrays_rel), allow_pickle=False) as arrays:
            ca = np.asarray(arrays["ca_angstrom"], dtype=np.float64)
            feature = np.asarray(arrays["gamma_delta_angstrom"], dtype=np.float64)
            ca_indices = np.asarray(arrays["ca_mature_indices"])
            feature_indices = np.asarray(arrays["feature_atom_indices"])
        if ca.shape != (nframes, 526, 3) or feature.shape != (nframes, 5, 3) or not np.isfinite(ca).all() or not np.isfinite(feature).all():
            raise CandidateFail("stored trajectory-derived coordinates have wrong shape or non-finite values")
        ca_map, feature_map, atom_count, _, total_mass_da = topology_maps[variant]
        expected_ca = np.asarray([ca_map[i] for i in range(526)])
        if not np.array_equal(ca_indices, np.arange(526)):
            raise CandidateFail("C-alpha coordinate array must use mature zero-based residue order")
        if not np.array_equal(feature_indices, np.asarray(feature_map)) or feature_map != FEATURE_ATOMS[variant]:
            raise CandidateFail("gamma/delta atom indices disagree with the variant-specific pinned PRMTOP mapping")
        expected_ca_hash = hashlib.sha256(",".join(map(str, expected_ca)).encode()).hexdigest()
        if r.get("ca_indices_sha256") != expected_ca_hash:
            raise CandidateFail("C-alpha native atom selection hash disagrees with the pinned PRMTOP mapping")
        dcd = secure_file(final, dcd_rel)
        with dcd.open("rb") as stream:
            header = stream.read(12)
        if len(header) != 12 or header[4:8] != b"CORD" or int.from_bytes(header[8:12], "little", signed=True) < nframes:
            raise CandidateFail("native DCD trajectory header/frame count is invalid")
        dcd_selected, dcd_volumes = dcd_selected_coordinates(dcd, nframes, atom_count,
                                                              expected_ca, np.asarray(feature_map))
        if not np.allclose(dcd_selected[:, :526, :], ca, rtol=TOLERANCES["dcd_coordinates_rtol"], atol=TOLERANCES["dcd_coordinates_atol_angstrom"]):
            raise CandidateFail("stored C-alpha analysis coordinates do not match the native DCD frames")
        if not np.allclose(dcd_selected[:, 526:, :], feature, rtol=TOLERANCES["dcd_coordinates_rtol"], atol=TOLERANCES["dcd_coordinates_atol_angstrom"]):
            raise CandidateFail("stored gamma/delta analysis coordinates do not match the native DCD frames")
        restart = secure_file(final, restart_rel)
        if restart.suffix == ".xml":
            restart_text = restart.read_text(encoding="utf-8", errors="strict")
            if "<State" not in restart_text or "<Positions" not in restart_text or "<Velocities" not in restart_text:
                raise CandidateFail("native OpenMM restart state does not contain positions and velocities")
        elif restart.stat().st_size < 16:
            raise CandidateFail("native Amber restart is implausibly short")
        logtext = secure_file(final, log_rel).read_text(encoding="utf-8", errors="strict")
        engine_ok = re.search(r"(?i)(?<!\w)engine\s*=\s*(openmm|pmemd(?:\.cuda)?)(?=$|\s|[;,])", logtext) is not None
        seed_values = re.findall(r"(?i)(?<!\w)seed\s*=\s*([^\s,;]+)", logtext)
        seed_ok = bool(seed_values) and all(value == str(seed) for value in seed_values)
        if not engine_ok or not seed_ok:
            raise CandidateFail("engine log lacks supported engine and exact matching seed evidence")
        state_rows = read_csv(secure_file(final, state_rel), {"step", "time_ps", "temperature_K", "density_g_ml", "volume_nm3"})
        if len(state_rows) < nframes:
            raise CandidateFail("state series is shorter than its stored production trajectory")
        for row in state_rows:
            for key in ("step", "time_ps", "temperature_K", "density_g_ml", "volume_nm3"):
                num(row[key], f"{variant} replica {replica} {key}")
        state_volumes = np.asarray([float(row["volume_nm3"]) for row in state_rows])
        state_densities = np.asarray([float(row["density_g_ml"]) for row in state_rows])
        state_temperatures = np.asarray([float(row["temperature_K"]) for row in state_rows])
        if len(state_rows) != nframes or not np.allclose(state_volumes, dcd_volumes, rtol=TOLERANCES["box_volume_rtol"], atol=TOLERANCES["box_volume_atol_nm3"]):
            raise CandidateFail("state-series box volumes do not match the periodic DCD unit cells")
        expected_density = total_mass_da * 0.00166053906660 / dcd_volumes
        if not np.allclose(state_densities, expected_density, rtol=TOLERANCES["density_rtol"], atol=TOLERANCES["density_atol_g_ml"]):
            raise CandidateFail("state-series density does not match the pinned PRMTOP mass and DCD box volume")
        if np.any(state_temperatures < 0) or np.any(state_temperatures > 1000):
            raise CandidateFail("state-series temperature is outside the broad physical sanity range")
        by_variant[variant].append((r, ca, feature))
        loaded[(variant, replica)] = (r, ca, feature)
    if any(len(by_variant[k]) < 2 for k in by_variant):
        raise CandidateFail("at least two independent velocity seeds are required for both variants")
    wt_replica_one(by_variant["M_WT"])
    if any(sum(len(entry[1]) for entry in by_variant[k]) < 21 for k in by_variant):
        raise CandidateFail("at least 21 production frames per variant are required to report top-20 PCA modes")
    if len(runs) != sum(len(v) for v in by_variant.values()):
        raise CandidateFail("run count is inconsistent")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        raise CandidateFail("run_manifest.runtime must be an object")
    total_wall = json_num(runtime.get("elapsed_seconds_total"), "elapsed_seconds_total")
    if total_wall < 0 or total_wall > 12 * 3600 or runtime.get("within_deadline") is not True:
        raise CandidateFail("total reference run wall time exceeds the 12-hour contract")

    # Verify output derivations directly from submitted coordinate frames.
    expected_desc = {}
    for variant, entries in by_variant.items():
        for run, ca, feature in entries:
            delta = np.linalg.norm(feature[:, 3] - feature[:, 4], axis=1)
            gamma = np.asarray([gamma_angle(x[:3]) for x in feature])
            for frame, (d, g) in enumerate(zip(delta, gamma)):
                key = (variant, int(run["replica"]), int(run["seed"]), frame)
                expected_desc[key] = (float(d), float(g))
    desc = read_csv(final / "descriptors.csv", {"variant", "replica", "seed", "frame", "time_ps", "delta_angstrom", "gamma_degrees"})
    if len(desc) != len(expected_desc):
        raise CandidateFail("descriptor row count does not match the native coordinate frames")
    seen = set()
    for row in desc:
        key = (row["variant"], int(row["replica"]), int(row["seed"]), int(row["frame"]))
        if key not in expected_desc or key in seen:
            raise CandidateFail("descriptor rows contain an unknown or repeated run/frame")
        seen.add(key)
        d, g = expected_desc[key]
        if abs(num(row["delta_angstrom"], "delta") - d) > TOLERANCES["descriptor_delta_atol_angstrom"] or abs(num(row["gamma_degrees"], "gamma") - g) > TOLERANCES["descriptor_gamma_atol_degree"]:
            raise CandidateFail("reported delta/gamma does not match the stored trajectory coordinates")

    expected_rmsf = {}
    ref = wt_replica_one(by_variant["M_WT"])[1][0]
    for variant, entries in by_variant.items():
        for run, ca, _ in entries:
            aligned = align_frames(ca, ca[0])
            avg = aligned.mean(axis=0)
            rmsf = np.sqrt(np.mean(np.sum((aligned - avg) ** 2, axis=2), axis=0))
            for i, value in enumerate(rmsf):
                expected_rmsf[(variant, int(run["replica"]), i)] = float(value)
    rows = read_csv(final / "rmsf.csv", {"variant", "replica", "mature_residue_index", "rmsf_angstrom"})
    if len(rows) != len(expected_rmsf):
        raise CandidateFail("RMSF row count does not match the four native replicas")
    seen = set()
    for row in rows:
        key = (row["variant"], int(row["replica"]), int(row["mature_residue_index"]))
        if key not in expected_rmsf or key in seen or abs(num(row["rmsf_angstrom"], "rmsf") - expected_rmsf[key]) > TOLERANCES["rmsf_atol_angstrom"]:
            raise CandidateFail("RMSF values do not match independent coordinate recomputation")
        seen.add(key)

    wt = np.concatenate([ca for _, ca, _ in by_variant["M_WT"]], axis=0)
    mut = np.concatenate([ca for _, ca, _ in by_variant["M_V72I"]], axis=0)
    df_wt, df_mut = df_matrix(wt), df_matrix(mut)
    expected_delta = np.full_like(df_wt, np.nan)
    valid = np.abs(df_wt) > TOLERANCES["zero_wt_df_threshold"]
    expected_delta[valid] = 100.0 * (df_mut[valid] - df_wt[valid]) / df_wt[valid]
    try:
        submitted_delta = np.load(final / "df_delta.npy", allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise CandidateFail(f"df_delta.npy cannot be read: {exc}") from exc
    if submitted_delta.shape != (526, 526) or not np.allclose(submitted_delta, expected_delta, rtol=TOLERANCES["df_delta_rtol"], atol=TOLERANCES["df_delta_atol_percent"], equal_nan=True):
        raise CandidateFail("DF delta matrix differs from the independent author-formula recomputation")

    # PCA is also recalculated from the native C-alpha coordinate arrays, after
    # least-squares alignment to the WT first frame on mature residues 2..522.
    pca_expected = {}
    top_vectors = {}
    for variant, entries in by_variant.items():
        aligned = np.concatenate([align_frames(ca, ref) for _, ca, _ in entries], axis=0)
        region = aligned[:, 2:523, :]
        centered = (region - region.mean(axis=0)).reshape(len(region), -1)
        _, singular, vt = np.linalg.svd(centered, full_matrices=False)
        if len(singular) < 20 or singular[:20].shape != (20,):
            raise CandidateFail("native trajectories do not support 20 PCA components")
        variance = singular**2
        pca_expected[variant] = variance[:20] / variance.sum()
        top_vectors[variant] = vt[:20]
    overlap = np.einsum("ik,jk->ij", top_vectors["M_WT"], top_vectors["M_V72I"])
    pca_expected["cross_variant"] = float(np.sqrt(np.sum(overlap**2) / 20.0))
    pca = read_json(final / "pca.json")
    for variant in ("M_WT", "M_V72I"):
        variant_pca = pca.get(variant)
        if not isinstance(variant_pca, dict):
            raise CandidateFail(f"{variant} PCA record must be an object")
        variance_values = variant_pca.get("top20_variance_fraction")
        if not isinstance(variance_values, list):
            raise CandidateFail(f"{variant} top20_variance_fraction must be a JSON array")
        submitted = np.asarray([json_num(x, f"{variant} PCA variance fraction") for x in variance_values], dtype=np.float64)
        if submitted.shape != (20,) or not np.allclose(submitted, pca_expected[variant], rtol=TOLERANCES["pca_variance_rtol"], atol=TOLERANCES["pca_variance_atol"]):
            raise CandidateFail(f"{variant} PCA variance fractions do not match native-coordinate recomputation")
        fit_reference = variant_pca.get("fit_reference")
        if not isinstance(fit_reference, str) or not fit_reference.strip():
            raise CandidateFail("PCA fit_reference must be a nonempty description")
    cross_variant = pca.get("cross_variant")
    if not isinstance(cross_variant, dict):
        raise CandidateFail("pca.json cross_variant must be an object")
    if not math.isclose(json_num(cross_variant.get("top20_rmsip"), "top20_rmsip"),
                        pca_expected["cross_variant"], rel_tol=TOLERANCES["rmsip_rtol"], abs_tol=TOLERANCES["rmsip_atol"]):
        raise CandidateFail("cross-variant top-20 RMSIP does not match recomputed PCA vectors")

    # The short Gold deliberately claims no scientific direction. The verifier accepts this
    # valid outcome and checks that the limitations are stated rather than substituting paper numbers.
    conclusions = read_json(final / "conclusions.json")
    if conclusions.get("schema") != "hsp60-case01-conclusions/v1" or conclusions.get("overall") not in {
        "INSUFFICIENT_SAMPLING", "NO_SIGNIFICANT_DIFFERENCE", "SUPPORTED_MUTATION_EFFECT"
    }:
        raise CandidateFail("conclusions must use the declared bounded-evidence status vocabulary")
    claims = conclusions.get("claims")
    conclusion_evidence = conclusions.get("evidence")
    if not isinstance(claims, dict) or not isinstance(conclusion_evidence, dict):
        raise CandidateFail("conclusions claims and evidence must be objects")
    names = ("rigidification", "dyad_preorganisation", "pca_similarity", "allosteric_rewiring")
    if any(not isinstance(claims.get(name), dict) or claims[name].get("status") not in {
        "INSUFFICIENT_SAMPLING", "NO_SIGNIFICANT_DIFFERENCE", "SUPPORTED_MUTATION_EFFECT"
    } for name in names):
        raise CandidateFail("each scientific claim must carry a recognized evidence status")
    for name in names:
        claim = claims[name]
        if claim["status"] == "INSUFFICIENT_SAMPLING":
            continue
        independent_replicas = conclusion_evidence.get("independent_replicas_per_variant")
        if (conclusion_evidence.get("convergence_demonstrated") is not True
                or type(independent_replicas) is not int or independent_replicas < 2):
            raise CandidateFail(f"{name} makes a non-insufficient claim without demonstrated convergence and independent replicas")
        ci = claim.get("ci95")
        effects = claim.get("replicate_effects")
        effect = json_num(claim.get("effect"), f"{name} effect")
        if (not isinstance(ci, list) or len(ci) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in ci)
                or ci[0] > ci[1]):
            raise CandidateFail(f"{name} needs a finite ordered 95% interval for a non-insufficient claim")
        if (not isinstance(effects, list) or len(effects) < 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in effects)):
            raise CandidateFail(f"{name} needs at least two finite independent-replica effects")
        if not (ci[0] <= effect <= ci[1]) or not math.isclose(effect, float(np.mean(effects)), rel_tol=0.1, abs_tol=1e-8):
            raise CandidateFail(f"{name} effect and 95% interval are inconsistent with the independent-replica effects")
        if claim["status"] == "NO_SIGNIFICANT_DIFFERENCE" and not (ci[0] <= 0.0 <= ci[1]):
            raise CandidateFail(f"{name} labels an interval excluding zero as no significant difference")
        if claim["status"] == "SUPPORTED_MUTATION_EFFECT":
            if ci[0] <= 0.0 <= ci[1] or not (all(x > 0 for x in effects) or all(x < 0 for x in effects)):
                raise CandidateFail(f"{name} claims an effect without a zero-excluding interval and consistent replica direction")
    if conclusions["overall"] != "INSUFFICIENT_SAMPLING":
        evidence = conclusion_evidence
        independent_replicas = evidence.get("independent_replicas_per_variant")
        if (evidence.get("convergence_demonstrated") is not True
                or type(independent_replicas) is not int or independent_replicas < 2):
            raise CandidateFail("a directional overall conclusion requires demonstrated convergence and independent replicas")
        supported = [claims[n]["status"] == "SUPPORTED_MUTATION_EFFECT" for n in names]
        if conclusions["overall"] == "SUPPORTED_MUTATION_EFFECT" and not any(supported):
            raise CandidateFail("overall effect conclusion has no supported claim")
        if conclusions["overall"] == "NO_SIGNIFICANT_DIFFERENCE" and any(supported):
            raise CandidateFail("overall no-difference conclusion conflicts with a supported individual claim")
    try:
        report = (final / "report.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateFail(f"report.md must be readable UTF-8 text: {exc}") from exc
    validate_report_text(report)
    convergence = read_json(final / "convergence.json")
    if convergence.get("overall") not in {"INSUFFICIENT", "DEMONSTRATED"}:
        raise CandidateFail("convergence report must classify sampling as INSUFFICIENT or DEMONSTRATED")
    if convergence.get("overall") == "DEMONSTRATED" and not convergence.get("criteria"):
        raise CandidateFail("demonstrated convergence must name the criteria applied")

    art = read_json(final / "native-artifacts.json")
    if art.get("schema") != "hsp60-case01-native-artifacts/v1" or not isinstance(art.get("files"), list):
        raise CandidateFail("native-artifacts.json schema is invalid")
    listed = {}
    for row in art["files"]:
        if not isinstance(row, dict) or not {"path", "bytes", "sha256"}.issubset(row):
            raise CandidateFail("native artifact inventory entry is malformed")
        p = secure_file(final, row["path"])
        if p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise CandidateFail(f"native artifact hash/size mismatch: {row['path']}")
        listed[row["path"]] = row["sha256"]
    for rel in files_from_runs:
        if rel not in listed:
            raise CandidateFail(f"run native artifact is not covered by native-artifacts.json: {rel}")
    for name in ("run_manifest.json", "descriptors.csv", "pca.json", "df_delta.npy", "rmsf.csv", "conclusions.json", "convergence.json", "report.md"):
        if name not in listed:
            raise CandidateFail(f"native-artifacts.json does not hash required derived output {name}")
    return {"replicas_per_variant": {k: len(v) for k, v in by_variant.items()},
            "production_frames": {k: sum(len(x[1]) for x in v) for k, v in by_variant.items()},
            "outputs_recomputed": ["DCD-selected coordinates", "periodic box volume", "density", "delta/gamma", "RMSF", "DF delta", "PCA variance fractions", "top-20 RMSIP"],
            "scientific_assessment": "INSUFFICIENT_SAMPLING accepted; no paper numerical result is required"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--assets", default=os.environ.get("CASE_ASSETS", "/app/assets"))
    parser.add_argument("--logs", default=os.environ.get("LOGS", "/tmp/case01-verifier"))
    args = parser.parse_args()
    try:
        details = verify(pathlib.Path(args.app), pathlib.Path(args.assets))
        return emit(pathlib.Path(args.logs), "PASS", "native DCD coordinates, periodic volumes, density, derived observables, and scientific evidence bounds agree", details)
    except EnvironmentInvalid as exc:
        return emit(pathlib.Path(args.logs), "ENV_INVALID", str(exc))
    except CandidateFail as exc:
        return emit(pathlib.Path(args.logs), "FAIL", str(exc))
    except (OSError, UnicodeError, csv.Error, ValueError, KeyError, TypeError, IndexError) as exc:
        return emit(pathlib.Path(args.logs), "FAIL", f"candidate evidence is malformed: {type(exc).__name__}: {exc}")
    except Exception as exc:
        return emit(pathlib.Path(args.logs), "ENV_INVALID", f"grader could not establish a safe result: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
