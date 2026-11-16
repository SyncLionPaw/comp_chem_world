#!/usr/bin/env bash
set -euo pipefail

APP="${APP:-/app}"
export CCB_ANSWER_MODE="${CCB_ANSWER_MODE:-oracle}"
exec python3 - --app "$APP" <<'PY'
"""Case04 finite-budget native MD campaign and evidence packaging."""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

import numpy as np

# Inlined analysis.py source follows; no source helper import remains.

from collections import Counter, deque
from pathlib import Path
import math
import numpy as np

ELEMENT = {1: "H", 2: "O", 3: "N", 4: "C", 5: "Cl"}
MASS = {"H": 1.0, "O": 16.0, "N": 14.0, "C": 12.0, "Cl": 35.45}
FORMULA = {"choline": Counter(C=5, H=14, N=1, O=1),
           "chloride": Counter(Cl=1), "urea": Counter(C=1, H=4, N=2, O=1)}
COUNTS = {"choline": 64, "chloride": 64, "urea": 128}
COLS = ["id", "type", "x", "y", "z", "ix", "iy", "iz", "xu", "yu", "zu", "vx", "vy", "vz"]


def min_image(delta, lengths):
    return delta - lengths * np.rint(delta / lengths)


def topology(structure: Path):
    types_by_id, xyz_by_id, bounds = {}, {}, {}
    inside = False
    for line in structure.read_text(encoding="utf-8").splitlines():
        words = line.split()
        if not words:
            continue
        if len(words) >= 4 and words[-2:] in (["xlo", "xhi"], ["ylo", "yhi"], ["zlo", "zhi"]):
            bounds[words[-2][0]] = (float(words[0]), float(words[1]))
        if words[0] == "Atoms":
            inside = True
            continue
        if not inside or words[0].startswith("#"):
            continue
        try:
            atom_id, atom_type = int(words[0]), int(words[1])
            xyz = np.array([float(x) for x in words[2:5]], dtype=float)
        except (ValueError, IndexError):
            if words[0][0].isalpha():
                inside = False
            continue
        if atom_id in types_by_id:
            raise ValueError(f"duplicate atom id {atom_id}")
        types_by_id[atom_id], xyz_by_id[atom_id] = atom_type, xyz
    n = 2432
    if sorted(types_by_id) != list(range(1, n + 1)) or set(bounds) != set("xyz"):
        raise ValueError("initial structure atom inventory or cell is invalid")
    box = np.array([bounds[k][1] - bounds[k][0] for k in "xyz"], dtype=float)
    types = np.array([types_by_id[i] for i in range(1, n + 1)], dtype=int)
    xyz = np.array([xyz_by_id[i] for i in range(1, n + 1)])
    if not np.isfinite(box).all() or np.any(box <= 0):
        raise ValueError("invalid orthogonal cell")

    heavy = np.flatnonzero(np.array([ELEMENT[int(t)] not in ("H", "Cl") for t in types]))
    adjacency = [set() for _ in range(n)]
    for q, atom_i in enumerate(heavy):
        delta = min_image(xyz[heavy[q + 1:]] - xyz[atom_i], box)
        dist2 = np.einsum("ij,ij->i", delta, delta)
        for atom_j in heavy[q + 1:][dist2 <= 1.85**2 + 1e-12]:
            adjacency[int(atom_i)].add(int(atom_j))
            adjacency[int(atom_j)].add(int(atom_i))
    for atom_i in np.flatnonzero(types == 1):
        delta = min_image(xyz[heavy] - xyz[atom_i], box)
        dist2 = np.einsum("ij,ij->i", delta, delta)
        nearest = int(np.argmin(dist2))
        if math.sqrt(float(dist2[nearest])) > 1.25 + 1e-12:
            raise ValueError(f"hydrogen atom {atom_i + 1} has no nearby heavy atom")
        atom_j = int(heavy[nearest])
        adjacency[int(atom_i)].add(atom_j)
        adjacency[atom_j].add(int(atom_i))

    seen, molecules = set(), []
    for start in range(n):
        if start in seen:
            continue
        seen.add(start)
        todo, component = deque([start]), []
        while todo:
            atom_i = todo.popleft()
            component.append(atom_i)
            for atom_j in adjacency[atom_i]:
                if atom_j not in seen:
                    seen.add(atom_j)
                    todo.append(atom_j)
        formula = Counter(ELEMENT[int(types[i])] for i in component)
        species = [name for name, expected in FORMULA.items() if expected == formula]
        if len(species) != 1:
            raise ValueError(f"unclassified molecular component: {dict(formula)}")
        ids = np.array(sorted(component), dtype=int)
        molecules.append({"species": species[0], "ids": ids,
                          "mass": np.array([MASS[ELEMENT[int(types[i])]] for i in ids]),
                          "adj": adjacency})
    molecules.sort(key=lambda m: (m["species"], int(m["ids"][0])))
    if dict(Counter(m["species"] for m in molecules)) != COUNTS:
        raise ValueError("molecular composition differs from public system specification")
    return types, box, molecules


def _frame_com(atom_rows, molecules, box):
    wrapped, atomv = atom_rows[:, 2:5], atom_rows[:, 11:14]
    pos, vel = np.empty((len(molecules), 3)), np.empty((len(molecules), 3))
    for mindex, molecule in enumerate(molecules):
        ids, allowed, adjacency = molecule["ids"], set(map(int, molecule["ids"])), molecule["adj"]
        root, unwrapped = int(ids[0]), {}
        unwrapped[root] = wrapped[root].copy()
        todo = deque([root])
        while todo:
            i = todo.popleft()
            for j in adjacency[i]:
                if j in allowed and j not in unwrapped:
                    unwrapped[j] = unwrapped[i] + min_image(wrapped[j] - wrapped[i], box)
                    todo.append(j)
        if len(unwrapped) != len(ids):
            raise ValueError("molecular periodic graph is disconnected")
        xyz = np.array([unwrapped[int(i)] for i in ids])
        weights = molecule["mass"]
        pos[mindex] = np.average(xyz, axis=0, weights=weights)
        vel[mindex] = np.average(atomv[ids], axis=0, weights=weights)
    return np.mod(pos, box), vel


def read_dump(path: Path, types, box_ref, molecules, dt_fs):
    natoms, steps, positions, velocities = len(types), [], [], []
    frame_box = None
    first_state = last_state = None
    with path.open(encoding="utf-8") as stream:
        while True:
            line = stream.readline()
            if not line:
                break
            if line.strip() != "ITEM: TIMESTEP":
                raise ValueError(f"invalid dump frame header in {path}")
            step_text = stream.readline().strip()
            if not step_text.isdigit():
                raise ValueError("dump timestep is not an integer")
            step = int(step_text)
            if stream.readline().strip() != "ITEM: NUMBER OF ATOMS" or int(stream.readline()) != natoms:
                raise ValueError("dump atom count differs from structure")
            header = stream.readline().split()
            if header[:3] != ["ITEM:", "BOX", "BOUNDS"]:
                raise ValueError("invalid dump box header")
            triclinic = header[3:6] == ["xy", "xz", "yz"]
            flags = header[6:] if triclinic else header[3:]
            if flags != ["pp", "pp", "pp"]:
                raise ValueError("trajectory boundary is not fully periodic")
            bounds = np.array([[float(v) for v in stream.readline().split()] for _ in range(3)])
            if bounds.shape != (3, 3 if triclinic else 2) or not np.isfinite(bounds).all():
                raise ValueError("invalid dump box")
            if triclinic and np.any(np.abs(bounds[:, 2]) > 1e-12):
                raise ValueError("nonzero triclinic tilt is unsupported")
            observed_box = bounds[:, 1] - bounds[:, 0]
            if frame_box is None:
                frame_box = observed_box.copy()
            elif not np.allclose(observed_box, frame_box, rtol=0, atol=1e-8):
                raise ValueError("trajectory box changed during the fixed-volume run")
            atom_header = stream.readline().split()
            if atom_header[:2] != ["ITEM:", "ATOMS"] or atom_header[2:] != COLS:
                raise ValueError("unexpected native atom columns")
            rows = np.array([[float(v) for v in stream.readline().split()] for _ in range(natoms)])
            if rows.shape != (natoms, len(COLS)) or not np.isfinite(rows).all():
                raise ValueError("truncated or nonfinite trajectory frame")
            rows = rows[np.argsort(rows[:, 0])]
            if not np.array_equal(rows[:, 0], np.arange(1, natoms + 1)) or not np.array_equal(rows[:, 1].astype(int), types):
                raise ValueError("atom ID/type mapping differs from source structure")
            image = rows[:, 5:8]
            if (not np.equal(image, np.rint(image)).all() or
                    np.max(np.abs(rows[:, 2:5] + image * frame_box - rows[:, 8:11])) > 2e-7):
                raise ValueError("wrapped and unwrapped coordinates disagree")
            p, v = _frame_com(rows, molecules, frame_box)
            if first_state is None:
                first_state = rows.copy()
            last_state = rows.copy()
            steps.append(step)
            positions.append(p)
            velocities.append(v)
    if len(steps) < 2:
        raise ValueError("native trajectory needs at least two frames")
    stride = np.diff(steps)
    if np.any(stride <= 0) or len(set(stride.tolist())) != 1:
        raise ValueError("native trajectory timestep spacing is irregular")
    pos = np.asarray(positions)
    unwrapped = np.empty_like(pos)
    unwrapped[0] = pos[0]
    for i in range(1, len(steps)):
        unwrapped[i] = unwrapped[i - 1] + min_image(pos[i] - pos[i - 1], frame_box)
    dt_ps = dt_fs / 1000.0
    return {"steps": np.asarray(steps, dtype=np.int64), "time": np.asarray(steps) * dt_ps,
            "pos": unwrapped, "vel": np.asarray(velocities), "box": frame_box,
            "stride_steps": int(stride[0]), "first_atom_state": first_state,
            "last_atom_state": last_state}


