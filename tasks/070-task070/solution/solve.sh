#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf '%s\n' \
    'Usage: solve.sh [--heating-steps N] [--equilibration-steps N] [--production-steps N] [--report-interval N] [--seed-base N]' \
    'Runs a fresh OpenMM CUDA solve through the configured task-71 HPC helper.' \
    'Uses the OpenMM CUDA environment available on the selected cluster.'
  exit 0
fi
# Oracle-only binding for the independently prepared task-71 OpenMM runtime.
export TASK71_HPC_CLI=/usr/local/bin/hpc
export TASK71_HPC_STATE_DIR=/app
export TASK71_ASSETS_DIR=/app/assets
route="$(python3 - <<'ROUTE'
import json
import os
from pathlib import Path
config = json.loads(Path('/app/submit-job.json').read_text())
target = os.environ.get('TASK71_TARGET') or config.get('profiles', {}).get('gpu')
spec = config['targets'].get(target, {})
partition = os.environ.get('TASK71_PARTITION') or spec.get('partition')
if spec.get('resource_class') != 'gpu' or not target or not partition:
    raise SystemExit('Select an authorized GPU route in the hpc configuration.')
print(target, partition)
ROUTE
)"
read -r TASK71_TARGET TASK71_PARTITION <<< "$route"
export TASK71_TARGET TASK71_PARTITION
if [[ -z "${TASK71_JOB_NAME:-}" ]]; then
  TASK71_JOB_NAME="task70-openmm-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
fi
export TASK71_REMOTE_WORKDIR="${TASK71_REMOTE_WORKDIR:-~/submit-jobs/compchemworld/task-70/$TASK71_JOB_NAME}"
export TASK71_JOB_NAME
export TASK71_REASON='Task 71 solve.py explicitly requires OpenMM CUDA; the configured target permits one GPU with the requested CPU and host memory. A fresh probe will confirm current partition and queue conditions.'
export TASK71_REMOTE_ACTIVATE="${TASK71_REMOTE_ACTIVATE:--}"
export TASK71_REMOTE_PYTHON="${TASK71_REMOTE_PYTHON:-python3}"
export TASK71_CPUS=4
export TASK71_MEMORY=16G
export TASK71_GPUS=1
export TASK71_WALLTIME=09:45:00
export TASK71_WAIT_TIMEOUT_SECONDS=43200
export TASK71_POLL_SECONDS=60
export TASK71_TRANSPORT_DIR=/app/task71-hpc-transport

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task71-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Bounded OpenMM reference workflow for the Hsp60 monomer case.

It creates two independent-velocity replicas for each author Amber system, runs
short restrained/unrestrained minimization, NVT heating, NPT equilibration and
NPT production, then calculates the declared observables from stored coordinates.
A short run is expected to yield an insufficient-sampling conclusion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import platform as pyplatform
import time

import numpy as np

INPUT_HASHES = {
    "M_WT.top": "dceab4ec34f173f55333834419cb899b4314403c1dce94a8e7ab3e52001ddade",
    "M_WT.rst": "8ed2817e87311600e639a98e84b00279c392a6ee9d3d51094b008ad6a0ac2228",
    "M_V72I.top": "77ba1507782c2a6a998075408155eae3993323604a3652b843195b535edc01c3",
    "M_V72I.rst": "cd365a05722db6e96321922d3f1f35a772a9efc233263a93a821ccea689f6209",
    "minimisation_stage1.in": "a2d899b992b9b2fe93a16103abe4b9afe1e049d05d0ee4a73e2244a673172d3d",
}


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prmtop_atoms(path: pathlib.Path):
    sections = {}
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("%FLAG "):
            current = line[6:].strip()
            sections[current] = []
        elif current is not None and not line.startswith(("%FORMAT", "%COMMENT")):
            sections[current].append(line)

    def fields(flag, width, cast):
        return [cast(row[i:i + width]) for row in sections[flag]
                for i in range(0, len(row), width) if row[i:i + width].strip()]

    names = [x.strip() for x in fields("ATOM_NAME", 4, str)]
    labels = [x.strip() for x in fields("RESIDUE_LABEL", 4, str)]
    starts = fields("RESIDUE_POINTER", 8, int)
    natom_nres = fields("POINTERS", 8, int)
    if len(names) != natom_nres[0] or len(labels) != natom_nres[11] or len(starts) != len(labels):
        raise ValueError("PRMTOP sections disagree with NATOM/NRES pointers")
    residue_for_atom = [None] * len(names)
    for r, start1 in enumerate(starts):
        end1 = starts[r + 1] if r + 1 < len(starts) else len(names) + 1
        for index in range(start1 - 1, end1 - 1):
            residue_for_atom[index] = r
    if any(x is None for x in residue_for_atom):
        raise ValueError("PRMTOP residue pointers leave atom indices unmapped")
    return names, labels, residue_for_atom


