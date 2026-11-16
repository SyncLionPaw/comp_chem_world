#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf '%s\n' \
    'Usage: solve.sh [--fresh] [OUTPUT_DIRECTORY [MAX_OPTIMIZATION_STEPS [COORDSYS [--resume]]]]' \
    'Runs fresh PySCF calculations; defaults: /app, 100 steps, tric coordinates.' \
    '--resume revalidates saved stationary geometries and recomputes endpoint spectra.'
  exit 0
fi
python_cmd="${PYTHON:-python3}"
if ! command -v "$python_cmd" >/dev/null 2>&1; then
  echo "Python interpreter not found: $python_cmd" >&2
  exit 127
fi
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task76-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Independent PySCF solution path for the two frozen model classes.

This performs fresh calculations from analytic carboxylate/water starting
geometries. It does not read the private author archive.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pyscf
from pyscf import dft, gto
from pyscf.geomopt import geometric_solver
from pyscf.hessian import thermo

HARTREE_TO_KCAL = 627.509474
NS_CML = "http://www.xml-cml.org/schema"
NS_CC = "http://www.xml-cml.org/dictionary/compchem/"
NS_G = "http://www.iochem-bd.org/dictionary/gaussian/"
ET.register_namespace("", NS_CML)
ET.register_namespace("cc", NS_CC)
ET.register_namespace("g", NS_G)


def add(atoms, element: str, xyz: tuple[float, float, float]) -> int:
    atoms.append((element, np.asarray(xyz, dtype=float)))
    return len(atoms) - 1


def add_formate_pair(bridge_water: bool, proton_side: int) -> tuple[list[tuple[str, np.ndarray]], dict]:
    atoms: list[tuple[str, np.ndarray]] = []
    transfer = {}
    for side in (-1, 1):
        add(atoms, "C", (side * 2.2, 0.0, 0.0))
        ob = add(atoms, "O", (side * 1.0, 0.0, 0.0))
        add(atoms, "O", (side * 2.8, -1.0392304845, 0.0))
        add(atoms, "H", (side * 2.8, 1.0392304845, 0.0))
        transfer[side] = ob
    h = add(atoms, "H", (0.20 * proton_side, 0.0, 0.0))
    water = []
    if bridge_water:
        # A separate, approximately planar water molecule begins beside the
        # shared O-H-O axis and is allowed to relax with the rest of the model.
        ow = add(atoms, "O", (0.0, 0.0, 2.15))
        water = [ow]
        for sign in (-1.0, 1.0):
            add(atoms, "H", (sign * 0.756, 0.0, 2.782))
    return atoms, {"oxygen_a": transfer[-1] + 1, "proton": h + 1, "oxygen_b": transfer[1] + 1, "water_atoms": water}


def add_acetate_pair(bridge_water: bool, proton_side: int) -> tuple[list[tuple[str, np.ndarray]], dict]:
    """Build an independent symmetric acetate pair with a transferable proton."""
    atoms: list[tuple[str, np.ndarray]] = []
    transfer = {}
    for side in (-1, 1):
        add(atoms, "C", (side * 2.2, 0.0, 0.0))
        ob = add(atoms, "O", (side * 1.0, 0.0, 0.0))
        add(atoms, "O", (side * 2.8, -1.0392304845, 0.0))
        methyl = add(atoms, "C", (side * 3.7, 0.0, 0.0))
        # Tetrahedral methyl geometry, with one C-H bond in the molecular plane
        # and the other two symmetrically displaced out of plane.
        hrad, hout = 0.363, 1.028
        for y, z in ((hout, 0.0), (-0.5 * hout, 0.8660254038 * hout),
                     (-0.5 * hout, -0.8660254038 * hout)):
            add(atoms, "H", (side * (3.7 + hrad), y, z))
        # Keep each starting fragment as acetate anion (two carboxylate O
        # atoms, no O-H hydrogen). The only transferable proton is the
        # separately added bridge proton below.
        transfer[side] = ob
    h = add(atoms, "H", (0.20 * proton_side, 0.0, 0.0))
    water = []
    if bridge_water:
        ow = add(atoms, "O", (0.0, 0.0, 2.15))
        water = [ow]
        for sign in (-1.0, 1.0):
            add(atoms, "H", (sign * 0.756, 0.0, 2.782))
    return atoms, {"oxygen_a": transfer[-1] + 1, "proton": h + 1,
                   "oxygen_b": transfer[1] + 1, "water_atoms": water}


