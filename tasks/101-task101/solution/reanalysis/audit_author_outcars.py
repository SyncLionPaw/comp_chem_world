#!/usr/bin/env python3
"""Parse deposited author OUTCARs to audit the analysis path (not new DFT evidence)."""

from __future__ import annotations

import itertools
import json
import math
import re
import sys
from pathlib import Path


OUT = Path(__file__).resolve().parent
CASES = [(0.0, "8"), (3.0, "10"), (6.0, "4"), (9.0, "1")]

MODE_RE = re.compile(
    r"^\s*(\d+)\s+(f/i|f)\s*=\s*([-+0-9.Ee]+)\s+THz.*?([-+0-9.Ee]+)\s+cm-1",
    re.MULTILINE,
)
PSTRESS_RE = re.compile(r"^\s*PSTRESS\s*=\s*([-+0-9.Ee]+)", re.MULTILINE)
STRESS_RE = re.compile(r"^\s*in kB\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)", re.MULTILINE)
EXTERNAL_RE = re.compile(r"^\s*external pressure\s*=\s*([-+0-9.Ee]+)\s*kB", re.MULTILINE)


def read_outcar(path: Path) -> dict:
    text = path.read_text(errors="replace")
    begin = text.find("Eigenvectors and eigenvalues of the dynamical matrix")
    if begin < 0:
        raise ValueError(f"No phonon eigenvector block in {path}")
    tail = text[begin:]
    headers = list(MODE_RE.finditer(tail))
    modes = []
    lines = tail.splitlines()
    for match in headers:
        line_idx = tail[: match.start()].count("\n")
        vectors = []
        for line in lines[line_idx + 1 : line_idx + 12]:
            vals = line.split()
            if len(vals) == 6:
                try:
                    vectors.append([float(v) for v in vals[-3:]])
                except ValueError:
                    pass
            if len(vectors) == 6:
                break
        if len(vectors) != 6:
            raise ValueError(f"Mode {match.group(1)} in {path} has {len(vectors)} displacement rows")
        sign = -1.0 if match.group(2) == "f/i" else 1.0
        modes.append(
            {
                "index": int(match.group(1)),
                "imaginary": match.group(2) == "f/i",
                "frequency_cm-1": sign * float(match.group(4)),
                "eigenvector_mass_weighted": vectors,
            }
        )
    if len(modes) != 18:
        raise ValueError(f"Expected 18 Gamma modes in {path}; parsed {len(modes)}")
    stress = STRESS_RE.search(text)
    external = EXTERNAL_RE.search(text)
    pstress = PSTRESS_RE.search(text)
    return {
        "path": str(path),
        "modes": modes,
        "PSTRESS_kbar": float(pstress.group(1)) if pstress else None,
        "initial_stress_diagonal_kbar": [float(x) for x in stress.groups()] if stress else None,
        "initial_external_pressure_kbar": float(external.group(1)) if external else None,
    }


def characterize(mode: dict) -> dict:
    v = mode["eigenvector_mass_weighted"]
    total = sum(x * x for atom in v for x in atom)
    z = sum(atom[2] ** 2 for atom in v)
    mo = math.sqrt(sum(x * x for atom in v[:2] for x in atom))
    sulfur = math.sqrt(sum(x * x for atom in v[2:] for x in atom))
    masses = [95.940, 95.940, 32.066, 32.066, 32.066, 32.066]
    physical = [[x / math.sqrt(masses[i]) for x in atom] for i, atom in enumerate(v)]
    return {
        "normalization_note": "VASP eigenvector normalization is arbitrary; these are relative physical displacement patterns, not absolute amplitudes",
        "z_polarization_fraction": z / total,
        "Mo_mass_weighted_amplitude": mo,
        "S_mass_weighted_amplitude": sulfur,
        "physical_displacements_A_per_sqrt_mass": physical,
    }


