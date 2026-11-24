#!/usr/bin/env bash
set -euo pipefail
export CCB_ANSWER_MODE="${CCB_ANSWER_MODE:-oracle}"
APP="${APP:-/app}"
cd "$APP"
exec python3 - --app "$APP" <<'__CCB_TASK46_PYTHON__'
#!/usr/bin/env python3
"""Budgeted, provenance-first DeepMD workflow for reline-05-collective."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import shlex
import sys
import uuid

import numpy as np

DT_FS = 0.5
FRAME_EVERY = 20
STEPS = {"pilot": 10_000, "intervention": 6_000,
         "adaptive": 10_000, "confirmation": 20_000}
MAX_STEPS, MAX_PS = 100_000, 50.0
TEMPERATURE = 363.0
RCUT_A = 5.0
MAX_LAG_PS = 1.5
EXCLUDED_INITIAL_PS = 1.0
INTEGRATION_WINDOWS_PS = (0.5, 1.0)
REMOTE_ENV_SH = os.environ.get("CCB_DEEPMD_ENV_SH", "")
REMOTE_ATTEMPT_ROOT = os.environ.get("CCB_REMOTE_ATTEMPT_ROOT", "")
TYPE_NAME = {1: "H", 2: "O", 3: "N", 4: "C", 5: "Cl"}
MASSES = {"H": 1.0, "O": 16.0, "N": 14.0, "C": 12.0, "Cl": 35.45}
CHARGES = {"choline": 1.0, "chloride": -1.0, "urea": 0.0}
FORMULAS = {
    "choline": {"C": 5, "H": 14, "N": 1, "O": 1},
    "chloride": {"Cl": 1},
    "urea": {"C": 1, "H": 4, "N": 2, "O": 1},
}
E_CHARGE = 1.602176634e-19
KB = 1.380649e-23


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_checked(argv: list[str], *, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, check=True, text=True,
                          capture_output=capture)


def inputs(app: Path) -> dict[str, Path]:
    root = app / "inputs"
    paths = {
        "data": root / "inputs" / "strc.lmp",
        "start_template": root / "inputs" / "start.lammps",
        "restart_template": root / "inputs" / "restart.lammps",
        "system": root / "system-spec.json",
        "budget": root / "decision-budget-05.json",
    }
    paths.update({f"model.{i:03d}": root / "models" / f"model.{i:03d}.pb" for i in range(4)})
    missing = [str(p) for p in paths.values() if not p.is_file() or p.is_symlink()]
    if missing:
        raise RuntimeError("required task inputs missing or unsafe: " + ", ".join(missing))
    return paths


def freeze_plan(app: Path, paths: dict[str, Path], attempt_id: str, site_config: Path) -> dict:
    budgets = json.loads(paths["budget"].read_text())
    planned = [
        {"run_id": "pilot01", "stage": "pilot", "seed": 42678,
         "steps": STEPS["pilot"], "source": "supplied starting structure", "thermostat_tau_ps": 0.1},
        {"run_id": "pilot02", "stage": "pilot", "seed": 42679,
         "steps": STEPS["pilot"], "source": "supplied starting structure", "thermostat_tau_ps": 0.1},
        {"run_id": "control_tau050", "stage": "intervention", "seed": 42678,
         "steps": STEPS["intervention"], "parent_run_id": "pilot01", "thermostat_tau_ps": 0.05},
        {"run_id": "control_tau200", "stage": "intervention", "seed": 42678,
         "steps": STEPS["intervention"], "parent_run_id": "pilot01", "thermostat_tau_ps": 0.2},
        {"run_id": "adaptive01", "stage": "adaptive", "seed": 63421, "fresh_seed_if_selected": 63423,
         "steps": STEPS["adaptive"], "source": "conditionally fresh supplied structure or selected pilot restart continuation",
         "selection_rule": "pilot fixed-shell 0.5-ps retention disagreement >15% => fresh-seed start; otherwise extend the pilot with lower initial-temperature deviation and combine trajectories after checkpoint-boundary validation",
         "thermostat_tau_ps": 0.1},
        {"run_id": "confirmation01", "stage": "confirmation", "seed": 74639,
         "steps": STEPS["confirmation"], "source": "supplied starting structure; held-out seed", "thermostat_tau_ps": 0.1},
    ]
    frozen = {
        "schema": "reline05-precommitted-plan/v1", "case_id": "reline-05-collective",
        "attempt_id": attempt_id, "frozen_at": iso_now(), "temperature_K": TEMPERATURE,
        "timestep_fs": DT_FS, "dump_every_steps": FRAME_EVERY,
        "statistical_unit": "independent MD trajectory/seed; time origins are correlated within a trajectory",
        "starting_state": "pilot, confirmation, and adaptive-fresh trajectories use supplied strc.lmp; controls share pilot01 final restart; adaptive-extension continues the selected pilot restart and joins parent/child analysis only after boundary validation",
        "model_policy": "supplied author model.000.pb frozen for production; no retraining, DFT, or author-ensemble frame probes",
        "topology_policy": "connected components reconstructed from periodic covalent geometry and checked against the supplied molecular composition",
        "observables": ["ordered-pair COM RDF and fixed-origin shell counts", "fixed-origin shell retention and refreshed-shell comparator", "molecular COM VACF", "ionic current CJJ, Cself, Cdistinct", "finite-window Green-Kubo and gamma_window=GK(total)/GK(self)"],
        "short_time_shell_signal_rule": "For each pilot, average normalized fixed-origin choline-chloride NC over 0.1-0.5 ps; both positive means supported in this sampled window, both nonpositive contradicted, disagreement inconclusive. Report refreshed-shell comparison separately.",
        "finite_window_plateau_rule": "Across both pilots, the adaptive tranche, and fresh-seed confirmation, compare total-current GK integrals at 0.5 and 1.0 ps using abs(I1-I0.5)/max(abs(I0.5),abs(I1),1e-30). Supported means every relative change is <=20% and no pair has opposite nonzero signs; contradicted means any change is >50% or any opposite nonzero sign pair; all other outcomes are inconclusive. Any supported result is a finite-window plateau only and never licenses equilibrium DC conductivity.",
        "charges_e": CHARGES, "shell_cutoff_A": RCUT_A,
        "origin_stride_frames": 10, "max_lag_ps": MAX_LAG_PS,
        "excluded_initial_time_ps": EXCLUDED_INITIAL_PS,
        "integration_windows_ps": list(INTEGRATION_WINDOWS_PS),
        "gamma_definition": "For each stated finite integration window, gamma_window is the integral of total ionic-current correlation divided by the self-current integral from the identical origins, sampling and window. It is not an ion-pair fraction.",
        "decision_rule": "after both pilots, compare fixed-cohort cation-chloride neighbor retention at 0.5 ps; if relative seed difference exceeds 15%, adaptive tranche starts from the supplied structure with a third seed; otherwise extend the pilot whose initial temperature is closer to 363 K. Record the pilot diagnostics and freeze the choice before the tranche. Confirmation is a new seed and is not used to select windows.",
        "attempts": planned,
        "budget": {"max_steps": budgets["max_md_steps"], "max_ps": budgets["max_aggregate_ps"],
                   "reserved_steps": sum(row["steps"] for row in planned),
                   "reserved_ps": sum(row["steps"] * DT_FS / 1000 for row in planned),
                   "unallocated_steps": budgets["max_md_steps"] - sum(row["steps"] for row in planned),
                   "unallocated_ps": budgets["max_aggregate_ps"] - sum(row["steps"] * DT_FS / 1000 for row in planned),
                   "max_allocations": 18, "max_concurrent_jobs": 1,
                   "resources_per_job": {"nodes": 1, "cpus": 4, "memory_mb": 8192,
                                          "gpus": 1, "walltime_minutes": 60}},
        "inputs_sha256": {key: sha(path) for key, path in paths.items()},
        "site_submit_config_sha256": sha(site_config),
        "software_environment_path": REMOTE_ENV_SH,
        "resource_selection": "probe configured GPU targets and allowed partitions, then select a compatible allocation within the public caps; record target, partition, reason, and probe snapshot",
        "remote_workdir_policy": "unique explicit per-attempt/per-run path, never scheduler default validation directory",
    }
    plan_path = app / "plan.json"
    if plan_path.exists() or (app / "execution").exists():
        raise RuntimeError("existing output detected; refusing to overwrite or reuse an attempt")
    json_write(plan_path, frozen)
    frozen["plan_sha256"] = sha(plan_path)
    return frozen


def lammps_input(run: dict, run_dir: Path, start_kind: str, tau_ps: float) -> str:
    model_paths = "inputs/models/model.000.pb"
    prefix = f"""# Generated from frozen plan; LAMMPS metal units use ps and Angstrom.
units metal
boundary p p p
atom_style atomic
neighbor 2.0 bin
neigh_modify every 10 delay 0 check no
"""
    if start_kind == "restart":
        prefix += "read_restart checkpoint.restart\n"
    else:
        prefix += """read_data inputs/strc.lmp
mass 1 1.0
mass 2 16.0
mass 3 14.0
mass 4 12.0
mass 5 35.45
"""
    prefix += f"""pair_style deepmd {model_paths}
pair_coeff * *
timestep 0.0005
"""
    if start_kind == "data":
        prefix += f"velocity all create {TEMPERATURE:.1f} {run['seed']} mom yes rot yes dist gaussian\n"
    prefix += f"""fix thermostat all nvt temp {TEMPERATURE:.1f} {TEMPERATURE:.1f} {tau_ps:.6f}
thermo 200
thermo_style custom step temp pe ke etotal press vol lx ly lz
thermo_modify flush yes
write_dump all custom initial.dump id type xu yu zu vx vy vz modify sort id
dump trajectory all custom {FRAME_EVERY} trajectory.dump id type xu yu zu vx vy vz
dump_modify trajectory sort id format float %20.12g
run {run['steps']}
undump trajectory
write_restart state.restart
"""
    return prefix


def batch_script(run_id: str, plan_hash: str, decision_commit_sha256: str | None,
                 source_manifest_sha256: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export OMP_NUM_THREADS=4
start_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start_epoch=$(python3 -c 'import time; print(time.time())')
finish() {{
  rc=$?
  end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  end_epoch=$(python3 -c 'import time; print(time.time())')
  steps=$(grep -Eo 'for [0-9]+ steps with' log.lammps 2>/dev/null | tail -1 | awk '{{print $2}}' || true)
  python3 - "$start_time" "$end_time" "$start_epoch" "$end_epoch" "${{steps:-0}}" "$rc" <<'PY'
import json,sys
json.dump({{'start_time':sys.argv[1], 'end_time':sys.argv[2], 'elapsed_seconds':float(sys.argv[4])-float(sys.argv[3]), 'executed_steps':int(sys.argv[5]), 'exit_code':int(sys.argv[6])}},open('native-timing.json','w'),indent=2)
PY
}}
trap finish EXIT
source {shlex.quote(REMOTE_ENV_SH)}
{{
  echo "schema=case05-native-runtime/v1"
  echo "run_id={run_id}"
  echo "plan_sha256={plan_hash}"
  echo "decision_commit_sha256={decision_commit_sha256 or 'not-applicable-before-pilot-decision'}"
  echo "source_manifest_sha256={source_manifest_sha256}"
  echo "start_time=$start_time"
  echo "hostname=$(hostname)"
  echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "software_env={REMOTE_ENV_SH}"
  echo "execution_device=gpu"
  echo "nvidia_smi=$(command -v nvidia-smi || true)"
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader || true
  echo "lammps=$(command -v lmp || command -v lmp_mpi || true)"
  (lmp -h 2>&1 || lmp_mpi -h 2>&1 || true) | head -30
  echo "deepmd_version=$(python -c 'import deepmd; print(getattr(deepmd,"__version__","unknown"))' 2>&1 || true)"
}} > runtime-evidence.txt
LMP=$(command -v lmp || command -v lmp_mpi || true)
test -n "$LMP" || {{ echo 'LAMMPS executable missing after env.sh' >&2; exit 127; }}
{{ /usr/bin/time -p "$LMP" -in in.lammps -log log.lammps; }} > engine.stdout 2> engine.stderr
"""