def build_molecule(atoms: list[tuple[str, np.ndarray]], coords: np.ndarray | None = None):
    if coords is None:
        coords = np.asarray([xyz for _, xyz in atoms])
    atom_text = ";".join(f"{element} {x:.10f} {y:.10f} {z:.10f}" for (element, _), (x, y, z) in zip(atoms, coords))
    return gto.M(atom=atom_text, basis="6-31g(d)", charge=-1, spin=0,
                 unit="Angstrom", symmetry=False, verbose=0, max_memory=5000)


def method_for(mol):
    mf = dft.RKS(mol)
    mf.xc = "b3lyp"
    mf.verbose = 4
    mf.grids.level = 3
    mf = mf.PCM()
    mf.with_solvent.method = "C-PCM"
    mf.with_solvent.eps = 4.0
    mf.conv_tol = 1e-10
    mf.max_cycle = 150
    return mf


def converged_minimum(atoms, seed_coords, maxsteps: int, coordsys: str):
    mol = build_molecule(atoms, seed_coords)
    mf = method_for(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("initial minimum SCF did not converge")
    optimized = geometric_solver.optimize(mf, maxsteps=maxsteps, coordsys=coordsys)
    opt_mf = method_for(optimized)
    energy = float(opt_mf.kernel())
    grad = np.asarray(opt_mf.nuc_grad_method().kernel())
    if not opt_mf.converged or float(np.max(np.abs(grad))) > 4e-4:
        raise RuntimeError(f"minimum failed SCF/gradient convergence: max |grad|={np.max(np.abs(grad)):.6g}")
    return optimized, opt_mf, energy, grad


def converged_ts(atoms, seed_coords, maxsteps: int, coordsys: str):
    mol = build_molecule(atoms, seed_coords)
    mf = method_for(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("initial TS SCF did not converge")
    grad = mf.nuc_grad_method()
    optimizer = grad.optimizer(solver="geomeTRIC")
    optimized = optimizer.kernel({"transition": True, "hessian": True, "maxiter": maxsteps, "coordsys": coordsys})
    opt_mf = method_for(optimized)
    energy = float(opt_mf.kernel())
    final_grad = np.asarray(opt_mf.nuc_grad_method().kernel())
    if not opt_mf.converged or float(np.max(np.abs(final_grad))) > 5e-4:
        raise RuntimeError(f"TS failed SCF/gradient convergence: max |grad|={np.max(np.abs(final_grad)):.6g}")
    return optimized, opt_mf, energy, final_grad


def endpoint_data(mol, mf, energy: float, role: str, transfer: dict, output: Path, xyz_path: Path) -> dict:
    hessian_raw = np.asarray(mf.Hessian().kernel(), dtype=float)
    hessian_transposed = hessian_raw.transpose(1, 0, 3, 2)
    hessian_asymmetry = float(np.max(np.abs(hessian_raw - hessian_transposed)))
    hessian_scale = float(np.max(np.abs(hessian_raw)))
    hessian_relative_asymmetry = hessian_asymmetry / max(hessian_scale, 1e-30)
    if not np.isfinite(hessian_raw).all() or hessian_relative_asymmetry > 1e-3:
        raise RuntimeError(
            f"{role} has an invalid analytic Hessian: relative asymmetry="
            f"{hessian_relative_asymmetry:.9g} (limit 1e-3)"
        )
    # The eigensolver requires a symmetric force-constant matrix. Preserve the
    # native analytic array and its defect, then use the orthogonal symmetric
    # projection for harmonic analysis.
    hessian = 0.5 * (hessian_raw + hessian_transposed)
    hessian_path = output.with_suffix(".hessian.npz")
    hessian_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(hessian_path, hessian_raw=hessian_raw,
                        hessian_symmetric=hessian)
    vib = thermo.harmonic_analysis(mol, hessian, imaginary_freq=False)
    # PySCF otherwise stores imaginary modes as positive-imaginary complex
    # values; request signed real cm^-1 so a TS mode is never discarded.
    freqs = np.asarray(vib["freq_wavenumber"], dtype=float)
    modes = np.asarray(vib["norm_mode"], dtype=float)
    natoms = mol.natm
    if freqs.size != 3 * natoms - 6 or modes.shape != (freqs.size, natoms, 3):
        raise RuntimeError(f"invalid normal modes: frequencies={freqs.shape}; modes={modes.shape}")
    negative = np.flatnonzero(freqs < -20.0)
    if role == "transition_state" and len(negative) != 1:
        raise RuntimeError(f"TS Hessian has {len(negative)} significant imaginary modes")
    if role != "transition_state" and len(negative):
        raise RuntimeError(f"minimum Hessian has {len(negative)} significant imaginary modes")
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    gradient = np.asarray(mf.nuc_grad_method().kernel())
    gradient_max = float(np.max(np.abs(gradient)))
    atoms = [{"element": mol.atom_symbol(i).capitalize(), "xyz": coords[i].tolist()} for i in range(natoms)]
    write_cml(output, atoms, energy, freqs.tolist(), modes.reshape(-1).tolist(), role, gradient_max)
    xyz_path.parent.mkdir(parents=True, exist_ok=True)
    xyz_path.write_text(f"{natoms}\nPySCF optimized {role}; electronic energy only\n" +
                        "".join(f"{a['element']} {a['xyz'][0]:.10f} {a['xyz'][1]:.10f} {a['xyz'][2]:.10f}\n" for a in atoms),
                        encoding="utf-8")
    import hashlib
    hessian_digest = hashlib.sha256(hessian_path.read_bytes()).hexdigest()
    return {"energy_hartree": energy, "frequencies_cm-1": freqs.tolist(),
            "max_abs_gradient_hartree_per_bohr": float(np.max(np.abs(gradient))),
            "native_output": str(output.relative_to(output.parents[3])),
            "geometry_xyz": str(xyz_path.relative_to(xyz_path.parents[3])),
            "hessian_method": "PySCF analytic Hessian; symmetric projection for harmonic analysis",
            "hessian_raw_max_asymmetry_hartree_per_bohr2": hessian_asymmetry,
            "hessian_raw_relative_asymmetry": hessian_relative_asymmetry,
            "hessian_array": str(hessian_path.relative_to(hessian_path.parents[3])),
            "hessian_array_sha256": hessian_digest,
            "hessian_array_bytes": hessian_path.stat().st_size}


def write_cml(path: Path, atoms: list[dict], energy: float, frequencies: list[float], displacements: list[float], role: str, gradient_max: float) -> None:
    root = ET.Element(f"{{{NS_CML}}}module", {"convention": "convention:compchem", "id": "pyscf-native-job"})
    job = ET.SubElement(root, f"{{{NS_CML}}}module", {"dictRef": "cc:job"})
    for ref, value in (("cc:program", f"PySCF {pyscf.__version__}"), ("cc:method", "B3LYP"),
                       ("cc:basis", "6-31G(d)"), ("g:charge", "-1"), ("g:mult", "1"),
                       ("g:solvent", "implicit low-dielectric continuum"),
                       ("g:eps", "4.0"), ("g:model", "C-PCM")):
        ET.SubElement(job, f"{{{NS_CML}}}scalar", {"dictRef": ref}).text = value
    opt = ET.SubElement(job, f"{{{NS_CML}}}scalar", {"dictRef": "g:optimization"})
    opt.text = f"geomeTRIC optimization completed. Stationary point found. Gradient maximum {gradient_max:.9g} Hartree/Bohr."
    ET.SubElement(job, f"{{{NS_CML}}}scalar", {"dictRef": "g:gradientmax", "units": "nonsi:hartree/bohr"}).text = f"{gradient_max:.12g}"
    ET.SubElement(job, f"{{{NS_CML}}}scalar", {"dictRef": "g:stationarytype"}).text = role
    ET.SubElement(job, f"{{{NS_CML}}}scalar", {"dictRef": "cc:hfenergy", "units": "nonsi:hartree"}).text = f"{energy:.12f}"
    mol = ET.SubElement(job, f"{{{NS_CML}}}molecule", {"id": "optimized"})
    aa = ET.SubElement(mol, f"{{{NS_CML}}}atomArray")
    for i, atom in enumerate(atoms, 1):
        x, y, z = atom["xyz"]
        ET.SubElement(aa, f"{{{NS_CML}}}atom", {"id": f"a{i}", "elementType": atom["element"],
                     "x3": f"{x:.10f}", "y3": f"{y:.10f}", "z3": f"{z:.10f}"})
    vib = ET.SubElement(job, f"{{{NS_CML}}}module", {"dictRef": "cc:vibrations"})
    ET.SubElement(vib, f"{{{NS_CML}}}array", {"dictRef": "cc:frequency", "dataType": "xsd:double", "size": str(len(frequencies))}).text = " ".join(f"{x:.8f}" for x in frequencies)
    ET.SubElement(vib, f"{{{NS_CML}}}array", {"dictRef": "cc:displacement", "dataType": "xsd:double", "size": str(len(displacements))}).text = " ".join(f"{x:.10g}" for x in displacements)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def solve_model(out: Path, water: bool, maxsteps: int, coordsys: str, species: str, resume: bool = False) -> dict:
    if species not in {"formate", "acetate"}:
        raise ValueError(f"unsupported carboxylate model: {species}")
    model_id = f"{species}-bridge-water" if water else f"{species}-no-water"
    builder = add_formate_pair if species == "formate" else add_acetate_pair
    atoms, transfer = builder(water, proton_side=-1)
    natoms = len(atoms)
    coords = np.asarray([xyz for _, xyz in atoms])
    base = out / "final/structures" / model_id
    base.mkdir(parents=True, exist_ok=True)
    checkpoint_path = base / "stationary-checkpoint.json"
    checkpoint = {
        "schema": "case06-stationary-checkpoint/v1",
        "model_id": model_id,
        "method": {"xc": "B3LYP", "basis": "6-31G(d)", "solvent": "C-PCM", "dielectric": 4.0,
                   "charge": -1, "multiplicity": 1},
        "stationary_points": {},
    }
    if resume and checkpoint_path.is_file():
        saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (saved.get("schema") != checkpoint["schema"] or saved.get("model_id") != model_id
                or saved.get("method") != checkpoint["method"]
                or not isinstance(saved.get("stationary_points"), dict)):
            raise RuntimeError("stationary checkpoint does not match this model/method; refusing unsafe resume")
        checkpoint = saved

    def persist_stationary(role: str, molecule, mf, energy: float) -> None:
        checkpoint["stationary_points"][role] = {
            "energy_hartree": energy,
            "coordinates_angstrom": molecule.atom_coords(unit="Angstrom").tolist(),
            "max_abs_gradient_hartree_per_bohr": float(np.max(np.abs(mf.nuc_grad_method().kernel()))),
            "electronic_state_converged": bool(mf.converged),
        }
        temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        temporary.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
        temporary.replace(checkpoint_path)

    def recover_stationary(role: str):
        saved = checkpoint["stationary_points"].get(role)
        if not saved or not saved.get("electronic_state_converged"):
            return None
        recovered = np.asarray(saved.get("coordinates_angstrom"), dtype=float)
        if recovered.shape != coords.shape or not np.isfinite(recovered).all():
            raise RuntimeError(f"{role} checkpoint has invalid coordinates")
        molecule = build_molecule(atoms, recovered)
        mf = method_for(molecule)
        energy = float(mf.kernel())
        gradient = np.asarray(mf.nuc_grad_method().kernel())
        threshold = 5e-4 if role == "transition_state" else 4e-4
        if not mf.converged or not np.isfinite(gradient).all() or float(np.max(np.abs(gradient))) > threshold:
            raise RuntimeError(f"recovered {role} checkpoint failed SCF/gradient verification")
        print(f"Reused checkpoint geometry for {model_id}:{role}; revalidated SCF/gradient before Hessian.", flush=True)
        return molecule, mf, energy, gradient

    def endpoint_start(role: str) -> None:
        print(f"CASE06_ENDPOINT_BEGIN model_id={model_id} role={role}", flush=True)

    def endpoint_finish(role: str, record: dict, energy: float) -> dict:
        record["native_log_id"] = f"{model_id}:{role}"
        print(f"CASE06_ENDPOINT_END model_id={model_id} role={role} energy_hartree={energy:.12f}", flush=True)
        return record

    # Two independent proton-localized endpoint starts and a symmetric TS start.
    seed_left = coords.copy(); seed_left[transfer["proton"] - 1, 0] = -0.20
    seed_right = coords.copy(); seed_right[transfer["proton"] - 1, 0] = 0.20
    seed_ts = coords.copy(); seed_ts[transfer["proton"] - 1, 0] = 0.0
    # Both endpoint starts preserve an identical independent molecular model.
    endpoint_start("minimum_1")
    recovered = recover_stationary("minimum_1") if resume else None
    min1, mf1, e1, _ = recovered if recovered is not None else converged_minimum(atoms, seed_left, maxsteps, coordsys)
    persist_stationary("minimum_1", min1, mf1, e1)
    ep1 = endpoint_finish("minimum_1", endpoint_data(min1, mf1, e1, "minimum", transfer,
                             base / "minimum-left.cml", base / "minimum-left.xyz"), e1)
    endpoint_start("minimum_2")
    recovered = recover_stationary("minimum_2") if resume else None
    min2, mf2, e2, _ = recovered if recovered is not None else converged_minimum(atoms, seed_right, maxsteps, coordsys)
    persist_stationary("minimum_2", min2, mf2, e2)
    ep2 = endpoint_finish("minimum_2", endpoint_data(min2, mf2, e2, "minimum", transfer,
                             base / "minimum-right.cml", base / "minimum-right.xyz"), e2)
    endpoint_start("transition_state")
    recovered = recover_stationary("transition_state") if resume else None
    ts, mfts, ets, _ = recovered if recovered is not None else converged_ts(atoms, seed_ts, maxsteps, coordsys)
    persist_stationary("transition_state", ts, mfts, ets)
    # Persist converged stationary geometries and native SCF energies before
    # the expensive numerical Hessians. A frequency failure can then be
    # recovered without repeating optimization.
    epts = endpoint_finish("transition_state", endpoint_data(ts, mfts, ets, "transition_state", transfer,
                                  base / "transition-state.cml", base / "transition-state.xyz"), ets)
    forward = (ets - e1) * HARTREE_TO_KCAL
    reverse = (ets - e2) * HARTREE_TO_KCAL
    if forward <= 0 or reverse <= 0:
        raise RuntimeError(f"{model_id}: TS does not lie above both minima ({forward:.3f}, {reverse:.3f} kcal/mol)")
    return {
        "model_id": model_id, "bridge_water": water,
        "energy_unit": "hartree", "barrier_unit": "kcal/mol",
        "barrier_basis": "electronic_energy",
        "charge": -1, "multiplicity": 1, "method": "B3LYP", "basis": "6-31G(d)",
        "solvent": {"model": "CPCM", "dielectric": 4.0},
        "transfer_atoms": {k: v for k, v in transfer.items() if k != "water_atoms"},
        "minima": [ep1, ep2], "transition_state": epts,
        "barriers_kcal_mol": {"forward": forward, "reverse": reverse},
        "scientific_assessment": {
            "barrier_basis": "electronic_energy",
            "facile_threshold_kcal_mol": 3.0,
            "maximum_bidirectional_barrier_kcal_mol": max(forward, reverse),
            "verdict": "facile" if max(forward, reverse) <= 3.0 else "not_facile",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--maxsteps", type=int, default=100)
    parser.add_argument("--coordsys", choices=("tric", "cart"), default="tric")
    parser.add_argument("--model", choices=("both", "no-water", "bridge-water"), default="both")
    parser.add_argument("--species", choices=("acetate", "formate"), default="acetate")
    parser.add_argument("--append", action="store_true", help="append calculated model rows to existing final/barriers.json")
    parser.add_argument("--resume", action="store_true", help="reuse validated stationary geometries from this model's checkpoint and recompute endpoint spectra")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    barrier_path = args.output / "final/barriers.json"
    if args.append and barrier_path.is_file():
        previous = json.loads(barrier_path.read_text(encoding="utf-8"))
        if previous.get("schema") != "case06-barriers/v1" or not isinstance(previous.get("models"), list):
            raise RuntimeError("cannot append to malformed existing barrier record")
        rows.extend(previous["models"])
    selected = {
        "both": (False, True), "no-water": (False,), "bridge-water": (True,),
    }[args.model]
    for water in selected:
        print("Native engine: PySCF; optimizer: geomeTRIC; B3LYP/6-31G(d); C-PCM epsilon=4.", flush=True)
        print(f"Starting fresh PySCF model: bridge_water={water}", flush=True)
        row = solve_model(args.output, water, args.maxsteps, args.coordsys, args.species, resume=args.resume)
        rows = [previous for previous in rows if previous.get("model_id") != row["model_id"]]
        rows.append(row)
    (args.output / "final").mkdir(parents=True, exist_ok=True)
    barrier_path.write_text(json.dumps({"schema": "case06-barriers/v1", "models": rows}, indent=2) + "\n", encoding="utf-8")
    species_name = "acetate" if args.species == "acetate" else "formate"
    report_assessment = json.dumps({
        "schema": "case06-scientific-assessment/v1",
        "models": [{"model_id": row["model_id"], **row["scientific_assessment"]} for row in rows],
    }, separators=(",", ":"))
    report = (
        "<!-- CASE06_SCIENTIFIC_ASSESSMENT_BEGIN\n" + report_assessment
        + "\nCASE06_SCIENTIFIC_ASSESSMENT_END -->\n\n"
        "# Asp50/Asp397 proton exchange QM calculation\n\n"
        f"Two independent minimal {species_name} models were built from analytic starting geometries: "
        "one without explicit water and one with a single explicit bridge water. Fresh restricted "
        "B3LYP/6-31G(d) calculations used PySCF 2.14.0, C-PCM with dielectric 4, geomeTRIC minima "
        "optimization, and geomeTRIC transition-state search.\n\n"
        "Barriers are electronic-energy differences in kcal/mol, calculated from native Hartree energies "
        "with 627.509474 kcal mol-1 Hartree-1. PySCF analytic Hessians are preserved as raw and "
        "symmetrized arrays; the symmetric projection is used for harmonic modes. Each submitted TS "
        "has one significant imaginary mode; its normal displacement is checked against the nominated "
        "O-H-O proton-transfer coordinate. The native SCF/optimization run log is also retained. "
        "These results do not include zero-point or thermal corrections.\n"
    )
    (args.output / "final/report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"pyscf_version": pyscf.__version__, "models": [{"model_id": r["model_id"], **r["barriers_kcal_mol"]} for r in rows]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
TASK_SOURCE_SOLVE_PY

if [ "${1:-}" = "--fresh" ]; then
  shift
  if [ "$#" -lt 1 ]; then
    echo "usage: $0 --fresh OUTPUT_DIRECTORY [MAX_OPTIMIZATION_STEPS [COORDSYS [--resume]]]" >&2
    exit 2
  fi
fi
output_dir="${1:-/app}"
maxsteps="${2:-100}"
coordsys="${3:-tric}"
resume_flag="${4:-}"
if [ -n "$resume_flag" ] && [ "$resume_flag" != "--resume" ]; then
  echo "fourth argument must be --resume" >&2
  exit 2
fi
mkdir -p "$output_dir/final"
if [ "$resume_flag" = "--resume" ]; then
  "$python_cmd" "$work_dir/solve.py" "$output_dir" --maxsteps "$maxsteps" --coordsys "$coordsys" --resume \
    2>&1 | tee "$output_dir/final/native-run.log"
else
  "$python_cmd" "$work_dir/solve.py" "$output_dir" --maxsteps "$maxsteps" --coordsys "$coordsys" \
    2>&1 | tee "$output_dir/final/native-run.log"
fi