def correlations(dataset, molecules, origins_ps, maximum_lag_ps, dt_ps):
    pos, vel, time = dataset["pos"], dataset["vel"], dataset["time"]
    mol_mass = np.array([float(m["mass"].sum()) for m in molecules])
    species_ids = {name: np.array([i for i, m in enumerate(molecules) if m["species"] == name], dtype=int)
                   for name in COUNTS}
    nlag = int(round(maximum_lag_ps / dt_ps))
    system_pos = np.average(pos, axis=1, weights=mol_mass)
    system_vel = np.average(vel, axis=1, weights=mol_mass)
    result = {}
    for species, ids in species_ids.items():
        out = {key: np.zeros(nlag + 1) for key in (
            "msd_A2", "msd_drift_corrected_A2", "vacf_A2_per_ps2", "vacf_drift_corrected_A2_per_ps2")}
        counts = np.zeros(nlag + 1, dtype=np.int64)
        corrected_vel = vel[:, ids, :] - system_vel[:, None, :]
        for lag_i in range(nlag + 1):
            lag = lag_i * dt_ps
            starts = np.flatnonzero((time >= origins_ps[0] - 1e-9) &
                                    (time <= origins_ps[1] + 1e-9) &
                                    (np.arange(len(time)) + lag_i < len(time)))
            if len(starts) == 0:
                raise ValueError(f"no time origins for lag {lag:g} ps")
            counts[lag_i] = len(starts)
            delta = pos[starts[:, None] + lag_i, ids[None, :]] - pos[starts[:, None], ids[None, :]]
            drift = system_pos[starts + lag_i] - system_pos[starts]
            out["msd_A2"][lag_i] = np.mean(np.sum(delta * delta, axis=2))
            out["msd_drift_corrected_A2"][lag_i] = np.mean(np.sum((delta - drift[:, None, :]) ** 2, axis=2))
            out["vacf_A2_per_ps2"][lag_i] = np.mean(np.sum(vel[starts[:, None], ids[None, :], :] *
                                                            vel[starts[:, None] + lag_i, ids[None, :], :], axis=2))
            out["vacf_drift_corrected_A2_per_ps2"][lag_i] = np.mean(np.sum(corrected_vel[starts] *
                                                                           corrected_vel[starts + lag_i], axis=2))
        out["lag_ps"], out["origin_count"] = np.arange(nlag + 1, dtype=float) * dt_ps, counts
        result[species] = out
    return result


def parse_all(app: Path, run_ledger: dict):
    structure = app / "inputs" / "inputs" / "strc.lmp"
    types, source_box, molecules = topology(structure)
    series = {}
    for run in run_ledger["runs"]:
        if run.get("status") != "complete":
            continue
        path = app / run["native_artifacts"]["trajectory"]["path"]
        series[run["run_id"]] = read_dump(path, types, source_box, molecules, float(run["dt_fs"]))
    return types, source_box, molecules, series

RUNTIME_WRITER_SOURCE = r'''#!/usr/bin/env python3
"""Write metadata only from files produced by the native job."""
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def package(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(f"required runtime package {name} is unavailable") from exc


def finite_forces(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    atoms = next((i for i, line in enumerate(lines) if line.startswith("ITEM: ATOMS ")), None)
    if atoms is None or lines[atoms].split()[2:] != ["id", "fx", "fy", "fz"]:
        return False
    try:
        count_marker = lines.index("ITEM: NUMBER OF ATOMS")
        natoms = int(lines[count_marker + 1].strip())
        rows = [[float(x) for x in line.split()] for line in lines[atoms + 1:atoms + 1 + natoms]]
    except (ValueError, IndexError):
        return False
    return natoms == 2432 and len(rows) == natoms and all(
        len(row) == 4 and all(math.isfinite(x) for x in row) for row in rows)


def main():
    config = json.loads(Path("run-config.json").read_text(encoding="utf-8"))
    input_manifest = json.loads(Path("input-manifest.json").read_text(encoding="utf-8"))
    decision_commit_hash = None
    if config.get("stage") == "adaptive":
        commit = Path("decision-commit.json")
        if not commit.is_file() or digest(commit) != config.get("decision_commit_sha256"):
            raise RuntimeError("adaptive run is not bound to its pre-submission decision commit")
        if input_manifest["files"].get(commit.name) != config["decision_commit_sha256"]:
            raise RuntimeError("decision commit is not included in the frozen adaptive input manifest")
        decision_commit_hash = config["decision_commit_sha256"]
    markers = Path("step-markers.txt").read_text(encoding="utf-8")
    start = re.search(r"CASE04_START_STEP\s+(\d+)", markers)
    end = re.search(r"CASE04_END_STEP\s+(\d+)", markers)
    if not start or not end:
        raise RuntimeError("LAMMPS step markers are missing")
    loop_rows = [(float(seconds), int(steps)) for seconds, steps in re.findall(
        r"Loop time of\s+([0-9.eE+-]+)\s+on\s+\d+\s+procs for\s+(\d+) steps",
        Path("log.lammps").read_text(errors="replace")) if int(steps) > 0]
    loops = [steps for _, steps in loop_rows]
    executed = sum(loops)
    if executed <= 0 or int(end.group(1)) - int(start.group(1)) != executed:
        raise RuntimeError("native step markers and LAMMPS loop accounting disagree")
    compatible, source_hashes = [], input_manifest["files"]
    for i in range(4):
        model = f"model.{i:03d}.pb"
        force_path, log_path = Path(f"forces-{model[:-3]}.txt"), Path(f"log-{model[:-3]}.probe")
        if not force_path.is_file() or not log_path.is_file():
            raise RuntimeError(f"model compatibility output missing for {model}")
        compatible.append({"model": model, "sha256": source_hashes[model],
                           "md_steps": 0, "forces_finite": finite_forces(force_path)})
    if not all(x["forces_finite"] for x in compatible):
        raise RuntimeError("at least one supplied model force probe is nonfinite")
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not re.fullmatch(r"(?:\d+|GPU-[0-9A-Fa-f-]{8,})", cuda_visible):
        raise RuntimeError("exactly one numeric device index or GPU UUID is required in CUDA_VISIBLE_DEVICES")
    gpu_rows = list(csv.reader(Path("gpu-identity.csv").read_text(encoding="utf-8").splitlines()))
    gpu_rows = [row for row in gpu_rows if len(row) == 3 and row[0].strip().isdigit()]
    if not gpu_rows:
        raise RuntimeError("GPU identity query returned no devices")
    if cuda_visible.isdigit():
        visible_rows = [row for row in gpu_rows if int(row[0].strip()) == int(cuda_visible)]
    else:
        visible_rows = [row for row in gpu_rows if row[1].strip().lower() == cuda_visible.lower()]
    if len(visible_rows) != 1:
        raise RuntimeError("CUDA_VISIBLE_DEVICES does not map to one queried GPU identity")
    binary = os.environ["CASE04_LAMMPS_COMMAND"]
    help_result = subprocess.run([binary, "-h"], capture_output=True, text=True, check=False)
    help_text = help_result.stdout + "\n" + help_result.stderr
    lammps_version = next((line.strip() for line in help_text.splitlines() if "LAMMPS" in line), "")
    if not lammps_version:
        raise RuntimeError("LAMMPS version could not be read from executed binary")
    software = {"tensorflow": package("tensorflow"), "deepmd-kit": package("deepmd-kit"),
                "lammps": lammps_version, "numpy": package("numpy")}
    runtime = {"schema": "case04-native-runtime/v1", "status": "COMPLETE",
               "run_id": config["run_id"], "kind": config["kind"], "T_K": config["T_K"],
               "seed": config["seed"], "source_seed": config.get("source_seed"),
               "requested_steps": config["requested_steps"], "executed_steps": executed,
               "loop_time_seconds": sum(seconds for seconds, _ in loop_rows),
               "simulated_ps": executed * float(config["dt_fs"]) / 1000.0,
               "simulated_ps_per_day": (executed * float(config["dt_fs"]) / 1000.0 /
                                        (sum(seconds for seconds, _ in loop_rows) / 86400.0)
                                        if sum(seconds for seconds, _ in loop_rows) > 0 else None),
               "dt_fs": config["dt_fs"], "initial_step": int(start.group(1)),
               "end_step": int(end.group(1)), "natoms": 2432,
               "automatic_plan_sha256": config["automatic_plan_sha256"],
               "execution_device": "gpu", "decision_commit_sha256": decision_commit_hash,
               "software_versions": software, "model_compatibility": compatible,
               "gpu_devices": [{"index": int(visible_rows[0][0]), "uuid": visible_rows[0][1].strip(),
                                "name": visible_rows[0][2].strip()}],
               "cuda_visible_devices": cuda_visible, "source_hashes": source_hashes,
               "input_manifest_sha256": config["input_manifest_sha256"],
               "job_id": os.environ.get("SLURM_JOB_ID")}
    if config.get("frozen_plan_sha256"):
        runtime["plan_sha256"] = config["frozen_plan_sha256"]
    if config.get("stage") == "adaptive":
        runtime.update({"retry01_plan_sha256": config["frozen_plan_sha256"],
                        "retry01_input_manifest_sha256": config["input_manifest_sha256"]})
    if config["kind"] == "continuation":
        runtime.update({"source_run": config["source_run"], "source_seed": config["source_seed"]})
    Path("native-runtime.json").write_text(json.dumps(runtime, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
'''

DT_FS = 0.5
STEPS = 20_000
WINDOWS = [[0.5, 2.0], [2.0, 8.0]]
MAX_LAG = 8.0
ORIGIN = [1.0, 10.0]
VACF_CUTOFFS = [1.0, 2.0]
TEMPS = {"pilot353a": 353, "pilot353b": 353, "pilot373a": 373, "pilot373b": 373,
         "adaptive353a": 353, "confirm353": 353, "confirm373": 373}
RUN_SEEDS = {"pilot353a": 1103, "pilot353b": 2207, "pilot373a": 3301,
             "pilot373b": 4409, "adaptive353a": 7717, "confirm353": 5519,
             "confirm373": 6629}
RUN_STAGE = {rid: ("pilot" if rid.startswith("pilot") else
                   "adaptive" if rid.startswith("adaptive") else "confirmation") for rid in TEMPS}
RUN_IDS = list(TEMPS)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path, root: Path):
    return {"path": path.relative_to(root).as_posix(), "sha256": sha(path)}


def contract_template():
    series = []
    for rid in RUN_IDS:
        origins = [1.0, 2.0] if rid == "adaptive353a" else ORIGIN
        series.append({"series_id": rid, "run_ids": [rid], "origins_ps": origins,
                       "maximum_lag_ps": MAX_LAG, "windows_ps": WINDOWS,
                       "vacf_cutoffs_ps": VACF_CUTOFFS, "merge_segments": False,
                       "T_K": TEMPS[rid]})
    precommit = {"method_id": "molecular-graph-periodic-COM-MSD-VACF/v1",
                 "fixed_exclusion_ps": 1.0, "series": series,
                 "claim_rules": [
                     {"claim_id": "diffusive_regime", "rule_id": "finite_window_nonidentifiable"},
                     {"claim_id": "temperature_trend", "rule_id": "temperature_trend_not_identified"},
                     {"claim_id": "activation_energy", "rule_id": "activation_energy_not_identified"}],
                 "model_ids": [f"model.{i:03d}.pb" for i in range(4)],
                 "starting_state_source": "inputs/inputs/strc.lmp",
                 "analysis_windows_ps": WINDOWS, "vacf_cutoffs_ps": VACF_CUTOFFS,
                 "statistical_unit": "independent velocity initialization; not molecule/time-origin"}
    alternatives = [
        {"alternative_id": "extend_low_seed_a", "action_kind": "extend",
         "target_temperatures_K": [353, 373], "duration_ps": 30.0, "cost_steps": 60_000,
         "dt_fs": DT_FS, "information_target": "long_lag_support",
         "observable_id": "late_window_alpha", "predicted_direction": "increase_lag_support",
         "bias_risk": "finite_window_bias", "mitigation": "compare_frozen_adjacent_windows"},
        {"alternative_id": "fresh_endpoint_seeds", "action_kind": "fresh_seed",
         "target_temperatures_K": [353, 373], "duration_ps": 30.0, "cost_steps": 60_000,
         "dt_fs": DT_FS, "information_target": "velocity_seed_spread",
         "observable_id": "seed_D_range", "predicted_direction": "resolve_seed_spread",
         "bias_risk": "shared_geometry_bias", "mitigation": "report_descriptive_seed_ranges"},
    ]
    return {"schema": "case04-automatic-decision/v1", "precommit": precommit,
            "alternatives": alternatives,
            "selection_rule_id": "extend_if_any_pilot_window_unstable_else_fresh_seed"}


