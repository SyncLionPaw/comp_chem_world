#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d "${TMPDIR:-/tmp}/bench06-oracle.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
ASSETS=${ASSETS_DIR:-/app/environment/assets}
OUT=${OUTPUT_DIR:-/app/final}
[ -d "$ASSETS" ] || { echo "missing public assets: $ASSETS" >&2; exit 2; }
mkdir -p "$OUT"
cat > "$work/analysis.py" <<'BENCH06_PY_40_0'
#!/usr/bin/env python3
"""Recompute Case 05 revision-3 local-response diagnostics from frozen VASP evidence."""
import csv
import hashlib
import json
import math
import os
import re
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


REQUIRED_POINTS = 13
MAX_HISTORICAL_FORCE_EVALUATIONS = 24
SHIFT_A = 0.02
ABS_TOL = 0.05
REL_TOL = 0.05
TRIPLES = ("water-r26", "water-r30", "2K-r26", "2K-r30")
POINT_IDS = (
    "water-r26-minus", "water-r26-center", "water-r26-plus",
    "water-r30-minus", "water-r30-center", "water-r30-plus",
    "2K-r26-minus", "2K-r26-center", "2K-r26-plus",
    "2K-r30-minus", "2K-r30-center", "2K-r30-plus",
    "2K-r26-alt-center",
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_native(asset_dir):
    """Read an unpacked fixture or a path-safe tar archive, never following archive links."""
    asset_dir = Path(asset_dir)
    archive = asset_dir / "IS_native.tar.gz"
    if archive.is_file():
        members = {}
        manifest_path = asset_dir / "IS_native_manifest.json"
        manifest = json_read(manifest_path) if manifest_path.is_file() else {}
        archive_digest = sha256(archive)
        if manifest.get("archive_sha256") and archive_digest != manifest["archive_sha256"].removeprefix("sha256:"):
            raise ValueError("native archive SHA-256 mismatch")
        with tarfile.open(archive, "r:gz") as tf:
            for m in tf.getmembers():
                p = PurePosixPath(m.name)
                if p.is_absolute() or ".." in p.parts or not p.parts:
                    raise ValueError("unsafe native archive member path")
                if m.issym() or m.islnk() or not (m.isfile() or m.isdir()):
                    raise ValueError("native archive contains a non-regular member")
                if m.isfile():
                    src = tf.extractfile(m)
                    if src is None:
                        raise ValueError("native archive member unreadable")
                    members[p.as_posix()] = src.read()
        if manifest:
            expected = manifest.get("files", manifest.get("sha256", {}))
            if isinstance(expected, dict):
                for name, value in expected.items():
                    digest = value.get("sha256") if isinstance(value, dict) else value
                    digest = str(digest).removeprefix("sha256:")
                    if name in members and hashlib.sha256(members[name]).hexdigest() != digest:
                        raise ValueError("native archive source hash mismatch: " + name)
                    if name not in members:
                        raise ValueError("manifest native source missing from archive: " + name)
        with tempfile.TemporaryDirectory(prefix="case05-native-") as td:
            root = Path(td)
            for name, data in members.items():
                dest = root.joinpath(*PurePosixPath(name).parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            yield_root = root
            return analyze_native(yield_root, asset_dir)
    # Developer mode for the author copy; runtime fixtures should use the archive.
    if (asset_dir / "native").is_dir():
        return analyze_native(asset_dir, asset_dir)
    raise ValueError("ASSET_DIR must contain IS_native.tar.gz and IS_native_manifest.json")


def parse_poscar(path):
    lines = Path(path).read_text().splitlines()
    scale = float(lines[1].split()[0])
    cell = [[float(x) * scale for x in lines[i].split()[:3]] for i in range(2, 5)]
    symbols = lines[5].split()
    counts = [int(x) for x in lines[6].split()]
    if len(symbols) != len(counts):
        raise ValueError("POSCAR species/count mismatch")
    i = 7
    if lines[i].strip().lower().startswith("s"):
        i += 1
    mode = lines[i].strip().lower()
    i += 1
    species = [s for s, n in zip(symbols, counts) for _ in range(n)]
    coords = [[float(x) for x in lines[i + j].split()[:3]] for j in range(len(species))]
    if mode.startswith("d"):
        coords = [[sum(coords[k] * cell[k][j] for k in range(3)) for j in range(3)] for coords in coords]
    elif not mode.startswith(("c", "k")):
        raise ValueError("unknown POSCAR coordinate mode")
    return {"cell": cell, "species": species, "cart": coords}


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def delta(a, b):
    return [x - y for x, y in zip(a, b)]


def periodic_vector(pos, i, j):
    d = delta(pos["cart"][i], pos["cart"][j])
    images = [[d[k]-a*pos["cell"][0][k]-b*pos["cell"][1][k]-c*pos["cell"][2][k] for k in range(3)]
              for a in (-1,0,1) for b in (-1,0,1) for c in (-1,0,1)]
    return min(images, key=norm)


def periodic_distance(pos, i, j):
    return norm(periodic_vector(pos, i, j))


def extxyz_frame(path, requested_id):
    lines = Path(path).read_text().splitlines()
    offset = 0
    while offset < len(lines):
        count = int(lines[offset].strip())
        header = lines[offset+1]
        if f"seed_id={requested_id}" in header:
            match = re.search(r'Lattice="([^"]+)"', header)
            if not match:
                raise ValueError("seed geometry lacks cell matrix")
            values = [float(x) for x in match.group(1).split()]
            cell = [values[3*i:3*i+3] for i in range(3)]
            atoms = [lines[offset+2+i].split() for i in range(count)]
            return {"cell": cell, "species": [a[0] for a in atoms],
                    "cart": [[float(x) for x in a[1:4]] for a in atoms]}
        offset += count + 2
    raise ValueError("seed candidate not found in public geometry panel: " + requested_id)


def co_angle(pos, co2):
    v1 = periodic_vector(pos, co2[1], co2[0])
    v2 = periodic_vector(pos, co2[2], co2[0])
    cosine = max(-1.0, min(1.0, dot(v1, v2)/(norm(v1)*norm(v2))))
    return math.degrees(math.acos(cosine))


def xml_point(attempt_dir, point):
    tree = ET.parse(attempt_dir / "vasprun.xml")
    root = tree.getroot()
    calcs = root.findall("calculation")
    if not calcs:
        raise ValueError("vasprun.xml has no calculations")
    calc = calcs[-1]
    e = calc.find('./energy/i[@name="e_fr_energy"]')
    fv = calc.find('./varray[@name="forces"]')
    if e is None or fv is None:
        raise ValueError("final XML calculation missing free energy or forces")
    forces = [[float(v) for v in row.text.split()[:3]] for row in fv.findall("v")]
    inds = point["CO2_indices_zero_based"]
    direction = point["direction_Au_to_C"]
    if max(inds) >= len(forces):
        raise ValueError("CO2 force index exceeds XML atom count")
    gradient = -sum(dot(forces[i], direction) for i in inds)
    scf = len(root.findall(".//scstep"))
    return float(e.text), gradient, scf, len(forces)


def analyze_native(root, asset_dir=None):
    root = Path(root)
    points = json_read(root / "points.json")
    if isinstance(points, dict):
        points = points.get("points")
    ledger = [json.loads(line) for line in (root / "native/force-budget.jsonl").read_text().splitlines() if line.strip()]
    by_id = {p["point_id"]: p for p in points}
    potcar_provenance = json_read(root / "potcar-provenance.json")
    potcar_hashes = {p["point_id"]: p["sha256"] for p in potcar_provenance["points"]}
    if len(points) != REQUIRED_POINTS or set(by_id) != set(POINT_IDS):
        raise ValueError("native point set/count does not match frozen revision-3 reference")
    if len(ledger) != REQUIRED_POINTS or len({x.get("point_id") for x in ledger}) != REQUIRED_POINTS:
        raise ValueError("historical force budget ledger does not account for 13 unique calls")
    rows = []
    geometry = {}
    source_hashes = {}
    for n, pid in enumerate(POINT_IDS, 1):
        p = by_id[pid]
        attempt = root / "native" / f"attempt-{n:03d}"
        inp = json_read(attempt / "input.json")
        if inp.get("point_id") != pid or inp.get("point") != p:
            raise ValueError("native input-to-point mapping mismatch: " + pid)
        for name in ("POSCAR", "INCAR", "KPOINTS"):
            expected = inp.get("input_sha256", {}).get(name)
            if not expected or sha256(attempt / name) != expected:
                raise ValueError("native input hash mismatch: " + pid + "/" + name)
        if inp.get("point", {}).get("POTCAR_sha256") != potcar_hashes.get(pid) or inp.get("input_sha256", {}).get("POTCAR") != potcar_hashes.get(pid):
            raise ValueError("native POTCAR source-provenance mismatch: " + pid)
        for name in ("vasprun.xml", "OUTCAR", "POSCAR", "INCAR", "KPOINTS", "OSZICAR", "input.json"):
            source_hashes[f"native/attempt-{n:03d}/{name}"] = sha256(attempt / name)
        energy, gradient, scf, natoms = xml_point(attempt, p)
        pos = parse_poscar(attempt / "POSCAR")
        if natoms != len(pos["species"]):
            raise ValueError("XML/POSCAR atom-count mismatch: " + pid)
        incar = (attempt / "INCAR").read_text()
        outcar = (attempt / "OUTCAR").read_text(errors="replace")
        oszicar_text = (attempt / "OSZICAR").read_text()
        oszicar_steps = len(re.findall(r"^(?:DAV|RMM|CG|DMP):\s*\d+", oszicar_text, re.M))
        def incar_value(name):
            match = re.search(r"^\s*" + re.escape(name) + r"\s*=\s*([^!#\n]+)", incar, re.I | re.M)
            return match.group(1).strip().lower() if match else None
        expected_controls = {"ENCUT": "400", "GGA": "pe", "IVDW": "11", "NSW": "0", "IBRION": "-1",
                             "ISMEAR": "1", "SIGMA": "0.20", "EDIFF": "1e-5"}
        controls_ok = all(incar_value(k) is not None and float(incar_value(k)) == float(v)
                          if k in {"ENCUT", "SIGMA", "EDIFF"} else incar_value(k) == v
                          for k, v in expected_controls.items())
        kpoints_ok = re.search(r"^\s*3\s+3\s+1\s*$", (attempt / "KPOINTS").read_text(), re.M) is not None
        direction_norm = norm(p["direction_Au_to_C"])
        static_ok = controls_ok and kpoints_ok
        scf_ok = "aborting loop because EDIFF is reached" in outcar and oszicar_steps == scf
        if not static_ok or not scf_ok or abs(direction_norm-1.0) > 1e-8:
            raise ValueError("native point did not satisfy static/SCF convergence audit: " + pid)
        result = {
            "point_id": pid, "system": p["system"], "kind": p["kind"],
            "center_id": p["center_id"], "q_center_A": p["q_center_A"],
            "shift_A": p["shift_A"], "point": p, "poscar": pos,
            "energy": energy, "gradient": gradient, "scf": scf,
            "scf_converged": scf_ok, "static_input": static_ok,
            "method_controls": {"required_controls_match": controls_ok, "kpoints_3x3x1": kpoints_ok,
                                "CO2_direction_norm": direction_norm},
            "native_id": f"native/attempt-{n:03d}", "attempt": attempt,
        }
        rows.append(result)
        geometry[pid] = result

    by_center = {}
    for row in rows:
        by_center.setdefault(row["center_id"], []).append(row)
    center_stats = {}
    for center in TRIPLES:
        group = sorted(by_center.get(center, []), key=lambda r: r["shift_A"])
        if len(group) != 3 or [r["shift_A"] for r in group] != [-SHIFT_A, 0.0, SHIFT_A]:
            raise ValueError("incomplete or incorrectly spaced three-point path: " + center)
        minus, middle, plus = group
        fd = (plus["energy"] - minus["energy"]) / (2 * SHIFT_A)
        diff = abs(middle["gradient"] - fd)
        threshold = ABS_TOL + REL_TOL * max(abs(middle["gradient"]), abs(fd))
        center_stats[center] = {"finite_difference_gradient_eV_per_A": fd,
                                "force_gradient_eV_per_A": middle["gradient"],
                                "deviation_eV_per_A": diff,
                                "threshold_eV_per_A": threshold,
                                "consistent": diff <= threshold,
                                "local_zero_energy_eV": middle["energy"],
                                "system": middle["point"]["system"],
                                "q_center_A": middle["point"]["q_center_A"]}

    # Verify structures from the actual POSCARs: same cell and environment, with CO2 translated rigidly.
    path_checks = {}
    for center in TRIPLES:
        group = [r for r in rows if r["center_id"] == center]
        center_row = next(r for r in group if r["shift_A"] == 0)
        base = center_row["poscar"]
        co2 = center_row["point"]["CO2_indices_zero_based"]
        u = center_row["point"]["direction_Au_to_C"]
        checks = []
        for row in group:
            pos = row["poscar"]
            same_env = pos["species"] == base["species"] and all(abs(pos["cell"][i][j]-base["cell"][i][j]) < 1e-8 for i in range(3) for j in range(3))
            cind, auind = row["point"]["C_Au_indices_zero_based"]
            observed_cv = periodic_distance(pos, cind, auind)
            expected_cv = row["q_center_A"] + row["shift_A"]
            actual_au_to_c = periodic_vector(pos, cind, auind)
            actual_unit = [x/observed_cv for x in actual_au_to_c]
            direction_error = norm(delta(actual_unit, u))
            max_co2_error = 0.0
            max_env_move = 0.0
            for i, (actual, origin) in enumerate(zip(pos["cart"], base["cart"])):
                d = delta(actual, origin)
                # VASP coordinates may wrap across a cell boundary; reduce by lattice vectors.
                # Enumerating nearby images handles the non-orthogonal slab cell robustly.
                d = periodic_vector({"cell": pos["cell"], "cart": [actual, origin]}, 0, 1)
                if i in co2:
                    max_co2_error = max(max_co2_error, norm(delta(d, [row["shift_A"]*x for x in u])))
                else:
                    max_env_move = max(max_env_move, norm(d))
            checks.append({"point_id": row["point_id"], "cell_species_match": same_env,
                           "observed_C_Au_distance_A": observed_cv,
                           "expected_C_Au_distance_A": expected_cv,
                           "C_Au_distance_error_A": abs(observed_cv-expected_cv),
                           "Au_to_C_direction_error": direction_error,
                           "max_CO2_translation_error_A": max_co2_error,
                           "max_environment_displacement_A": max_env_move})
        path_checks[center] = {"points": checks,
                               "pass": all(c["cell_species_match"] and c["C_Au_distance_error_A"] < 2e-5 and c["Au_to_C_direction_error"] < 1e-8 and c["max_CO2_translation_error_A"] < 2e-5 and c["max_environment_displacement_A"] < 2e-5 for c in checks)}

    # Explicitly audit the central/alternate structures at the shared 2K, 2.6 A nominal CV.
    center = geometry["2K-r26-center"]["poscar"]
    alt = geometry["2K-r26-alt-center"]["poscar"]
    cv_indices = geometry["2K-r26-center"]["point"]["C_Au_indices_zero_based"]
    cind, auind = cv_indices
    cv_main, cv_alt = periodic_distance(center, cind, auind), periodic_distance(alt, cind, auind)
    alt_direction = geometry["2K-r26-alt-center"]["point"]["direction_Au_to_C"]
    alt_vector = periodic_vector(alt, cind, auind)
    alt_direction_error = norm(delta([x/cv_alt for x in alt_vector], alt_direction))
    co2i = geometry["2K-r26-center"]["point"]["CO2_indices_zero_based"]
    def co_bond(pos): return periodic_distance(pos, co2i[0], co2i[1]), periodic_distance(pos, co2i[0], co2i[2])
    main_bond, alt_bond = co_bond(center), co_bond(alt)
    init_sensitivity = geometry["2K-r26-alt-center"]["gradient"] - geometry["2K-r26-center"]["gradient"]
    sys_effects = {}
    for q in (2.6, 3.0):
        w = center_stats[f"water-r{int(10*q)}"]["force_gradient_eV_per_A"]
        k = center_stats[f"2K-r{int(10*q)}"]["force_gradient_eV_per_A"]
        sys_effects[str(q)] = {"water_gradient_eV_per_A": w, "2K_gradient_eV_per_A": k,
                               "2K_minus_water_eV_per_A": k-w}

    method_checks = {r["point_id"]: r["method_controls"] for r in rows}
    source_hashes["points.json"] = sha256(root / "points.json")
    source_hashes["native/force-budget.jsonl"] = sha256(root / "native/force-budget.jsonl")
    source_hashes["potcar-provenance.json"] = sha256(root / "potcar-provenance.json")
    unselected = None
    if asset_dir is not None:
        asset_dir = Path(asset_dir)
        seed_records = json_read(asset_dir / "IS_seed_provenance.json")["records"]
        source_hashes["IS_seed_panel.extxyz"] = sha256(asset_dir / "IS_seed_panel.extxyz")
        source_hashes["IS_seed_provenance.json"] = sha256(asset_dir / "IS_seed_provenance.json")
        record = next(r for r in seed_records if r["seed_id"] == "2K-SG-1713")
        seed = extxyz_frame(asset_dir / "IS_seed_panel.extxyz", record["seed_id"])
        seed_co2 = geometry["2K-r30-center"]["point"]["CO2_indices_zero_based"]
        seed_c, seed_au = record["carbon_index_zero_based"], record["nearest_Au_index_zero_based"]
        target = geometry["2K-r30-center"]["poscar"]
        def seed_metrics(pos, co2, cidx, auidx):
            nearest_k = min(periodic_distance(pos, cidx, i) for i, s in enumerate(pos["species"]) if s == "K")
            non_co2_oxygen = [i for i, s in enumerate(pos["species"]) if s == "O" and i not in co2]
            nearest_water_o = min(periodic_distance(pos, cidx, i) for i in non_co2_oxygen)
            return {"C_Au_distance_A": periodic_distance(pos, cidx, auidx),
                    "CO_bond_lengths_A": [periodic_distance(pos, co2[0], co2[1]), periodic_distance(pos, co2[0], co2[2])],
                    "OCO_angle_deg": co_angle(pos, co2), "nearest_K_to_C_A": nearest_k,
                    "nearest_non_CO2_oxygen_to_C_A": nearest_water_o}
        unselected = {"seed_id": record["seed_id"], "source_frame_zero_based": record["frame_zero_based"],
                      "source_geometry_sha256": json_read(asset_dir / "IS_seed_provenance.json")["panel_sha256"],
                      "metrics": seed_metrics(seed, seed_co2, seed_c, seed_au),
                      "comparison_selected_point": "2K-r30-center",
                      "selected_metrics": seed_metrics(target, seed_co2, seed_c, seed_au),
                      "selection_status": "not selected for the frozen force-gradient comparison; no paired +/-h energies exist for this distinct seed",
                      "information_tradeoff": "Adds a distinct independently sourced interface snapshot in the nearby 3.0 A C-Au range, but comparing one seed geometry to the chosen static center without a matched displacement triplet cannot estimate a local gradient."}

    response = []
    for r in rows:
        stat = center_stats.get(r["center_id"])
        response.append({"point_id": r["point_id"], "system": r["point"]["system"],
                         "center_id": r["center_id"], "kind": r["kind"], "shift_A": r["shift_A"],
                         "electronic_free_energy_eV": r["energy"],
                         "local_zero_energy_eV": stat["local_zero_energy_eV"] if stat else None,
                         "local_zeroed_energy_eV": r["energy"]-stat["local_zero_energy_eV"] if stat else None,
                         "rigid_CO2_gradient_eV_per_A": r["gradient"],
                         "finite_difference_gradient_eV_per_A": stat["finite_difference_gradient_eV_per_A"] if stat else None,
                         "deviation_eV_per_A": stat["deviation_eV_per_A"] if stat else None,
                         "threshold_eV_per_A": stat["threshold_eV_per_A"] if stat else None,
                         "finite_difference_consistent": stat["consistent"] if stat else None,
                         "SCF_iterations": r["scf"], "native_id": r["native_id"]})

    calculations = sum(int(x.get("reserved_force_evaluations", 0)) for x in ledger)
    return {"rows": response, "center_stats": center_stats, "path_checks": path_checks,
            "method_checks": method_checks, "unselected_geometry": unselected,
            "geometry": {"2K_r26_center_C_Au_A": cv_main, "2K_r26_alt_C_Au_A": cv_alt,
                         "2K_r26_alt_Au_to_C_direction_error": alt_direction_error,
                         "2K_r26_center_CO_A_A": main_bond[0], "2K_r26_center_CO_B_A": main_bond[1],
                         "2K_r26_alt_CO_A_A": alt_bond[0], "2K_r26_alt_CO_B_A": alt_bond[1]},
            "initial_state_gradient_difference_eV_per_A": init_sensitivity,
            "system_effects": sys_effects, "historical_force_evaluations": calculations,
            "source_hashes": source_hashes,
            "native_ids": [r["native_id"] for r in rows], "inputs": rows}


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def build_outputs(result, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stats = result["center_stats"]
    selection = {
        "schema": "case05-selection/v1", "interpretation_timing": "retrospective",
        "selected_centers": [{"center_id": c, "system": stats[c]["system"],
                              "C_Au_distance_A": stats[c]["q_center_A"],
                              "point_ids": [r["point_id"] for r in result["rows"] if r["center_id"] == c],
                              "CO2_indices_zero_based": next(r["point"]["CO2_indices_zero_based"] for r in result["inputs"] if r["center_id"] == c),
                              "direction_Au_to_C": next(r["point"]["direction_Au_to_C"] for r in result["inputs"] if r["center_id"] == c)} for c in TRIPLES],
        "same_CV_alternate_initial_state": {"point_id": "2K-r26-alt-center", "paired_center": "2K-r26-center",
                                            "nominal_C_Au_distance_A": 2.6,
                                            "input_geometry_metrics": result["geometry"]},
        "unselected_geometry_comparison": result["unselected_geometry"],
        "alternative_comparison": {"candidate": "2K-SG-1713 distinct source snapshot near the selected 2K-r30 C-Au distance",
                                   "measured_comparison": result["unselected_geometry"],
                                   "rejection_reason": "This independent seed has no matching -h/center/+h static outputs; its geometry alone cannot provide a local response estimate.",
                                   "information_gain": "Would add an independent structural snapshot and expand configuration diversity if a matched static triplet were later acquired.",
                                   "basis": "Observed same-CV initialization gradient difference and the four measured local gradients",
                                   "opportunity_cost": "A complete triplet would cost 3 static force evaluations from the 11 historical reserve, leaving 8 for other targeted checks.",
                                   "timing": "retrospective; this comparison was not documented as a pre-submission decision."},
        "scope": "fixed-environment neutral-charge static local response and observed initialization sensitivity only"}
    write_json(out / "selection.json", selection)

    d = result["initial_state_gradient_difference_eV_per_A"]
    errors = {k: stats[k]["deviation_eV_per_A"] for k in TRIPLES}
    max_error = max(errors.values())
    max_scope_effect = max(abs(v["2K_minus_water_eV_per_A"]) for v in result["system_effects"].values())
    hypotheses = {
        "schema": "case05-hypotheses/v1", "preregistration_status": "RETROSPECTIVE_NOT_PRE_REGISTERED",
        "explanations": [
            {"id": "local_fixed_environment_response", "support_code": "OBSERVED_LOCAL_RESPONSE", "claim": "Rigid CO2 displacement has a local potential-energy response that depends on the sampled interface and C-Au location.",
             "observable_predictions": ["centered energy slopes and raw force projections are finite and numerically comparable", "measured gradients may differ across water and 2K sampled structures"],
             "observed": {"local_force_gradients_eV_per_A": {k: stats[k]["force_gradient_eV_per_A"] for k in TRIPLES}, "water_vs_2K_gradient_differences_eV_per_A": result["system_effects"]},
             "support": "supported_as_a_description_of_this_finite_sample" if max_scope_effect > 0 else "not_resolved",
             "falsifier": "Native forces fail the declared projection/sign convention or the paired energy derivative is inconsistent beyond the frozen diagnostic threshold.",
             "remaining_confounders": ["different interface microstructures and cation coordination co-vary", "single neutral-charge static configurations do not represent equilibrium averages"]},
            {"id": "initial_state_and_path_confounding", "support_code": "OBSERVED_PAIR_DIFFERENCE", "claim": "The same nominal CV can conceal distinct configurations with different local responses.",
             "observable_predictions": ["same-CV center and alternate center have distinct geometry and/or projected gradients"],
             "observed": {"gradient_difference_alt_minus_center_eV_per_A": d, "same_CV_C_Au_distances_A": [result["geometry"]["2K_r26_center_C_Au_A"], result["geometry"]["2K_r26_alt_C_Au_A"]],
                          "CO_bond_lengths_center_A": [result["geometry"]["2K_r26_center_CO_A_A"], result["geometry"]["2K_r26_center_CO_B_A"]],
                          "CO_bond_lengths_alt_A": [result["geometry"]["2K_r26_alt_CO_A_A"], result["geometry"]["2K_r26_alt_CO_B_A"]]},
             "support": "supported_for_this_pair; multiple structural variables change together",
             "falsifier": "An independent geometry audit shows the alternate is not a distinct configuration at the same nominal CV.",
             "remaining_confounders": ["the alternate simultaneously changes bending, hydration, and coordination; this does not isolate a single cause"]},
            {"id": "numerical_estimation_error", "support_code": "WITHIN_DIAGNOSTIC_THRESHOLD" if all(v["consistent"] for v in stats.values()) else "THRESHOLD_EXCEEDED", "claim": "Finite-step energy differences and electronic-force derivatives may disagree due to numerical estimation error.",
             "observable_predictions": ["absolute force-versus-difference deviations can be compared to 0.05 eV/A + 5% of the larger slope magnitude"],
             "observed": {"deviations_eV_per_A": errors, "diagnostic_thresholds_eV_per_A": {k: stats[k]["threshold_eV_per_A"] for k in TRIPLES}, "maximum_deviation_eV_per_A": max_error},
             "support": "all_four_pairs_within_frozen_diagnostic_threshold" if all(v["consistent"] for v in stats.values()) else "at_least_one_pair_exceeds_threshold_and_is_retained",
             "falsifier": "A future h/2 or tighter-SCF derivative that shifts beyond the same diagnostic tolerance would falsify numerical stability for the affected center; agreement would lower, not eliminate, this concern.",
             "remaining_confounders": ["one displacement step size only", "SCF tolerance and smearing sensitivity were not independently varied", "the tolerance is not a statistical confidence interval"]}
        ],
        "scope_flags": {"retrospective": True, "equilibrium_mean_force": False, "equilibrium_free_energy": False,
                         "transition_state_or_barrier": False, "global_adsorption_stability": False,
                         "constant_potential_cation_effect": False, "single_variable_causal_attribution": False,
                         "statistical_confidence_interval": False},
        "expert_extensions": {"status": "REVIEW_REQUIRED", "description": "Any explanation beyond the frozen numerical/path protocol requires evaluator review and cannot substitute for the machine-checkable claims."}
    }
    write_json(out / "hypotheses.json", hypotheses)

    with (out / "response.csv").open("w", newline="", encoding="utf-8") as f:
        fields = list(result["rows"][0].keys())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(result["rows"])

    path_audit = {
        "schema": "case05-path-audit/v1", "historical_native_points": len(result["rows"]),
        "historical_force_evaluations": result["historical_force_evaluations"],
        "historical_budget_limit": MAX_HISTORICAL_FORCE_EVALUATIONS,
        "new_scientific_calls_during_analysis": 0,
        "new_calculation_authorized": False,
        "source_hashes": result["source_hashes"],
        "static_path_checks": result["path_checks"],
        "method_control_checks": result["method_checks"],
        "centered_difference_checks": result["center_stats"],
        "symbols": "force_gradient = -sum(F_CO2 dot u_Au_to_C); energy derivative uses (E_fr(+h)-E_fr(-h))/(2h); eV and Angstrom",
        "energy_definition": "VASP electronic free energy e_fr_energy at finite smearing, not an adsorption/free-energy profile",
        "energy_zero": "Each three-point center is shifted by its own center e_fr_energy; no cross-environment absolute energy differences.",
        "attempt_validation": {"expected_static_points": REQUIRED_POINTS, "actual_static_points": len(result["rows"]),
                               "all_status_converged": all(x["scf_converged"] for x in result["inputs"]),
                               "all_inputs_static": all(x["static_input"] for x in result["inputs"]),
                               "ledger_unique_calls": result["historical_force_evaluations"],
                               "within_historical_24_call_budget": result["historical_force_evaluations"] <= MAX_HISTORICAL_FORCE_EVALUATIONS},
        "equilibrium_deltaA_eV": None, "equilibrium_CI": None,
        "scope": "fixed-environment static neutral-charge local response and one multi-variable alternate initialization comparison"}
    write_json(out / "path_audit.json", path_audit)

    options = [
        {"priority": 1, "action": "Complete the 2K-r26 alternate-center energy derivative with its missing -h/+h static points",
         "cost_force_evaluations": 2, "opportunity_cost": "Uses 2 of the 11 historical reserve calls; leaves 9.",
         "evidence_pointer": "path_audit.json:/centered_difference_checks/2K-r26; hypotheses.json:/explanations/1/observed",
         "outcome_branches": ["If its energy slope agrees with the alternate center force projection, the large center-to-alternate difference is less likely to be a single-point numerical artifact.",
                              "If its slope disagrees beyond threshold, retain an unresolved method/step issue and do not interpret the alternate gradient as a robust initialization effect."],
         "trigger_rule": "Preferred because the only alternate geometry has a force value but no matched finite-difference derivative."},
        {"priority": 2, "action": "Evaluate two additional 2K structures at nominal C-Au 2.6 A with complete +/-h triplets",
         "cost_force_evaluations": 6, "opportunity_cost": "Uses 6 calls; together with priority 1 uses 8 and leaves 3 for one precision triplet.",
         "evidence_pointer": "hypotheses.json:/explanations/1/observed; selection.json:/same_CV_alternate_initial_state",
         "outcome_branches": ["If gradients span a broad range, report finite-sample initialization sensitivity without assigning it to one geometry variable.",
                              "If both cluster near the base center, weaken generalization from the original alternate pair."],
         "trigger_rule": "Consider only after alternate-center derivative is numerically checked."},
        {"priority": 3, "action": "Run one h/2 three-point triplet for a preselected already measured center",
         "cost_force_evaluations": 3, "opportunity_cost": "Uses the remaining 3 calls after priority 1; combined with the 6-call matched-structure option totals 11.",
         "evidence_pointer": "path_audit.json:/centered_difference_checks",
         "outcome_branches": ["If the smaller-step slope and force projection remain stable, step-size error is less plausible for that center.",
                              "If they move materially, report finite-step sensitivity and avoid extending the derivative claim."],
         "trigger_rule": "Select the center with the largest absolute force-versus-difference deviation in the frozen data."}
    ]
    decision = {"schema": "case05-decision-log/v1", "timing": "retrospective reconstruction from completed evidence; not a contemporaneous preregistration",
               "evidence_received": [{"pointer": "native/manifest.json:/reference_native_ids", "summary": "13 converged static native outputs; no failed call is present in the force budget ledger."},
                                     {"pointer": "path_audit.json:/centered_difference_checks", "summary": "Four force projections compared with same-center e_fr_energy differences."},
                                     {"pointer": "hypotheses.json:/explanations/1", "summary": "One same nominal-CV 2K alternate structure with simultaneous geometry changes."}],
               "historical_calls": result["historical_force_evaluations"], "historical_budget": MAX_HISTORICAL_FORCE_EVALUATIONS,
               "historical_remaining_calls": MAX_HISTORICAL_FORCE_EVALUATIONS-result["historical_force_evaluations"],
               "new_calls_in_this_replay": 0, "options": options,
               "no_calculation_authorized": True,
               "decision_rule": "Choose follow-up only after evaluator review and separate explicit user authorization; deadlines or unused historical budget do not authorize submission."}
    write_json(out / "decision_log.json", decision)
    next_calc = {"schema": "case05-next-calculation/v1", "recommendation": "NO_NEW_CALCULATION_IN_THIS_REPLAY",
                 "new_calculation_authorized": False, "new_scientific_calls": 0,
                 "historical_unspent_revision3_reserve": MAX_HISTORICAL_FORCE_EVALUATIONS-result["historical_force_evaluations"],
                 "preferred_action": options[0]["action"], "preferred_priority": 1,
                 "preferred_reason": "The alternate 2K-r26 structure is the strongest observed gradient contrast, but it lacks +/-h energies needed to test its own force against an energy derivative.",
                 "candidates": options,
                 "sequential_plan_if_later_authorized": {"actions": [options[0]["action"], options[1]["action"], options[2]["action"]],
                                                         "estimated_total_calls": 11, "within_historical_reserve": True},
                 "selection_basis": "Retrospective prioritization from measured initialization sensitivity and derivative diagnostics; requires separate authorization before any execution."}
    write_json(out / "next_calculation.json", next_calc)

    native_out = out / "native"
    native_out.mkdir(exist_ok=True)
    write_json(native_out / "manifest.json", {"schema": "case05-native-reference/v1", "source_job_id": "3887390",
                                                  "reference_native_ids": result["native_ids"],
                                                  "source_hashes": result["source_hashes"],
                                                  "historical_force_evaluations": result["historical_force_evaluations"],
                                                  "copied_native_outputs": False})

    max_shift = max(abs(r["deviation_eV_per_A"]) for r in result["rows"] if r["deviation_eV_per_A"] is not None)
    claim_block = {
        "scope_flags": hypotheses["scope_flags"],
        "numerical_claims": {
            "force_gradients_eV_per_A": {c: stats[c]["force_gradient_eV_per_A"] for c in TRIPLES},
            "finite_difference_gradients_eV_per_A": {c: stats[c]["finite_difference_gradient_eV_per_A"] for c in TRIPLES},
            "deviations_eV_per_A": {c: stats[c]["deviation_eV_per_A"] for c in TRIPLES},
            "thresholds_eV_per_A": {c: stats[c]["threshold_eV_per_A"] for c in TRIPLES},
            "same_CV_alt_minus_center_gradient_eV_per_A": result["initial_state_gradient_difference_eV_per_A"],
            "water_vs_2K_gradient_differences_eV_per_A": result["system_effects"]
        },
        "interpretation_status": {x["id"]: x["support_code"] for x in hypotheses["explanations"]},
        "expert_extensions": "REVIEW_REQUIRED"
    }
    report = ["# Case 05 revision 3: frozen static local response", "",
              "The analysis replays the 13 completed VASP static points from job 3887390. It submits no calculation. The 13 historical force evaluations used 13 of the original 24-call construction budget; 11 remained unused.", "",
              "The four central-force projections are compared with derivatives of the corresponding three-point VASP electronic free energies. Each energy triplet uses its own center as zero. The largest force-versus-difference deviation is %.6f eV/Å; the frozen diagnostic is 0.05 eV/Å plus 5%% of the larger slope magnitude." % max_shift, "",
              "The 2K alternate initialization at nominal C–Au 2.6 Å differs from its paired center by %.6f eV/Å in the rigid CO₂ force gradient. Bending, hydration, and coordination change together, so this pair does not identify an isolated cause." % result["initial_state_gradient_difference_eV_per_A"], "",
              "The hypotheses and decision fields are retrospective reconstructions. They were not recorded as a pre-submission preregistration. This finite static sample does not establish an equilibrium mean force, free energy, barrier, global adsorption stability, constant-potential cation effect, or single-variable causal effect.",
              "", "<!-- scientific-claims:start -->", json.dumps(claim_block, sort_keys=True, separators=(",", ":")), "<!-- scientific-claims:end -->"]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    # Submit the replay source itself as a required artifact.
    src = Path(__file__).resolve()
    target = out / "analysis.py"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def main():
    if len(sys.argv) != 3:
        print("usage: analysis.py ASSET_DIR OUTPUT_DIR", file=sys.stderr)
        return 2
    try:
        result = read_native(sys.argv[1])
        build_outputs(result, sys.argv[2])
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "OK", "historical_points": REQUIRED_POINTS,
                      "new_scientific_calls": 0, "outputs": 9}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
BENCH06_PY_40_0
python3 "$work/analysis.py" "$ASSETS" "$OUT"