def read_dump(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    frames, coords, velocities, types, boxes = [], [], [], [], []
    with path.open() as f:
        while True:
            line = f.readline()
            if not line:
                break
            if line.strip() != "ITEM: TIMESTEP":
                raise ValueError(f"invalid dump marker in {path}: {line[:80]!r}")
            step = int(f.readline())
            if f.readline().strip() != "ITEM: NUMBER OF ATOMS":
                raise ValueError("missing atom count in LAMMPS dump")
            n = int(f.readline())
            boundary = f.readline().split()
            if boundary[:3] != ["ITEM:", "BOX", "BOUNDS"]:
                raise ValueError("missing BOX BOUNDS")
            tilt_encoded = any(x in boundary[3:] for x in ("xy", "xz", "yz"))
            flags = boundary[6:] if tilt_encoded else boundary[3:]
            if flags != ["pp", "pp", "pp"]:
                raise ValueError("trajectory must use fully periodic boundaries")
            raw_bounds = [list(map(float, f.readline().split())) for _ in range(3)]
            expected_bound_columns = 3 if tilt_encoded else 2
            if any(len(row) != expected_bound_columns or not np.isfinite(row).all() for row in raw_bounds):
                raise ValueError("malformed or nonfinite box bounds")
            if tilt_encoded and any(len(row) < 3 or abs(row[2]) > 1e-10 for row in raw_bounds):
                raise ValueError("nonzero triclinic tilt is unsupported")
            bounds = np.array([row[:2] for row in raw_bounds])
            box = bounds[:, 1] - bounds[:, 0]
            atom_header = f.readline().split()
            required = ["id", "type", "xu", "yu", "zu", "vx", "vy", "vz"]
            if atom_header[:2] != ["ITEM:", "ATOMS"] or atom_header[2:] != required:
                raise ValueError(f"unexpected atom columns: {atom_header}")
            row = np.array([[float(x) for x in f.readline().split()] for _ in range(n)])
            if row.shape != (n, 8) or not np.isfinite(row).all():
                raise ValueError("malformed atom row")
            if (not np.array_equal(row[:, 0], np.rint(row[:, 0]))
                    or not np.array_equal(row[:, 1], np.rint(row[:, 1]))):
                raise ValueError("atom IDs and types must be integers")
            row = row[np.argsort(row[:, 0].astype(int))]
            if not np.array_equal(row[:, 0].astype(int), np.arange(1, n + 1)):
                raise ValueError("atom IDs must be unique and contiguous from one")
            if frames and not np.array_equal(row[:, 1].astype(int), types[0]):
                raise ValueError("atom types changed during trajectory")
            if boxes and not np.allclose(box, boxes[0], rtol=0, atol=1e-8):
                raise ValueError("trajectory box changed; fixed-volume NVT expected")
            frames.append(step); types.append(row[:, 1].astype(int))
            coords.append(row[:, 2:5]); velocities.append(row[:, 5:8]); boxes.append(box)
    if not frames:
        raise ValueError(f"no frames in {path}")
    step_diffs = np.diff(frames)
    if np.any(step_diffs <= 0) or (len(step_diffs) and np.any(step_diffs != step_diffs[0])):
        raise ValueError("trajectory steps must strictly increase at a fixed dump stride")
    return np.asarray(frames), np.asarray(coords), np.asarray(velocities), np.asarray(types[0]), np.asarray(boxes)


def pbc_delta(delta: np.ndarray, box: np.ndarray) -> np.ndarray:
    return delta - box * np.rint(delta / box)


def reconstruct_topology(xyz: np.ndarray, types: np.ndarray, box: np.ndarray) -> tuple[list[dict], dict]:
    """Connected components from minimum-image covalent distances; no atom-order assumptions."""
    n = len(types)
    parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a
    radii = {1: .31, 2: .66, 3: .71, 4: .76, 5: 0.0}
    bonded = {(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4), (4, 4)}
    for i in range(n):
        for j in range(i + 1, n):
            ti, tj = sorted((int(types[i]), int(types[j])))
            if (ti, tj) not in bonded:
                continue
            dr = pbc_delta(xyz[j] - xyz[i], box)
            cutoff = 1.25 * (radii[ti] + radii[tj])
            if np.dot(dr, dr) <= cutoff * cutoff:
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    molecules = []
    counts = {key: 0 for key in FORMULAS}
    for atom_ids in groups.values():
        composition: dict[str, int] = {}
        for atom in atom_ids:
            label = TYPE_NAME[int(types[atom])]
            composition[label] = composition.get(label, 0) + 1
        species = next((s for s, formula in FORMULAS.items() if formula == composition), None)
        if species is None:
            raise ValueError(f"periodic covalent component does not match supplied molecule formula: {composition}")
        counts[species] += 1
        masses = np.array([MASSES[TYPE_NAME[int(types[i])]] for i in atom_ids])
        molecules.append({"species": species, "atom_ids_1based": [i + 1 for i in atom_ids],
                          "mass_amu": float(masses.sum()), "charge_e": CHARGES[species]})
    expected = {"choline": 64, "chloride": 64, "urea": 128}
    if counts != expected or sum(counts.values()) != 256:
        raise ValueError(f"topology counts mismatch: got {counts}, expected {expected}")
    details = {"method": "minimum-image covalent-radius graph connected components; radius multiplier 1.25",
               "species_counts": counts, "atom_type_mapping_1_based": TYPE_NAME,
               "masses_amu": MASSES, "charges_e": CHARGES,
               "coordinate_definition": "LAMMPS xu yu zu; mass-weighted molecular COM, velocity is mass-weighted atom velocity",
               "periodic_box_A": box.tolist(), "molecules": molecules}
    return molecules, details


def molecular_series(coords: np.ndarray, vel: np.ndarray, types: np.ndarray,
                     boxes: np.ndarray, molecules: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray, np.ndarray]:
    nframe, _, _ = coords.shape
    nmol = len(molecules)
    com = np.zeros((nframe, nmol, 3)); vcom = np.zeros_like(com)
    species = []
    for m, molecule in enumerate(molecules):
        ids = np.array(molecule["atom_ids_1based"], dtype=int) - 1
        masses = np.array([MASSES[TYPE_NAME[int(types[i])]] for i in ids])
        anchor = coords[:, ids[0]]
        relative = pbc_delta(coords[:, ids] - anchor[:, None, :], boxes[:, None, :])
        com[:, m] = anchor + np.einsum("a,tac->tc", masses, relative) / masses.sum()
        vcom[:, m] = np.einsum("a,tac->tc", masses, vel[:, ids]) / masses.sum()
        species.append(molecule["species"])
    charges = np.array([CHARGES[s] for s in species])
    return com, vcom, species, charges, np.array([m["mass_amu"] for m in molecules])


def pair_geometry(com: np.ndarray, box: np.ndarray, ia: np.ndarray, ib: np.ndarray) -> np.ndarray:
    dr = com[ia][:, None, :] - com[ib][None, :, :]
    return np.sqrt(np.sum(pbc_delta(dr, box) ** 2, axis=-1))


def _dump_blocks(path: Path):
    with path.open() as stream:
        while True:
            marker = stream.readline()
            if not marker:
                return
            if marker.strip() != "ITEM: TIMESTEP":
                raise ValueError("invalid dump marker while joining trajectories")
            block = [marker, stream.readline(), stream.readline(), stream.readline()]
            n_atoms = int(block[3])
            block.extend(stream.readline() for _ in range(5))
            block.extend(stream.readline() for _ in range(n_atoms))
            if len(block) != n_atoms + 9 or any(not line for line in block):
                raise ValueError("truncated dump frame while joining trajectories")
            yield int(block[1]), block


def combine_extension(parent_dump: Path, extension_dump: Path, combined_dump: Path) -> dict:
    """Join a restart continuation only after validating its exact boundary."""
    pstep, pxyz, pv, ptypes, pbox = read_dump(parent_dump)
    estep, exyz, ev, etypes, ebox = read_dump(extension_dump)
    if not np.array_equal(ptypes, etypes) or not np.allclose(pbox[-1], ebox[0], rtol=0, atol=1e-8):
        raise ValueError("restart continuation topology or cell differs from its parent")
    stride = int(np.median(np.diff(pstep)))
    offset = int(estep[0] - pstep[-1])
    if offset == 0:
        if (not np.allclose(pxyz[-1], exyz[0], rtol=0, atol=2e-8)
                or not np.allclose(pv[-1], ev[0], rtol=0, atol=2e-8)):
            raise ValueError("restart boundary frame does not match the parent checkpoint")
        skip_first = True
    elif offset == stride:
        skip_first = False
    else:
        raise ValueError(f"restart continuation starts {offset} steps after parent; expected 0 or {stride}")
    with combined_dump.open("w") as destination:
        for source, skip in ((parent_dump, False), (extension_dump, skip_first)):
            for index, (_, block) in enumerate(_dump_blocks(source)):
                if not (skip and index == 0):
                    destination.writelines(block)
    return {"parent_dump_sha256": sha(parent_dump), "extension_dump_sha256": sha(extension_dump),
        "analysis_dump_sha256": sha(combined_dump), "parent_final_step": int(pstep[-1]),
        "extension_first_step": int(estep[0]), "extension_last_step": int(estep[-1]),
        "dump_stride_steps": stride, "duplicate_boundary_frame_removed": skip_first,
        "analysis_ps_including_parent_and_extension": float((estep[-1] - pstep[0]) * DT_FS / 1000)}


def pilot_signal(run_dir: Path, app: Path) -> dict:
    frames, xyz, vel, types, boxes = read_dump(run_dir / "trajectory.dump")
    frame_dt_ps = FRAME_EVERY * DT_FS / 1000
    keep = frames - frames[0] >= int(round(EXCLUDED_INITIAL_PS / frame_dt_ps)) * FRAME_EVERY
    frames, xyz, vel, boxes = frames[keep], xyz[keep], vel[keep], boxes[keep]
    molecules, _ = reconstruct_topology(xyz[0], types, boxes[0])
    com, _, species, _, _ = molecular_series(xyz, vel, types, boxes, molecules)
    ia = np.array([i for i, s in enumerate(species) if s == "choline"])
    ib = np.array([i for i, s in enumerate(species) if s == "chloride"])
    stride = 10
    lag = int(round(.5 * 1000 / (FRAME_EVERY * DT_FS)))
    origins = np.arange(0, len(frames) - lag, stride)
    values = []
    for o in origins:
        d0 = pair_geometry(com[o], boxes[o], ia, ib)
        shell = d0 <= RCUT_A
        dt_dist = pair_geometry(com[o + lag], boxes[o + lag], ia, ib)
        values.append(float(np.count_nonzero(shell & (dt_dist <= RCUT_A)) / max(1, shell.sum())))
    if not values:
        raise ValueError("pilot trajectory is too short to evaluate the frozen 0.5-ps shell diagnostic")
    therm = (run_dir / "log.lammps").read_text(errors="replace")
    temps = [float(x) for x in re.findall(r"^\s*\d+\s+([-+0-9.eE]+)\s+", therm, re.M)]
    return {"n_origins": len(values), "fixed_cohort_retention_0p5ps": float(np.mean(values)),
            "origin_range": [int(frames[origins[0]]), int(frames[origins[-1]])],
            "mean_thermo_temperature_K": float(np.mean(temps)) if temps else None}


def cumulative_trapezoid(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(y, dtype=float)
    dx = np.diff(x).reshape((1,) * (y.ndim - 1) + (-1,))
    out[..., 1:] = np.cumsum((y[..., 1:] + y[..., :-1]) * dx / 2, axis=-1)
    return out


def analyze_run(run_dir: Path, plan: dict) -> tuple[dict, dict]:
    analysis_dump = run_dir / "trajectory-analysis.dump"
    if not analysis_dump.is_file():
        analysis_dump = run_dir / "trajectory.dump"
    steps, xyz, atom_v, atom_types, boxes = read_dump(analysis_dump)
    raw_frame_dt_ps = float(np.median(np.diff(steps)) * DT_FS / 1000) if len(steps) > 1 else FRAME_EVERY * DT_FS / 1000
    keep = steps - steps[0] >= int(round(EXCLUDED_INITIAL_PS / raw_frame_dt_ps)) * FRAME_EVERY
    steps, xyz, atom_v, boxes = steps[keep], xyz[keep], atom_v[keep], boxes[keep]
    molecules, topology = reconstruct_topology(xyz[0], atom_types, boxes[0])
    com, vel, species, charges, masses = molecular_series(xyz, atom_v, atom_types, boxes, molecules)
    species_names = ["choline", "chloride", "urea"]
    ids = {s: np.flatnonzero(np.array(species) == s) for s in species_names}
    dt_ps = float(np.median(np.diff(steps)) * DT_FS / 1000) if len(steps) > 1 else FRAME_EVERY * DT_FS / 1000
    max_lag = min(int(round(MAX_LAG_PS / dt_ps)), len(steps) - 1)
    origin_stride = 10
    origins = np.arange(0, len(steps) - max_lag, origin_stride, dtype=int)
    if len(origins) < 2:
        raise ValueError(f"not enough independent time origins in {run_dir.name}")
    lag_time = np.arange(max_lag + 1) * dt_ps
    # All origins use the same trajectory window and weight.
    vacf = np.zeros((3, max_lag + 1)); shell_fixed = np.zeros((3, 3, max_lag + 1))
    shell_refresh = np.zeros_like(shell_fixed); shell_retention = np.zeros_like(shell_fixed)
    shell_vcorr_fixed = np.zeros_like(shell_fixed); shell_vcorr_refresh = np.zeros_like(shell_fixed)
    nc0 = np.zeros((3, 3))
    current = vel * charges[None, :, None]
    ionic = np.flatnonzero(charges != 0)
    c_total = np.zeros(max_lag + 1); c_self = np.zeros_like(c_total)
    rdf_edges = np.linspace(0.0, 10.0, 201); rdf_hist = np.zeros((3, 3, len(rdf_edges)-1))
    rdf_counts = np.zeros((3, 3))
    vol_mean = float(np.mean(np.prod(boxes, axis=1)))
    # RDF averaged over the same sampled time-origin frames; self molecule excluded.
    rdf_frames = origins
    for a, sa in enumerate(species_names):
        for b, sb in enumerate(species_names):
            ia, ib = ids[sa], ids[sb]
            hist = np.zeros(len(rdf_edges) - 1, dtype=float)
            for frame in rdf_frames:
                distance = pair_geometry(com[frame], boxes[frame], ia, ib)
                if sa == sb:
                    distance[np.diag_indices_from(distance)] = np.inf
                h, _ = np.histogram(distance[np.isfinite(distance)], bins=rdf_edges)
                hist += h
            n_pairs = len(ia) * (len(ib) - (1 if sa == sb else 0))
            rho = (len(ib) - (1 if sa == sb else 0)) / vol_mean
            shell_vol = (4*np.pi/3) * (rdf_edges[1:]**3 - rdf_edges[:-1]**3)
            rdf_hist[a, b] = hist / max(1, len(rdf_frames) * len(ia)) / np.maximum(rho * shell_vol, 1e-30)
            rdf_counts[a, b] = n_pairs
    for o in origins:
        for s, name in enumerate(species_names):
            subset = ids[name]
            if len(subset):
                for k in range(max_lag + 1):
                    vacf[s, k] += np.mean(np.einsum("ic,ic->i", vel[o, subset], vel[o+k, subset]))
        for a, sa in enumerate(species_names):
            ia = ids[sa]
            for b, sb in enumerate(species_names):
                ib = ids[sb]
                d0 = pair_geometry(com[o], boxes[o], ia, ib)
                if sa == sb:
                    d0[np.diag_indices_from(d0)] = np.inf
                origin_shell = d0 <= RCUT_A
                nc0[a, b] += float(origin_shell.sum() / max(1, len(ia)))
                for k in range(max_lag + 1):
                    dlag = pair_geometry(com[o+k], boxes[o+k], ia, ib)
                    if sa == sb:
                        dlag[np.diag_indices_from(dlag)] = np.inf
                    now_shell = dlag <= RCUT_A
                    shell_fixed[a, b, k] += float(np.count_nonzero(origin_shell & now_shell) / max(1, len(ia)))
                    shell_refresh[a, b, k] += float(now_shell.sum() / max(1, len(ia)))
                    shell_retention[a, b, k] += float(np.count_nonzero(origin_shell & now_shell) / max(1, origin_shell.sum()))
                    pair_v = np.einsum("ic,jc->ij", vel[o, ia], vel[o+k, ib])
                    shell_vcorr_fixed[a, b, k] += float(pair_v[origin_shell].sum() / max(1, len(ia)))
                    shell_vcorr_refresh[a, b, k] += float(pair_v[now_shell].sum() / max(1, len(ia)))
        for k in range(max_lag + 1):
            j0 = np.sum(current[o, ionic], axis=0)
            jt = np.sum(current[o+k, ionic], axis=0)
            c_total[k] += float(np.dot(j0, jt))
            v0, vt = current[o, ionic], current[o+k, ionic]
            c_self[k] += float(np.einsum("ic,ic->", v0, vt))
    n_origin = len(origins)
    vacf /= n_origin; shell_fixed /= n_origin; shell_refresh /= n_origin
    shell_retention /= n_origin; shell_vcorr_fixed /= n_origin; shell_vcorr_refresh /= n_origin
    nc0 /= n_origin; c_total /= n_origin; c_self /= n_origin
    species_v2 = np.array([np.mean(np.sum(vel[:, ids[s], :] ** 2, axis=-1)) for s in species_names])
    denominator = np.sqrt(species_v2[:, None] * species_v2[None, :])
    nc_fixed_norm = shell_vcorr_fixed / np.maximum(denominator[:, :, None], 1e-30)
    nc_refresh_norm = shell_vcorr_refresh / np.maximum(denominator[:, :, None], 1e-30)
    c_distinct = c_total - c_self
    int_total = cumulative_trapezoid(c_total, lag_time)
    int_self = cumulative_trapezoid(c_self, lag_time)
    int_distinct = cumulative_trapezoid(c_distinct, lag_time)
    shell_integral_fixed = cumulative_trapezoid(nc_fixed_norm, lag_time)
    shell_integral_refresh = cumulative_trapezoid(nc_refresh_norm, lag_time)
    window_values = {}
    for window in INTEGRATION_WINDOWS_PS:
        i = int(np.argmin(abs(lag_time - window)))
        if abs(lag_time[i] - window) > dt_ps * .51:
            continue
        sigma_factor = E_CHARGE**2 * 1e22 / (3 * max(vol_mean, 1e-9) * KB * TEMPERATURE)
        total_sigma = float(int_total[i] * sigma_factor)
        self_sigma = float(int_self[i] * sigma_factor)
        window_values[f"{window:g}_ps"] = {
            "lag_ps": float(lag_time[i]), "integral_current_total_e2_A2_ps-1": float(int_total[i]),
            "integral_current_self_e2_A2_ps-1": float(int_self[i]),
            "integral_current_distinct_e2_A2_ps-1": float(int_distinct[i]),
            "finite_window_conductivity_S_m": total_sigma,
            "self_nernst_einstein_proxy_S_m": self_sigma,
            "gamma_window_total_over_self": float(int_total[i] / int_self[i]) if abs(int_self[i]) > 1e-30 else None,
            "equilibrium_dc_claim": False,
        }
    if not np.allclose(c_total, c_self + c_distinct, rtol=1e-12, atol=1e-12):
        raise ValueError("current correlation self/distinct decomposition failed")
    log_text = (run_dir / "log.lammps").read_text(errors="replace")
    loop = re.findall(r"Loop time of\s+([0-9.eE+-]+).*?for\s+(\d+)\s+steps", log_text)
    runtime_text = (run_dir / "runtime-evidence.txt").read_text(errors="replace") if (run_dir / "runtime-evidence.txt").is_file() else ""
    performance = None
    if loop:
        seconds, executed_steps = map(float, loop[-1])
        performance = {"lammps_loop_seconds": seconds, "executed_steps": int(executed_steps),
                       "md_steps_per_second": float(executed_steps / seconds) if seconds > 0 else None,
                       "basis": "native LAMMPS loop time in log.lammps"}
    # Neighbor reciprocity uses the same cutoff and the same origin set.
    navg = nc0.copy()
    populations = np.array([len(ids[s]) for s in species_names], dtype=float)
    recip = populations[:, None] * navg - populations[None, :] * navg.T
    pair_results = {}
    for a, sa in enumerate(species_names):
        for b, sb in enumerate(species_names):
            key = f"{sa}__{sb}"
            pair_results[key] = {
                "NC0_mean_neighbors_per_center": float(navg[a, b]),
                "reciprocity_residual_pair_counts": float(recip[a, b]),
                "NC_fixed_origin_normalized_velocity_correlation": nc_fixed_norm[a, b].tolist(),
                "NC_refreshed_normalized_velocity_correlation": nc_refresh_norm[a, b].tolist(),
                "fixed_origin_cohort_retention_fraction": shell_retention[a, b].tolist(),
                "fixed_origin_neighbor_count_per_center": shell_fixed[a, b].tolist(),
                "refreshed_shell_neighbors_per_center": shell_refresh[a, b].tolist(),
            }
    result = {"run_id": run_dir.name, "n_frames": int(len(steps)), "n_time_origins": int(n_origin),
              "statistical_unit": "trajectory; origins share the same finite trajectory and are not independent replicates",
              "trajectory_steps": steps.tolist(), "species_counts": {s: int(len(ids[s])) for s in species_names},
              "volume_mean_A3": vol_mean, "shell_cutoff_A": RCUT_A,
              "excluded_initial_time_ps": EXCLUDED_INITIAL_PS,
              "pair_results": pair_results, "windows": window_values,
              "measured_performance": performance,
              "measured_gpu_and_software_evidence": runtime_text,
              "current_units": "e Angstrom ps^-1; unnormalized C(t)=mean_origin[J(0) dot J(t)]",
              "CJJ_self_distinct_max_abs_residual": float(np.max(abs(c_total - c_self - c_distinct))),
              "gamma_scope": "finite-window total/self ionic-current Green-Kubo ratio; not an ion-pair fraction or equilibrium property",
              "plateau_status": "not assessed as equilibrium plateau; finite 5-10 ps records only",
              "trajectory_path": analysis_dump.relative_to(run_dir.parent.parent).as_posix(),
              "trajectory_sha256": sha(analysis_dump),
              "trajectory_analysis_basis": "parent+restart continuation" if analysis_dump.name == "trajectory-analysis.dump" else "single native trajectory"}
    series = {"lag_ps": lag_time, "rdf_edges_A": rdf_edges, "rdf_ordered_pairs": rdf_hist,
              "NC0_ordered_pairs": nc0, "NC_fixed_origin_ordered_pairs": shell_fixed,
              "NC_refreshed_ordered_pairs": shell_refresh,
              "NC_fixed_origin_velocity_correlation_normalized": nc_fixed_norm,
              "NC_refreshed_velocity_correlation_normalized": nc_refresh_norm,
              "NC_integral_fixed_origin_ps": shell_integral_fixed,
              "NC_integral_refreshed_ps": shell_integral_refresh,
              "VACF_species_A2_ps-2": vacf,
              "C_current_total_e2_A2_ps-2": c_total, "C_current_self_e2_A2_ps-2": c_self,
              "C_current_distinct_e2_A2_ps-2": c_distinct,
              "GK_total_e2_A2_ps-1": int_total, "GK_self_e2_A2_ps-1": int_self,
              "GK_distinct_e2_A2_ps-1": int_distinct,
              "n_origins": np.array([n_origin]), "ordered_species": np.array(species_names)}
    return result, {"series": series, "topology": topology}


def cli_json(argv: list[str], cwd: Path) -> tuple[dict | None, subprocess.CompletedProcess]:
    proc = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    try:
        payload = json.loads(proc.stdout)
    except (ValueError, TypeError):
        payload = None
    return payload if isinstance(payload, dict) else None, proc


def submit_config(app: Path) -> tuple[Path, dict]:
    configured = os.environ.get("CCB_IKKEM_SUBMIT_CONFIG")
    options = [Path(configured).expanduser()] if configured else [app / "submit-job.json", Path.home() / ".config/submit-job/config.json"]
    for path in options:
        if path.is_file() and not path.is_symlink():
            doc = json.loads(path.read_text())
            targets = doc.get("targets", {}) if isinstance(doc, dict) else {}
            if isinstance(targets, dict) and any(isinstance(t, dict) and t.get("resource_class") == "gpu"
                                                  for t in targets.values()):
                return path, doc
    raise RuntimeError("no configured GPU target is available to hpc; refusing to guess a route")


def _memory_mb(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid memory ceiling")
    if isinstance(value, int):
        return value // (1024 * 1024)
    if not isinstance(value, str):
        raise ValueError("invalid memory ceiling")
    match = re.fullmatch(r"([1-9][0-9]*)([KMGTPkmgpt])(?:i?B)?", value.strip())
    if not match:
        raise ValueError("invalid memory ceiling")
    scale = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4, "p": 1024**5}[match.group(2).lower()]
    return int(int(match.group(1)) * scale // (1024 * 1024))


def _duration_seconds(value: object) -> int:
    if isinstance(value, str) and value.strip().lower() in {"unlimited", "infinite", "infinity"}:
        return 3600
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ValueError("invalid walltime limit")
    if "-" in value:
        d, value = value.split("-", 1)
        days = int(d)
    else:
        days = 0
    parts = value.split(":")
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        raise ValueError("invalid walltime limit")
    h, m, s = map(int, parts)
    return days * 86400 + h * 3600 + m * 60 + s


def select_route(app: Path, config_path: Path, config: dict) -> dict:
    cli = shutil.which("hpc")
    if not cli:
        raise RuntimeError("hpc CLI unavailable")
    targets = config.get("targets", {})
    candidates = []
    probe_dir = app / "execution" / "route-probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    for target_id, target in targets.items():
        if not isinstance(target, dict) or target.get("resource_class") != "gpu" or target.get("backend") != "slurm":
            continue
        host = target.get("host")
        partitions = target.get("allowed_partitions") or ([target.get("partition")] if target.get("partition") else [])
        for partition in partitions:
            if not isinstance(host, str) or not isinstance(partition, str) or not partition:
                continue
            snapshot, proc = cli_json([cli, "probe", "--host", host, "--partition", partition, "--json", "--detail"], probe_dir)
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{target_id}-{partition}")
            (probe_dir / f"{safe_name}.stdout").write_text(proc.stdout)
            (probe_dir / f"{safe_name}.stderr").write_text(proc.stderr)
            if proc.returncode or not isinstance(snapshot, dict):
                continue
            limits = target.get("partition_limits", {}).get(partition)
            if not isinstance(limits, dict) or not limits.get("enabled"):
                continue
            eligible = []
            for node in snapshot.get("nodes", []):
                gpu_text = f"{node.get('gres','')} {node.get('features','')}".lower()
                model = "v100" if "v100" in gpu_text else "p100" if "p100" in gpu_text else None
                if (node.get("partition") == partition and model and node.get("gpu_capacity", 0) >= 1
                        and node.get("gpu_allocation_known") is True and node.get("gpu_available", 0) >= 1
                        and node.get("cpus") and node.get("memory_mb")):
                    eligible.append((node, model))
            if not eligible:
                continue
            queue_waiting = sum(int(row.get("count", 0)) for row in snapshot.get("queue", [])
                                if row.get("partition") == partition and row.get("state", "").lower() in {"pending", "configuring"})
            for node, model in eligible:
                try:
                    cpus = min(4, int(limits["max_cpus_per_task"]), int(node["cpus"]))
                    mem_mb = min(8192, _memory_mb(limits["max_memory_per_node"]), int(node["memory_mb"]))
                    part_info = next(p for p in snapshot["partitions"] if p.get("name") == partition)
                    wall_s = min(3600, _duration_seconds(limits["max_walltime"]), _duration_seconds(part_info["time_limit"]))
                except (KeyError, ValueError, TypeError):
                    continue
                if cpus < 1 or mem_mb < 1 or wall_s < 60:
                    continue
                tier = 0 if model == "v100" else 1
                candidates.append((tier, queue_waiting, -int(node["gpu_available"]), target_id, partition,
                                   {"target_id": target_id, "host": host, "partition": partition,
                                    "gpu_model": model, "probe_node": node["name"],
                                    "gpu_capacity": node["gpu_capacity"], "gpu_allocated": node["gpu_allocated"],
                                    "gpu_available": node["gpu_available"], "queue_waiting_jobs": queue_waiting,
                                    "resources": {"nodes": 1, "ntasks": 1, "cpus": cpus,
                                                  "memory_mb": mem_mb, "gpus": 1,
                                                  "walltime_minutes": max(1, wall_s // 60)},
                                    "snapshot": snapshot,
                                    "reason": f"Current detailed probe found {model.upper()} on {node['name']} with {node['gpu_available']} known available GPU(s); selected over other configured targets by model preference, then pending queue count and known availability."}))
    if not candidates:
        raise RuntimeError("no configured V100/P100 GPU target has known available capacity within its current probe and policy limits")
    selected = sorted(candidates, key=lambda row: row[:3])[0][-1]
    json_write(probe_dir / "selected-resource.json", {k: v for k, v in selected.items() if k != "snapshot"})
    json_write(probe_dir / "selected-probe.json", selected["snapshot"])
    selected["config_sha256"] = sha(config_path)
    return selected


def parse_elapsed(raw: object) -> float | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw
    days = 0
    if "-" in text:
        day, text = text.split("-", 1)
        if not day.isdigit():
            return None
        days = int(day)
    parts = text.split(":")
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        return None
    h, m, s = map(int, parts)
    if m >= 60 or s >= 60:
        return None
    return float(days * 86400 + h * 3600 + m * 60 + s)


def scheduler_receipt_matches(receipt: object, job_id: str, partition: str,
                              native_elapsed: object) -> bool:
    if not isinstance(receipt, dict) or receipt.get("JobIDRaw") != str(job_id):
        return False
    encoded, digest = receipt.get("sacct_rows_base64"), receipt.get("sacct_rows_sha256")
    if not isinstance(encoded, str) or not isinstance(digest, str):
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = raw.decode("utf-8", errors="strict")
    except (ValueError, UnicodeError):
        return False
    lines = decoded.splitlines()
    fields = lines[0].split("|") if len(lines) == 1 else []
    scheduler_elapsed = parse_elapsed(receipt.get("Elapsed"))
    return (hashlib.sha256(raw).hexdigest() == digest
            and len(fields) == 9 and fields[0] == str(job_id)
            and fields[1] == partition and receipt.get("Partition") == partition
            and fields[7] in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"}
            and fields[8] == str(receipt.get("ExitCode"))
            and scheduler_elapsed is not None
            and isinstance(native_elapsed, (int, float))
            and abs(scheduler_elapsed - float(native_elapsed)) <= 2.0)


def copy_file(source: Path, target: Path) -> bool:
    if source.is_file() and not source.is_symlink():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return True
    return False


class RecordedSubmissionError(RuntimeError):
    def __init__(self, message: str, run_record: dict, job_record: dict):
        super().__init__(message)
        self.run_record, self.job_record = run_record, job_record


def record_unresolved_submission(app: Path, out: Path, plan: dict, run: dict, job_name: str,
                                 resources: dict, remote_workdir: str, start_time: str,
                                 end_time: str, state: dict, returncode: int,
                                 stdout_text: str, stderr_text: str, tau_ps: float,
                                 parent_restart: Path | None) -> tuple[dict, dict]:
    phase = state.get("phase")
    status = "failed" if phase in {"SUBMISSION_REJECTED", "REMOTE_PREP_FAILED", "REMOTE_SYNC_FAILED"} else "unknown"
    start = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    end = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    elapsed = max(0.0, (end - start).total_seconds())
    handle = str(state.get("name") or job_name)
    missing = ["scheduler batch file", "scheduler stdout", "scheduler stderr"]
    json_write(out / "submit-failure-evidence.json", {"state": state, "returncode": returncode,
        "stdout": stdout_text, "stderr": stderr_text, "missing_sources": missing,
        "timing_basis": "client observation of submit CLI invocation, not scheduler allocation timing",
        "start_time": start_time, "end_time": end_time, "elapsed_seconds": elapsed})
    scheduler = {"schema": "case05-candidate-scheduler-record/v2", "origin": "candidate-submitted",
        "attempt_id": plan["attempt_id"], "run_id": run["run_id"], "job_id": handle,
        "job_id_kind": "hpc-local-handle; scheduler ID unavailable", "state": status,
        "requested_steps": run["steps"], "executed_steps": None, "dt_fs": DT_FS, "gpu_count": 1,
        "exit_code": None, "resources": resources, "allocation_id": None, "array_job": False,
        "elapsed_seconds": elapsed, "start_time": start_time, "end_time": end_time,
        "timing_basis": "client observation of submit CLI invocation, not scheduler allocation timing",
        "submission_phase": phase, "missing_sources": missing}
    scheduler_path = out / "scheduler-record.json"; json_write(scheduler_path, scheduler)
    files = {"scheduler_record": {"path": f"execution/{run['run_id']}/scheduler-record.json",
                                  "sha256": sha(scheduler_path)}}
    row = {"run_id": run["run_id"], "T_K": TEMPERATURE, "seed": run["seed"], "stage": run["stage"],
        "status": status, "requested_steps": run["steps"], "executed_steps": None, "dt_fs": DT_FS,
        "gpu_count": 1, "plan_sha256": plan["plan_sha256"], "job_id": handle, "allocation_id": None,
        "native_artifacts": {}, "control_setting": f"nvt_Tdamp_ps={tau_ps:g}",
        "parent_checkpoint_sha256": sha(parent_restart) if parent_restart else None,
        "remote_workdir": remote_workdir, "submission_phase": phase}
    job = {"attempt_id": plan["attempt_id"], "run_id": run["run_id"], "job_id": handle,
        "stage": run["stage"], "status": status, "plan_sha256": plan["plan_sha256"],
        "requested_steps": run["steps"], "executed_steps": None, "dt_fs": DT_FS, "gpu_count": 1,
        "exit_code": None, "allocation_id": None, "array_job": False, "resources": resources,
        "elapsed_seconds": elapsed, "start_time": start_time, "end_time": end_time, "files": files}
    json_write(out / "attempt.json", {"run": row, "job": job})
    return row, job


def persist_ledger(app: Path, plan: dict, runs: list[dict], jobs: list[dict]) -> None:
    charged_steps = sum(r["requested_steps"] if r["status"] != "complete" else r["executed_steps"] for r in runs)
    charged_ps = charged_steps * DT_FS / 1000
    ledger = {"schema": "case05-author-cumulative-run-ledger/v1", "attempt_id": plan["attempt_id"],
              "plan_sha256": plan["plan_sha256"], "runs": runs, "charged_steps": int(charged_steps),
              "charged_ps": float(charged_ps), "author_probe_frame_ids": []}
    ledger_path = app / "run-ledger.json"
    json_write(ledger_path, ledger)
    order = {"schema": "case05-candidate-execution-order/v1", "attempt_id": plan["attempt_id"],
             "run_ids": [r["run_id"] for r in runs]}
    order_path = app / "execution" / "execution-order.json"
    json_write(order_path, order)
    complete_refs = bool(jobs) and len(jobs) == len(runs) and all(isinstance(job.get("files"), dict)
                        and set(job["files"]) == {"batch", "stdout", "stderr", "scheduler_record"}
                        for job in jobs)
    receipt = {"schema": "case05-candidate-execution-provenance/v2",
               "origin": "candidate-submitted-crosschecked" if complete_refs else "candidate-submission-evidence-incomplete",
               "attempt_id": plan["attempt_id"],
              "evidence_mode": os.environ.get("CCB_ANSWER_MODE", "oracle"),
               "ledger_sha256": sha(ledger_path), "order_sha256": sha(order_path), "jobs": jobs}
    json_write(app / "execution" / "execution-receipt.json", receipt)


def source_stage(app: Path, run_dir: Path, run: dict, paths: dict[str, Path],
                 start_kind: str, parent_restart: Path | None, tau_ps: float, plan_hash: str,
                 decision_commit: Path | None, decision_commit_sha256: str | None) -> Path:
    src = run_dir / "submitted"
    src.mkdir(parents=True, exist_ok=False)
    (src / "inputs" / "models").mkdir(parents=True)
    if start_kind == "data":
        (src / "inputs").mkdir(exist_ok=True)
        shutil.copy2(paths["data"], src / "inputs/strc.lmp")
    shutil.copy2(paths["model.000"], src / "inputs/models/model.000.pb")
    if start_kind == "restart":
        if parent_restart is None or not parent_restart.is_file():
            raise RuntimeError(f"restart source unavailable for {run['run_id']}")
        shutil.copy2(parent_restart, src / "checkpoint.restart")
    if decision_commit is not None and decision_commit.is_file():
        shutil.copy2(decision_commit, src / "decision-commit.json")
    (src / "in.lammps").write_text(lammps_input(run, run_dir, start_kind, tau_ps))
    source_files = [p for p in src.rglob("*") if p.is_file() and p.name != "submitted-source-manifest.json"]
    oversized_sources = [p.relative_to(src).as_posix() for p in source_files if p.stat().st_size > 512 * 1024**2]
    if oversized_sources:
        raise RuntimeError(f"submitted source exceeds the per-remote-file 512 MiB cap: {oversized_sources}")
    source_manifest = {p.relative_to(src).as_posix(): sha(p) for p in sorted(source_files)}
    json_write(src / "submitted-source-manifest.json", {
        "schema": "case05-submitted-source-manifest/v1", "run_id": run["run_id"],
        "plan_sha256": plan_hash, "decision_commit_sha256": decision_commit_sha256,
        "files": source_manifest})
    source_manifest_sha256 = sha(src / "submitted-source-manifest.json")
    (src / "run-native.sh").write_text(batch_script(run["run_id"], plan_hash,
        decision_commit_sha256, source_manifest_sha256))
    (src / "run-native.sh").chmod(0o755)
    json_write(src / "run-manifest.json", {"run_id": run["run_id"], "stage": run["stage"],
        "seed": run["seed"], "requested_steps": run["steps"], "dt_fs": DT_FS,
        "input_sha256": sha(src / "in.lammps"), "restart_parent_sha256": sha(parent_restart) if parent_restart else None,
        "model_sha256": sha(src / "inputs/models/model.000.pb"),
        "plan_sha256": plan_hash, "decision_commit_sha256": decision_commit_sha256,
        "submitted_source_manifest_sha256": source_manifest_sha256,
        "run_native_script_sha256": sha(src / "run-native.sh")})
    return src


def execute_run(app: Path, plan: dict, paths: dict[str, Path], run: dict,
                start_kind: str, parent_restart: Path | None, tau_ps: float,
                selection: dict, config_path: Path) -> tuple[dict, dict]:
    cli = shutil.which("hpc")
    if not cli:
        raise RuntimeError("hpc CLI unavailable")
    run_id = run["run_id"]
    out = app / "execution" / run_id
    out.mkdir(parents=True, exist_ok=False)
    decision_commit = app / "execution" / "decision-commit.json"
    decision_hash = sha(decision_commit) if decision_commit.is_file() else None
    src = source_stage(app, out, run, paths, start_kind, parent_restart, tau_ps,
                       plan["plan_sha256"], decision_commit if decision_hash else None, decision_hash)
    # CLI consumes the selected operator configuration from this attempt directory.
    shutil.copy2(config_path, out / "submit-job.json")
    job_name = f"r05-{plan['attempt_id'][:8]}-{run_id}"
    if not Path(REMOTE_ATTEMPT_ROOT).is_absolute() or any(x in REMOTE_ATTEMPT_ROOT.split("/") for x in ("..", ".")):
        raise RuntimeError("CCB_REMOTE_ATTEMPT_ROOT must be an absolute, traversal-free configured path")
    remote_root = f"{REMOTE_ATTEMPT_ROOT.rstrip('/')}/{plan['attempt_id']}"
    remote_workdir = f"{remote_root}/{run_id}"
    probe, probe_proc = cli_json([cli, "probe", "--host", selection["host"], "--partition", selection["partition"], "--json", "--detail"], out)
    (out / "probe.stdout").write_text(probe_proc.stdout)
    (out / "probe.stderr").write_text(probe_proc.stderr)
    if probe_proc.returncode != 0 or probe is None or probe.get("host") != selection["host"] or selection["partition"] not in [x.get("name") for x in probe.get("partitions", []) if isinstance(x, dict)]:
        raise RuntimeError("read-only selected GPU route probe failed or did not return the requested partition")
    json_write(out / "probe.json", probe)
    res = selection["resources"]
    wall_s = res["walltime_minutes"] * 60
    wall_arg = f"{wall_s // 3600:02d}:{(wall_s % 3600) // 60:02d}:{wall_s % 60:02d}"
    submit = [cli, "submit", "--target", selection["target_id"], "--name", job_name, "--cmd", "./run-native.sh",
              "--reason", selection["reason"] + f" Requested one GPU, {res['cpus']} CPUs, {res['memory_mb']} MiB host RAM, one node, within the declared per-job cap; retains native LAMMPS trajectory.",
              "--probe-snapshot", str(out / "probe.json"), "--snapshot-sha256", str(probe.get("snapshot_sha256", "")),
              "--workdir", remote_workdir, "--src", str(src), "--partition", selection["partition"], "--nodes", "1",
              "--ntasks", "1", "--cpus", str(res["cpus"]), "--mem", f"{res['memory_mb']}M", "--gpus", "1", "--time", wall_arg]
    dry, dry_proc = cli_json(submit + ["--dry-run"], out)
    (out / "dry-run.stdout").write_text(dry_proc.stdout)
    (out / "dry-run.stderr").write_text(dry_proc.stderr)
    if dry_proc.returncode != 0 or dry is None or dry.get("plan_sha256") is None:
        raise RuntimeError("hpc dry-run rejected the requested route/resources/workdir")
    json_write(out / "ikkem-plan.json", dry)
    t_submit = iso_now()
    submitted, sub_proc = cli_json(submit, out)
    (out / "submit.stdout").write_text(sub_proc.stdout)
    (out / "submit.stderr").write_text(sub_proc.stderr)
    if sub_proc.returncode != 0 or submitted is None or not submitted.get("job_id"):
        state_path = out / ".submit-job" / f"{job_name}.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        state_job_id = state.get("job_id")
        if state_job_id:
            submitted = {"job_id": str(state_job_id), "state": state.get("phase"),
                         "state_path": str(state_path)}
        else:
            ended = iso_now()
            recorded, job_record = record_unresolved_submission(app, out, plan, run, job_name,
                {"nodes": 1, "cpus": res["cpus"], "memory_mb": res["memory_mb"],
                 "gpus": 1, "walltime_minutes": res["walltime_minutes"]}, remote_workdir,
                t_submit, ended, state, sub_proc.returncode, sub_proc.stdout, sub_proc.stderr,
                tau_ps, parent_restart)
            raise RecordedSubmissionError("hpc submission failed or is unresolved; no retry was attempted",
                                          recorded, job_record)
    json_write(out / "submit-result.json", submitted)
    job_id = str(submitted["job_id"])
    # The native CLI owns status polling and collection; no direct SSH/rsync/sbatch is used here.
    wait, wait_proc = cli_json([cli, "wait", "--job", job_name, "--poll", "15", "--timeout", "3600"], out)
    (out / "wait.stdout").write_text(wait_proc.stdout)
    (out / "wait.stderr").write_text(wait_proc.stderr)
    succeeded = wait_proc.returncode == 0 and isinstance(wait, dict) and wait.get("state") == "completed" and wait.get("exit_code") == 0
    collected_dir = out / "collected"
    collect_args = [cli, "collect", "--job", job_name, "--dest", str(collected_dir)]
    if not succeeded:
        collect_args.append("--allow-unsuccessful")
    collected, collect_proc = cli_json(collect_args, out)
    (out / "collect.stdout").write_text(collect_proc.stdout)
    (out / "collect.stderr").write_text(collect_proc.stderr)
    if collect_proc.returncode != 0 or not collected_dir.is_dir():
        succeeded = False
    collected_files = [p for p in collected_dir.rglob("*") if p.is_file() and not p.is_symlink()] if collected_dir.is_dir() else []
    oversized_files = [p.relative_to(collected_dir).as_posix() for p in collected_files
                       if p.stat().st_size > 512 * 1024**2]
    prior_collected_bytes = sum(p.stat().st_size for run_root in (app / "execution").iterdir()
                                if run_root.is_dir() and run_root != out
                                for p in (run_root / "collected").rglob("*")
                                if p.is_file() and not p.is_symlink())
    collected_bytes = sum(p.stat().st_size for p in collected_files)
    collection_limit_ok = not oversized_files and prior_collected_bytes + collected_bytes <= 4 * 1024**3
    if not collection_limit_ok:
        succeeded = False
    timing_path = collected_dir / "native-timing.json"
    timing = json.loads(timing_path.read_text()) if timing_path.is_file() else {}
    log_file = collected_dir / "log.lammps"
    step_matches = re.findall(r"for\s+(\d+)\s+steps\s+with", log_file.read_text(errors="replace")) if log_file.is_file() else []
    executed = int(step_matches[-1]) if step_matches else int(timing.get("executed_steps", 0))
    if succeeded and executed != run["steps"]:
        succeeded = False
    status = "complete" if succeeded else ("failed" if wait and wait.get("state") in {"failed", "cancelled"} else "unknown")
    # Bring native evidence into the canonical execution/<run_id>/ tree.
    for name in ("in.lammps", "log.lammps", "trajectory.dump", "initial.dump", "state.restart",
                 "native-timing.json", "runtime-evidence.txt", "engine.stdout", "engine.stderr",
                 "run-manifest.json", "submitted-source-manifest.json"):
        copy_file(collected_dir / name, out / name)
    script = collected_dir / "submit.sh"
    if not script.is_file():
        # The CLI persists the exact generated scheduler script in its local state.
        state = Path(out) / ".submit-job" / f"{job_name}.json"
        if state.is_file():
            state_doc = json.loads(state.read_text())
            saved_script = state_doc.get("plan", {}).get("script")
            if isinstance(saved_script, str) and saved_script:
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text(saved_script)
    if script.is_file() and script.stat().st_size:
        copy_file(script, out / "batch.txt")
    logs = list((collected_dir / "logs").glob("*.out")) if (collected_dir / "logs").is_dir() else []
    errlogs = list((collected_dir / "logs").glob("*.err")) if (collected_dir / "logs").is_dir() else []
    missing_scheduler_files = []
    if not (logs and copy_file(logs[0], out / "stdout.txt")):
        missing_scheduler_files.append("stdout")
    if not (errlogs and copy_file(errlogs[0], out / "stderr.txt")):
        missing_scheduler_files.append("stderr")
    if not (out / "batch.txt").is_file():
        missing_scheduler_files.append("batch")
    json_write(out / "scheduler-collection.json", {
        "stdout_source": str(logs[0].name) if logs else None,
        "stderr_source": str(errlogs[0].name) if errlogs else None,
        "batch_source": "collected/submit.sh" if script.is_file() and script.stat().st_size else None,
        "missing_sources": missing_scheduler_files,
        "collected_bytes": collected_bytes,
        "aggregate_collected_bytes_including_previous_runs": prior_collected_bytes + collected_bytes,
        "oversized_files": oversized_files,
        "collection_limits_passed": collection_limit_ok,
        "note": "Missing scheduler artifacts are not replaced with CLI wait/collect output."})
    if not collection_limit_ok:
        missing_scheduler_files.append("collection_size_limit")
    if missing_scheduler_files:
        status = "unknown"
    required = {"input": out / "in.lammps", "log": out / "log.lammps",
                "trajectory": out / "trajectory.dump", "restart": out / "state.restart"}
    artifacts = {key: {"path": p.relative_to(app).as_posix(), "sha256": sha(p)}
                 for key, p in required.items() if p.is_file() and p.stat().st_size > 0}
    missing_native = sorted(set(required) - set(artifacts))
    runtime_evidence_path = out / "runtime-evidence.txt"
    runtime_evidence_text = runtime_evidence_path.read_text(errors="replace") if runtime_evidence_path.is_file() else ""
    gpu_query_observed = bool(re.search(r"(?m)^.+,\s*GPU-[A-Za-z0-9-]+,", runtime_evidence_text))
    if missing_native or not gpu_query_observed:
        status = "unknown"
    # Preserve truthful timing from the native trap or the CLI's scheduler receipt.
    receipt_info = (wait or {}).get("receipt") if isinstance(wait, dict) else (submitted or {}).get("receipt")
    receipt_valid = scheduler_receipt_matches(receipt_info, job_id, selection["partition"], timing.get("elapsed_seconds"))
    if status in {"complete", "failed"} and not receipt_valid:
        status = "unknown"
    if isinstance(wait, dict):
        json_write(out / "wait-result.json", wait)
        if wait.get("resource_evidence") is not None:
            json_write(out / "resource-evidence.json", wait["resource_evidence"])
    json_write(out / "collect-result.json", collected if isinstance(collected, dict) else {
        "returncode": collect_proc.returncode, "stdout": collect_proc.stdout, "stderr": collect_proc.stderr})
    elapsed = timing.get("elapsed_seconds")
    start_time, end_time = timing.get("start_time"), timing.get("end_time")
    if status == "complete" and not (isinstance(elapsed, (int, float)) and isinstance(start_time, str) and isinstance(end_time, str)):
        status = "unknown"
    exit_code = 0 if status == "complete" else None
    if isinstance(wait, dict) and isinstance(wait.get("exit_code"), int):
        exit_code = wait["exit_code"]
    elif status != "complete" and isinstance(receipt_info, dict):
        ec = receipt_info.get("ExitCode")
        if isinstance(ec, str) and re.match(r"^\d+:", ec):
            exit_code = int(ec.split(":", 1)[0])
    resources = {"nodes": 1, "cpus": res["cpus"], "memory_mb": res["memory_mb"],
                 "gpus": 1, "walltime_minutes": res["walltime_minutes"]}
    allocation = job_id if receipt_valid else None
    scheduler = {"schema": "case05-candidate-scheduler-record/v2", "origin": "candidate-submitted",
                 "attempt_id": plan["attempt_id"], "run_id": run_id, "job_id": job_id,
                 "state": status, "requested_steps": run["steps"], "executed_steps": executed if executed else None,
                 "dt_fs": DT_FS, "gpu_count": 1, "exit_code": exit_code, "resources": resources,
                 "allocation_id": allocation, "array_job": False,
                 "elapsed_seconds": float(elapsed) if isinstance(elapsed, (int, float)) else None,
                 "start_time": start_time, "end_time": end_time,
                 "scheduler_cli_wait": wait, "scheduler_cli_receipt": receipt_info,
                 "scheduler_collection": json.loads((out / "scheduler-collection.json").read_text()),
                 "resource_evidence": (wait or {}).get("resource_evidence") if isinstance(wait, dict) else None,
                 "missing_native_artifacts": missing_native,
                 "gpu_query_observed_in_native_runtime": gpu_query_observed,
                 "scheduler_raw_receipt_validated": receipt_valid}
    for kind, file_name in (("batch", "batch.txt"), ("stdout", "stdout.txt"),
                            ("stderr", "stderr.txt")):
        file_path = out / file_name
        if file_path.is_file():
            scheduler[kind] = {"path": f"execution/{run_id}/{file_name}", "sha256": sha(file_path)}
    scheduler_path = out / "scheduler-record.json"
    files = {kind: {"path": f"execution/{run_id}/{name}", "sha256": sha(out / name)}
             for kind, name in (("batch", "batch.txt"), ("stdout", "stdout.txt"), ("stderr", "stderr.txt"))
             if (out / name).is_file()}
    # The scheduler record binds the three transport files; its own raw hash is in the receipt.
    scheduler["files"] = {kind: files[kind] for kind in ("batch", "stdout", "stderr") if kind in files}
    json_write(scheduler_path, scheduler)
    files["scheduler_record"] = {"path": f"execution/{run_id}/scheduler-record.json", "sha256": sha(scheduler_path)}
    job = {"attempt_id": plan["attempt_id"], "run_id": run_id, "job_id": job_id, "stage": run["stage"],
           "status": status, "plan_sha256": plan["plan_sha256"], "requested_steps": run["steps"],
           "executed_steps": executed if executed else None, "dt_fs": DT_FS, "gpu_count": 1,
           "exit_code": exit_code, "allocation_id": allocation, "array_job": False,
           "resources": resources, "elapsed_seconds": float(elapsed) if isinstance(elapsed, (int, float)) else None,
           "start_time": start_time,
           "end_time": end_time, "files": files}
    ledger_run = {"run_id": run_id, "T_K": TEMPERATURE, "seed": run["seed"], "stage": run["stage"],
                  "status": status, "requested_steps": run["steps"], "executed_steps": executed if executed else None,
                  "dt_fs": DT_FS, "gpu_count": 1, "plan_sha256": plan["plan_sha256"], "job_id": job_id,
                  "allocation_id": allocation, "native_artifacts": artifacts,
                  "control_setting": f"nvt_Tdamp_ps={tau_ps:g}",
                  "parent_checkpoint_sha256": sha(parent_restart) if parent_restart else None,
                  "remote_workdir": remote_workdir}
    json_write(out / "attempt.json", {"run": ledger_run, "job": job})
    return ledger_run, job


def execute_reserved_attempt(app: Path, plan: dict, paths: dict[str, Path], run: dict,
                             start_kind: str, parent_restart: Path | None, tau_ps: float,
                             selection: dict, config_path: Path,
                             runs: list[dict], jobs: list[dict]) -> tuple[dict, dict]:
    reservation = {"run_id": run["run_id"], "T_K": TEMPERATURE, "seed": run["seed"],
        "stage": run["stage"], "status": "unknown", "requested_steps": run["steps"],
        "executed_steps": None, "dt_fs": DT_FS, "gpu_count": 1, "plan_sha256": plan["plan_sha256"],
        "job_id": None, "allocation_id": None, "native_artifacts": {},
        "control_setting": f"nvt_Tdamp_ps={tau_ps:g}",
        "parent_checkpoint_sha256": sha(parent_restart) if parent_restart else None,
        "reservation_state": "persisted before stage setup/submission; unresolved attempts charge full requested steps"}
    runs.append(reservation)
    persist_ledger(app, plan, runs, jobs)
    json_write(app / "execution" / "execution-status.json", {
        "status": "RUNNING", "attempt_id": plan["attempt_id"],
        "plan_sha256": plan["plan_sha256"], "active_run_id": run["run_id"],
        "active_run_requested_steps": run["steps"],
        "charged_steps_if_unresolved": sum(r["requested_steps"] if r["status"] != "complete" else r["executed_steps"] for r in runs),
        "note": "Reservation is persisted before setup or submission; unresolved/failed work is charged in full."})
    try:
        row, job = execute_run(app, plan, paths, run, start_kind, parent_restart,
                               tau_ps, selection, config_path)
    except RecordedSubmissionError as exc:
        runs[-1] = exc.run_record
        jobs.append(exc.job_record)
        persist_ledger(app, plan, runs, jobs)
        raise
    except Exception as exc:
        runs[-1]["failure_reason"] = str(exc)
        runs[-1]["reservation_state"] = "pre-submitted or submitted work failed without a returned terminal record; full requested steps remain charged"
        persist_ledger(app, plan, runs, jobs)
        raise
    runs[-1] = row
    jobs.append(job)
    persist_ledger(app, plan, runs, jobs)
    return row, job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("APP", "/app")))
    args = parser.parse_args()
    app = args.app.resolve()
    evidence_mode = os.environ.get("CCB_ANSWER_MODE")
    if evidence_mode not in {"agent", "oracle"}:
        raise RuntimeError("CCB_ANSWER_MODE must be agent or oracle; solve.sh defaults reference execution to oracle")
    paths = inputs(app)
    attempt = uuid.uuid4().hex
    global REMOTE_ENV_SH, REMOTE_ATTEMPT_ROOT
    site_config, config_doc = submit_config(app)
    site = config_doc.get("bench07_reference", {}).get("case05", {})
    REMOTE_ENV_SH = REMOTE_ENV_SH or site.get("environment_sh", "")
    REMOTE_ATTEMPT_ROOT = REMOTE_ATTEMPT_ROOT or site.get("remote_attempt_root", "")
    if not isinstance(REMOTE_ENV_SH, str) or not isinstance(REMOTE_ATTEMPT_ROOT, str) or not REMOTE_ENV_SH.startswith("/") or not REMOTE_ATTEMPT_ROOT.startswith("/"):
        raise RuntimeError("configure case05 environment_sh and remote_attempt_root before the first run")
    plan = freeze_plan(app, paths, attempt, site_config)
    print(f"Frozen precommit: {app / 'plan.json'} sha256={plan['plan_sha256']}", flush=True)
    (app / "execution").mkdir()
    try:
        selection = select_route(app, site_config, config_doc)
    except Exception as exc:
        json_write(app / "execution" / "execution-status.json", {
            "status": "NO_RUN_STARTED", "phase": "live-resource-probe",
            "attempt_id": attempt, "plan_sha256": plan["plan_sha256"],
            "reason": str(exc), "native_runs": 0})
        raise
    json_write(app / "execution" / "resource-selection.json", {k: v for k, v in selection.items() if k != "snapshot"})
    shutil.copy2(site_config, app / "execution" / "site-submit-config.json")
    runs: list[dict] = []; jobs: list[dict] = []
    specs = {r["run_id"]: r for r in plan["attempts"]}
    checkpoint = None
    try:
        for run_id in ("pilot01", "pilot02"):
            row, job = execute_reserved_attempt(app, plan, paths, specs[run_id], "data", None,
                0.1, selection, site_config, runs, jobs)
            if row["status"] != "complete":
                raise RuntimeError(f"{run_id} did not complete; its reservation remains charged")
            if run_id == "pilot01":
                checkpoint = app / row["native_artifacts"]["restart"]["path"]
        pilot01 = pilot_signal(app / "execution/pilot01", app)
        pilot02 = pilot_signal(app / "execution/pilot02", app)
        retention = [pilot01["fixed_cohort_retention_0p5ps"], pilot02["fixed_cohort_retention_0p5ps"]]
        rel_diff = abs(retention[0] - retention[1]) / max(abs(np.mean(retention)), 1e-12)
        confirm_bounds = [max(0.0, min(retention) - 0.15), min(1.0, max(retention) + 0.15)]
        tempdev = [abs((x["mean_thermo_temperature_K"] or TEMPERATURE) - TEMPERATURE) for x in (pilot01, pilot02)]
        adaptive = dict(specs["adaptive01"])
        adapt_parent_id = None
        if rel_diff > .15:
            adaptive["seed"] = 63423
            adapt_start, adapt_restart = "data", None
            adaptive_choice = "fresh third-seed 5 ps tranche because pilot shell retention differs by more than 15%"
        else:
            parent = 0 if tempdev[0] <= tempdev[1] else 1
            parent_id = ("pilot01", "pilot02")[parent]
            adapt_parent_id = parent_id
            adapt_start = "restart"
            adapt_restart = app / f"execution/{parent_id}/state.restart"
            adaptive["seed"] = specs[parent_id]["seed"]
            adaptive_choice = f"extend {parent_id} 5 ps because pilot retention difference is at most 15%; lower pilot temperature deviation"
        trace = {"schema": "reline05-decision-trace/v1", "attempt_id": attempt,
                 "frozen_plan_sha256": plan["plan_sha256"], "decisions": [{
                     "decision_id": "pilot-adaptation", "alternatives": [
                         {"name": "extend-pilot", "budget_ps": 5, "information_value": "longer current and shell correlation from one seed", "risk": "shared starting configuration"},
                         {"name": "fresh-seed", "budget_ps": 5, "information_value": "independent stochastic velocity draw on supplied structure", "risk": "not an independently equilibrated configuration"}],
                     "pilot_evidence": {"pilot01": pilot01, "pilot02": pilot02,
                                        "relative_retention_difference": float(rel_diff),
                                        "frozen_threshold": .15},
                     "chosen": "fresh-seed" if rel_diff > .15 else "extend-pilot",
                     "prediction": {"observable": "fixed-cohort choline-chloride retention at 0.5 ps after the precommitted 1.0-ps exclusion",
                                    "confirmation_interval": confirm_bounds,
                                    "test": "The fresh-seed confirmation mean must fall inside the pilot mean range expanded by 0.15 absolute; this is a descriptive falsification check, not a confidence interval."},
                     "followup_run_ids": ["adaptive01"], "selected_action": adaptive_choice,
                     "selected_at": iso_now()}]}
        decision_commit = {"schema": "reline05-adaptive-decision-commit/v1", "attempt_id": attempt,
                           "frozen_plan_sha256": plan["plan_sha256"],
                           "decision": trace["decisions"][0]}
        commit_path = app / "execution" / "decision-commit.json"
        json_write(commit_path, decision_commit)
        trace["decision_commit_sha256"] = sha(commit_path)
        json_write(app / "decision-trace.json", trace)
        parent_hash = sha(checkpoint) if checkpoint and checkpoint.is_file() else None
        for run_id, tau in (("control_tau050", 0.05), ("control_tau200", 0.2)):
            row, job = execute_reserved_attempt(app, plan, paths, specs[run_id], "restart", checkpoint,
                tau, selection, site_config, runs, jobs)
            row["control_parameters"] = {"paired_parent_run_id": "pilot01", "parent_checkpoint_sha256": parent_hash}
            row["parent_checkpoint_sha256"] = parent_hash
            persist_ledger(app, plan, runs, jobs)
            if row["status"] != "complete":
                raise RuntimeError(f"{run_id} failed; its reservation remains charged")
        row, job = execute_reserved_attempt(app, plan, paths, adaptive, adapt_start, adapt_restart,
            0.1, selection, site_config, runs, jobs)
        if row["status"] != "complete":
            raise RuntimeError("adaptive tranche failed; reserved steps remain charged")
        if adapt_parent_id is not None:
            adaptive_dir = app / "execution" / "adaptive01"
            extension_manifest = combine_extension(
                app / "execution" / adapt_parent_id / "trajectory.dump",
                adaptive_dir / "trajectory.dump",
                adaptive_dir / "trajectory-analysis.dump")
            extension_manifest.update({"parent_run_id": adapt_parent_id,
                "parent_checkpoint_sha256": row["parent_checkpoint_sha256"],
                "analysis_excluded_initial_time_ps": EXCLUDED_INITIAL_PS})
            json_write(adaptive_dir / "trajectory-analysis-manifest.json", extension_manifest)
        row, job = execute_reserved_attempt(app, plan, paths, specs["confirmation01"], "data", None,
            0.1, selection, site_config, runs, jobs)
        if row["status"] != "complete":
            raise RuntimeError("fresh-seed confirmation failed; its reservation remains charged")
        confirmation_signal = pilot_signal(app / "execution/confirmation01", app)
        trace["confirmation_validation"] = {
            "run_id": "confirmation01", "seed": specs["confirmation01"]["seed"],
            "observed_fixed_cohort_retention_0p5ps": confirmation_signal["fixed_cohort_retention_0p5ps"],
            "predeclared_interval": confirm_bounds,
            "prediction_test_passed": confirm_bounds[0] <= confirmation_signal["fixed_cohort_retention_0p5ps"] <= confirm_bounds[1],
            "note": "Confirmation did not influence cutoff, excluded time, windows, or the pilot-selected adaptive branch."}
        json_write(app / "decision-trace.json", trace)
        results = {}; all_series = {}; topology = None
        for row in runs:
            item, extra = analyze_run(app / "execution" / row["run_id"], plan)
            results[row["run_id"]] = item
            all_series[row["run_id"]] = extra["series"]
            if topology is None:
                topology = extra["topology"]
        results_path = app / "results.json"
        json_write(results_path, {"schema": "reline05-native-results/v1", "runs": results,
                                  "decision_scope": "finite 363 K trajectories only; no equilibrium DC conductivity claim"})
        json_write(app / "topology.json", topology)
        # NPZ keys are namespaced by run to retain the raw computed series per trajectory.
        np.savez_compressed(app / "correlations.npz", **{
            f"{rid}__{key}": value for rid, series in all_series.items() for key, value in series.items()})
        nc_means = {}
        for run_id in ("pilot01", "pilot02", "adaptive01", "confirmation01"):
            fixed = np.asarray(results[run_id]["pair_results"]["choline__chloride"]["NC_fixed_origin_normalized_velocity_correlation"])
            refresh = np.asarray(results[run_id]["pair_results"]["choline__chloride"]["NC_refreshed_normalized_velocity_correlation"])
            nc_means[run_id] = {"fixed_0p1_to_0p5_ps": float(np.mean(fixed[10:51])),
                                "refreshed_0p1_to_0p5_ps": float(np.mean(refresh[10:51]))}
        pilot_sign = [nc_means[x]["fixed_0p1_to_0p5_ps"] for x in ("pilot01", "pilot02")]
        shell_status = "supported" if all(x > 0 for x in pilot_sign) else "contradicted" if all(x <= 0 for x in pilot_sign) else "inconclusive"
        plateau_changes = []
        plateau_sign_stable = True
        for run_id in ("pilot01", "pilot02", "adaptive01", "confirmation01"):
            windows = results[run_id]["windows"]
            if not all(key in windows for key in ("0.5_ps", "1_ps")):
                plateau_sign_stable = False
                continue
            a = windows["0.5_ps"]["integral_current_total_e2_A2_ps-1"]
            b = windows["1_ps"]["integral_current_total_e2_A2_ps-1"]
            plateau_changes.append(abs(b-a) / max(abs(a), abs(b), 1e-30))
            plateau_sign_stable &= a == 0 or b == 0 or np.sign(a) == np.sign(b)
        plateau_status = "supported" if len(plateau_changes) == 4 and max(plateau_changes) <= .20 and plateau_sign_stable else "contradicted" if any(x > .50 for x in plateau_changes) or not plateau_sign_stable else "inconclusive"
        control_nc = {rid: float(np.mean(np.asarray(results[rid]["pair_results"]["choline__chloride"]["NC_fixed_origin_normalized_velocity_correlation"])[10:51]))
                      for rid in ("control_tau050", "control_tau200")}
        control_gk = {rid: results[rid]["windows"].get("0.5_ps", {}).get("integral_current_total_e2_A2_ps-1")
                      for rid in ("control_tau050", "control_tau200")}
        control_comparison = {"NC_fixed_shell_0p1_to_0p5_ps": control_nc,
                              "NC_difference_tau050_minus_tau200": control_nc["control_tau050"] - control_nc["control_tau200"],
                              "GK_0p5ps": control_gk,
                              "GK_difference_tau050_minus_tau200": control_gk["control_tau050"] - control_gk["control_tau200"],
                              "shared_checkpoint_sha256": parent_hash}
        gamma_runs = ("pilot01", "pilot02", "adaptive01", "confirmation01")
        gamma_rows = [results[rid]["windows"].get("0.5_ps", {}).get("gamma_window_total_over_self") for rid in gamma_runs]
        gamma_window_comparison = {rid: {window: {
            "gamma_total_over_self": results[rid]["windows"].get(window, {}).get("gamma_window_total_over_self"),
            "total_integral_e2_A2_ps-1": results[rid]["windows"].get(window, {}).get("integral_current_total_e2_A2_ps-1"),
            "self_integral_e2_A2_ps-1": results[rid]["windows"].get(window, {}).get("integral_current_self_e2_A2_ps-1")}
            for window in ("0.5_ps", "1_ps")} for rid in gamma_runs}
        gamma_status = "supported" if all(isinstance(x, (int, float)) and math.isfinite(x) for x in gamma_rows) else "inconclusive"
        claims = {
            "short_time_shell_signal": {"status": shell_status,
                "scope": "positive/negative normalized fixed-origin choline-chloride shell velocity correlation averaged over 0.1-0.5 ps after 1.0-ps exclusion, at 363 K",
                "evidence": ["correlations.npz", "results.json"],
                "reason": f"Pilot means are {pilot_sign}; refreshed means are {[nc_means[x]['refreshed_0p1_to_0p5_ps'] for x in ('pilot01','pilot02')]}. This is a finite-window shell-conditioned velocity signal, not stable ion pairing."},
            "GK_plateau": {"status": plateau_status,
                "scope": "finite-window 0.5-1.0 ps Green-Kubo integral stability in pilots, adaptive tranche, and held-out confirmation only",
                "evidence": ["correlations.npz", "results.json"],
                "reason": f"Observed relative changes are {plateau_changes}; sign stable={plateau_sign_stable}. Even a supported finite-window plateau is not equilibrium DC conductivity."},
            "gamma_interpretation": {"status": gamma_status,
                "scope": "gamma_window equals total/self ionic-current Green-Kubo integral ratio over the identical finite window and origins",
                "evidence": ["plan.json", "correlations.npz", "results.json"],
                "reason": f"The pilot/adaptive/confirmation gamma values at 0.5 and 1.0 ps, with numerator and self denominator, are {gamma_window_comparison}. Large changes when the self integral is small are denominator-sensitive finite-window estimates, not ion-pair fractions or equilibrium properties."},
        }
        json_write(app / "decision.json", {"claims": claims,
            "paired_control_comparison": control_comparison,
            "gamma_window_comparison": gamma_window_comparison,
            "next_action": {"priority": "run at least three independently initialized 363-K trajectories of 50 ps each, retaining the same COM ionic current and fixed-shell observables",
                            "discriminates": ["a true slow collective-current tail", "a finite-time cancellation that creates a false plateau"],
                            "expected_information_gain": "separate seed-to-seed variance from within-trajectory tail drift; assess plateau stability across the 1-10 ps windows"},
            "expected_information_gain": "The adaptive tranche targets the observed pilot seed disagreement; held-out confirmation evaluates its predeclared retention prediction without selecting analysis windows."})
        pilot_retention = {"pilot01": pilot01["fixed_cohort_retention_0p5ps"],
                           "pilot02": pilot02["fixed_cohort_retention_0p5ps"]}
        confirmation_retention = confirmation_signal["fixed_cohort_retention_0p5ps"]
        confirmation_prediction = trace["confirmation_validation"]["prediction_test_passed"]
        fixed_refresh_diffs = {rid: nc_means[rid]["fixed_0p1_to_0p5_ps"] - nc_means[rid]["refreshed_0p1_to_0p5_ps"]
                               for rid in nc_means}
        gk_differences = {rid: (results[rid]["windows"]["1_ps"]["integral_current_total_e2_A2_ps-1"]
                                - results[rid]["windows"]["0.5_ps"]["integral_current_total_e2_A2_ps-1"])
                          for rid in ("pilot01", "pilot02", "adaptive01", "confirmation01")
                          if all(key in results[rid]["windows"] for key in ("0.5_ps", "1_ps"))}
        gpu_software = {rid: results[rid]["measured_gpu_and_software_evidence"]
                        for rid in results if results[rid]["measured_gpu_and_software_evidence"]}
        throughput = {rid: results[rid]["measured_performance"] for rid in results
                      if results[rid]["measured_performance"] is not None}
        report = ["# Finite-budget collective-current study", "",
                  "## Execution and budget", "",
                  f"Completed native attempts: {len([r for r in runs if r['status']=='complete'])}; charged {sum(r['executed_steps'] for r in runs if r['status']=='complete')} steps ({sum(r['executed_steps'] for r in runs if r['status']=='complete')*DT_FS/1000:.3f} ps) at {DT_FS} fs.",
                  "Production used the supplied model.000.pb. The two thermostat branches share the exact pilot01 restart hash; pilot seed trajectories use the same supplied coordinates, so seed variation does not imply independent starting configurations.",
                  f"Live-probe resource choice: target={selection['target_id']}, partition={selection['partition']}, observed candidate GPU={selection['gpu_model']} on {selection['probe_node']}; request={selection['resources']}. Selection reason: {selection['reason']}",
                  f"Adaptive choice: {adaptive_choice}; parent run={adapt_parent_id}; analyzed basis={results['adaptive01']['trajectory_analysis_basis']} over {results['adaptive01']['n_frames']} post-exclusion frames.",
                  f"Pilot fixed-cohort retention at 0.5 ps: {pilot_retention}; held-out confirmation={confirmation_retention:.6g}, predeclared prediction passed={confirmation_prediction}.",
                  f"Paired-control measured comparison (shared checkpoint {parent_hash}): {control_comparison}.",
                  f"Measured NC fixed-minus-refreshed means over 0.1-0.5 ps: {fixed_refresh_diffs}.",
                  f"Measured GK 1.0-0.5 ps integral differences (e² Å² ps⁻¹): {gk_differences}; relative changes: {plateau_changes}; same-sign={plateau_sign_stable}.",
                  f"Finite-window gamma numerator/self denominator at 0.5 and 1.0 ps (pilot/adaptive/confirmation): {gamma_window_comparison}. Ratios are denominator-sensitive when the self integral is near zero.",
                  f"Native pilot software/GPU records: {gpu_software}; measured LAMMPS throughput: {throughput}.", "",
                  "## Interpretation", "",
                  "The COM neighbor shell is selected at each origin at the frozen 5.0-A cutoff and retained as a fixed cohort over lag; the refreshed comparison reselects contacts at each lag. Ordered-pair reciprocity is reported with species populations. Ionic current is sum(q*v_COM) with choline +1e, chloride -1e, and neutral urea.",
                  "Green-Kubo values are finite-window integrals at 0.5 and 1.0 ps. gamma is defined as total/self current-integral ratio over those same windows. Neither a short-time neighbor signal nor a truncated integral establishes equilibrium DC conductivity or an ion-pair fraction.", "",
                  "## Limitations and next measurement", "",
                  "Time origins and molecules within each box are not independent trajectories. With two pilot seeds and one held-out confirmation, uncertainty is descriptive and does not support calibrated population coverage. Prioritize longer independent 363-K trajectories with the same native positions, velocities, and box records to determine whether the total-current tail remains stable as the integration window expands.", ""]
        (app / "report.md").write_text("\n".join(report))
        persist_ledger(app, plan, runs, jobs)
        json_write(app / "execution" / "execution-status.json", {"status": "COMPLETE", "attempt_id": attempt,
                   "plan_sha256": plan["plan_sha256"], "native_runs": len(runs)})
    except Exception as exc:
        persist_ledger(app, plan, runs, jobs)
        json_write(app / "execution" / "execution-status.json", {"status": "INCOMPLETE", "reason": str(exc),
                   "attempt_id": attempt, "plan_sha256": plan["plan_sha256"], "native_runs": len(runs)})
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"solve.py: {exc}", file=sys.stderr)
        raise
__CCB_TASK46_PYTHON__