def freeze_plan(app: Path, route=None):
    inputs = app / "inputs"
    structure = inputs / "inputs" / "strc.lmp"
    models = [inputs / "models" / f"model.{i:03d}.pb" for i in range(4)]
    if not structure.is_file() or any(not p.is_file() for p in models):
        raise RuntimeError("public structure or author model files are missing")
    inputs_hash = {p.relative_to(app).as_posix(): sha(p) for p in [structure, *models]}
    planned = []
    for rid in RUN_IDS:
        adaptive_choice = rid == "adaptive353a"
        planned.append({"run_id": rid, "stage": RUN_STAGE[rid],
                        "kind": "pilot_selected" if adaptive_choice else "fresh", "T_K": TEMPS[rid],
                        "seed": None if adaptive_choice else RUN_SEEDS[rid], "requested_steps": STEPS, "dt_fs": DT_FS,
                        "source_run": None, "source_restart": None,
                        "source_native": None, "source_seed": None,
                        "source_start_step": None, "target_end_step": None if adaptive_choice else STEPS})
    contract = contract_template()
    plan = {"schema": "case04-md-plan/v1", "case_id": "reline-04-diffusion",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_hashes": inputs_hash, "models": [p.name for p in models],
            "estimator": contract["precommit"]["method_id"],
            "timestep_fs": DT_FS, "requested_steps_total": len(RUN_IDS) * STEPS,
            "budget_ps_total": len(RUN_IDS) * STEPS * DT_FS / 1000.0,
            "planned_runs": planned, "reserved_failure_ps": 30.0,
            "automatic_decision_contract": contract,
            "software_resource_gate": "fresh GPU probe + explicit site command/setup; no inferred modules or route"}
    if route is not None:
        target_name, target, partition, snapshot, availability = route
        nodes = [{"node": n["name"], "state": n["state"], "gres": n["gres"],
                  "gpu_capacity": n.get("gpu_capacity"), "gpu_allocated": n.get("gpu_allocated"),
                  "gpu_available": n.get("gpu_available")}
                 for n in snapshot["nodes"] if n.get("partition") == partition]
        plan["resource_selection"] = {
            "target": target_name, "partition": partition, "snapshot_sha256": snapshot["snapshot_sha256"],
            "captured_at": snapshot["captured_at"], "probed_nodes": nodes,
            "availability": availability,
            "selection_rule": "prefer a probed route with known free GPU capacity; otherwise choose a compatible configured route by observed queue count without inferring start time"}
    # The digest is self-referential by construction; omit its own field.
    unsigned = json.loads(json.dumps(contract["precommit"]))
    unsigned.pop("frozen_plan_sha256", None)
    contract["precommit"]["frozen_plan_sha256"] = canonical_hash({
        "precommit": unsigned, "alternatives": contract["alternatives"],
        "selection_rule_id": contract["selection_rule_id"]})
    plan["automatic_decision_contract"] = contract
    write_json(app / "plan.json", plan)
    frozen = app / "execution" / "frozen-plan.json"
    write_json(frozen, plan)
    plan["raw_frozen_plan_sha256"] = sha(frozen)
    return plan


def site_route(app: Path):
    configured = os.environ.get("CCB_IKKEM_SUBMIT_CONFIG")
    cfg_paths = [Path(configured).expanduser()] if configured else [app / "submit-job.json", Path.home() / ".config/submit-job/config.json"]
    cfg_path = next((p for p in cfg_paths if p.is_file()), None)
    if cfg_path is None:
        raise RuntimeError("missing site-owned submit-job.json; no resource route is configured")
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    cli = Path(os.environ.get("IKKEM_SLURM_SUBMIT_CLI", "/opt/skills/ikkem-slurm/scripts/submit.py"))
    if not cli.is_file():
        raise RuntimeError(f"maintainer ikkem-slurm CLI is missing: {cli}")
    routes = []
    for name, target in config.get("targets", {}).items():
        if not isinstance(target, dict) or target.get("backend") != "slurm" or target.get("resource_class") != "gpu":
            continue
        partitions = target.get("allowed_partitions")
        if not isinstance(partitions, list):
            continue
        if target.get("gpus") not in (None, 1, "1") or target.get("gres") not in (None, "gpu:1"):
            continue
        lammps = target.get("case04_lammps_command")
        setup = target.get("case04_setup_command", "")
        tz_name = target.get("case04_scheduler_timezone")
        if (not isinstance(target.get("host"), str) or not isinstance(lammps, str) or not lammps.strip() or
                len(shlex.split(lammps)) != 1 or not isinstance(setup, str) or not isinstance(tz_name, str)):
            continue
        try:
            ZoneInfo(tz_name)
        except Exception:
            continue
        for partition in partitions:
            try:
                _, snapshot = cli_call(cli, ["probe", "--host", target["host"], "--partition", partition,
                                             "--json", "--detail"], app)
            except Exception:
                continue
            nodes = [n for n in snapshot.get("nodes", []) if n.get("partition") == partition]
            free_gpu = any(n.get("gpu_allocation_known") is True and
                           isinstance(n.get("gpu_available"), int) and n["gpu_available"] > 0 and
                           n.get("state", "").lower().startswith(("idle", "mix")) for n in nodes)
            queue_rows = snapshot.get("queue")
            matching_queue = [q for q in queue_rows if isinstance(q, dict)
                              if q.get("partition") == partition and q.get("state", "").lower() in
                              ("pending", "configuring")] if isinstance(queue_rows, list) else []
            queue_known = isinstance(queue_rows, list) and all(
                isinstance(q.get("count"), int) and q["count"] >= 0 for q in matching_queue)
            queue_count = sum(q["count"] for q in matching_queue) if queue_known else None
            routes.append((0 if free_gpu else 1, queue_count if queue_count is not None else math.inf,
                           name, target, partition, snapshot,
                           {"known_free_gpu": free_gpu, "observed_pending_configuring": queue_count,
                            "queue_count_known": queue_known,
                            "selection_note": ("probed free GPU capacity" if free_gpu else
                                               "compatible configured route selected; capacity is busy or unknown, so submission may queue and no start time is inferred")}))
    if not routes:
        raise RuntimeError("no configured compatible GPU target returned a usable read-only probe")
    routes.sort(key=lambda row: (row[0], row[1], row[2], row[4]))
    _, _, target_name, target, partition, snapshot, availability = routes[0]
    lammps = target.get("case04_lammps_command")
    setup = target.get("case04_setup_command", "")
    tz_name = target.get("case04_scheduler_timezone")
    if not isinstance(lammps, str) or not lammps.strip() or not isinstance(setup, str) or not isinstance(tz_name, str):
        raise RuntimeError("selected site target must define LAMMPS command, setup command (possibly empty), and scheduler timezone")
    if len(shlex.split(lammps)) != 1:
        raise RuntimeError("case04_lammps_command must name one executable; launcher arguments require a site wrapper")
    ZoneInfo(tz_name)
    return config, cfg_path, target_name, target, partition, lammps, setup, tz_name, cli, snapshot, availability


def lammps_script(run_id, temp, seed, kind, model_paths, restart_file=None, thermostat_tau=0.1):
    lines = ["units metal", "boundary p p p", "atom_style atomic", "neighbor 2.0 bin",
             "neigh_modify every 10 delay 0 check no"]
    if kind == "continuation":
        lines.append("read_restart parent.restart")
    else:
        lines += ["read_data strc.lmp", "mass 1 1.0", "mass 2 16.0", "mass 3 14.0",
                  "mass 4 12.0", "mass 5 35.45"]
    models = model_paths[0].name
    lines += [f"pair_style deepmd {models}", "pair_coeff * *", "timestep 0.0005",
              "thermo_style custom step pe ke etotal temp press vol lx ly lz", "thermo 200"]
    if kind != "continuation":
        lines.append(f"velocity all create {temp} {seed} mom yes rot yes dist gaussian")
    lines += [f"fix integrator all nvt temp {temp} {temp} {thermostat_tau}",
              "dump trajectory all custom 200 traj.lammpstrj id type x y z ix iy iz xu yu zu vx vy vz",
              "dump_modify trajectory sort id append yes first yes format float %.15g",
              "variable case04_start equal step", 'print "CASE04_START_STEP $(v_case04_start)" file step-markers.txt',
              f"run {STEPS}", "variable case04_end equal step",
              'print "CASE04_END_STEP $(v_case04_end)" append step-markers.txt',
              "write_restart final.restart"]
    return "\n".join(lines) + "\n"


def probe_input(model_path):
    return "\n".join(["units metal", "boundary p p p", "atom_style atomic", "neighbor 2.0 bin",
                     "read_data strc.lmp", "mass 1 1.0", "mass 2 16.0", "mass 3 14.0",
                     "mass 4 12.0", "mass 5 35.45", f"pair_style deepmd {model_path.name}",
                     "pair_coeff * *", "thermo_style custom step pe ke temp", "thermo 1", "run 0",
                     f"write_dump all custom forces-{model_path.stem}.txt id fx fy fz modify sort id", ""])