def atoms_for_residue(names, labels, residue_for_atom, mature_index, label, atom_name):
    if mature_index >= len(labels) or labels[mature_index].upper() != label:
        raise ValueError(f"expected mature residue {mature_index} to be {label}")
    found = [i for i, (name, residue) in enumerate(zip(names, residue_for_atom))
             if residue == mature_index and name.upper() == atom_name]
    if len(found) != 1:
        raise ValueError(f"expected one {atom_name} at mature residue {mature_index}, got {found}")
    return found[0]


def align_frames(frames, reference):
    aligned = np.empty_like(frames, dtype=np.float64)
    ref_center = reference.mean(axis=0)
    q = reference - ref_center
    for i, frame in enumerate(frames):
        p_center = frame.mean(axis=0)
        p = frame - p_center
        u, _, vt = np.linalg.svd(p.T @ q)
        correction = np.eye(3)
        correction[2, 2] = np.linalg.det(u @ vt)
        rotation = u @ correction @ vt
        aligned[i] = p @ rotation + ref_center
    return aligned


def df_matrix(frames):
    # Colombo lab distance_fluctuation.py method: mean[(d_ij(t)-mean(d_ij))^2],
    # excluding |i-j|<2 in its published DF matrix.
    mean_dist = None
    m2 = None
    count = 0
    for frame in frames:
        distances = np.linalg.norm(frame[:, None, :] - frame[None, :, :], axis=2)
        if mean_dist is None:
            mean_dist = np.zeros_like(distances)
            m2 = np.zeros_like(distances)
        count += 1
        delta = distances - mean_dist
        mean_dist += delta / count
        m2 += delta * (distances - mean_dist)
    if count < 2:
        raise ValueError("at least two frames per variant are required for DF")
    matrix = m2 / count
    idx = np.arange(matrix.shape[0])
    matrix[np.abs(idx[:, None] - idx[None, :]) < 2] = 0.0
    return matrix


def gamma_angle(points):
    a, b, c = points
    u, v = a - b, c - b
    cosine = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def add_amber_harmonic_restraints(system, indices, reference_positions, weight, unit, mm, parameter="k"):
    """Amber ntr energy form, k*(dx^2+dy^2+dz^2), no one-half factor."""
    force = mm.CustomExternalForce(f"{parameter}*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    force.addGlobalParameter(parameter, (weight * unit.kilocalorie_per_mole / unit.angstrom**2).value_in_unit(
        unit.kilojoule_per_mole / unit.nanometer**2))
    for parameter in ("x0", "y0", "z0"):
        force.addPerParticleParameter(parameter)
    for index in indices:
        xyz = reference_positions[index].value_in_unit(unit.nanometer)
        force.addParticle(index, [float(value) for value in xyz])
    system.addForce(force)