def flatten(vector: list[list[float]]) -> list[float]:
    return [value for atom in vector for value in atom]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def main() -> None:
    case_root = OUT.parents[2] if len(OUT.parents) > 2 else OUT
    asset_outcars = case_root / "extracted_data" / "scientific_assets" / "calculation_outputs"
    asset_dir = case_root / "packages" / "case-06-pressure-dft-raman-phonons" / "environment" / "assets"
    data = [{"pressure_GPa": p, **read_outcar(asset_outcars / f"OUTCAR_{suffix}")} for p, suffix in CASES]
    sys.path.insert(0, str(OUT))
    import build_final as analysis
    poscars = {0.0: asset_dir / "POSCAR_0GPa", 3.0: asset_dir / "POSCAR_3GPa", 6.0: asset_dir / "POSCAR_6GPa", 9.0: asset_dir / "POSCAR_9GPa"}
    base_assignment = analysis.identify_raman_modes_from_symmetry(data[0]["modes"], poscars[0.0])
    seed_modes = {name: modes for name, modes in base_assignment.items()}
    seed_doc = {
        "classification": "0-GPa reference eigenvectors selected by D6h point group, POSCAR-derived inversion parity and layer-resolved physical displacement; author reference vectors are auxiliary cross-checks, not labels by index",
        "pressure_GPa": 0,
        "frequency_unit": "cm-1",
        "vectors_are": "VASP mass-weighted eigenvectors (dx,dy,dz); inversion parity uses polar-vector transformation -u(mapped atom)",
        "poscar_path": str(poscars[0.0]),
        "inversion_mapping_one_based": {"Mo1": 2, "Mo2": 1, "S1": 4, "S2": 3, "S3": 2, "S4": 1},
        "modes": {name: modes for name, modes in seed_modes.items()},
    }
    seed_path = OUT / "author_mode_seed.json"
    seed_path.write_text(json.dumps(seed_doc, indent=2) + "\n")
    run_like = []
    for point in data:
        pressure = point["pressure_GPa"]
        outcar = asset_outcars / f"OUTCAR_{dict(CASES)[pressure]}"
        run_like.append({
            "pressure_GPa": pressure,
            "job_id": None,
            "run_name": f"deposited-author-{pressure:g}GPa",
            "run_directory": str(outcar.parent),
            "poscar_path": str(poscars[pressure]),
            "point_group": analysis.first_point_group(outcar.read_text(errors="replace")) or "unknown",
            "modes": point["modes"],
        })
    raman = analysis.raman_tracks(run_like, seed_path)
    branches = {**raman["branches"], "fits": raman["linear_fits"], "assignment_basis": raman["assignment_basis"], "primary_0GPa_layer_parity_assignment": raman["primary_0GPa_layer_parity_assignment"], "rejected_tentative_seed_candidate": raman["rejected_tentative_seed_candidate"]}
    for name in ("E2g2", "E2g1"):
        branches[name + "_fit"] = branches["fits"][name]
    branches["A1g_fit"] = branches["fits"]["A1g"]
    payload = {
        "classification": "offline audit of deposited author OUTCAR files; not new DFT evidence and not a case completion result",
        "analysis_correction": "An earlier tentative seed selected mode 4 as A1g by eigenvector overlap. POSCAR-derived polar-vector inversion parity shows mode 4 is ungerade; mode 3 is the gerade out-of-plane Raman candidate and is now used. The deposited OUTCAR has no irrep label, so this corrects our analysis and does not claim the author mislabeled it.",
        "outcar_suffix_to_pressure_GPa": {"8": 0, "10": 3, "4": 6, "1": 9},
        "points": [
            {
                "pressure_GPa": x["pressure_GPa"],
                "author_PSTRESS_kbar": x["PSTRESS_kbar"],
                "initial_stress_diagonal_kbar": x["initial_stress_diagonal_kbar"],
                "initial_external_pressure_kbar": x["initial_external_pressure_kbar"],
                "modes": [{k: v for k, v in m.items() if k != "eigenvector_mass_weighted"} for m in x["modes"]],
            }
            for x in data
        ],
        "raman_tracking": branches,
        "author_zero_pressure_mode_seeds": seed_doc["modes"],
    }
    (OUT / "author_outcar_audit.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"mode_counts": [len(x["modes"]) for x in data], "branch_tracking": branches, "output": str(OUT / "author_outcar_audit.json")}, indent=2))


if __name__ == "__main__":
    main()