def make_source(app, run_id, plan, lammps_command, setup_command, model_paths, thermostat_tau=0.1):
    run_dir = app / "execution" / run_id
    source = run_dir / "source"
    source.mkdir(parents=True, exist_ok=True)
    chosen = plan.get("automatic_decision_contract", {}).get("chosen_alternative_id")
    parent = "pilot353a" if run_id == "adaptive353a" and chosen == "extend_low_seed_a" else None
    kind = "continuation" if parent else "fresh"
    shutil.copy2(app / "inputs" / "inputs" / "strc.lmp", source / "strc.lmp")
    for model in model_paths:
        shutil.copy2(model, source / model.name)
    if parent:
        shutil.copy2(app / "execution" / parent / "final.restart", source / "parent.restart")
    (source / "run.lammps").write_text(lammps_script(run_id, TEMPS[run_id], RUN_SEEDS[run_id], kind,
                                                       model_paths, thermostat_tau=thermostat_tau), encoding="utf-8")
    for model in model_paths:
        (source / f"probe-{model.stem}.lammps").write_text(probe_input(model), encoding="utf-8")
    config = {"run_id": run_id, "stage": RUN_STAGE[run_id], "kind": kind, "T_K": TEMPS[run_id],
              "seed": RUN_SEEDS[run_id], "dt_fs": DT_FS, "requested_steps": STEPS,
              "dump_stride_steps": 200, "driver": f"execution/{run_id}/source/run.lammps",
              "control_setting": {"thermostat": "nvt", "damping_ps": thermostat_tau},
              "source_run": parent, "frozen_plan": "execution/frozen-plan.json",
              "frozen_plan_sha256": plan["raw_frozen_plan_sha256"],
              "automatic_plan_sha256": plan["automatic_decision_contract"]["precommit"]["frozen_plan_sha256"]}
    if run_id == "adaptive353a":
        decision_commit = app / "execution" / "decision-commit.json"
        if not decision_commit.is_file():
            raise RuntimeError("adaptive action cannot be prepared before an immutable decision commit")
        shutil.copy2(decision_commit, source / "decision-commit.json")
        config["decision_commit_sha256"] = sha(decision_commit)
        config["frozen_config"] = {"run_id": run_id, "kind": kind, "T_K": TEMPS[run_id],
                                   "seed": RUN_SEEDS[run_id], "requested_steps": STEPS, "dt_fs": DT_FS,
                                   "source_run": parent}
    if parent:
        parent_dir = app / "execution" / parent
        native_parent = json.loads((parent_dir / "native-runtime.json").read_text(encoding="utf-8"))
        restart_hash = sha(parent_dir / "final.restart")
        config.update({"source_seed": RUN_SEEDS[parent], "source_start_step": native_parent["end_step"],
                       "target_end_step": native_parent["end_step"] + STEPS,
                       "decision_commit_sha256": sha(decision_commit),
                       "source_native": f"execution/{parent}/native-runtime.json",
                       "source_restart": f"execution/{parent}/final.restart",
                       "source_restart_sha256": restart_hash,
                       "frozen_config": {"run_id": run_id, "kind": "continuation", "T_K": TEMPS[run_id],
                                         "source_run": parent, "source_native": f"execution/{parent}/native-runtime.json",
                                         "source_restart": f"execution/{parent}/final.restart",
                                         "source_seed": RUN_SEEDS[parent],
                                         "source_start_step": native_parent["end_step"],
                                         "target_end_step": native_parent["end_step"] + STEPS,
                                         "source_restart_sha256": restart_hash}})
    write_json(run_dir / "run-config.json", config)
    (source / "run-config.json").write_bytes((run_dir / "run-config.json").read_bytes())
    (source / "runtime_writer.py").write_text(RUNTIME_WRITER_SOURCE, encoding="utf-8")
    shell_lines = ["#!/usr/bin/env bash", "set -euo pipefail", setup_command,
                   f"export CASE04_LAMMPS_COMMAND={json.dumps(lammps_command)}",
                   "export OMP_NUM_THREADS=4", "command -v nvidia-smi >/dev/null",
                   "[[ \"${CUDA_VISIBLE_DEVICES:-}\" =~ ^([0-9]+|GPU-[[:xdigit:]-]{8,})$ ]]",
                   "printf 'index,uuid,name\\n' > gpu-identity.csv",
                   "nvidia-smi -i \"$CUDA_VISIBLE_DEVICES\" --query-gpu=index,uuid,name --format=csv,noheader >> gpu-identity.csv",
                   ":"]
    for model in model_paths:
        shell_lines += [f"$CASE04_LAMMPS_COMMAND -in probe-{model.stem}.lammps -log log-{model.stem}.probe",
                        f"grep -Eq '^[[:space:]]*0[[:space:]]+[-+0-9.eE]+[[:space:]]+[-+0-9.eE]+' log-{model.stem}.probe"]
    shell_lines += ["$CASE04_LAMMPS_COMMAND -in run.lammps -log log.lammps",
                    "python3 runtime_writer.py"]
    (source / "run.sh").write_text("\n".join(shell_lines) + "\n", encoding="utf-8")
    (source / "run.sh").chmod(0o755)
    return run_dir, source, config


