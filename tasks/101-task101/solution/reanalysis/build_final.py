#!/usr/bin/env python3
"""Build case06 final JSON/Markdown from successful, new VASP OUTCARs."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_author_outcars as audit  # shared parser; this script does not read its author-only paths

TAG_RE = {
    name: re.compile(rf"^\s*{name}\s*=\s*([-+0-9.Ee]+)", re.MULTILINE)
    for name in ("POTIM", "NSW", "NFREE", "EDIFF", "PSTRESS", "ENCUT", "KPAR", "IBRION", "ISIF", "ISYM", "IVDW")
}
POINT_GROUP_RE = re.compile(r"point group associated with its full space group is\s+([A-Za-z0-9_]+)", re.I)
FORCE_HEADER = "POSITION                                       TOTAL-FORCE"
OSZICAR_STEP_RE = re.compile(r"^\s*\d+\s+F=", re.M)


def last_tag(text: str, tag: str, cast=float):
    matches = TAG_RE[tag].findall(text)
    return cast(matches[-1]) if matches else None


def first_tag(text: str, tag: str, cast=float):
    matches = TAG_RE[tag].findall(text)
    return cast(matches[0]) if matches else None


def first_force_block(text: str) -> list[list[float]]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "POSITION" in line and "TOTAL-FORCE" in line:
            atoms = []
            for row in lines[i + 1 : i + 20]:
                fields = row.split()
                if len(fields) == 6:
                    try:
                        atoms.append([float(x) for x in fields[-3:]])
                    except ValueError:
                        pass
                if len(atoms) == 6:
                    return atoms
    raise ValueError("no six-atom TOTAL-FORCE block in OUTCAR")


def force_blocks(path: Path) -> list[list[list[float]]]:
    lines = path.read_text(errors="replace").splitlines()
    blocks = []
    for i, line in enumerate(lines):
        if "POSITION" not in line or "TOTAL-FORCE" not in line:
            continue
        atoms = []
        for row in lines[i + 1 : i + 20]:
            fields = row.split()
            if len(fields) == 6:
                try:
                    atoms.append([float(x) for x in fields])
                except ValueError:
                    pass
            if len(atoms) == 6:
                break
        if len(atoms) == 6:
            blocks.append(atoms)
    return blocks


def force_noise_comparison(reference_outcar: Path, variant_outcar: Path) -> dict:
    reference, variant = force_blocks(reference_outcar), force_blocks(variant_outcar)
    if len(reference) != 21 or len(variant) != 21:
        return {"status": "not comparable: expected one reference plus 20 displacement force blocks", "reference_block_count": len(reference), "variant_block_count": len(variant)}
    same_structure_max_A = 0.0
    force_differences = []
    for left, right in zip(reference, variant):
        lp, rp = audit.flatten([row[:3] for row in left]), audit.flatten([row[:3] for row in right])
        same_structure_max_A = max(same_structure_max_A, max(abs(a - b) for a, b in zip(lp, rp)))
        lf, rf = audit.flatten([row[3:] for row in left]), audit.flatten([row[3:] for row in right])
        force_differences.append(math.sqrt(sum((a - b) ** 2 for a, b in zip(lf, rf))))
    pair_response, pair_cosines = [], []
    for i in range(1, 21, 2):
        left = reference[i]
        right = reference[i + 1]
        lp = audit.flatten([row[:3] for row in left])
        rp = audit.flatten([row[:3] for row in right])
        base = audit.flatten([row[:3] for row in reference[0]])
        dl, dr = [x - y for x, y in zip(lp, base)], [x - y for x, y in zip(rp, base)]
        nl, nr = math.sqrt(sum(x * x for x in dl)), math.sqrt(sum(x * x for x in dr))
        pair_cosines.append(sum(a * b for a, b in zip(dl, dr)) / (nl * nr) if nl * nr else None)
        lf = audit.flatten([row[3:] for row in left])
        rf = audit.flatten([row[3:] for row in right])
        pair_response.append(math.sqrt(sum((a - b) ** 2 for a, b in zip(lf, rf))))
    min_pair_response = min(pair_response)
    return {
        "status": "compared",
        "reference_force_blocks": len(reference),
        "variant_force_blocks": len(variant),
        "maximum_same_structure_coordinate_difference_A": same_structure_max_A,
        "maximum_force_difference_L2_eV_per_A_across_same_displacement": max(force_differences[1:]),
        "rms_force_difference_L2_eV_per_A_across_same_displacement": math.sqrt(sum(x * x for x in force_differences[1:]) / 20),
        "minimum_reference_antipodal_pair_force_signal_L2_eV_per_A": min_pair_response,
        "maximum_same_displacement_force_difference_over_minimum_pair_signal": max(force_differences[1:]) / min_pair_response if min_pair_response else None,
        "antipodal_displacement_pair_cosines": pair_cosines,
        "all_displacement_pairs_antipodal": all(c is not None and c < -0.999 for c in pair_cosines),
    }


def first_point_group(text: str) -> str | None:
    match = POINT_GROUP_RE.search(text)
    return match.group(1) if match else None


def scf_summary(path: Path, ediff: float | None, outcar_text: str) -> dict:
    text = path.read_text(errors="replace")
    final_deltas = []
    final_deps = []
    last_delta = None
    last_deps = None
    scf_count = 0
    for line in text.splitlines():
        if re.match(r"^\s*(DAV|RMM|CG):", line):
            fields = line.split(":", 1)[1].split()
            if len(fields) >= 4:
                try:
                    last_delta = float(fields[2])
                    last_deps = float(fields[3])
                    scf_count += 1
                except ValueError:
                    pass
        elif OSZICAR_STEP_RE.match(line):
            if last_delta is not None:
                final_deltas.append(last_delta)
                final_deps.append(last_deps)
            last_delta = None
            last_deps = None
    if last_delta is not None:
        final_deltas.append(last_delta)
        final_deps.append(last_deps)
    return {
        "oszicar_energy_steps": len(final_deltas),
        "total_electronic_iterations": scf_count,
        "maximum_abs_final_delta_E_eV": max((abs(x) for x in final_deltas), default=None),
        "maximum_abs_final_deps_eV": max((abs(x) for x in final_deps if x is not None), default=None),
        "EDIFF_eV": ediff,
        "all_final_delta_E_within_EDIFF": bool(final_deltas) and ediff is not None and all(abs(x) <= ediff for x in final_deltas),
        "OUTCAR_aborting_loop_because_EDIFF_reached_count": outcar_text.count("aborting loop because EDIFF is reached"),
        "OUTCAR_NELM": int(re.findall(r"^\s*NELM\s*=\s*(\d+)", outcar_text, re.M)[-1]) if re.findall(r"^\s*NELM\s*=\s*(\d+)", outcar_text, re.M) else None,
        "OUTCAR_NELM_limit_events": len(re.findall(r"reached\s+NELM|NELM\s+reached", outcar_text, re.I)),
        "every_energy_step_has_EDIFF_stop": len(final_deltas) > 0 and outcar_text.count("aborting loop because EDIFF is reached") == len(final_deltas),
        "final_delta_E_eV": final_deltas,
        "final_deps_eV": final_deps,
    }


def parse_run(pressure: float, outcar_path: Path, oszicar_path: Path | None = None) -> dict:
    text = outcar_path.read_text(errors="replace")
    parsed = audit.read_outcar(outcar_path)
    forces = first_force_block(text)
    stress = parsed["initial_stress_diagonal_kbar"]
    target_gpa = (parsed["PSTRESS_kbar"] or 0.0) / 10.0
    mean_stress_kbar = sum(stress) / 3.0 if stress else None
    residual_gpa = parsed["initial_external_pressure_kbar"] / 10.0 if parsed["initial_external_pressure_kbar"] is not None else None
    ediff = last_tag(text, "EDIFF")
    run_dir = outcar_path.parent
    grid = None
    kpoints_path = run_dir / "KPOINTS"
    if kpoints_path.exists():
        kp_lines = kpoints_path.read_text().splitlines()
        if len(kp_lines) >= 4:
            try:
                grid = [int(x) for x in kp_lines[3].split()[:3]]
            except ValueError:
                pass
    job_id = None
    submission_path = run_dir / "scheduler_submission.txt"
    if submission_path.exists():
        match = re.search(r"^job_id=(\d+)$", submission_path.read_text(errors="replace"), re.M)
        job_id = match.group(1) if match else None
    input_hashes = {}
    input_hash_path = run_dir / "INPUT_SHA256.txt"
    if input_hash_path.exists():
        for line in input_hash_path.read_text().splitlines():
            fields = line.split()
            if len(fields) == 2:
                input_hashes[fields[1]] = fields[0]
    potcar_identity = {}
    identity_path = run_dir / "POTCAR.identity.sha256"
    if identity_path.exists():
        potcar_identity = {parts[0]: parts[1] for line in identity_path.read_text().splitlines() if len(parts := line.split(maxsplit=1)) == 2}
    engine = {}
    engine_path = run_dir / "ENGINE.txt"
    if engine_path.exists():
        for line in engine_path.read_text(errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                engine[key] = value
    version_banner = next((line.strip() for line in text.splitlines() if re.search(r"vasp\.\d+\.\d+\.\d+", line)), None)
    prepared_incar = (run_dir / "INCAR").read_text(errors="replace") if (run_dir / "INCAR").exists() else ""
    prepared_tags = {tag: last_tag(prepared_incar, tag) for tag in TAG_RE}
    duplicate_tags = {tag: len(TAG_RE[tag].findall(prepared_incar)) for tag in TAG_RE if len(TAG_RE[tag].findall(prepared_incar)) > 1}
    runtime_tags = {tag: first_tag(text, tag) for tag in TAG_RE}
    checked_tags = ("PSTRESS", "ENCUT", "EDIFF", "KPAR", "IBRION", "ISIF", "ISYM", "IVDW", "NFREE", "POTIM")
    tag_matches = {tag: prepared_tags[tag] is not None and runtime_tags[tag] is not None and math.isclose(prepared_tags[tag], runtime_tags[tag], rel_tol=1e-8, abs_tol=1e-10) for tag in checked_tags}
    return {
        "pressure_GPa": pressure,
        "job_id": job_id,
        "run_name": run_dir.name,
        "run_directory": str(run_dir),
        "kpoint_grid": grid,
        "input_sha256": input_hashes,
        "potential_identity_sha256": potcar_identity,
        "engine_provenance": {"version_banner": version_banner, "ENGINE_txt": engine},
        "prepared_incar_tags": prepared_tags,
        "prepared_incar_duplicate_tags": duplicate_tags,
        "runtime_tag_matches_prepared_incar": tag_matches,
        "all_runtime_tags_match_prepared_incar": all(tag_matches.values()) and not duplicate_tags,
        "outcar": str(outcar_path),
        "point_group": first_point_group(text),
        "PSTRESS_kbar": parsed["PSTRESS_kbar"],
        "target_pressure_GPa_from_PSTRESS": target_gpa,
        "initial_stress_diagonal_kbar": stress,
        "initial_hydrostatic_pressure_GPa_from_stress_trace": mean_stress_kbar / 10.0 if mean_stress_kbar is not None else None,
        "initial_pressure_residual_GPa_from_external_pressure": residual_gpa,
        "initial_force_eV_per_A": forces,
        "initial_max_force_eV_per_A": max(math.sqrt(sum(v * v for v in atom)) for atom in forces),
        "requested_tags_from_first_OUTCAR_block": {
            "NSW": first_tag(text, "NSW", int),
            "NFREE": first_tag(text, "NFREE", int),
            "POTIM_A": first_tag(text, "POTIM", float),
            **{tag: first_tag(text, tag, float) for tag in ("PSTRESS", "ENCUT", "EDIFF", "KPAR", "IBRION", "ISIF", "ISYM", "IVDW")},
        },
        "effective_tags_from_last_OUTCAR_block": {
            "NSW": last_tag(text, "NSW", int),
            "NFREE": last_tag(text, "NFREE", int),
            "POTIM_A": last_tag(text, "POTIM", float),
            **{tag: last_tag(text, tag, float) for tag in ("PSTRESS", "ENCUT", "EDIFF", "KPAR", "IBRION", "ISIF", "ISYM", "IVDW")},
        },
        "modes": parsed["modes"],
        "scf": scf_summary(oszicar_path, ediff, text) if oszicar_path and oszicar_path.exists() else None,
    }


def flat(mode: dict) -> list[float]:
    return audit.flatten(mode["eigenvector_mass_weighted"])


def layer_symmetry_evidence(mode: dict, poscar_path: Path) -> dict:
    lines = poscar_path.read_text().splitlines()
    species = lines[5].split()
    counts = [int(v) for v in lines[6].split()]
    if len(species) != 2 or species != ["Mo", "S"] or counts != [2, 4]:
        raise ValueError(f"unexpected species/count order in {poscar_path}: {species} {counts}")
    coord_line = next(i for i, line in enumerate(lines[7:], 7) if line.strip().lower().startswith(("direct", "cart")))
    is_direct = lines[coord_line].strip().lower().startswith("direct")
    coords = [[float(x) for x in lines[coord_line + j + 1].split()[:3]] for j in range(6)]
    if not is_direct:
        # The deposited structures are Direct; fail rather than silently invent
        # a fractional z mapping for a Cartesian structure.
        raise ValueError(f"layer parity requires fractional Direct POSCAR coordinates: {poscar_path}")
    mo_z = [coords[0][2] % 1.0, coords[1][2] % 1.0]
    layer_atoms = {0: [0], 1: [1]}
    layer_top_bottom = {0: {"upper": [], "lower": []}, 1: {"upper": [], "lower": []}}
    for atom in range(2, 6):
        z = coords[atom][2] % 1.0
        distances = [((z - center + 0.5) % 1.0) - 0.5 for center in mo_z]
        layer = min(range(2), key=lambda i: abs(distances[i]))
        layer_atoms[layer].append(atom)
        layer_top_bottom[layer]["upper" if distances[layer] > 0 else "lower"].append(atom)

    masses = [95.940, 95.940, 32.066, 32.066, 32.066, 32.066]
    physical = [[x / math.sqrt(masses[i]) for x in row] for i, row in enumerate(mode["eigenvector_mass_weighted"])]
    layer_vectors = {}
    for layer, atoms in layer_atoms.items():
        mo = physical[atoms[0]][:2]
        sulfur = [a for a in atoms if a >= 2]
        s_mean = [sum(physical[a][axis] for a in sulfur) / len(sulfur) for axis in range(2)]
        net = [(mo[i] + sum(physical[a][i] for a in sulfur)) / 3 for i in range(2)]
        cos = None
        norm = math.hypot(*mo) * math.hypot(*s_mean)
        if norm:
            cos = sum(mo[i] * s_mean[i] for i in range(2)) / norm
        layer_vectors[layer] = {"Mo_in_plane_relative": mo, "mean_S_in_plane_relative": s_mean, "Mo_S_in_plane_cosine": cos, "layer_net_in_plane_relative": net}
    net0, net1 = layer_vectors[0]["layer_net_in_plane_relative"], layer_vectors[1]["layer_net_in_plane_relative"]
    norm = math.hypot(*net0) * math.hypot(*net1)
    layer_net_cos = sum(net0[i] * net1[i] for i in range(2)) / norm if norm else None
    top_bottom = {}
    for layer, parts in layer_top_bottom.items():
        upper = [physical[a][2] for a in parts["upper"]]
        lower = [physical[a][2] for a in parts["lower"]]
        top_bottom[str(layer)] = {
            "upper_S_z_relative_displacements": upper,
            "lower_S_z_relative_displacements": lower,
            "upper_lower_product_signs_opposite": bool(upper and lower and sum(upper) * sum(lower) < 0),
        }
    return {
        "classification_basis": "relative physical displacement pattern from fractional POSCAR layer assignment and VASP mass-weighted eigenvectors divided by sqrt(atomic mass); overall normalization is arbitrary",
        "layer_Mo_S_in_plane_phase": layer_vectors,
        "interlayer_net_in_plane_cosine": layer_net_cos,
        "S_top_bottom_out_of_plane_phase": top_bottom,
    }


def inversion_evidence(mode: dict, poscar_path: Path) -> dict:
    """Find a POSCAR inversion center/map and evaluate polar-vector parity."""
    lines = poscar_path.read_text().splitlines()
    species = lines[5].split()
    counts = [int(v) for v in lines[6].split()]
    coord_line = next(i for i, line in enumerate(lines[7:], 7) if line.strip().lower().startswith("direct"))
    coords = [[float(x) % 1.0 for x in lines[coord_line + j + 1].split()[:3]] for j in range(sum(counts))]
    atom_species = [name for name, count in zip(species, counts) for _ in range(count)]
    seen = {name: 0 for name in species}
    atom_labels = []
    for name in atom_species:
        seen[name] += 1
        atom_labels.append(f"{name}{seen[name]}")
    candidates = set()
    for i, j in itertools.combinations_with_replacement(range(len(coords)), 2):
        if atom_species[i] != atom_species[j]:
            continue
        twice_center = tuple(round((coords[i][a] + coords[j][a]) % 1.0, 8) for a in range(3))
        candidates.add(twice_center)
    valid = []
    for twice in candidates:
        center = [x / 2 for x in twice]
        mapping = []
        for i, r in enumerate(coords):
            transformed = [(2 * center[a] - r[a]) % 1.0 for a in range(3)]
            matches = []
            for j, rj in enumerate(coords):
                if atom_species[i] != atom_species[j]:
                    continue
                delta = [((transformed[a] - rj[a] + 0.5) % 1.0) - 0.5 for a in range(3)]
                if math.sqrt(sum(x * x for x in delta)) < 1e-6:
                    matches.append(j)
            if len(matches) != 1:
                break
            mapping.append(matches[0])
        if len(mapping) == len(coords) and len(set(mapping)) == len(coords):
            valid.append((center, mapping))
    if not valid:
        raise ValueError(f"no inversion operation maps the POSCAR atoms in {poscar_path}")
    # Equivalent centers can produce the same permutation; de-duplicate those.
    center, mapping = sorted(valid, key=lambda item: (item[0], item[1]))[0]
    vectors = mode["eigenvector_mass_weighted"]
    norm = sum(v * v for row in vectors for v in row)
    parity = sum(sum(vectors[i][a] * (-vectors[mapping[i]][a]) for a in range(3)) for i in range(len(mapping))) / norm
    return {
        "center_fractional": center,
        "atom_mapping_0_based": mapping,
        "atom_mapping_by_species_label": {atom_labels[i]: atom_labels[mapping[i]] for i in range(len(mapping))},
        "polar_vector_inversion_eigenvalue": parity,
        "parity": "gerade" if parity > 0.95 else "ungerade" if parity < -0.95 else "mixed/degenerate",
        "convention": "inversion transforms a polar displacement as -u(mapped_atom); gerade eigenvectors therefore satisfy u_i=-u_map(i)",
    }


def match_pair(reference: list[dict], modes: list[dict]) -> tuple[list[dict], float]:
    best = None
    refs = [flat(m) for m in reference]
    for pair in itertools.combinations(modes, 2):
        score = sum(audit.dot(r, flat(c)) ** 2 for r in refs for c in pair)
        if best is None or score > best[1]:
            best = (list(pair), score)
    if best is None:
        raise ValueError("could not select Raman doublet")
    return best


def match_scalar(reference: dict, modes: list[dict]) -> tuple[dict, float]:
    scores = [audit.dot(flat(reference), flat(mode)) ** 2 for mode in modes]
    i = max(range(len(scores)), key=scores.__getitem__)
    return modes[i], scores[i]


def identify_raman_modes_from_symmetry(modes: list[dict], poscar_path: Path) -> dict:
    """Select the 0-GPa reference branches from displacement parity/phase.

    Frequency windows exclude unrelated optical families, while the primary
    identifiers are the layer-resolved physical displacement signatures.
    Author eigenvectors are only used afterwards as an independent cross-check.
    """
    evidence = {m["index"]: layer_symmetry_evidence(m, poscar_path) for m in modes}
    parity = {m["index"]: inversion_evidence(m, poscar_path) for m in modes}
    inplane = [m for m in modes if audit.characterize(m)["z_polarization_fraction"] < 0.1]

    def cosines(m: dict) -> list[float | None]:
        return [v["Mo_S_in_plane_cosine"] for v in evidence[m["index"]]["layer_Mo_S_in_plane_phase"].values()]

    e2g2 = [m for m in inplane if parity[m["index"]]["parity"] == "gerade" and abs(m["frequency_cm-1"]) < 100 and
            all(v is not None and v > 0.95 for v in cosines(m)) and
            evidence[m["index"]]["interlayer_net_in_plane_cosine"] is not None and
            evidence[m["index"]]["interlayer_net_in_plane_cosine"] < -0.95]
    e2g1 = [m for m in inplane if parity[m["index"]]["parity"] == "gerade" and 300 < m["frequency_cm-1"] < 430 and
            all(v is not None and v < -0.95 for v in cosines(m)) and
            evidence[m["index"]]["interlayer_net_in_plane_cosine"] is not None and
            evidence[m["index"]]["interlayer_net_in_plane_cosine"] < -0.95]
    a1g = []
    for m in modes:
        phase = evidence[m["index"]]["S_top_bottom_out_of_plane_phase"]
        if (m["frequency_cm-1"] > 300 and audit.characterize(m)["z_polarization_fraction"] > 0.95 and
                all(v["upper_lower_product_signs_opposite"] for v in phase.values()) and
                parity[m["index"]]["parity"] == "gerade"):
            a1g.append(m)
    if len(e2g2) != 2 or len(e2g1) != 2 or len(a1g) != 1:
        raise ValueError(f"layer/parity Raman classifier was not unique: E2g2={[m['index'] for m in e2g2]}, E2g1={[m['index'] for m in e2g1]}, A1g={[m['index'] for m in a1g]}")
    return {"E2g2": e2g2, "E2g1": e2g1, "A1g": a1g[0]}


def linear_fit(points: list[tuple[float, float]]) -> dict:
    xbar = sum(x for x, _ in points) / len(points)
    ybar = sum(y for _, y in points) / len(points)
    denominator = sum((x - xbar) ** 2 for x, _ in points)
    if len(points) < 2 or denominator == 0:
        return {
            "method": "ordinary least squares, unweighted linear fit",
            "status": "not estimable: at least two distinct pressures are required",
            "n_points": len(points),
            "pressure_unit": "GPa",
            "frequency_unit": "cm-1",
            "slope_cm-1_per_GPa": None,
            "intercept_cm-1": None,
            "residuals": [],
        }
    slope = sum((x - xbar) * (y - ybar) for x, y in points) / denominator
    intercept = ybar - slope * xbar
    residuals = [
        {"pressure_GPa": x, "observed_cm-1": y, "fit_cm-1": intercept + slope * x, "residual_cm-1": y - (intercept + slope * x)}
        for x, y in points
    ]
    return {
        "method": "ordinary least squares, unweighted linear fit",
        "status": "fit",
        "n_points": len(points),
        "pressure_unit": "GPa",
        "frequency_unit": "cm-1",
        "slope_cm-1_per_GPa": slope,
        "intercept_cm-1": intercept,
        "residuals": residuals,
    }


def raman_tracks(runs: list[dict], seed_path: Path) -> dict:
    seed_doc = json.loads(seed_path.read_text())
    # The case-local seed file is deliberately a provenance-bearing document
    # with its vectors under `modes`; accept the legacy wrapper as well so a
    # previously staged execution record remains reproducible.
    seed = seed_doc.get("modes", seed_doc.get("author_zero_pressure_mode_seeds"))
    if not isinstance(seed, dict):
        raise ValueError(f"mode seed {seed_path} must contain a `modes` mapping")
    base_modes = runs[0]["modes"]
    seed_pair = {name: seed[name] for name in ("E2g2", "E2g1")}
    seed_scalar = seed["A1g"]
    def poscar_for(run: dict) -> Path:
        return Path(run.get("poscar_path", Path(run["run_directory"]) / "POSCAR"))
    base_assignment = identify_raman_modes_from_symmetry(base_modes, poscar_for(runs[0]))
    base_pair = {"E2g2": base_assignment["E2g2"], "E2g1": base_assignment["E2g1"]}
    base_scalar = base_assignment["A1g"]
    author_seed_evidence = {}
    for name, ref_modes in seed_pair.items():
        selected, score = match_pair(ref_modes, base_modes)
        author_seed_evidence[name] = {"mode_indices_1_based": [m["index"] for m in selected], "subspace_overlap_squared_to_author_0GPa": score, "matches_layer_parity_assignment": sorted(m["index"] for m in selected) == sorted(m["index"] for m in base_pair[name])}
    selected_seed_scalar, score = match_scalar(seed_scalar, base_modes)
    author_seed_evidence["A1g"] = {"mode_index_1_based": selected_seed_scalar["index"], "eigenvector_overlap_squared_to_author_0GPa": score, "matches_layer_parity_assignment": selected_seed_scalar["index"] == base_scalar["index"]}
    ungerade_neighbors = [m for m in base_modes if m["frequency_cm-1"] > 300 and audit.characterize(m)["z_polarization_fraction"] > 0.95 and inversion_evidence(m, poscar_for(runs[0]))["parity"] == "ungerade"]
    rejected_seed_candidate = None
    if selected_seed_scalar["index"] != base_scalar["index"]:
        rejected_seed_candidate = {
            "classification": "earlier tentative seed match rejected by independent symmetry analysis; deposited OUTCAR supplies eigenvectors/frequencies but no irrep label",
            "seed_matched_mode_index_1_based": selected_seed_scalar["index"],
            "seed_matched_mode_frequency_cm-1": selected_seed_scalar["frequency_cm-1"],
            "seed_matched_mode_inversion_evidence": inversion_evidence(selected_seed_scalar, poscar_for(runs[0])),
            "primary_A1g_mode_index_1_based": base_scalar["index"],
            "primary_A1g_frequency_cm-1": base_scalar["frequency_cm-1"],
            "primary_A1g_inversion_evidence": inversion_evidence(base_scalar, poscar_for(runs[0])),
        }

    branches: dict[str, list[dict]] = {name: [] for name in ("E2g2", "E2g1", "A1g")}
    for run in runs:
        if run["point_group"] != "D_6h":
            raise ValueError(f"Raman assignment expects observed D_6h symmetry; {run['run_name']} reports {run['point_group']}")
        for name in ("E2g2", "E2g1"):
            ref = base_pair[name] if run is runs[0] else base_pair[name]
            selected, score = match_pair(ref, run["modes"])
            if any(inversion_evidence(m, poscar_for(run))["parity"] != "gerade" for m in selected):
                raise ValueError(f"tracked {name} doublet is not inversion-even at {run['run_name']}")
            freqs = [m["frequency_cm-1"] for m in selected]
            branches[name].append(
                {
                    "pressure_GPa": run["pressure_GPa"],
                    "job_id": run["job_id"],
                    "run_name": run["run_name"],
                    "point_group": run["point_group"],
                    "mode_indices_1_based": [m["index"] for m in selected],
                    "frequencies_cm-1": freqs,
                    "mean_cm-1": sum(freqs) / 2,
                    "doublet_splitting_cm-1": abs(freqs[0] - freqs[1]),
                    "subspace_overlap_squared_to_0GPa": score,
                    "z_polarization_fraction": sum(audit.characterize(m)["z_polarization_fraction"] for m in selected) / 2,
                    "layer_symmetry_evidence_by_mode": [layer_symmetry_evidence(m, poscar_for(run)) for m in selected],
                    "inversion_evidence_by_mode": [inversion_evidence(m, poscar_for(run)) for m in selected],
                }
            )
        selected, score = match_scalar(base_scalar, run["modes"])
        if inversion_evidence(selected, poscar_for(run))["parity"] != "gerade":
            raise ValueError(f"tracked A1g mode is not inversion-even at {run['run_name']}")
        branches["A1g"].append(
            {
                "pressure_GPa": run["pressure_GPa"],
                "job_id": run["job_id"],
                "run_name": run["run_name"],
                "point_group": run["point_group"],
                "mode_index_1_based": selected["index"],
                "frequency_cm-1": selected["frequency_cm-1"],
                "eigenvector_overlap_squared_to_0GPa": score,
                **audit.characterize(selected),
                "layer_symmetry_evidence": layer_symmetry_evidence(selected, poscar_for(run)),
                "inversion_evidence": inversion_evidence(selected, poscar_for(run)),
            }
        )
    fits = {
        "E2g2": linear_fit([(p["pressure_GPa"], p["mean_cm-1"]) for p in branches["E2g2"]]),
        "E2g1": linear_fit([(p["pressure_GPa"], p["mean_cm-1"]) for p in branches["E2g1"]]),
        "A1g": linear_fit([(p["pressure_GPa"], p["frequency_cm-1"]) for p in branches["A1g"]]),
    }
    return {
        "assignment_basis": f"Author subspaces are auxiliary cross-checks only. New modes are classified from actual OUTCAR point-group symmetry {sorted({r['point_group'] for r in runs})}, mass-unweighted displacement character, layer phase, and POSCAR-derived inversion eigenvalue. Inversion maps are generated from fractional coordinates; a polar vector transforms as -u(mapped_atom), and gerade means eigenvalue +1. E2g2 is identified by intralayer Mo/S in-plane phase alignment plus opposite layer translations; E2g1 by Mo/S in-plane phase opposition within each trilayer; A1g by gerade sulfur-only out-of-plane motion with opposite top/bottom S displacement. Doublets are tracked as two-dimensional subspaces.",
        "primary_0GPa_layer_parity_assignment": {name: [m["index"] for m in value] if isinstance(value, list) else value["index"] for name, value in base_assignment.items()},
        "author_seed_provenance": {"path": str(seed_path), "sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(), "role": "auxiliary cross-check only"},
        "author_seed_matches_to_new_0GPa": author_seed_evidence,
        "analysis_correction_note": "Earlier tentative matching used the nearby out-of-plane mode 4 as A1g. POSCAR-derived inversion of polar displacements shows mode 4 is ungerade; the gerade out-of-plane Raman candidate is mode 3. The deposited OUTCAR contains eigenvectors and frequencies but no irrep names; this is a correction to our analysis.",
        "nearest_ungerade_out_of_plane_neighbor": [{"mode_index_1_based": m["index"], "frequency_cm-1": m["frequency_cm-1"], "inversion_evidence": inversion_evidence(m, poscar_for(runs[0]))} for m in ungerade_neighbors],
        "rejected_tentative_seed_candidate": rejected_seed_candidate,
        "branches": branches,
        "linear_fits": fits,
    }


def write_outputs(root: Path, outcars: dict[float, Path], oszicars: dict[float, Path], convergence_runs: dict[str, tuple[float, Path]], supplementary_outcars: dict[float, Path], seed: Path) -> None:
    pressures = [0.0, 3.0, 6.0, 9.0]
    runs = [parse_run(p, outcars[p], oszicars.get(p, outcars[p].with_name("OSZICAR"))) for p in pressures]
    if any(len(r["modes"]) != 18 for r in runs):
        raise ValueError("each pressure must contain exactly 18 Gamma modes")
    if any(not r["all_runtime_tags_match_prepared_incar"] for r in runs):
        raise ValueError("production OUTCAR effective setup does not match the prepared INCAR")
    if any(r["PSTRESS_kbar"] != p * 10 for p, r in zip(pressures, runs)):
        raise ValueError("PSTRESS mapping does not match [0,3,6,9] GPa")
    production_signature = {(tuple(r["kpoint_grid"] or []), r["effective_tags_from_last_OUTCAR_block"]["ENCUT"], r["effective_tags_from_last_OUTCAR_block"]["EDIFF"]) for r in runs}
    if len(production_signature) != 1 or next(iter(production_signature))[0] != (12, 12, 1):
        raise ValueError(f"four-point main route must use a single common 12x12x1/ENCUT/EDIFF setup; got {production_signature}")
    for r in runs:
        scf = r["scf"]
        if (scf is None or scf["oszicar_energy_steps"] != 21 or
                scf["OUTCAR_aborting_loop_because_EDIFF_reached_count"] != 21 or
                scf["OUTCAR_NELM_limit_events"] != 0 or not scf["every_energy_step_has_EDIFF_stop"]):
            raise ValueError(f"production job {r['job_id']} lacks verified convergence for all 21 reference/displacement SCF steps")
    supplementary_runs = [parse_run(p, supplementary_outcars[p], supplementary_outcars[p].with_name("OSZICAR")) for p in pressures] if supplementary_outcars else []
    if supplementary_runs and any(len(r["modes"]) != 18 or not r["all_runtime_tags_match_prepared_incar"] or r["PSTRESS_kbar"] != p * 10 for p, r in zip(pressures, supplementary_runs)):
        raise ValueError("supplementary four-point route has incomplete modes or an input/runtime mismatch")
    if supplementary_runs and any(tuple(r["kpoint_grid"] or []) != (12, 12, 1) or r["effective_tags_from_last_OUTCAR_block"]["ENCUT"] != 500.0 or r["effective_tags_from_last_OUTCAR_block"]["EDIFF"] != 1e-5 for r in supplementary_runs):
        raise ValueError("the separately labelled author-route supplement must be Kz=1, ENCUT=500 eV, EDIFF=1e-5 at every pressure")
    convergence_parsed = {label: parse_run(p, path, path.with_name("OSZICAR")) for label, (p, path) in convergence_runs.items()}
    mismatches = {label: run["runtime_tag_matches_prepared_incar"] for label, run in convergence_parsed.items() if not run["all_runtime_tags_match_prepared_incar"]}
    if mismatches:
        raise ValueError(f"convergence OUTCAR configuration mismatch: {mismatches}")
    pressure_mismatches = {label: (run["PSTRESS_kbar"], run["pressure_GPa"]) for label, run in convergence_parsed.items() if run["PSTRESS_kbar"] != run["pressure_GPa"] * 10}
    if pressure_mismatches:
        raise ValueError(f"convergence check pressure/PSTRESS mismatch: {pressure_mismatches}")
    final = root / "final"
    final.mkdir(parents=True, exist_ok=True)
    phonons = {
        "pressures_GPa": pressures,
        "frequency_unit": "cm-1",
        "frequency_sign_convention": "imaginary VASP f/i modes are encoded as negative frequencies and imaginary=true; no absolute-value folding",
        "source_classification": "new case06 VASP outputs",
        "points": [{k: v for k, v in r.items() if k in (
            "pressure_GPa", "job_id", "run_name", "run_directory", "kpoint_grid", "input_sha256", "potential_identity_sha256", "engine_provenance",
            "PSTRESS_kbar", "target_pressure_GPa_from_PSTRESS", "initial_stress_diagonal_kbar",
            "initial_hydrostatic_pressure_GPa_from_stress_trace", "initial_pressure_residual_GPa_from_external_pressure",
        "initial_max_force_eV_per_A", "point_group", "requested_tags_from_first_OUTCAR_block",
            "effective_tags_from_last_OUTCAR_block", "prepared_incar_tags", "prepared_incar_duplicate_tags",
            "runtime_tag_matches_prepared_incar", "all_runtime_tags_match_prepared_incar", "scf", "modes"
        )} for r in runs],
    }
    if supplementary_runs:
        phonons["supplementary_author_EDIFF1e-5_route"] = {
            "description": "Separate four-point Kz=1/ENCUT=500 eV author-input electronic precision set; not the selected tight main route.",
            "points": [{k: v for k, v in r.items() if k in ("pressure_GPa", "job_id", "run_name", "kpoint_grid", "input_sha256", "potential_identity_sha256", "engine_provenance", "PSTRESS_kbar", "initial_hydrostatic_pressure_GPa_from_stress_trace", "initial_pressure_residual_GPa_from_external_pressure", "initial_max_force_eV_per_A", "effective_tags_from_last_OUTCAR_block", "point_group", "scf", "modes")} for r in supplementary_runs],
        }
    (final / "phonons.json").write_text(json.dumps(phonons, indent=2) + "\n")
    raman = {"pressures_GPa": pressures, "frequency_unit": "cm-1", "pressure_unit": "GPa", **raman_tracks(runs, seed)}
    raman["d_omega_dP"] = {name: raman["linear_fits"][name]["slope_cm-1_per_GPa"] for name in ("E2g2", "E2g1", "A1g")}
    raman["d_omega_dP_unit"] = "cm-1/GPa"
    if supplementary_runs:
        raman["supplementary_author_EDIFF1e-5_route"] = {
            "description": "Four-point Kz=1/ENCUT=500 eV author-input electronic precision set; independently tracked with the same POSCAR-derived layer and inversion-parity classifier; not mixed into the tight main-route fit.",
            "pressures_GPa": pressures,
            "actual_EDIFF_eV": [r["effective_tags_from_last_OUTCAR_block"]["EDIFF"] for r in supplementary_runs],
            "job_ids": [r["job_id"] for r in supplementary_runs],
            **raman_tracks(supplementary_runs, seed),
        }
        supplement = raman["supplementary_author_EDIFF1e-5_route"]
        supplement["d_omega_dP"] = {name: supplement["linear_fits"][name]["slope_cm-1_per_GPa"] for name in ("E2g2", "E2g1", "A1g")}
        supplement["d_omega_dP_unit"] = "cm-1/GPa"

    rows = [
        "# Pressure state and input structures",
        "",
        "Pressures below come from the input PSTRESS (kbar) and the first, undisplaced stress/force block of each new OUTCAR. VASP external-pressure residual is reported separately from the target; no relaxation was applied in the IBRION=6 run.",
        "",
        "| Target GPa | JobID | K grid | PSTRESS kbar | raw stress trace pressure GPa | external residual GPa | max initial force eV/Å | effective NSW/NFREE/POTIM | VASP symmetry |",
        "|---:|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for r in runs:
        eff = r["effective_tags_from_last_OUTCAR_block"]
        grid = "×".join(map(str, r["kpoint_grid"] or []))
        rows.append(f"| {r['pressure_GPa']:g} | {r['job_id']} | {grid} | {r['PSTRESS_kbar']:g} | {r['initial_hydrostatic_pressure_GPa_from_stress_trace']:.6f} | {r['initial_pressure_residual_GPa_from_external_pressure']:.6f} | {r['initial_max_force_eV_per_A']:.6f} | {eff['NSW']}/{eff['NFREE']}/{eff['POTIM_A']} Å | {r['point_group']} |")
    rows += ["", "Each case uses the author POSCAR for its corresponding target pressure. Actual structures were not re-relaxed; this preserves the deposited pressure-state route. Requested NSW=1 is internally reset by VASP to effective NSW=109 for IBRION=6 finite displacement; effective NFREE=2 and POTIM=0.015 Å are confirmed from OUTCAR. The reported force and stress components are raw run evidence, not scorer thresholds.", ""]
    (final / "pressure_state.md").write_text("\n".join(rows))

    convergence_text = [
        "# Fixed-structure parameter sensitivity and reference tolerance evidence", "",
        f"The primary four-point route uses the deposited pressure-specific POSCARs, Gamma-centred {runs[0]['kpoint_grid']} sampling, ENCUT={runs[0]['effective_tags_from_last_OUTCAR_block']['ENCUT']} eV and EDIFF={runs[0]['effective_tags_from_last_OUTCAR_block']['EDIFF']} eV. Every comparison below is grouped by actual OUTCAR runtime tags; controls with different EDIFF, ENCUT, pressure state or structure are never folded into one convergence difference.", "",
        "All 0-GPa controls use the deposited 0-GPa POSCAR without re-relaxation. Denser Kz grids are fixed-geometry sampling checks only: include their raw stress/force change and do not treat them as an equilibrated same-pressure reference. The author EDIFF=1e-5 four-point series, when supplied, is a separate supplement.", "",
    ]
    parsed = {"primary-0GPa": runs[0], **{label: run for label, run in convergence_parsed.items() if run["pressure_GPa"] == 0}}
    tracks = {label: raman_tracks([run], seed)["branches"] for label, run in {**parsed, **convergence_parsed}.items()}
    def frequency(label: str, name: str) -> float:
        branch = tracks[label][name][0]
        return branch["mean_cm-1"] if name != "A1g" else branch["frequency_cm-1"]
    def actual(run: dict, name: str) -> float:
        return run["effective_tags_from_last_OUTCAR_block"][name]
    main = runs[0]
    main_ediff, main_encut, main_kz = actual(main, "EDIFF"), actual(main, "ENCUT"), main["kpoint_grid"][2]
    families = {
        "same_EDIFF_grid": {k: r for k, r in parsed.items() if r["kpoint_grid"][:2] == main["kpoint_grid"][:2] and actual(r, "EDIFF") == main_ediff and actual(r, "ENCUT") == main_encut},
        "same_EDIFF_encut": {k: r for k, r in parsed.items() if r["kpoint_grid"] == main["kpoint_grid"] and actual(r, "EDIFF") == main_ediff},
        "same_grid_encut_electronic_ladder": {k: r for k, r in parsed.items() if r["kpoint_grid"] == main["kpoint_grid"] and actual(r, "ENCUT") == main_encut and actual(r, "EDIFF") < 1e-5 * (1 - 1e-9)},
    }
    family_outputs = {}
    for family, members in families.items():
        if not members:
            continue
        family_outputs[family] = {
            label: {"job_id": r["job_id"], "kpoint_grid": r["kpoint_grid"], "ENCUT_eV": actual(r, "ENCUT"), "EDIFF_eV": actual(r, "EDIFF"), "input_sha256": r["input_sha256"], "potential_identity_sha256": r["potential_identity_sha256"], "engine_provenance": r["engine_provenance"], "branch_frequencies_cm-1": {name: frequency(label, name) for name in ("E2g2", "E2g1", "A1g")}, "raw_trace_pressure_GPa": r["initial_hydrostatic_pressure_GPa_from_stress_trace"], "external_pressure_residual_GPa": r["initial_pressure_residual_GPa_from_external_pressure"], "max_initial_force_eV_per_A": r["initial_max_force_eV_per_A"], "SCF": r["scf"]}
            for label, r in members.items()
        }
    legacy_grid = {label: r for label, r in parsed.items() if label != "primary-0GPa" and r["kpoint_grid"] != main["kpoint_grid"] and actual(r, "EDIFF") == 1e-5 and actual(r, "ENCUT") == main_encut}
    if legacy_grid:
        family_outputs["separate_legacy_EDIFF1e-5_fixed_geometry_grid_checks"] = {
            label: {"job_id": r["job_id"], "kpoint_grid": r["kpoint_grid"], "EDIFF_eV": actual(r,"EDIFF"), "ENCUT_eV": actual(r,"ENCUT"), "branch_frequencies_cm-1": {name: frequency(label,name) for name in ("E2g2","E2g1","A1g")}, "raw_trace_pressure_GPa": r["initial_hydrostatic_pressure_GPa_from_stress_trace"], "external_pressure_residual_GPa": r["initial_pressure_residual_GPa_from_external_pressure"], "max_initial_force_eV_per_A": r["initial_max_force_eV_per_A"], "interpretation": "legacy author-precision fixed-geometry control; excluded from same-EDIFF tight-grid comparisons"}
            for label,r in legacy_grid.items()
        }
    raman["fixed_geometry_parameter_sensitivity"] = family_outputs
    convergence_text += ["## Same-EDIFF Kz sampling family", "", f"Only runs with actual EDIFF={main_ediff:g} eV and ENCUT={main_encut:g} eV are included; adjacent differences are meaningful only as fixed-structure sampling sensitivity.", ""]
    grid_family = sorted(families["same_EDIFF_grid"].items(), key=lambda kv: kv[1]["kpoint_grid"][2])
    convergence_text += ["| Kz | JobID | EDIFF eV | E2g2 cm⁻¹ | E2g1 cm⁻¹ | A1g cm⁻¹ | raw pressure GPa | pressure residual GPa | max force eV/Å |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label, run in grid_family:
        convergence_text.append(f"| {run['kpoint_grid'][2]} | {run['job_id']} | {actual(run,'EDIFF'):.0e} | {frequency(label,'E2g2'):.6f} | {frequency(label,'E2g1'):.6f} | {frequency(label,'A1g'):.6f} | {run['initial_hydrostatic_pressure_GPa_from_stress_trace']:.6f} | {run['initial_pressure_residual_GPa_from_external_pressure']:.6f} | {run['initial_max_force_eV_per_A']:.6f} |")
    if legacy_grid:
        convergence_text += ["", "## Separate legacy author-precision (EDIFF=1e-5) frozen-geometry Kz controls", "", "These older runs are preserved as supplementary sensitivity evidence only; their Kz deltas are not combined with the electronically tighter same-EDIFF grid family above.", "", "| K grid | JobID | E2g2 cm⁻¹ | E2g1 cm⁻¹ | A1g cm⁻¹ | raw pressure GPa | residual GPa | max force eV/Å |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for label,run in legacy_grid.items():
            convergence_text.append(f"| {run['kpoint_grid']} | {run['job_id']} | {frequency(label,'E2g2'):.6f} | {frequency(label,'E2g1'):.6f} | {frequency(label,'A1g'):.6f} | {run['initial_hydrostatic_pressure_GPa_from_stress_trace']:.6f} | {run['initial_pressure_residual_GPa_from_external_pressure']:.6f} | {run['initial_max_force_eV_per_A']:.6f} |")
    ediff_family = sorted(families["same_grid_encut_electronic_ladder"].items(), key=lambda kv: actual(kv[1], "EDIFF"), reverse=True)
    convergence_text += ["", "## Same-grid / same-ENCUT electronic-convergence ladder", "", "Each row uses the same Kz=1 structure and ENCUT; the EDIFF value is read from the first OUTCAR input summary and checked against the prepared INCAR.", "", "| EDIFF eV | JobID | E2g2 cm⁻¹ | E2g1 cm⁻¹ | A1g cm⁻¹ | E2g2 Δ from tight route cm⁻¹ | raw pressure GPa | max force eV/Å | EDIFF-stop / steps | NELM hits |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    force_noise = {}
    for label, run in ediff_family:
        scf = run["scf"]
        convergence_text.append(f"| {actual(run,'EDIFF'):.0e} | {run['job_id']} | {frequency(label,'E2g2'):.6f} | {frequency(label,'E2g1'):.6f} | {frequency(label,'A1g'):.6f} | {frequency(label,'E2g2')-frequency('primary-0GPa','E2g2'):+.6f} | {run['initial_hydrostatic_pressure_GPa_from_stress_trace']:.6f} | {run['initial_max_force_eV_per_A']:.6f} | {scf['OUTCAR_aborting_loop_because_EDIFF_reached_count']}/{scf['oszicar_energy_steps']} | {scf['OUTCAR_NELM_limit_events']} |")
        if label != "primary-0GPa":
            force_noise[label] = force_noise_comparison(Path(main["outcar"]), Path(run["outcar"]))
    if len(ediff_family) >= 2:
        tightest_pair = sorted(ediff_family, key=lambda kv: actual(kv[1], "EDIFF"))[:2]
        tight_label, tight_run = tightest_pair[0]
        loose_label, loose_run = tightest_pair[1]
        delta = {name: frequency(tight_label,name)-frequency(loose_label,name) for name in ("E2g2","E2g1","A1g")}
        raman["fixed_geometry_parameter_sensitivity"]["tightest_adjacent_EDIFF_pair_delta_cm-1"] = {"looser_job_id":loose_run["job_id"], "looser_EDIFF_eV":actual(loose_run,"EDIFF"), "tighter_job_id":tight_run["job_id"], "tighter_EDIFF_eV":actual(tight_run,"EDIFF"), "frequency_change_tighter_minus_looser_cm-1":delta}
        convergence_text += ["", f"Tightest adjacent 0-GPa EDIFF pair ({actual(loose_run,'EDIFF'):.0e} → {actual(tight_run,'EDIFF'):.0e} eV): ΔE2g2={delta['E2g2']:+.6f}, ΔE2g1={delta['E2g1']:+.6f}, ΔA1g={delta['A1g']:+.6f} cm⁻¹. This is a branch-specific observed change, not a global score tolerance.", ""]
    high_pressure_controls = {label: run for label, run in convergence_parsed.items() if run["pressure_GPa"] != 0}
    if high_pressure_controls:
        raman["nonzero_pressure_ediff_endpoint_checks"] = {}
        convergence_text += ["", "## Nonzero-pressure endpoint electronic checks (separate from the 0-GPa ladder)", "", "The table also reports the change in each four-point OLS slope if only this endpoint replaces the primary 9-GPa point.", "", "| Target GPa | JobID | EDIFF eV | E2g2 Δ cm⁻¹ | E2g1 Δ cm⁻¹ | A1g Δ cm⁻¹ | OLS slope Δ E2g2/E2g1/A1g cm⁻¹/GPa | EDIFF stops / steps | NELM hits |", "|---:|---:|---:|---:|---:|---:|---|---:|---:|"]
        for label, run in high_pressure_controls.items():
            target = next(r for r in runs if r["pressure_GPa"] == run["pressure_GPa"])
            ref_label = "primary-0GPa" if target["pressure_GPa"] == 0 else f"primary-{target['pressure_GPa']:g}GPa"
            tracks[ref_label] = raman_tracks([target], seed)["branches"]
            scf = run["scf"]
            deltas = [frequency(label, name) - (tracks[ref_label][name][0]["mean_cm-1"] if name != "A1g" else tracks[ref_label][name][0]["frequency_cm-1"]) for name in ("E2g2", "E2g1", "A1g")]
            slope_deltas = {}
            for name in ("E2g2", "E2g1", "A1g"):
                base_branch = raman["branches"][name]
                pts = [(pt["pressure_GPa"], pt["mean_cm-1"] if name != "A1g" else pt["frequency_cm-1"]) for pt in base_branch]
                pts[-1] = (run["pressure_GPa"], frequency(label, name))
                slope_deltas[name] = linear_fit(pts)["slope_cm-1_per_GPa"] - raman["linear_fits"][name]["slope_cm-1_per_GPa"]
            slope_delta_text = "/".join(f"{slope_deltas[n]:+.6f}" for n in ("E2g2", "E2g1", "A1g"))
            convergence_text.append(f"| {run['pressure_GPa']:g} | {run['job_id']} | {actual(run,'EDIFF'):.0e} | {deltas[0]:+.6f} | {deltas[1]:+.6f} | {deltas[2]:+.6f} | {slope_delta_text} | {scf['OUTCAR_aborting_loop_because_EDIFF_reached_count']}/{scf['oszicar_energy_steps']} | {scf['OUTCAR_NELM_limit_events']} |")
            raman["nonzero_pressure_ediff_endpoint_checks"][label] = {"pressure_GPa": run["pressure_GPa"], "job_id": run["job_id"], "kpoint_grid": run["kpoint_grid"], "ENCUT_eV": actual(run,"ENCUT"), "EDIFF_eV": actual(run,"EDIFF"), "input_sha256": run["input_sha256"], "potential_identity_sha256": run["potential_identity_sha256"], "engine_provenance": run["engine_provenance"], "branch_frequencies_cm-1": {name: frequency(label,name) for name in ("E2g2","E2g1","A1g")}, "branch_delta_from_main_route_cm-1": dict(zip(("E2g2","E2g1","A1g"),deltas)), "four_point_OLS_slope_delta_if_endpoint_replaced_cm-1_per_GPa": slope_deltas, "SCF": scf}
    encut_family = families["same_EDIFF_encut"]
    convergence_text += ["", "## Same-EDIFF / same-grid ENCUT family", "", "| ENCUT eV | JobID | E2g2 cm⁻¹ | E2g1 cm⁻¹ | A1g cm⁻¹ | raw pressure GPa | max force eV/Å |", "|---:|---:|---:|---:|---:|---:|---:|"]
    for label, run in sorted(encut_family.items(), key=lambda kv: actual(kv[1], "ENCUT")):
        convergence_text.append(f"| {actual(run,'ENCUT'):g} | {run['job_id']} | {frequency(label,'E2g2'):.6f} | {frequency(label,'E2g1'):.6f} | {frequency(label,'A1g'):.6f} | {run['initial_hydrostatic_pressure_GPa_from_stress_trace']:.6f} | {run['initial_max_force_eV_per_A']:.6f} |")
    raman["fixed_geometry_parameter_sensitivity"]["finite_difference_force_noise_vs_tight_primary"] = force_noise
    raman["reference_tolerance_guidance"] = {
        "same_route_EDIFF_stability": "0-GPa branch changes across the EDIFF ladder and the independent 9-GPa EDIFF endpoint check are reported; no next-tighter EDIFF endpoint checks were run at 3 or 6 GPa",
        "same_route_exact_repeatability": "not measured: no identical duplicate production calculation was run",
        "ENCUT_and_Kz_controls": "only controls with the main route's actual EDIFF are compared in their same-EDIFF families",
        "fixed_geometry_k_sampling": "only 0 GPa measured; Kz changes raw force/stress and is not an equilibrated same-pressure uncertainty estimate",
        "global_frequency_tolerance_cm-1": None,
        "scorer_guidance": "keep the EDIFF=1e-5 author-route supplement separate from the selected tight route; branch matching requires POSCAR-derived inversion parity and layer phase, E2g doublet subspace overlap, signed acoustic modes separately, and refitting each branch across all four pressures; no global tolerance is frozen",
    }
    convergence_text += ["", "## Error scope and scorer integration guidance", "", "No identical duplicate production run was made, so exact-route repeatability remains unmeasured. The EDIFF ladder checks branch sensitivity at 0 GPa, and one stricter EDIFF endpoint check is reported at 9 GPa; no next-tighter endpoint tests were run at 3 or 6 GPa. Kz and ENCUT controls are single-point fixed-geometry checks. The Kz=2 raw pressure and force must be considered when interpreting its frequencies; it is not a same-equilibrium physical accuracy bound. A whole-structure force-difference norm is a mixed-direction diagnostic, not a projection onto the soft E2g2 branch, and cannot rule out mode-specific SCF noise.", "", "For mirror/scorer integration, keep the four-point author EDIFF=1e-5 supplement separate from the selected tight production reference. Use runtime input tags and JobIDs; assign branches from actual POSCAR inversion parity, layer phase and point-group symmetry, track E2g doublets with 2D subspace overlap, treat signed acoustic modes separately, and refit each branch across all four pressures. No global frequency tolerance is frozen by these controls.", ""]
    if supplementary_runs:
        convergence_text += ["## Separate author-route four-point supplement", "", "The author-input Kz=1, ENCUT=500 eV, EDIFF=1e−5 series is stored and fit separately in raman_modes.json; it is not mixed with the tight-main route table above.", ""]
    (final / "raman_modes.json").write_text(json.dumps(raman, indent=2) + "\n")
    (final / "convergence.md").write_text("\n".join(convergence_text))
    provenance = {
        "case": "case-06-pressure-dft-raman-phonons",
        "delivery_scope": "scientific fixed-pressure finite-displacement DFT reference and Raman-mode tracking; mirror/scorer integration is external",
        "rebuild_command": "final/engine_io/scripts/build_final.command (full main, supplement, convergence-control and author-mode-seed input paths are recorded in this runnable command)",
        "main_pressure_points_GPa": pressures,
        "main_job_ids": [r["job_id"] for r in runs],
        "main_runtime_setup": {"kpoint_grid": runs[0]["kpoint_grid"], "ENCUT_eV": actual(runs[0], "ENCUT"), "EDIFF_eV": actual(runs[0], "EDIFF"), "POTIM_A": runs[0]["effective_tags_from_last_OUTCAR_block"]["POTIM_A"], "NFREE": runs[0]["effective_tags_from_last_OUTCAR_block"]["NFREE"], "effective_NSW": runs[0]["effective_tags_from_last_OUTCAR_block"]["NSW"], "PSTRESS_kbar_by_pressure": {str(r["pressure_GPa"]): r["PSTRESS_kbar"] for r in runs}},
        "engine": {"VASP_banner_by_pressure": {str(r["pressure_GPa"]): r["engine_provenance"]["version_banner"] for r in runs}, "binary_sha256_by_pressure": {str(r["pressure_GPa"]): r["engine_provenance"]["ENGINE_txt"].get("vasp_sha256") for r in runs}, "launcher": "Intel MPI mpirun -launcher slurm -np 16", "scheduler": "Slurm, partition cpu, account ai4eccsc, QOS normal"},
        "POTCAR_component_and_combined_identity_sha256_by_pressure": {str(r["pressure_GPa"]): r["potential_identity_sha256"] for r in runs},
        "branch_slopes_d_omega_dP_cm-1_per_GPa": raman["d_omega_dP"],
        "branch_linear_fit_residuals": {name: fit["residuals"] for name, fit in raman["linear_fits"].items()},
        "mode_assignment": {"point_group": sorted({r["point_group"] for r in runs}), "primary_0GPa_modes": raman["primary_0GPa_layer_parity_assignment"], "POSCAR_inversion_map_and_eigenvector_parity": "Recorded for each selected mode in raman_modes.json; polar-vector inversion is -u(mapped_atom), and gerade eigenvalue is +1; mode3 is A1g, mode4 is an ungerade neighbor."},
        "author_precision_supplement_job_ids": [r["job_id"] for r in supplementary_runs],
        "limits": ["No ionic/structural relaxation was performed; each pressure uses its deposited POSCAR.", "Denser Kz results are 0-GPa frozen-geometry controls and shift pressure/forces; they do not provide an equilibrated higher-grid reference.", "No identical duplicate run or Raman intensity tensor was calculated.", "The tighter EDIFF endpoint check was done at 9 GPa; no next-tighter endpoint checks were made at 3 or 6 GPa.", "No universal scorer frequency tolerance is proposed."],
        "raw_engine_evidence": "final/engine_io/runs and final/engine_io/resources; POTCAR bytes are excluded, hashes only.",
    }
    (final / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    readme = [
        "# Case 06 scientific results", "",
        "This directory contains the case-specific scientific calculation outputs and machine-readable Raman results. The user will connect the mirror and scorer separately; no scorer or readiness state is modified here.", "",
        f"The primary reference is a four-point 0/3/6/9 GPa finite-displacement calculation using the deposited pressure-specific POSCARs, Gamma-centred {runs[0]['kpoint_grid']}, ENCUT={actual(runs[0],'ENCUT'):g} eV, and EDIFF={actual(runs[0],'EDIFF'):g} eV. It uses the site VASP 6.4.1 CPU binary and Intel MPI under Slurm. Explicit NSW=1, NFREE=2, and POTIM=0.015 Å were added to the author inputs; VASP internally uses effective NSW={runs[0]['effective_tags_from_last_OUTCAR_block']['NSW']} for IBRION=6. Runtime input tags, SCF stop counts, JobIDs, engine/potential identities and raw artifacts are included.", "",
        "`phonons.json` contains all 18 signed Γ frequencies and initial pressure/force state for each pressure. `raman_modes.json` contains the parity/layer-resolved E2g2, E2g1 and A1g branches, the explicit `d_omega_dP` values in cm⁻¹/GPa, and the four-point unweighted OLS fits with residuals. The mode assignment is based on observed D6h symmetry and a POSCAR-derived inversion map of Mo1↔Mo2, S1↔S4 and S2↔S3. Polar-vector inversion flips sign, so mode 3 is the gerade A1g candidate; mode 4 is the nearby ungerade mode. The earlier tentative mode-4 seed was corrected and is documented in the JSON.", "",
        "`pressure_state.md` reports target PSTRESS, stress-trace pressure, VASP external-pressure residuals and max initial forces. `convergence.md` separates the 0-GPa EDIFF ladder, same-EDIFF Kz and ENCUT controls, the 9-GPa tighter-EDIFF endpoint check, and the older author-precision controls. It records the frozen-geometry limitation of denser Kz runs and deliberately gives no universal frequency tolerance.", "",
        "`engine_io/` preserves raw run input/output, scheduler and resource records, input and binary/potential hashes, and a checksum manifest. POTCAR bytes are excluded from this export; identity hashes are retained. `provenance.json` summarizes the route and its scientific limits. Rebuild all generated outputs with `engine_io/scripts/build_final.command`; the command lists the primary runs, author-route supplement, every control OUTCAR and the branch seed explicitly.", "",
    ]
    (final / "README.md").write_text("\n".join(readme))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--outcar", action="append", default=[], help="PRESSURE=PATH, repeat for 0,3,6,9")
    parser.add_argument("--oszicar", action="append", default=[], help="PRESSURE=PATH, optional")
    parser.add_argument("--convergence-outcar", action="append", default=[], help="LABEL=PATH, repeat for grid or electronic convergence runs")
    parser.add_argument("--supplementary-outcar", action="append", default=[], help="PRESSURE=PATH, repeat for a separate 0,3,6,9 GPa supplement route")
    args = parser.parse_args()
    parse_map = lambda items: {float(k): Path(v) for k, v in (item.split("=", 1) for item in items)}
    outcars = parse_map(args.outcar)
    oszicars = parse_map(args.oszicar)
    if set(outcars) != {0.0, 3.0, 6.0, 9.0}:
        parser.error("provide --outcar for exactly 0, 3, 6, and 9 GPa")
    convergence_runs = {}
    for item in args.convergence_outcar:
        prefix, path = item.rsplit("=", 1)
        if ":" in prefix:
            pressure_text, label = prefix.split(":", 1)
            try:
                pressure = float(pressure_text)
            except ValueError:
                parser.error(f"invalid convergence pressure: {pressure_text}")
        else:
            pressure, label = 0.0, prefix
        if label == "Kz=1" or label in convergence_runs:
            parser.error("convergence labels must be unique")
        convergence_runs[label] = (pressure, Path(path))
    supplementary_outcars = parse_map(args.supplementary_outcar)
    if supplementary_outcars and set(supplementary_outcars) != {0.0, 3.0, 6.0, 9.0}:
        parser.error("supplementary route requires exactly 0, 3, 6, and 9 GPa")
    write_outputs(args.root, outcars, oszicars, convergence_runs, supplementary_outcars, args.seed)


if __name__ == "__main__":
    main()