def run_one(tag, variant, replica, seed, args, assets, out, input_record, runtime):
    from openmm import app, unit
    try:
        import openmm as mm
    except ModuleNotFoundError as exc:
        if exc.name == "openmm":
            raise SystemExit("ENV_INVALID: fresh task-71 solving requires an OpenMM installation with the CUDA platform") from exc
        raise

    run_started = time.monotonic()
    top_name = f"M_{tag}.top"
    rst_name = f"M_{tag}.rst"
    top_path, rst_path = assets / top_name, assets / rst_name
    prmtop = app.AmberPrmtopFile(str(top_path))
    inpcrd = app.AmberInpcrdFile(str(rst_path))
    if inpcrd.positions is None or inpcrd.boxVectors is None:
        raise ValueError(f"{rst_name} needs coordinates and periodic box vectors")
    prmtop.topology.setPeriodicBoxVectors(inpcrd.boxVectors)
    names, labels, residue_for_atom = prmtop_atoms(top_path)
    ca_by_residue = {}
    for i, (name, residue) in enumerate(zip(names, residue_for_atom)):
        if residue < 526 and name.upper() == "CA":
            if residue in ca_by_residue:
                raise ValueError(f"duplicate C-alpha at mature residue {residue}")
            ca_by_residue[residue] = i
    if set(ca_by_residue) != set(range(526)):
        raise ValueError("author monomer does not provide exactly one C-alpha for mature residues 0..525")
    ca_indices = [ca_by_residue[i] for i in range(526)]
    if labels[72].upper() != ("ILE" if tag == "V72I" else "VAL"):
        raise ValueError(f"{tag} mature position 72 identity is incorrect")
    feature_indices = [
        atoms_for_residue(names, labels, residue_for_atom, 232, "VAL", "CA"),
        atoms_for_residue(names, labels, residue_for_atom, 404, "ALA", "CA"),
        atoms_for_residue(names, labels, residue_for_atom, 513, "LEU", "CA"),
        atoms_for_residue(names, labels, residue_for_atom, 50, "ASP", "CG"),
        atoms_for_residue(names, labels, residue_for_atom, 397, "ASP", "CG"),
    ]
    feature_selectors = [
        {"mature_residue_index_zero_based": mature, "amber_residue_number_one_based": mature + 1,
         "prmtop_residue_index_zero_based": mature, "residue_label": labels[mature],
         "atom_name": atom_name, "prmtop_atom_index_zero_based": atom_index}
        for mature, atom_name, atom_index in zip((232, 404, 513, 50, 397), ("CA", "CA", "CA", "CG", "CG"), feature_indices)
    ]
    # Author stage 1: restraint all atoms except H/H1 in non-WAT residues.
    stage1 = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=8.0 * unit.angstrom,
                                 constraints=None, rigidWater=False)
    excluded = [i for i, (name, r) in enumerate(zip(names, residue_for_atom))
                if name.upper() in {"H", "H1"} and labels[r].upper() != "WAT"]
    expected_excluded = 511
    if len(excluded) != expected_excluded:
        raise ValueError(f"raw PRMTOP stage-1 selection expected {expected_excluded} excluded atoms, got {len(excluded)}")
    if len(names) == 79905 and len(names) - len(excluded) != 79394:
        raise ValueError("raw PRMTOP stage-1 mask does not match the audited 79394/511 counts")
    restrained = sorted(set(range(len(names))) - set(excluded))
    add_amber_harmonic_restraints(stage1, restrained, inpcrd.positions, 5.0, unit, mm)
    minimizer = mm.VerletIntegrator(1.0 * unit.femtoseconds)
    platform = mm.Platform.getPlatformByName("CUDA")
    properties = {"DeviceIndex": os.environ.get("OPENMM_CUDA_DEVICE_INDEX", "0"), "Precision": "mixed"}
    context = mm.Context(stage1, minimizer, platform, properties)
    context.setPositions(inpcrd.positions)
    mm.LocalEnergyMinimizer.minimize(context, 10.0 * unit.kilojoule_per_mole / unit.nanometer, 300)
    pos1 = context.getState(getPositions=True).getPositions(asNumpy=True)
    del context, minimizer

    # Author stage 2 uses an unrestrained full-system minimization.
    stage2 = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=8.0 * unit.angstrom,
                                 constraints=None, rigidWater=False)
    mini2 = mm.VerletIntegrator(1.0 * unit.femtoseconds)
    context = mm.Context(stage2, mini2, platform, properties)
    context.setPositions(pos1)
    mm.LocalEnergyMinimizer.minimize(context, 10.0 * unit.kilojoule_per_mole / unit.nanometer, 300)
    start_positions = context.getState(getPositions=True).getPositions(asNumpy=True)
    del context, mini2

    ca_indices = [ca_by_residue[i] for i in range(526)]
    heating_system = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=8.0 * unit.angstrom,
                                         constraints=app.HBonds, rigidWater=True)
    add_amber_harmonic_restraints(heating_system, ca_indices, start_positions, 5.0, unit, mm)
    heating_integrator = mm.LangevinMiddleIntegrator(25.0 * unit.kelvin, 1.0 / unit.picosecond,
                                                     2.0 * unit.femtoseconds)
    heating_integrator.setRandomNumberSeed(seed)
    heating = app.Simulation(topology=prmtop.topology, system=heating_system,
                             integrator=heating_integrator, platform=platform,
                             platformProperties=properties)
    heating.context.setPositions(start_positions)
    heating.context.setVelocitiesToTemperature(25.0 * unit.kelvin, seed)
    heat_steps = args.heating_steps
    completed = 0
    while completed < heat_steps:
        amount = min(args.report_interval, heat_steps - completed)
        completed += amount
        heating_integrator.setTemperature((25.0 + 275.0 * completed / max(1, heat_steps)) * unit.kelvin)
        heating.step(amount)
    warm_state = heating.context.getState(getPositions=True, getVelocities=True)
    del heating, heating_integrator

    production_system = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=8.0 * unit.angstrom,
                                            constraints=app.HBonds, rigidWater=True)
    k375 = add_amber_harmonic_restraints(production_system, ca_indices, start_positions, 0.0,
                                          unit, mm, "restraint_375")
    k175 = add_amber_harmonic_restraints(production_system, ca_indices, start_positions, 0.0,
                                          unit, mm, "restraint_175")
    barostat = mm.MonteCarloBarostat(1.0 * unit.bar, 300.0 * unit.kelvin, 25)
    barostat.setRandomNumberSeed(seed + 100000)
    production_system.addForce(barostat)
    integrator = mm.LangevinMiddleIntegrator(300.0 * unit.kelvin, 1.0 / unit.picosecond, 2.0 * unit.femtoseconds)
    integrator.setRandomNumberSeed(seed + 1)

    directory = out / "runs" / variant / f"replica-{replica:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    topology = prmtop.topology
    stem = f"{variant}-replica-{replica:02d}"
    dcd = directory / f"{stem}.dcd"
    state_csv = directory / f"{stem}-state.csv"
    log = directory / f"{stem}-engine.log"
    xyz_frames, feature_frames, frame_steps = [], [], []
    interval = args.report_interval
    simulation = app.Simulation(topology, production_system, integrator, platform, properties)
    device_name = simulation.context.getPlatform().getPropertyValue(simulation.context, "DeviceName")
    system_mass_da = sum(production_system.getParticleMass(i).value_in_unit(unit.dalton)
                         for i in range(production_system.getNumParticles()))
    simulation.context.setPositions(warm_state.getPositions())
    simulation.context.setVelocities(warm_state.getVelocities())
    del warm_state
    with state_csv.open("w", newline="") as sf, log.open("w") as lf:
        writer = csv.writer(sf)
        writer.writerow(["step", "time_ps", "temperature_K", "density_g_ml", "volume_nm3"])
        lf.write(f"engine=openmm {mm.version.version}\nplatform=CUDA\ndevice={device_name}\n"
                 f"cuda_visible_devices={os.environ.get('CUDA_VISIBLE_DEVICES', 'unset')}\nseed={seed}\n")
        # Two Amber-like restrained NPT stages. Restraint strengths follow the
        # published input deck; the bounded duration is a reference choice.
        k_to_internal = (1.0 * unit.kilocalorie_per_mole / unit.angstrom**2).value_in_unit(
            unit.kilojoule_per_mole / unit.nanometer**2)
        first_eq = args.equilibration_steps // 2
        simulation.context.setParameter("restraint_375", 3.75 * k_to_internal)
        simulation.step(first_eq)
        simulation.context.setParameter("restraint_375", 0.0)
        simulation.context.setParameter("restraint_175", 1.75 * k_to_internal)
        simulation.step(args.equilibration_steps - first_eq)
        simulation.context.setParameter("restraint_175", 0.0)
        # Keep the DCDReporter schedule and the auxiliary coordinate/state
        # samples on the same cumulative stage-step grid.  A new Simulation
        # starts currentStep at zero even though heating/equilibration have
        # already run in earlier Simulation objects.
        total_step = heat_steps + args.equilibration_steps
        simulation.currentStep = total_step
        simulation.reporters.append(app.DCDReporter(str(dcd), interval))
        left = args.production_steps
        next_output_step = total_step + (interval - total_step % interval)
        while left > 0:
            amount = min(next_output_step - total_step, left)
            simulation.step(amount)
            left -= amount
            total_step += amount
            if total_step != next_output_step:
                continue
            state = simulation.context.getState(getPositions=True, getEnergy=True)
            xyz = np.asarray(state.getPositions(asNumpy=True).value_in_unit(unit.angstrom), dtype=np.float64)
            xyz_frames.append(xyz[ca_indices])
            feature_frames.append(xyz[feature_indices])
            frame_steps.append(total_step - (heat_steps + args.equilibration_steps))
            volume_nm3 = float(state.getPeriodicBoxVolume().value_in_unit(unit.nanometer**3))
            density = system_mass_da * 0.00166053906660 / volume_nm3
            temp = float(state.getKineticEnergy().value_in_unit(unit.kilojoule_per_mole))
            ndof = max(1, 3 * len(names) - production_system.getNumConstraints() - 3)
            # kJ/mol/K; avoid depending on version-specific unit constant exports.
            temp = 2.0 * temp / (ndof * 0.00831446261815324)
            writer.writerow([total_step, total_step * 0.002, temp, density, volume_nm3])
            next_output_step += interval
        final_state = simulation.context.getState(getPositions=True, getVelocities=True, getEnergy=True)
        final_pdb = directory / f"{stem}-final.pdb"
        with final_pdb.open("w") as pf:
            app.PDBFile.writeFile(topology, final_state.getPositions(), pf, keepIds=True)
        lf.write(f"final_potential_energy_kj_mol={float(final_state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole))}\n")
        lf.write("npt_equilibration_restraints_kcal_mol_A2=3.75,1.75\nproduction_restraint_kcal_mol_A2=0\n")
    restart = directory / f"{stem}-final-state.xml"
    restart.write_text(mm.XmlSerializer.serialize(final_state) + "\n")
    coords_file = directory / f"{stem}-analysis-coordinates.npz"
    np.savez_compressed(coords_file,
                        ca_angstrom=np.asarray(xyz_frames, dtype=np.float32),
                        gamma_delta_angstrom=np.asarray(feature_frames, dtype=np.float32),
                        ca_mature_indices=np.arange(526, dtype=np.int32),
                        feature_atom_indices=np.asarray(feature_indices, dtype=np.int32))
    del simulation, integrator
    return {
        "variant": variant, "replica": replica, "seed": seed,
        "input_topology": top_name, "input_restart": rst_name,
        "input_topology_sha256": input_record[top_name], "input_restart_sha256": input_record[rst_name],
        "heating_steps": heat_steps, "equilibration_steps": args.equilibration_steps,
        "production_steps": args.production_steps, "report_interval_steps": interval,
        "production_frames": len(xyz_frames), "timestep_fs": 2.0,
        "production_frame_steps": frame_steps,
        "production_frame_times_ps": [step * 0.002 for step in frame_steps],
        "elapsed_seconds": round(time.monotonic() - run_started, 3),
        "engine": "OpenMM", "engine_version": mm.version.version, "platform": "CUDA",
        "device": device_name, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "unset"),
        "artifacts": [str(p.relative_to(out)) for p in [dcd, state_csv, log, final_pdb, restart, coords_file]],
        "ca_indices_sha256": hashlib.sha256(",".join(map(str, ca_indices)).encode()).hexdigest(),
        "feature_atom_indices": feature_indices,
        "feature_selectors": feature_selectors,
        "restraint_selection": {"excluded_count": len(excluded), "restrained_count": len(names) - len(excluded),
                                "excluded_indices_sha256": hashlib.sha256(",".join(map(str, excluded)).encode()).hexdigest()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", default="environment/assets")
    parser.add_argument("--out", default="final")
    parser.add_argument("--heating-steps", type=int, default=10000)
    parser.add_argument("--equilibration-steps", type=int, default=20000)
    parser.add_argument("--production-steps", type=int, default=50000)
    parser.add_argument("--report-interval", type=int, default=500)
    parser.add_argument("--seed-base", type=int, default=91000)
    args = parser.parse_args()
    if min(args.heating_steps, args.equilibration_steps, args.production_steps, args.report_interval) <= 0:
        parser.error("all step counts and report interval must be positive")
    if args.production_steps % args.report_interval:
        parser.error("production steps must be a multiple of report interval so native trajectory and analysis frames agree")
    assets, out = pathlib.Path(args.assets), pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    input_record = {}
    for name, expected in INPUT_HASHES.items():
        if name == "minimisation_stage1.in":
            path = assets / "md_inputs" / name
        else:
            path = assets / name
        if not path.is_file() or sha(path) != expected:
            raise SystemExit(f"ENV_INVALID: missing or changed pinned input {path}")
        input_record[name] = expected
    runtime = {"start_monotonic": time.monotonic()}
    try:
        import openmm as mm
    except ModuleNotFoundError as exc:
        if exc.name == "openmm":
            raise SystemExit("ENV_INVALID: fresh task-71 solving requires an OpenMM installation with the CUDA platform") from exc
        raise
    run_records = []
    seed = args.seed_base
    for tag, variant in (("WT", "M_WT"), ("V72I", "M_V72I")):
        for replica in (1, 2):
            seed += 1
            run_records.append(run_one(tag, variant, replica, seed, args, assets, out, input_record, runtime))
    elapsed = round(time.monotonic() - runtime["start_monotonic"], 3)
    manifest = {
        "schema": "hsp60-case01-run-manifest/v1",
        "method": {"engine": "OpenMM", "platform": "CUDA", "force_field": "author Amber PRMTOP", "nonbonded": "PME, 8 angstrom cutoff",
                   "stage1_mask": "!(@H,H1&!:WAT)", "restraint_energy": "k*sum((delta x)^2) without 1/2",
                   "restraint_reference": "starting M_WT/M_V72I .rst coordinates",
                   "minimization": "OpenMM LocalEnergyMinimizer; not algorithmically equivalent to Amber ntmin=1",
                   "heating_steps": args.heating_steps, "equilibration_steps": args.equilibration_steps,
                   "production_steps": args.production_steps, "timestep_fs": 2.0,
                   "interpretation": "bounded reference sampling; do not presume equilibration or significance"},
        "input_sha256": input_record, "runs": run_records,
        "runtime": {"python": pyplatform.python_version(), "openmm": mm.version.version,
                    "elapsed_seconds_total": elapsed, "deadline_hours": 12.0,
                    "within_deadline": elapsed <= 12 * 3600,
                    "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                    "slurm_node": os.environ.get("SLURMD_NODENAME", os.environ.get("SLURM_JOB_NODELIST")),
                    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "unset")},
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    analyze(out, run_records, args, input_record)


def analyze(out, runs, args, input_record):
    frames_by_variant = {"M_WT": [], "M_V72I": []}
    replica_metrics = []
    with (out / "descriptors.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["variant", "replica", "seed", "frame", "time_ps", "delta_angstrom", "gamma_degrees"])
        for run in runs:
            npz = np.load(out / run["artifacts"][-1])
            ca = np.asarray(npz["ca_angstrom"], dtype=np.float64)
            features = np.asarray(npz["gamma_delta_angstrom"], dtype=np.float64)
            if ca.ndim != 3 or ca.shape[1:] != (526, 3) or features.shape != (ca.shape[0], 5, 3):
                raise ValueError("analysis coordinate arrays have invalid dimensions")
            frames_by_variant[run["variant"]].append((run, ca))
            delta = np.linalg.norm(features[:, 3] - features[:, 4], axis=1)
            gamma = np.asarray([gamma_angle(row[:3]) for row in features])
            for i, (d, g) in enumerate(zip(delta, gamma)):
                writer.writerow([run["variant"], run["replica"], run["seed"], i,
                                 run["production_frame_times_ps"][i], f"{d:.8f}", f"{g:.8f}"])
            aligned = align_frames(ca, ca[0])
            mean = aligned.mean(axis=0)
            rmsf = np.sqrt(np.mean(np.sum((aligned - mean) ** 2, axis=2), axis=0))
            replica_metrics.append({"variant": run["variant"], "replica": run["replica"],
                                   "rmsf_angstrom": rmsf.tolist(), "delta_mean_angstrom": float(delta.mean()),
                                   "delta_fraction_below_4_5": float(np.mean(delta < 4.5)),
                                   "gamma_sd_degrees": float(gamma.std(ddof=1)) if len(gamma) > 1 else 0.0})
    # RMSF output retains each independent replica, plus equal-weight variant summaries.
    with (out / "rmsf.csv").open("w", newline="") as f:
        writer = csv.writer(f); writer.writerow(["variant", "replica", "mature_residue_index", "rmsf_angstrom"])
        for row in replica_metrics:
            for i, value in enumerate(row["rmsf_angstrom"]):
                writer.writerow([row["variant"], row["replica"], i, f"{value:.8f}"])
    wt_frames = np.concatenate([x for _, x in frames_by_variant["M_WT"]], axis=0)
    mut_frames = np.concatenate([x for _, x in frames_by_variant["M_V72I"]], axis=0)
    wt_df, mut_df = df_matrix(wt_frames), df_matrix(mut_frames)
    delta_df = np.full_like(wt_df, np.nan)
    valid = np.abs(wt_df) > 1e-15
    delta_df[valid] = 100.0 * (mut_df[valid] - wt_df[valid]) / wt_df[valid]
    np.save(out / "df_delta.npy", delta_df)
    ref = np.load(out / "runs/M_WT/replica-01/M_WT-replica-01-analysis-coordinates.npz")["ca_angstrom"][0].astype(float)
    aligned = {}
    pca = {}
    for variant, batches in frames_by_variant.items():
        all_frames = np.concatenate([align_frames(x, ref) for _, x in batches], axis=0)
        centered = (all_frames[:, 2:523, :] - all_frames[:, 2:523, :].mean(axis=0)).reshape(len(all_frames), -1)
        _, singular, vt = np.linalg.svd(centered, full_matrices=False)
        variances = singular**2
        pca[variant] = {"frames": len(all_frames), "top20_variance_fraction": (variances[:20] / variances.sum()).tolist(),
                        "top20_eigenvectors": vt[:20].tolist(), "fit_reference": "M_WT replica 1 first production frame",
                        "fit_region_mature_indices": [2, 522], "analysis_region_mature_indices": [2, 522]}
        aligned[variant] = vt[:20]
    overlap = np.einsum("ik,jk->ij", aligned["M_WT"], aligned["M_V72I"])
    rmsip = float(np.sqrt(np.sum(overlap**2) / 20.0))
    pca["cross_variant"] = {"top20_rmsip": rmsip, "n_components": 20}
    (out / "pca.json").write_text(json.dumps(pca, indent=2, sort_keys=True) + "\n")
    # Short bounded runs are deliberately classified as insufficient, regardless of apparent mean direction.
    conclusions = {
        "schema": "hsp60-case01-conclusions/v1", "overall": "INSUFFICIENT_SAMPLING",
        "claims": {name: {"status": "INSUFFICIENT_SAMPLING", "direction": "not assigned",
                           "reason": "two short independent replicas per variant do not establish convergence or a stable population difference"}
                   for name in ["rigidification", "dyad_preorganisation", "pca_similarity", "allosteric_rewiring"]},
        "evidence": {"replicate_count_per_variant": 2, "production_steps_per_replica": args.production_steps,
                     "production_frames_per_replica": args.production_steps // args.report_interval,
                     "maximum_author_reference_trajectory": "2 microseconds; not supplied in this package",
                     "data_sufficiency": "insufficient"},
    }
    (out / "conclusions.json").write_text(json.dumps(conclusions, indent=2, sort_keys=True) + "\n")
    (out / "convergence.json").write_text(json.dumps({
        "schema": "hsp60-case01-convergence/v1", "overall": "INSUFFICIENT",
        "criterion": "per-replica temperature and mass/volume density time series are reported; stationarity was not demonstrated for this short reference run",
        "pressure": {"target_bar": 1.0, "instantaneous_pressure_series": "not sampled by this bounded reference solver"},
        "runs": [{"variant": r["variant"], "replica": r["replica"], "state_csv": r["artifacts"][1],
                  "equilibration_steps": r["equilibration_steps"], "production_steps": r["production_steps"],
                  "equilibration_status": "not established"} for r in runs],
    }, indent=2, sort_keys=True) + "\n")
    (out / "report.md").write_text(
        "# Bounded Hsp60 monomer reference sample\n\n"
        "This reference workflow ran two independently seeded replicas each for author M_WT and M_V72I inputs. "
        "It used a short NVT heating stage, short NPT equilibration, and short NPT production. The 100 ns author `production.in` "
        "setting was not treated as mandatory.\n\n"
        "The reported temperature and density traces do not establish convergence; instantaneous pressure was not recorded. "
        "The four science claims are therefore marked INSUFFICIENT_SAMPLING, even where the observed replica means have a direction. "
        "This sample is a runnable reference path for the output and verifier contract, not a reproduction of the paper's 2 μs data or a production result.\n\n"
        "The gamma angle uses Cα(Val232)–Cα(Ala404)–Cα(Leu513); delta is Asp50:CG–Asp397:CG. Residue mapping is mature zero-based index to Amber one-based residue number plus one.\n",
        encoding="utf-8",
    )
    # Hash every native record and required output except this recursive index.
    artifacts = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "native-artifacts.json":
            artifacts.append({"path": str(p.relative_to(out)), "bytes": p.stat().st_size, "sha256": sha(p)})
    (out / "native-artifacts.json").write_text(json.dumps({"schema": "hsp60-case01-native-artifacts/v1", "files": artifacts}, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
TASK_SOURCE_SOLVE_PY

bash "${TASK71_SUBMIT_HELPER:-/app/environment/submit-hpc.sh}" "$work_dir" \
  "${TASK71_ASSETS_DIR:-/app/assets}" "${TASK71_OUTPUT_DIR:-/app/final}" "$@"