def cli_call(cli, args, cwd, accept_error=False):
    proc = subprocess.run([sys.executable, str(cli), *args], cwd=cwd,
                          capture_output=True, text=True)
    if proc.returncode and not accept_error:
        raise RuntimeError(f"ikkem-slurm {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = None
    return proc, payload


def submit_one(app, cli, target_name, target, partition, tz_name, plan, run_id,
               lammps_command, setup_command, model_paths):
    run_dir, source, config = make_source(app, run_id, plan, lammps_command,
                                          setup_command, model_paths)
    snapshot_path = run_dir / "probe-snapshot.json"
    _, snapshot = cli_call(cli, ["probe", "--host", target["host"], "--partition", partition,
                                 "--json", "--detail"], app)
    write_json(snapshot_path, snapshot)
    reason_path = run_dir / "submission-reason.txt"
    reason_path.write_text(
        f"Serialized 10 ps NVT segment {run_id} from the frozen finite-budget study. One GPU is required for the measured DeepMD/LAMMPS execution.\n",
        encoding="utf-8")
    job_name = f"case04-{run_id}-{uuid.uuid4().hex[:8]}"
    common = ["submit", "--target", target_name, "--name", job_name, "--cmd", "bash run.sh",
              "--reason-file", str(reason_path), "--probe-snapshot", str(snapshot_path),
              "--snapshot-sha256", snapshot["snapshot_sha256"], "--src", str(source),
              "--nodes", "1", "--ntasks", "1", "--cpus", "4", "--mem", "8G",
              "--time", "01:00:00", "--partition", partition, "--gres", "gpu:1"]
    _, dry = cli_call(cli, common + ["--dry-run"], app)
    batch = dry.get("plan", {}).get("script")
    if not isinstance(batch, str) or not re.search(r"^\s*#SBATCH\s+--gres(?:=|\s+)gpu:1\s*$", batch, re.M):
        raise RuntimeError("the real ikkem-slurm dry-run did not render the required one-GPU request")
    batch_path = run_dir / "submit.sh"
    batch_path.write_text(batch, encoding="utf-8")
    files = [source / "strc.lmp", *sorted(source.glob("model.*.pb")), source / "run.lammps",
             source / "run.sh", source / "runtime_writer.py", batch_path]
    if (source / "decision-commit.json").is_file():
        files.append(source / "decision-commit.json")
    if (source / "parent.restart").is_file():
        files.append(source / "parent.restart")
    manifest = {"schema": "case04-native-input-manifest/v1",
                "files": {p.name: sha(p) for p in files}}
    manifest_path = source / "input-manifest.json"
    write_json(manifest_path, manifest)
    config.update({"slurm_wrapper": f"execution/{run_id}/submit.sh",
                   "input_manifest": f"execution/{run_id}/source/input-manifest.json",
                   "input_manifest_sha256": sha(manifest_path)})
    write_json(run_dir / "run-config.json", config)
    write_json(source / "run-config.json", config)
    submit_proc, submit_data = cli_call(cli, common, app, accept_error=True)
    (run_dir / "submit.stdout").write_text(submit_proc.stdout, encoding="utf-8")
    (run_dir / "submit.stderr").write_text(submit_proc.stderr, encoding="utf-8")
    state_path = app / ".submit-job" / f"{job_name}.json"
    if submit_proc.returncode or not isinstance(submit_data, dict) or not state_path.is_file():
        raise RuntimeError(f"submission for {run_id} failed before a traceable job ID was recorded")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("plan", {}).get("script") != batch:
        raise RuntimeError("submitted batch source differs from its preflight dry-run")
    if not re.fullmatch(r"\d+", str(state.get("job_id", ""))):
        raise RuntimeError("scheduler did not return an unambiguous numeric job ID")
    wait_proc, wait_data = cli_call(cli, ["wait", "--job", job_name, "--poll", "30", "--timeout", "3600"],
                                    app, accept_error=True)
    (run_dir / "wait.stdout").write_text(wait_proc.stdout, encoding="utf-8")
    (run_dir / "wait.stderr").write_text(wait_proc.stderr, encoding="utf-8")
    status_proc, status_data = cli_call(cli, ["status", "--job", job_name], app, accept_error=True)
    (run_dir / "status.stdout").write_text(status_proc.stdout, encoding="utf-8")
    (run_dir / "status.stderr").write_text(status_proc.stderr, encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    collected = run_dir / "collected"
    collect_args = ["collect", "--job", job_name, "--dest", str(collected)]
    if wait_proc.returncode:
        collect_args.append("--allow-unsuccessful")
    collect_proc, collect_data = cli_call(cli, collect_args, app, accept_error=True)
    (run_dir / "collect.stdout").write_text(collect_proc.stdout, encoding="utf-8")
    (run_dir / "collect.stderr").write_text(collect_proc.stderr, encoding="utf-8")
    if collect_proc.returncode:
        raise RuntimeError(f"collection failed for {run_id}; preserved tool state at {state_path}")
    for name in ("traj.lammpstrj", "final.restart", "log.lammps", "native-runtime.json",
                 "gpu-identity.csv", "step-markers.txt"):
        src = next(collected.rglob(name), None)
        if src is not None:
            shutil.copy2(src, run_dir / name)
    job_id = str(state["job_id"])
    for suffix, dest in (("out", "scheduler.stdout"), ("err", "scheduler.stderr")):
        src = next(collected.rglob(f"{job_name}-{job_id}.{suffix}"), None)
        if src is not None:
            shutil.copy2(src, run_dir / dest)
    shutil.copy2(state_path, run_dir / "scheduler-tool-state.json")
    return {"run_dir": run_dir, "state": state, "wait_data": wait_data, "timezone": tz_name,
            "scheduler_complete": wait_proc.returncode == 0 and isinstance(wait_data, dict)
                                  and wait_data.get("state") == "completed"}


def iso_scheduler(value, timezone_name):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.isoformat()


def elapsed_seconds(value):
    if not isinstance(value, str):
        raise RuntimeError("sacct elapsed time is missing")
    days = 0
    if "-" in value:
        day_text, value = value.split("-", 1)
        days = int(day_text)
    parts = value.split(":")
    if len(parts) != 3:
        raise RuntimeError("sacct elapsed time is malformed")
    hours, minutes, seconds = (int(p) for p in parts)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def scheduler_record(run_dir, state, timezone_name):
    evidence = state.get("resource_evidence")
    receipt = state.get("receipt")
    if not isinstance(evidence, dict) or not isinstance(receipt, dict):
        raise RuntimeError(f"{run_dir.name}: complete raw scontrol and sacct evidence is missing")
    raw = base64.b64decode(evidence.get("scontrol_rows_base64", ""), validate=True).decode("utf-8")
    fields = {}
    for key, value in re.findall(r"(?:^|\s)(SubmitTime|StartTime|EndTime)=([^\s]+)", raw):
        fields[key] = value
    if "SubmitTime" not in fields or "StartTime" not in fields:
        raise RuntimeError(f"{run_dir.name}: scontrol raw record lacks scheduler timestamps")
    tres = receipt.get("AllocTRES")
    if not isinstance(tres, str) or not tres:
        raise RuntimeError(f"{run_dir.name}: sacct AllocTRES was unavailable")
    gpu_match = re.search(r"(?:^|,)gres/gpu(?::[^=,]+)?=(\d+)(?:,|$)", tres)
    resources_cfg = state.get("resources", {})
    memory = str(resources_cfg.get("mem", ""))
    mem_match = re.fullmatch(r"(\d+)([KMGTP])", memory, re.I)
    if not mem_match:
        raise RuntimeError(f"{run_dir.name}: submitted memory limit is not parseable")
    gib = int(mem_match.group(1)) * {"K": 1/1024**2, "M": 1/1024, "G": 1, "T": 1024, "P": 1024**2}[mem_match.group(2).upper()]
    job_id = str(state.get("job_id"))
    allocation_id = job_id
    raw_state = str(receipt.get("State", "")).split()[0].upper()
    exit_pair = str(receipt.get("ExitCode", ""))
    if not re.fullmatch(r"\d+:\d+", exit_pair):
        raise RuntimeError(f"{run_dir.name}: sacct ExitCode is unavailable")
    try:
        ended_at = iso_scheduler(fields.get("EndTime", "Unknown"), timezone_name)
    except (ValueError, TypeError):
        started = datetime.fromisoformat(iso_scheduler(fields["StartTime"], timezone_name))
        ended_at = (started + timedelta(seconds=elapsed_seconds(receipt.get("Elapsed")))).isoformat()
    record = {"schema": "case04-candidate-scheduler-record/v1", "attempt_id": None,
              "run_id": run_dir.name, "job_id": job_id, "allocation_id": allocation_id,
              "submitted_at": iso_scheduler(fields["SubmitTime"], timezone_name),
              "started_at": iso_scheduler(fields["StartTime"], timezone_name),
              "ended_at": ended_at,
              "state": raw_state, "exit_code": int(exit_pair.split(":")[0]),
              "partition": receipt.get("Partition"), "allocation_tres": tres,
              "resources": {"nodes": 1, "cpus": int(resources_cfg.get("cpus", 0)),
                            "memory_gib": gib, "walltime_seconds": 3600,
                            "gpus": int(gpu_match.group(1)) if gpu_match else None},
              "array": False}
    return record, allocation_id


def make_ledger_row(run_id, submitted, stage):
    run_dir, state = submitted["run_dir"], submitted["state"]
    complete = submitted["scheduler_complete"] and (run_dir / "native-runtime.json").is_file()
    job_id = str(state.get("job_id", ""))
    record, allocation_id = scheduler_record(run_dir, state, submitted["timezone"])
    native_path = run_dir / "native-runtime.json"
    if complete:
        native = json.loads(native_path.read_text(encoding="utf-8"))
        if native.get("status") != "COMPLETE" or native.get("job_id") != job_id:
            raise RuntimeError(f"{run_id}: native runtime does not bind the completed scheduler job")
        executed = int(native["executed_steps"])
        status = "complete"
    else:
        native = None
        executed = None
        status = "failed" if record["state"] in {"FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"} else "unknown"
    config = json.loads((run_dir / "run-config.json").read_text(encoding="utf-8"))
    artifacts = {}
    for kind, path in (("input", run_dir / "source" / "run.lammps"),
                       ("log", run_dir / "log.lammps"), ("trajectory", run_dir / "traj.lammpstrj"),
                       ("restart", run_dir / "final.restart")):
        if path.is_file():
            artifacts[kind] = {"path": path.relative_to(run_dir.parent.parent).as_posix(), "sha256": sha(path)}
    gpu_evidence = {}
    for key, path in (("gpu_identity", run_dir / "gpu-identity.csv"),):
        if path.is_file():
            gpu_evidence[key] = {"path": path.relative_to(run_dir.parent.parent).as_posix(), "sha256": sha(path)}
    row = {"run_id": run_id, "allocation_id": allocation_id, "job_id": job_id,
           "T_K": TEMPS[run_id], "seed": RUN_SEEDS[run_id], "stage": stage,
           "status": status, "requested_steps": STEPS, "executed_steps": executed,
           "dt_fs": DT_FS, "gpu_count": 1, "native_artifacts": artifacts,
           "native_runtime_path": f"execution/{run_id}/native-runtime.json" if complete else None,
           "native_runtime_sha256": sha(native_path) if complete else None,
           "author_probe_frame_ids": ([f"model.{i:03d}" for i in range(4)]
                                      if complete and len(native.get("model_compatibility", [])) == 4 else []),
           "gpu_evidence": gpu_evidence,
           "control_setting": config.get("control_setting")}
    if stage == "adaptive":
        row.update({"source_seed": RUN_SEEDS["pilot353a"],
                    "parent_checkpoint_sha256": config.get("source_restart_sha256")})
    return row, record


def fit_line(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def analyze(app, plan, ledger):
    types, box, molecules, datasets = parse_all(app, ledger)
    restart_continuity = None
    if "pilot353a" in datasets and "adaptive353a" in datasets:
        parent, continuation = datasets["pilot353a"], datasets["adaptive353a"]
        adaptive_config = json.loads((app / "execution" / "adaptive353a" / "run-config.json").read_text(encoding="utf-8"))
        if adaptive_config.get("kind") == "continuation":
            max_state_delta = float(np.max(np.abs(parent["last_atom_state"][:, 2:] -
                                                  continuation["first_atom_state"][:, 2:])))
            if (parent["steps"][-1] != continuation["steps"][0] or
                    not np.array_equal(parent["last_atom_state"][:, :2], continuation["first_atom_state"][:, :2]) or
                    max_state_delta > 2e-7):
                raise RuntimeError("adaptive native trajectory does not start at the parent's identical restart frame")
            parent_dir = app / "execution" / "pilot353a"
            parent_runtime = json.loads((parent_dir / "native-runtime.json").read_text(encoding="utf-8"))
            restart_hash = sha(parent_dir / "final.restart")
            if (adaptive_config.get("source_restart_sha256") != restart_hash or
                    adaptive_config.get("source_start_step") != int(parent_runtime["end_step"]) or
                    adaptive_config.get("T_K") != adaptive_config.get("frozen_config", {}).get("T_K") or
                    adaptive_config.get("seed") != adaptive_config.get("source_seed")):
                raise RuntimeError("adaptive run configuration does not preserve parent restart/temperature/seed lineage")
            restart_continuity = {"parent_run_id": "pilot353a", "continuation_run_id": "adaptive353a",
                                  "restart_sha256": restart_hash,
                                  "parent_end_step": int(parent["steps"][-1]),
                                  "continuation_first_step": int(continuation["steps"][0]),
                                  "maximum_atom_state_delta": max_state_delta,
                                  "tolerance": 2e-7, "identical_native_restart_frame": True,
                                  "temperature_K": adaptive_config["T_K"], "seed": adaptive_config["seed"]}
        else:
            pilot_seeds = {int(r["seed"]) for r in ledger["runs"] if r["stage"] == "pilot" and int(r["T_K"]) == 353}
            if adaptive_config.get("kind") != "fresh" or int(adaptive_config.get("seed", -1)) in pilot_seeds:
                raise RuntimeError("fresh adaptive run must use a new, explicitly recorded velocity seed")
            restart_continuity = {"adaptive_kind": "fresh_seed", "seed": int(adaptive_config["seed"]),
                                  "distinct_from_pilot_seeds": True}
    species_map = {name: [i for i, mol in enumerate(molecules) if mol["species"] == name] for name in COUNTS}
    result_rows, arrays, diagnostics = {}, {}, {}
    for spec in plan["automatic_decision_contract"]["precommit"]["series"]:
        sid, ids = spec["series_id"], spec["run_ids"]
        if len(ids) != 1 or ids[0] not in datasets:
            raise RuntimeError(f"analysis series {sid} lacks its declared native trajectory")
        run_id, ds = ids[0], datasets[ids[0]]
        dt_ps = float(np.median(np.diff(ds["time"])))
        corr = correlations(ds, molecules, spec["origins_ps"], spec["maximum_lag_ps"], dt_ps)
        row = {"T_K": TEMPS[run_id], "series_id": sid, "constituent_run_ids": ids,
               "origins_ps": spec["origins_ps"], "species": {}}
        for species, values in corr.items():
            for field, data in values.items():
                arrays[f"{sid}__{species}__{field}"] = data
            sp_row = {"windows": {}, "vacf_integrals": {},
                      "maximum_lag_ps": spec["maximum_lag_ps"]}
            window_ds = []
            for index, (lo, hi) in enumerate(spec["windows_ps"]):
                use = (values["lag_ps"] >= lo - 1e-9) & (values["lag_ps"] <= hi + 1e-9)
                slope, intercept = fit_line(values["lag_ps"][use], values["msd_A2"][use])
                drift_slope, _ = fit_line(values["lag_ps"][use], values["msd_drift_corrected_A2"][use])
                alpha = (math.log(values["msd_A2"][use][-1] / values["msd_A2"][use][0]) /
                         math.log(values["lag_ps"][use][-1] / values["lag_ps"][use][0]))
                name = f"w{index + 1}"
                summary = {"lag_range_ps": [lo, hi], "maximum_lag_ps": hi,
                           "MSD_slope_A2_per_ps": slope, "MSD_intercept_A2": intercept,
                           "D_MSD_m2_per_s": slope / 6.0 * 1e-8,
                           "drift_corrected_MSD_slope_A2_per_ps": drift_slope,
                           "drift_corrected_D_MSD_m2_per_s": drift_slope / 6.0 * 1e-8,
                           "D_YH_conditional_m2_s": None,
                           "loglog_endpoint_slope": alpha,
                           "origin_count_at_window_start": int(values["origin_count"][np.flatnonzero(use)[0]]),
                           "origin_count_at_window_end": int(values["origin_count"][np.flatnonzero(use)[-1]])}
                sp_row["windows"][name] = summary
                window_ds.append(summary["D_MSD_m2_per_s"])
            for cutoff in spec["vacf_cutoffs_ps"]:
                use = values["lag_ps"] <= cutoff + 1e-10
                raw_integral = float(np.trapz(values["vacf_A2_per_ps2"][use], values["lag_ps"][use]))
                drift_integral = float(np.trapz(values["vacf_drift_corrected_A2_per_ps2"][use], values["lag_ps"][use]))
                sp_row["vacf_integrals"][f"{cutoff:.1f}ps"] = {
                    "integral_A2_per_ps": raw_integral, "D_VACF_m2_per_s": raw_integral / 3 * 1e-8,
                    "drift_corrected_integral_A2_per_ps": drift_integral,
                    "drift_corrected_D_VACF_m2_per_s": drift_integral / 3 * 1e-8}
            vacf = values["vacf_drift_corrected_A2_per_ps2"]
            if vacf[0] != 0:
                normalized = vacf / vacf[0]
                first_nonpositive = np.flatnonzero(normalized <= 0)
                corr_end = int(first_nonpositive[0]) if len(first_nonpositive) else len(normalized)
                tau = float(np.trapz(normalized[:max(corr_end, 2)], values["lag_ps"][:max(corr_end, 2)]))
            else:
                tau = float("nan")
            duration = float(ds["time"][-1] - ds["time"][0])
            sp_row["correlation_summary"] = {
                "drift_corrected_VACF_integral_time_ps": tau,
                "integral_cutoff_ps": (float(values["lag_ps"][max(corr_end - 1, 0)]) if vacf[0] != 0 else None),
                "trajectory_duration_ps": duration,
                "nominal_blocks_at_two_tau": (int(duration // (2 * tau)) if math.isfinite(tau) and tau > 0 else 0),
                "note": "descriptive correlation diagnostic; blocks are not independent replicas"}
            dvals = np.asarray(window_ds, dtype=float)
            spread = max((float(abs(a - b) / max(abs(a), abs(b), 1e-30))
                          for a, b in zip(dvals[:-1], dvals[1:])), default=0.0)
            alpha_bad = any(abs(w["loglog_endpoint_slope"] - 1.0) > 0.2 for w in sp_row["windows"].values())
            nonident = bool(alpha_bad or np.any(dvals <= 0) or spread > 0.25)
            diagnostics[f"{sid}__{species}__window_comparison"] = {
                "relative_D_spread": spread, "finite_window_nonidentifiable": nonident,
                "window_alpha": [w["loglog_endpoint_slope"] for w in sp_row["windows"].values()]}
            sp_row["window_relative_D_spread"] = spread
            row["species"][species] = sp_row
        result_rows[sid] = row

    thermal = app / "inputs" / "thermophysical.csv"
    with thermal.open(encoding="utf-8", newline="") as stream:
        therm = {int(x["T_K"]): x for x in csv.DictReader(stream)}
    kb = 1.380649e-23
    yh = {}
    for t in sorted({TEMPS[r["run_id"]] for r in ledger["runs"] if r["status"] == "complete"}):
        eta = float(therm[t]["eta_mPa_s"]) * 1e-3
        length = float(therm[t]["L_A"]) * 1e-10
        delta = 2.837297 * kb * t / (6 * math.pi * eta * length)
        yh[str(t)] = {"deltaD_m2_s": delta, "viscosity_Pa_s": eta,
                      "box_length_m": length, "source_sha256": sha(thermal),
                      "conditional_only": True}
        for row in result_rows.values():
            if int(row["T_K"]) == t:
                for item in row["species"].values():
                    for w in item["windows"].values():
                        w["D_YH_conditional_m2_s"] = w["D_MSD_m2_per_s"] + delta
    completed = [r for r in ledger["runs"] if r["status"] == "complete"]
    seeds_per_t = {str(t): len({(r["seed"], r["run_id"]) for r in completed if int(r["T_K"]) == t and r["stage"] != "adaptive"})
                   for t in sorted({int(r["T_K"]) for r in completed})}
    # The initializations are unique velocity seeds; the continued segment is not a new seed.
    seeds_per_t = {str(t): len({r["seed"] for r in completed if int(r["T_K"]) == t})
                   for t in sorted({int(r["T_K"]) for r in completed})}
    results = {"schema": "case04-diffusion-results/v1", "runs": result_rows,
               "yeh_hummer": yh,
               "restart_continuity": restart_continuity,
               "replication": {"confidence_intervals": None,
                               "molecules_and_time_origins_are_not_replicates": True,
                               "shared_starting_coordinates": True,
                               "initializations_per_temperature": seeds_per_t},
               "statistical_unit": "independent velocity initialization; molecular and time-origin samples are correlated",
               "temperature_trend": {"scope": "descriptive endpoint comparison only", "temperatures_K": sorted({int(r["T_K"]) for r in completed}),
                                     "activation_energy_identifiable": False,
                                     "reason": "two endpoint temperatures, short shared-coordinate trajectories, and finite-window MSD nonlinearity"}}
    diagnostics["global__temperature_count"] = {
        "temperature_count": len(results["temperature_trend"]["temperatures_K"]),
        "temperatures_K": results["temperature_trend"]["temperatures_K"]}
    np.savez_compressed(app / "msd-vacf.npz", **arrays)
    write_json(app / "results.json", results)
    return results, arrays, diagnostics


def write_topology(app, types, source_box, molecules):
    source = app / "inputs" / "inputs" / "strc.lmp"
    rows = []
    for molecule_id, molecule in enumerate(molecules, start=1):
        elements = [ELEMENT[int(types[i])] for i in molecule["ids"]]
        rows.append({"molecule_id": molecule_id, "species": molecule["species"],
                     "atom_ids": [int(i) + 1 for i in molecule["ids"]],
                     "atom_masses_amu": [MASS[element] for element in elements],
                     "molecular_mass_amu": float(molecule["mass"].sum()),
                     "molecular_charge_e": {"choline": 1, "chloride": -1, "urea": 0}[molecule["species"]]})
    type_ids, type_counts = np.unique(types, return_counts=True)
    write_json(app / "topology.json", {
        "schema": "case04-molecular-topology/v1",
        "source": {"path": "inputs/inputs/strc.lmp", "sha256": sha(source)},
        "composition": {"atoms": 2432, "molecules": len(molecules), "species_counts": COUNTS},
        "source_structure_box_lengths_A": [float(x) for x in source_box],
        "type_to_element_1_based": {str(k): v for k, v in ELEMENT.items()},
        "atomic_masses_amu": MASS,
        "charge_model": {"species_net_charge_e": {"choline": 1, "chloride": -1, "urea": 0},
                         "atom_partial_charges": None,
                         "note": "Net molecular charges are from the public system specification; the supplied atomic-coordinate data and DeepMD production model do not provide per-atom partial charges."},
        "periodic_reconstruction": {"heavy_atom_bond_cutoff_A": 1.85,
                                     "hydrogen_nearest_heavy_cutoff_A": 1.25,
                                     "method": "minimum-image geometric graph; each hydrogen joins its nearest heavy atom"},
        "COM_definition": "mass-weighted position after graph unwrapping; coordinates then continuously unwrapped between frames",
        "velocity_definition": "mass-weighted atom velocity in Angstrom per ps",
        "checks": {"observed_species_counts": COUNTS,
                   "atom_type_inventory": {str(int(k)): int(v) for k, v in zip(type_ids, type_counts)}},
        "molecules": rows})


def pilot_unstable(diagnostics):
    pilot_ids = [rid for rid in RUN_IDS if RUN_STAGE[rid] == "pilot"]
    evidence = {rid: {key: value for key, value in diagnostics.items() if key.startswith(rid + "__")}
                for rid in pilot_ids}
    triggered = any(row["finite_window_nonidentifiable"]
                    for per_run in evidence.values() for row in per_run.values())
    return triggered, evidence


def make_decision(app, diagnostics, results):
    diag_ids = sorted(diagnostics)
    numeric_evidence = [{"diagnostic_id": key, **diagnostics[key]} for key in diag_ids]
    series_diag_ids = [key for key in diag_ids if key != "global__temperature_count"]
    spreads = [float(diagnostics[key]["relative_D_spread"]) for key in series_diag_ids]
    alpha_deviations = [abs(float(alpha) - 1.0) for key in diag_ids
                        for alpha in diagnostics[key].get("window_alpha", [])]
    unstable_count = sum(bool(diagnostics[key]["finite_window_nonidentifiable"]) for key in series_diag_ids)
    temperatures = sorted({int(row["T_K"]) for row in results["runs"].values()})
    endpoint_summary = {}
    for species in COUNTS:
        d_by_t = {}
        for temp in temperatures:
            values = [float(row["species"][species]["windows"]["w2"]["D_MSD_m2_per_s"])
                      for row in results["runs"].values() if int(row["T_K"]) == temp]
            if values:
                d_by_t[str(temp)] = float(np.mean(values))
        slope = None; conditional_ea = None
        if len(d_by_t) == 2 and all(v > 0 for v in d_by_t.values()):
            t1, t2 = sorted(map(int, d_by_t))
            slope = (math.log(d_by_t[str(t2)]) - math.log(d_by_t[str(t1)])) / (1.0/t2 - 1.0/t1)
            conditional_ea = -0.008314462618 * slope
        endpoint_summary[species] = {"mean_w2_D_m2_s_by_temperature": d_by_t,
                                     "two_point_lnD_vs_inverseT_slope_K": slope,
                                     "conditional_two_point_Ea_kJ_mol": conditional_ea,
                                     "interpretation": "two-point descriptive slope; not a validated Arrhenius model or mechanism"}
    confirmation_comparisons = {}
    for temp, confirm_id, pilot_ids in ((353, "confirm353", ["pilot353a", "pilot353b"]),
                                        (373, "confirm373", ["pilot373a", "pilot373b"])):
        if confirm_id not in results["runs"]:
            continue
        for species in COUNTS:
            pilot_ds = [float(results["runs"][rid]["species"][species]["windows"]["w2"]["D_MSD_m2_per_s"])
                        for rid in pilot_ids if rid in results["runs"]]
            confirm_d = float(results["runs"][confirm_id]["species"][species]["windows"]["w2"]["D_MSD_m2_per_s"])
            confirmation_comparisons[f"{temp}__{species}"] = {
                "pilot_run_ids": [rid for rid in pilot_ids if rid in results["runs"]],
                "pilot_w2_D_m2_s": pilot_ds, "confirmation_run_id": confirm_id,
                "confirmation_w2_D_m2_s": confirm_d,
                "within_pilot_range": bool(pilot_ds and min(pilot_ds) <= confirm_d <= max(pilot_ds)),
                "interpretation": "descriptive one-seed confirmation against two pilot seeds"}
    alpha_pilot = [abs(float(results["runs"][rid]["species"][species]["windows"]["w2"]["loglog_endpoint_slope"]) - 1.0)
                   for rid in ("pilot353a", "pilot353b") if rid in results["runs"]
                   for species in COUNTS]
    alpha_adaptive = [abs(float(results["runs"]["adaptive353a"]["species"][species]["windows"]["w2"]["loglog_endpoint_slope"]) - 1.0)
                      for species in COUNTS] if "adaptive353a" in results["runs"] else []
    selected_id = plan["automatic_decision_contract"]["chosen_alternative_id"]
    selected_observable = "late_window_alpha" if selected_id == "extend_low_seed_a" else "seed_D_range"
    prediction_test = {"observable_id": selected_observable,
                       "pilot353_mean_abs_distance_from_one": float(np.mean(alpha_pilot)) if alpha_pilot else None,
                       "adaptive353_abs_distance_from_one": float(np.mean(alpha_adaptive)) if alpha_adaptive else None,
                       "moved_toward_one": bool(alpha_pilot and alpha_adaptive and
                                                np.mean(alpha_adaptive) < np.mean(alpha_pilot)),
                       "note": "compares the same frozen 2-8 ps window; it does not claim a longer maximum lag"}
    claims = {
        "diffusive_regime": {"status": "inconclusive",
                             "scope": "finite-window COM diffusion at the sampled 353 and 373 K",
                             "diagnostic_ids": series_diag_ids,
                             "evidence": [item for item in numeric_evidence if item["diagnostic_id"] in series_diag_ids],
                             "reason_code": "finite_window_nonidentifiable",
                             "reason": {"rule_id": "finite_window_nonidentifiable",
                                        "nonidentifiable_series_species_count": unstable_count,
                                        "maximum_relative_window_D_spread": max(spreads, default=0.0),
                                        "maximum_abs_endpoint_alpha_distance_from_one": max(alpha_deviations, default=0.0)}},
        "temperature_trend": {"status": "inconclusive",
                              "scope": "two endpoint temperatures with shared starting coordinates and short correlated trajectories",
                              "diagnostic_ids": ["global__temperature_count"], "evidence": [{"diagnostic_id": "global__temperature_count",
                                  "temperature_count": len(temperatures), "temperatures_K": temperatures}],
                              "reason_code": "temperature_trend_not_identified",
                              "reason": {"rule_id": "temperature_trend_not_identified",
                                         "temperature_count": len(temperatures), "temperatures_K": temperatures}},
        "activation_energy": {"status": "inconclusive",
                              "scope": "activation energy is not identifiable from two endpoint temperatures and finite-window estimates",
                              "diagnostic_ids": ["global__temperature_count"],
                              "evidence": [{"diagnostic_id": "global__temperature_count",
                                            "temperature_count": len(temperatures), "temperatures_K": temperatures}],
                              "reason_code": "activation_energy_not_identified",
                              "reason": {"rule_id": "activation_energy_not_identified",
                                         "temperature_count": len(temperatures), "fit_points": len(temperatures),
                                         "physical_activation_energy_identified": False}}}
    if plan["automatic_decision_contract"]["chosen_alternative_id"] == "extend_low_seed_a":
        next_action = {"action_kind": "extend", "target_temperatures_K": [353],
                       "duration_ps": 10.0, "cost_steps": 20_000, "dt_fs": DT_FS,
                       "observable_id": "late_window_alpha",
                       "competing_hypotheses": [
                           {"hypothesis_id": "persistent_caging", "observable_id": "late_window_alpha",
                            "predicted_direction": "remain_non_linear", "trigger_rule_id": "finite_window_nonidentifiable"},
                           {"hypothesis_id": "emergent_translation", "observable_id": "late_window_alpha",
                            "predicted_direction": "approach_linear", "trigger_rule_id": "finite_window_nonidentifiable"}]}
    else:
        next_action = {"action_kind": "fresh_seed", "target_temperatures_K": [353],
                       "duration_ps": 10.0, "cost_steps": 20_000, "dt_fs": DT_FS,
                       "observable_id": "seed_D_range",
                       "competing_hypotheses": [
                           {"hypothesis_id": "shared_geometry_bias", "observable_id": "seed_D_range",
                            "predicted_direction": "unchanged", "trigger_rule_id": "velocity_seed_spread_unresolved"},
                           {"hypothesis_id": "velocity_seed_effect", "observable_id": "seed_D_range",
                            "predicted_direction": "increase", "trigger_rule_id": "velocity_seed_spread_unresolved"}]}
    decision = {"schema": "case04-diffusion-decision/v1", "claims": claims,
                "next_action": next_action,
                "expected_information_gain": {"observable": next_action["observable_id"],
                                               "resolves": [h["hypothesis_id"] for h in next_action["competing_hypotheses"]],
                                               "scope": "pilot-selected finite-window or velocity-seed diagnostic; not an equilibrium test"},
                "confirmation_comparisons": confirmation_comparisons,
                "two_temperature_endpoint_summary": endpoint_summary,
                "prediction_test": prediction_test,
                "budget_tradeoff": {"chosen_action": selected_id, "cost_steps": 60_000,
                                    "alternative_action": ("fresh_endpoint_seeds" if selected_id == "extend_low_seed_a" else "extend_low_seed_a"),
                                    "alternative_cost_steps": 60_000,
                                    "reason": ("pilot finite-window diagnostics trigger the frozen extension rule; confirmations then test reproducibility at both endpoint temperatures"
                                               if selected_id == "extend_low_seed_a"
                                               else "no pilot group triggers the frozen rule, so the precommitted fresh-seed action measures velocity-seed spread")}}
    write_json(app / "decision.json", decision)
    return decision


def ledger_snapshot(rows):
    charged_steps = sum(r["executed_steps"] if r["status"] == "complete" else r["requested_steps"] for r in rows)
    return {"schema": "case04-run-ledger/v1", "runs": rows,
            "charged_steps": charged_steps, "charged_ps": charged_steps * DT_FS / 1000.0,
            "author_probe_frame_ids": [f"{r['run_id']}:{frame_id}" for r in rows
                                       for frame_id in r.get("author_probe_frame_ids", [])]}


def reservation_row(app, run_id):
    run_dir = app / "execution" / run_id
    artifacts = {}
    input_path = run_dir / "source" / "run.lammps"
    if input_path.is_file():
        artifacts["input"] = {"path": input_path.relative_to(app).as_posix(), "sha256": sha(input_path)}
    return {"run_id": run_id, "allocation_id": None, "job_id": None,
            "T_K": TEMPS[run_id], "seed": RUN_SEEDS[run_id], "stage": RUN_STAGE[run_id],
            "status": "unknown", "requested_steps": STEPS, "executed_steps": None,
            "dt_fs": DT_FS, "gpu_count": 1, "native_artifacts": artifacts,
            "author_probe_frame_ids": [],
            "native_runtime_path": None, "native_runtime_sha256": None,
            "gpu_evidence": {}, "control_setting": {"thermostat": "nvt", "damping_ps": 0.1}}


def package_candidate_scheduler(app, ledger, records, attempt_id, evidence_mode):
    if evidence_mode not in {"agent", "oracle"}:
        raise RuntimeError("CCB_ANSWER_MODE must be provided as agent or oracle by the runner")
    evidence_items, starts = [], []
    for run in ledger["runs"]:
        rid = run["run_id"]
        record = records[rid]
        record["attempt_id"] = attempt_id
        run_dir = app / "execution" / rid
        record_path = run_dir / "scheduler-record.json"
        write_json(record_path, record)
        for name in ("submit.sh", "scheduler.stdout", "scheduler.stderr"):
            if not (run_dir / name).is_file():
                raise RuntimeError(f"{rid}: required raw scheduler evidence is missing: {name}")
        evidence_items.append({"run_id": rid, "allocation_id": run["allocation_id"],
                               "scheduler_record": ref(record_path, app),
                               "batch_script": ref(run_dir / "submit.sh", app),
                               "stdout": ref(run_dir / "scheduler.stdout", app),
                               "stderr": ref(run_dir / "scheduler.stderr", app)})
        starts.append((datetime.fromisoformat(record["started_at"]), rid))
    ordered = [rid for _, rid in sorted(starts)]
    order_path = app / "execution" / "execution-order.json"
    write_json(order_path, {"schema": "case04-execution-order/v1", "attempt_id": attempt_id,
                            "attempts": ordered})
    receipt = {"schema": "case04-candidate-scheduler-receipt/v1",
               "origin": "candidate-submitted-crosschecked", "evidence_mode": evidence_mode,
               "attempt_id": attempt_id, "ledger_sha256": canonical_hash(ledger),
               "execution_order": ref(order_path, app), "attempts": evidence_items}
    write_json(app / "execution" / "candidate-scheduler-receipt.json", receipt)


def write_report(app, plan, ledger, results, diagnostics, trace):
    chosen = trace['decisions'][0]['chosen_alternative_id']
    if chosen == 'extend_low_seed_a':
        action_summary = "The pilot rule selected extension. The adaptive segment continues pilot353a from its native restart; the saved boundary and same-seed lineage are independently checked."
        next_summary = "The registered next measurement extends at 353 K and compares the frozen finite windows to distinguish persistent caging from emergent translation."
    else:
        action_summary = "No pilot group triggered the frozen finite-window rule, so the registered action used a fresh velocity seed at 353 K. The seed differs from the pilot seeds; this is a descriptive seed comparison."
        next_summary = "The registered next measurement targets velocity-seed spread at 353 K; it does not claim a longer lag range or an equilibrium result."
    lines = ["# Finite-budget COM diffusion study", "",
             "## Design and execution", "",
             f"The campaign sampled 353 K and 373 K with four 10 ps pilot velocity seeds, one 10 ps adaptive run, and two fresh 10 ps confirmation seeds. It charged **{ledger['charged_ps']:.1f} ps** across **{ledger['charged_steps']} MD steps** at 0.5 fs. Adaptation and confirmations were submitted only after all pilots completed and the pilot-only choice was frozen.", "",
             f"The selected follow-up was `{chosen}`. {action_summary}", "",
             "Four supplied author models were force-probed with zero MD steps in each run; model 000 was used for production. GPU identity, visible device, software versions, native logs, restart files, and scheduler receipts are preserved under `execution/`.", "",
             "## Finite-window estimates", "",
             "MSD slopes are reported for the two predeclared lag windows (0.5–2 ps and 2–8 ps). The molecule and time-origin observations within a run are correlated; the independent statistical unit is a velocity initialization. Confirmation runs use fresh velocities but share the supplied coordinates.", "",
             "| Run | T (K) | Species | D (0.5–2 ps), m²/s | D (2–8 ps), m²/s | Endpoint α (2–8 ps) |",
             "|---|---:|---|---:|---:|---:|"]
    for sid, row in results["runs"].items():
        for species, value in row["species"].items():
            w1, w2 = value["windows"]["w1"], value["windows"]["w2"]
            lines.append(f"| {sid} | {row['T_K']} | {species} | {w1['D_MSD_m2_per_s']:.6g} | {w2['D_MSD_m2_per_s']:.6g} | {w2['loglog_endpoint_slope']:.3f} |")
    lines += ["", "## Interpretation and limits", "",
              "The finite-window diagnostics compare positive diffusion slopes, adjacent-window relative spread, and the log–log endpoint slope. They describe the sampled lag range and do not by themselves establish a converged diffusion plateau. VACF integrals and drift-corrected quantities are available alongside raw estimates in `results.json` and `msd-vacf.npz`.", "",
              "The endpoint temperature comparison is descriptive. `decision.json` reports the two-temperature endpoint D difference and conditional two-point ln(D) versus 1/T slope when finite positive values are available. Two points do not validate Arrhenius shape, mechanism, uncertainty, or equilibrium extrapolation; the slope is not a validated physical activation energy.", "",
              "Yeh–Hummer values in `results.json` are conditional corrections using the supplied viscosity and box data. They do not demonstrate a plateau. Model, finite-size, shared-geometry, and initialization sensitivity remain open.", "",
              "## Next measurement", "",
              next_summary, ""]
    (app / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_file_manifest(app):
    outputs = ["plan.json", "execution", "run-ledger.json", "topology.json", "msd-vacf.npz",
               "results.json", "decision-trace.json", "decision.json", "report.md"]
    rows = []
    for output in outputs:
        p = app / output
        paths = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        for path in paths:
            rows.append({"path": path.relative_to(app).as_posix(), "sha256": sha(path),
                         "size": path.stat().st_size})
    rows.sort(key=lambda x: x["path"])
    write_json(app / "file-manifest.json", {"schema": "case04-file-manifest/v1", "files": rows,
                                             "files_sha256": canonical_hash(rows)})


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Site selection reads APP/submit-job.json or ~/.config/submit-job/config.json. "
                "Configure a Slurm GPU target with host, allowed_partitions, resource_class='gpu', "
                "case04_lammps_command (one executable), optional case04_setup_command, and "
                "case04_scheduler_timezone. Routes are probed read-only; known free capacity is "
                "preferred, while busy/unknown compatible capacity may queue without an inferred start time."))
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("APP", "/app")))
    args = parser.parse_args()
    app = args.app.resolve()
    app.mkdir(parents=True, exist_ok=True)
    evidence_mode = os.environ.get("CCB_ANSWER_MODE", "")
    if evidence_mode not in {"agent", "oracle"}:
        raise RuntimeError("CCB_ANSWER_MODE must be agent or oracle before resource probes or submissions")
    route = site_route(app)
    config, cfg_path, target_name, target, partition, lammps, setup, timezone_name, cli, snapshot, availability = route
    write_json(app / "execution" / "resource-probe.json", snapshot)
    if "case04_scheduler_timezone" not in target:
        raise RuntimeError("site target does not record the scheduler timezone")
    plan = freeze_plan(app, (target_name, target, partition, snapshot, availability))
    plan["runtime_profile"] = {"target": target_name, "partition": partition,
                               "lammps_command": lammps,
                               "setup_command_sha256": hashlib.sha256(setup.encode("utf-8")).hexdigest(),
                               "scheduler_timezone": timezone_name,
                               "site_config_path": str(cfg_path)}
    # Freeze the exact pre-run plan, then store its digest only in the public plan.
    frozen = app / "execution" / "frozen-plan.json"
    plan.pop("raw_frozen_plan_sha256", None)
    write_json(frozen, plan)
    plan["raw_frozen_plan_sha256"] = sha(frozen)
    write_json(app / "plan.json", plan)
    inputs = app / "inputs"
    model_paths = [inputs / "models" / f"model.{i:03d}.pb" for i in range(4)]
    types, box, molecules = topology(inputs / "inputs" / "strc.lmp")
    write_topology(app, types, box, molecules)
    attempt_id = uuid.uuid4().hex
    rows, records = [], {}

    def attempt(run_id):
        row = reservation_row(app, run_id)
        rows.append(row)
        write_json(app / "run-ledger.json", ledger_snapshot(rows))
        try:
            submitted = submit_one(app, cli, target_name, target, partition, timezone_name,
                                   plan, run_id, lammps, setup, model_paths)
            row, record = make_ledger_row(run_id, submitted, RUN_STAGE[run_id])
        except Exception as exc:
            run_dir = app / "execution" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "attempt-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            states = sorted((app / ".submit-job").glob(f"case04-{run_id}-*.json"), key=lambda p: p.stat().st_mtime)
            if states:
                state_path = states[-1]
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    job_id = state.get("job_id")
                    if re.fullmatch(r"\d+", str(job_id or "")):
                        row["job_id"] = str(job_id)
                        row["allocation_id"] = str(job_id)
                    shutil.copy2(state_path, run_dir / "scheduler-tool-state.json")
                except (OSError, json.JSONDecodeError):
                    pass
            for kind, path in (("input", run_dir / "source" / "run.lammps"),
                               ("log", run_dir / "log.lammps"), ("trajectory", run_dir / "traj.lammpstrj"),
                               ("restart", run_dir / "final.restart")):
                if path.is_file():
                    row["native_artifacts"][kind] = {"path": path.relative_to(app).as_posix(), "sha256": sha(path)}
            write_json(app / "run-ledger.json", ledger_snapshot(rows))
            write_file_manifest(app)
            raise
        rows[-1] = row
        records[run_id] = record
        write_json(app / "run-ledger.json", ledger_snapshot(rows))
        if row["status"] != "complete":
            package_candidate_scheduler(app, ledger_snapshot(rows), records, attempt_id,
                                        evidence_mode)
            write_file_manifest(app)
            raise RuntimeError(f"{run_id} ended as {row['status']}; charged its full reservation and stopped without retry")

    for run_id in RUN_IDS[:4]:
        attempt(run_id)

    # Pilot-only summaries determine the action; no adaptive or confirmation data are read here.
    pilot_plan = json.loads(json.dumps(plan))
    pilot_plan["automatic_decision_contract"]["precommit"]["series"] = \
        pilot_plan["automatic_decision_contract"]["precommit"]["series"][:4]
    pilot_ledger = ledger_snapshot(rows)
    pilot_results, _, pilot_diagnostics = analyze(app, pilot_plan, pilot_ledger)
    unstable, pilot_evidence = pilot_unstable(pilot_diagnostics)
    contract = plan["automatic_decision_contract"]
    if unstable:
        contract["chosen_alternative_id"] = "extend_low_seed_a"
        RUN_SEEDS["adaptive353a"] = RUN_SEEDS["pilot353a"]
    else:
        contract["chosen_alternative_id"] = "fresh_endpoint_seeds"
        RUN_SEEDS["adaptive353a"] = 7717
    write_json(app / "plan.json", plan)
    frozen_hash = contract["precommit"]["frozen_plan_sha256"]
    chosen_at = datetime.now(timezone.utc).isoformat()
    pilot_alpha_distance = float(np.mean([
        abs(float(pilot_results["runs"][rid]["species"][species]["windows"]["w2"]["loglog_endpoint_slope"]) - 1.0)
        for rid in ("pilot353a", "pilot353b") for species in COUNTS]))
    if unstable:
        prediction = {"observable_id": "late_window_alpha",
                      "comparison": "mean absolute distance from one in the frozen 2-8 ps window",
                      "baseline_pilot353_mean_abs_distance_from_one": pilot_alpha_distance,
                      "predicted_direction": "decrease_abs_distance_from_one"}
    else:
        prediction = {"observable_id": "seed_D_range",
                      "comparison": "descriptive w2 D range across pilot and fresh adaptive velocity seeds",
                      "baseline_pilot353_mean_abs_distance_from_one": pilot_alpha_distance,
                      "predicted_direction": "resolve_seed_spread"}
    decision_commit = {"schema": "case04-decision-commit/v1", "attempt_id": attempt_id,
                       "chosen_at": chosen_at, "chosen_alternative_id": contract["chosen_alternative_id"],
                       "selection_rule_id": contract["selection_rule_id"],
                       "frozen_plan_sha256": sha(frozen), "automatic_plan_sha256": frozen_hash,
                       "pilot_ledger_sha256": canonical_hash(pilot_ledger),
                       "pilot_evidence": pilot_evidence,
                       "prediction": prediction,
                       "followup_run_ids": ["adaptive353a", "confirm353", "confirm373"]}
    commit_path = app / "execution" / "decision-commit.json"
    write_json(commit_path, decision_commit)
    commit_ref = ref(commit_path, app)
    trace = {"schema": "case04-decision-trace/v1", "decisions": [{
        "decision_id": "pilot_adaptation", "chosen_at": chosen_at,
        "frozen_plan_sha256": sha(frozen), "automatic_plan_sha256": frozen_hash,
        "alternatives": [a["alternative_id"] for a in contract["alternatives"]],
        "alternative_details": contract["alternatives"],
        "pilot_evidence": pilot_evidence,
        "chosen": contract["chosen_alternative_id"],
        "chosen_alternative_id": contract["chosen_alternative_id"],
        "prediction": prediction,
        "followup_run_ids": ["adaptive353a", "confirm353", "confirm373"],
        "selection_rule_id": contract["selection_rule_id"],
        "decision_commit": commit_ref}]}
    write_json(app / "decision-trace.json", trace)

    attempt("adaptive353a")
    attempt("confirm353")
    attempt("confirm373")
    ledger = ledger_snapshot(rows)
    write_json(app / "run-ledger.json", ledger)
    results, _, diagnostics = analyze(app, plan, ledger)
    # Keep the pre-run choice timestamp and attach only the observed follow-up test after execution.
    decision = make_decision(app, diagnostics, results)
    trace["decisions"][0]["observed_followup"] = {
        "run_ids": ["adaptive353a", "confirm353", "confirm373"],
        "finite_window_diagnostics": {k: v for k, v in diagnostics.items() if k.startswith("adaptive353a__")},
        "confirmation_comparisons": decision["confirmation_comparisons"],
        "prediction_test": decision["prediction_test"],
        "information_gain_test": "Compare the precommitted finite-window prediction against continuation diagnostics and fresh-seed measurements."}
    write_json(app / "decision-trace.json", trace)
    write_report(app, plan, ledger, results, diagnostics, trace)
    package_candidate_scheduler(app, ledger, records, attempt_id, evidence_mode)
    write_file_manifest(app)
    print(json.dumps({"status": "COMPLETE", "attempt_id": attempt_id,
                      "charged_ps": ledger["charged_ps"], "charged_steps": ledger["charged_steps"],
                      "selected_target": target_name, "partition": partition}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Case04 solve unavailable/incomplete: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
PY
