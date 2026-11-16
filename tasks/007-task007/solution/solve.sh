#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
cat > "$work_dir/native.py" <<'CCB_NATIVE_PY'
"""Read native VASP results without executing scientific software. Python stdlib only."""
import gzip
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def read_poscar(path):
    lines = Path(path).read_text().splitlines()
    scale = float(lines[1]); assert scale > 0, "Negative-volume POSCAR scale unsupported"
    cell = [[float(v)*scale for v in line.split()[:3]] for line in lines[2:5]]
    species = lines[5].split(); counts = list(map(int, lines[6].split()))
    index = 7
    if lines[index].lower().startswith("s"): index += 1
    direct = lines[index].lower().startswith("d"); index += 1
    positions = []
    for line in lines[index:index+sum(counts)]:
        coord = list(map(float, line.split()[:3]))
        positions.append([sum(coord[k]*cell[k][j] for k in range(3)) for j in range(3)] if direct else [x*scale for x in coord])
    assert len(positions) == sum(counts)
    return cell, species, counts, positions

def parameters(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("!",1)[0].split("#",1)[0]
        for entry in line.split(";"):
            if "=" in entry:
                key, value = entry.split("=",1); result[key.strip().upper()] = value.strip()
    return result


_ITERATION_LABELS = {"DAV", "RMM", "CG", "DMP", "SDA", "CGA"}
_NUMBER_PATTERN = r"[+-]?(?:\d+\.\d*|\.\d+)(?:[EeDd][+-]\d{2})?"
_ITERATION_RECORD = re.compile(
    r"^\s*(DAV|RMM|CG|DMP|SDA|CGA)\s*:\s*(\d+)\s+"
    + r"(" + _NUMBER_PATTERN + r")\s+(" + _NUMBER_PATTERN + r")\s+(" + _NUMBER_PATTERN + r")"
    # d eps is normally followed by a whitespace-delimited integer ncg. Some
    # VASP outputs fill the fixed-width ncg field with six digits and omit the
    # separator (for example -0.10846E+01100904). Accept only that exact
    # adjacency after a complete two-digit exponent; do not relax this to \s*
    # or allow arbitrary-width adjacent integers.
    + r"(?:\s+\d+|(?<=[EeDd][+-]\d{2})\d{6}(?=\s|$))(?:\s+|$)"
)


def electronic_iteration_records(text):
    """Parse complete supported electronic rows; fail closed on unknown tags."""
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        prefix = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*:", line)
        if not prefix:
            continue
        label = prefix.group(1)
        if label not in _ITERATION_LABELS:
            raise ValueError(f"Unsupported OSZICAR electronic label {label!r} on line {line_number}")
        match = _ITERATION_RECORD.match(line)
        if not match:
            raise ValueError(f"Malformed/truncated {label} electronic iteration on OSZICAR line {line_number}")
        rows.append(match)
    return rows

def electronic_stop(run, expected_iterations, energy_sigma0):
    """Verify both native OSZICAR changes, not just a sub-NELM count."""
    path = Path(run)/"OSZICAR"
    if not path.is_file(): raise ValueError("Missing OSZICAR electronic convergence evidence")
    text = path.read_text(errors="replace")
    # VASP direct minimization emits SDA/CGA rows for ALGO=All.
    rows = electronic_iteration_records(text)
    if not rows: raise ValueError("No supported native electronic iteration records in OSZICAR")
    last = rows[-1]
    # Keep global line ordering: Match.start() is relative to its individual
    # line, so comparing it directly with a whole-file summary offset is wrong.
    iteration_lines = [i for i, line in enumerate(text.splitlines())
                       if re.match(r"^\s*[A-Z][A-Z0-9_]*\s*:", line)]
    convert = lambda value: float(value.replace("D","E").replace("d","e"))
    delta_free = convert(last.group(4)); delta_bands = convert(last.group(5))
    ediff = float(parameters(Path(run)/"INCAR").get("EDIFF", "1e-4"))
    if not all(math.isfinite(v) for v in (delta_free,delta_bands,ediff)) or ediff <= 0:
        raise ValueError("Nonfinite/invalid electronic convergence values")
    if int(last.group(2)) != expected_iterations:
        raise ValueError("OSZICAR and completed XML final SCF iteration counts disagree")
    if abs(delta_free) >= ediff or abs(delta_bands) >= ediff:
        raise ValueError(f"Final SCF energy changes exceed EDIFF: dE={delta_free}, d_eps={delta_bands}, EDIFF={ediff}")
    summaries = list(re.finditer(r"^\s*\d+\s+.*?\bF=\s*("+_NUMBER_PATTERN+r").*?\bE0=\s*("+_NUMBER_PATTERN+r")",text,re.M))
    summary_lines = [text.count("\n", 0, m.start()) for m in summaries]
    if not summaries or summary_lines[-1] <= iteration_lines[-1]:
        raise ValueError("No completed ionic/static summary after final electronic loop")
    e0 = convert(summaries[-1].group(2))
    # OSZICAR prints fewer digits than OUTCAR; this compares record identity only.
    if not math.isfinite(e0) or abs(e0-energy_sigma0) > 5e-4:
        raise ValueError("Final OSZICAR E0 and OUTCAR sigma0 energy disagree")
    return dict(final_delta_free_energy_eV=delta_free,final_delta_band_energy_eV=delta_bands,
        EDIFF_eV=ediff,electronic_energy_changes_valid=True)

def read_native(run):
    run = Path(run)
    missing = [name for name in ("OUTCAR", "CONTCAR", "execution-exit-code.txt") if not (run/name).is_file()]
    xml_path = run/"vasprun.xml"
    if not xml_path.is_file(): xml_path = run/"vasprun.xml.gz"
    if not xml_path.is_file(): missing.append("vasprun.xml[.gz]")
    if missing: raise ValueError("Missing native files: "+", ".join(missing))
    if (run/"execution-exit-code.txt").read_text().strip() != "0": raise ValueError("Nonzero engine/launcher exit")
    if (run/"STOPCAR").exists(): raise ValueError("STOPCAR termination requires manual review")
    incar = parameters(run/"INCAR")
    nelm = int(incar.get("NELM",60)); threshold = float(incar.get("EDIFFG",-.01))
    expected_ions = sum(read_poscar(run/"CONTCAR")[2])
    last = None; ionic_steps = 0; top_band_occupation = None
    discarded_depth = 0
    opener = gzip.open if xml_path.suffix == ".gz" else open
    with opener(xml_path, "rb") as xml_stream:
      for event, element in ET.iterparse(xml_stream, events=("start", "end")):
        if event == "start":
            if discarded_depth or element.tag in ("projected", "dos"): discarded_depth += 1
            continue
        if discarded_depth:
            element.clear(); discarded_depth -= 1
            continue
        if element.tag == "eigenvalues":
            occupations = []
            for band_set in element.findall(".//set"):
                rows = band_set.findall("r")
                if rows: occupations.append(abs(float(rows[-1].text.split()[1])))
            if any(not math.isfinite(v) for v in occupations): raise ValueError("Nonfinite highest-band occupations")
            if occupations: top_band_occupation = max(occupations)
            element.clear()
        elif element.tag == "calculation":
            steps = element.findall("scstep")
            forces = [[float(v) for v in row.text.split()] for row in element.findall("./varray[@name='forces']/v")]
            if len(forces) != expected_ions or any(not math.isfinite(v) for row in forces for v in row):
                raise ValueError("Missing, mismatched or nonfinite native forces")
            energies = {row.attrib["name"]:float(row.text) for row in element.findall("./energy/i")}
            if any(not math.isfinite(v) for v in energies.values()): raise ValueError("Nonfinite XML energies")
            last = dict(scf_iterations=len(steps), max_force_eV_A=max((math.sqrt(sum(v*v for v in f)) for f in forces), default=float("inf")), xml_energies=energies)
            ionic_steps += 1; element.clear()
    if last is None: raise ValueError("No completed XML ionic calculation")
    outcar = (run/"OUTCAR").read_text(errors="replace")
    if "General timing and accounting informations for this job" not in outcar:
        raise ValueError("Missing native normal-termination timing footer")
    records = re.findall(r"energy\(\s*sigma\s*->\s*0\s*\)\s*=\s*([-+0-9.EeDd]+)", outcar)
    if not records: raise ValueError("No native energy(sigma->0) record")
    energy = float(records[-1].replace("D","E").replace("d","e"))
    if not math.isfinite(energy): raise ValueError("Nonfinite energy")
    scf_valid = 0 < last["scf_iterations"] < nelm
    if not scf_valid: raise ValueError("Final electronic loop reached NELM or has no iterations")
    stop = electronic_stop(run, last["scf_iterations"], energy)
    # Numerical convergence does not prove magnetic ground state.
    force_valid = last["max_force_eV_A"] <= abs(threshold if threshold < 0 else -.01)
    bands_valid = top_band_occupation is not None and top_band_occupation < 1e-3
    return dict(energy_sigma0_eV=energy, ionic_steps=ionic_steps,
        electronic_iteration_termination_valid=scf_valid, force_valid=force_valid,
        top_band_occupation=top_band_occupation, empty_band_check_valid=bands_valid,
        convergence_basis="completed native XML, normal OUTCAR footer, matching OSZICAR final iteration and energy, both energy changes below EDIFF, engine exit 0, force and highest-band occupancy",
        magnetic_ground_state_proven=False, **stop, **last)


CCB_NATIVE_PY
cat > "$work_dir/solve.py" <<'CCB_SOLVER_PY'
#!/usr/bin/env python3
"""Offline reference replay that derives all scientific claims from six native runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path, PurePosixPath

from native import parameters, read_native


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path, relative: str) -> dict:
    data = path.read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}




def extract_runs(archive: Path, target: Path, task_ids: set[str]) -> dict[str, Path]:
    paths = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            pure = PurePosixPath(info.filename)
            if (pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 3
                    or pure.parts[0] != "runs" or pure.parts[1] not in task_ids
                    or pure.parts[2] not in {"INCAR", "KPOINTS", "POSCAR", "READY.json", "job.json",
                                             "OUTCAR", "CONTCAR", "OSZICAR", "vasprun.xml.gz",
                                             "execution-exit-code.txt"}):
                continue
            destination = target / pure.parts[1] / pure.parts[2]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(info))
            paths[pure.parts[1]] = target / pure.parts[1]
    if set(paths) != task_ids:
        raise RuntimeError("reference native archive does not contain all six tasks")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=Path("/run/compchembench/task7-reference-inputs"))
    parser.add_argument("--outdir", type=Path, default=Path("/app/final"))
    args = parser.parse_args()
    reference, output = args.reference, args.outdir
    app_assets = Path("/app/assets")
    if not app_assets.is_dir():
        app_assets = Path(__file__).resolve().parents[1] / "environment/assets"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"reference output directory must be empty: {output}")
    shutil.copy2(reference / "settings.json", output / "settings.json")
    shutil.copy2(reference / "pre-result-site-choice.json", output / "pre-result-site-choice.json")
    shutil.copy2(reference / "native_outputs.zip", output / "native_outputs.zip")
    shutil.copy2(reference / "execution-receipt.json", output / "execution-receipt.json")
    shutil.copytree(reference / "execution-evidence", output / "execution-evidence")
    shutil.copy2(app_assets / "task07-site-inventory.csv", output / "site_inventory.csv")

    settings = json.loads((output / "settings.json").read_text(encoding="utf-8"))
    choice = json.loads((output / "pre-result-site-choice.json").read_text(encoding="utf-8"))
    task_ids = {job["task_id"] for job in settings["jobs"]}
    job_map = {job["task_id"]: job for job in settings["jobs"]}
    task_ids_by_condition = {
        condition: {site: next(job["task_id"] for job in settings["jobs"]
                              if job["condition"] == condition and job["site"] == site)
                   for site in ("A", "B")}
        for condition in ("baseline", "numerical_sensitivity", "magnetic_sensitivity")
    }

    with tempfile.TemporaryDirectory(prefix="case01-reference-native-") as temporary:
        runs = extract_runs(output / "native_outputs.zip", Path(temporary), task_ids)
        energies = {task: read_native(run)["energy_sigma0_eV"] for task, run in runs.items()}
        deltas = []
        for condition, sites in task_ids_by_condition.items():
            delta = energies[sites["A"]] - energies[sites["B"]]
            deltas.append({"condition": condition, "delta_E_A_minus_B_eV": delta})

        physical = {}
        for task_id, run in runs.items():
            ready = json.loads((run / "READY.json").read_text(encoding="utf-8"))
            physical[task_id] = {"incar": parameters(run / "INCAR"),
                                 "kpoints": (run / "KPOINTS").read_bytes(),
                                 "potcar_sha256": ready["sha256"]["POTCAR"]}
        numerical_controls = {}
        for site in ("A", "B"):
            baseline = task_ids_by_condition["baseline"][site]
            tight = task_ids_by_condition["numerical_sensitivity"][site]
            changed = [key for key in ("ENCUT", "EDIFF", "NBANDS", "PREC", "ISMEAR", "SIGMA")
                       if physical[baseline]["incar"].get(key) != physical[tight]["incar"].get(key)]
            if physical[baseline]["kpoints"] != physical[tight]["kpoints"]:
                changed.append("KPOINTS")
            numerical_controls[site] = changed

        counts = {site: {element: int(choice[f"site_{site}"]["neighbor_counts"][element])
                         for element in ("Co", "Cr", "Fe", "Ni")} for site in ("A", "B")}
        m1_joint_fields = []
        for site in ("A", "B"):
            base = physical[task_ids_by_condition["baseline"][site]]
            alternate = physical[task_ids_by_condition["magnetic_sensitivity"][site]]
            keys = (set(base["incar"]) | set(alternate["incar"])) - {"MAGMOM", "SYSTEM"}
            m1_joint_fields.extend(key for key in keys if base["incar"].get(key) != alternate["incar"].get(key))
            if base["kpoints"] != alternate["kpoints"]:
                m1_joint_fields.append("KPOINTS")
            if base["potcar_sha256"] != alternate["potcar_sha256"]:
                m1_joint_fields.append("POTCAR")
        interpretation = ("initial_magnetization_and_solver_joint_response" if m1_joint_fields
                          else "initial_magnetization_response")

        values = {row["condition"]: Decimal(str(row["delta_E_A_minus_B_eV"])) for row in deltas}
        same_sign = all(value > 0 for value in values.values()) or all(value < 0 for value in values.values())
        numerical_response = abs(values["numerical_sensitivity"] - values["baseline"])
        minimum_delta = min(abs(value) for value in values.values())
        rule_pass = same_sign and minimum_delta > numerical_response + Decimal("0.0082")
        claim = ("UNDECIDED" if not rule_pass else
                 "B_lower" if values["baseline"] > 0 else "A_lower")
        report = {
            "schema": "case01-scientific-claims/v1",
            "scope": {"model_sha256": settings["model_sha256"],
                      "domain": "fixed_32_metal_cell_selected_A_B_pair",
                      "claims_random_alloy_representativeness": False,
                      "claims_thermodynamic_occupancy": False,
                      "claims_magnetic_ground_state": False,
                      "claims_relaxed_absorption_enthalpy": False,
                      "claims_fracture_or_P3_P7_completion": False},
            "site_choice": {"purpose": "first_shell_composition_contrast",
                            "site_ids": {site: choice[f"site_{site}"]["site_id"] for site in ("A", "B")},
                            "neighbor_counts": counts,
                            "descriptor_delta": {element: counts["A"][element] - counts["B"][element]
                                                 for element in counts["A"]}},
            "method_design": {"condition_task_ids": task_ids_by_condition,
                              "baseline_start": next(job["magnetic_start"] for job in settings["jobs"]
                                                     if job["condition"] == "baseline"),
                              "alternate_start": next(job["magnetic_start"] for job in settings["jobs"]
                                                      if job["condition"] == "magnetic_sensitivity"),
                              "numerical_controls_changed": numerical_controls,
                              "numerical_sensitivity_purpose": "test_numerical_parameter_sensitivity",
                              "alternate_start_purpose": "test_alternative_magnetic_initialization",
                              "m1_interpretation": interpretation,
                              "stopping_rule": "complete_three_matched_pairs_or_authorized_deadline"},
            "paired_results": [{"condition": row["condition"],
                                 "task_ids":[task_ids_by_condition[row["condition"]]["A"],
                                             task_ids_by_condition[row["condition"]]["B"]],
                                 "delta_eV": row["delta_E_A_minus_B_eV"],
                                 "direction": "positive" if row["delta_E_A_minus_B_eV"] > 0 else
                                             "negative" if row["delta_E_A_minus_B_eV"] < 0 else "zero"}
                                for row in deltas],
            "decision": {"claim": claim, "rule_id": "case01-exploratory-8p2mev/v1",
                         "rule_pass": rule_pass, "same_sign": same_sign,
                         "minimum_abs_delta_eV": float(minimum_delta),
                         "numerical_response_eV": float(numerical_response),
                         "alternate_response_eV": float(values["magnetic_sensitivity"] - values["baseline"]),
                         "exploratory_scale_eV": 0.0082,
                         "condition_directions": {condition: "positive" if value > 0 else
                                                   "negative" if value < 0 else "zero"
                                                   for condition, value in values.items()},
                         "undecided_reason": None if rule_pass else "exploratory_rule_not_met"}
        }
        (output / "scientific-claims.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

        with zipfile.ZipFile(output / "models.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(reference / "model.json", "models/model.json")
            bundle.write(output / "site_inventory.csv", "models/site-inventory.csv")
            bundle.write(runs[task_ids_by_condition["baseline"]["A"]] / "POSCAR", "models/site-A-with-H.POSCAR")
            bundle.write(runs[task_ids_by_condition["baseline"]["B"]] / "POSCAR", "models/site-B-with-H.POSCAR")

    with (output / "convergence.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["phase", "condition", "magnetic_start", "algorithm",
            "array_job_id", "delta_E_A_minus_B_eV", "gate", "notes"])
        writer.writeheader()
        for phase, condition in enumerate(("baseline", "numerical_sensitivity", "magnetic_sensitivity"), 1):
            task = task_ids_by_condition[condition]["A"]
            job = job_map[task]
            algorithm = parameters_from_zip(output / "native_outputs.zip", task).get("ALGO", "")
            writer.writerow({"phase": phase, "condition": {"baseline": "baseline",
                "numerical_sensitivity": "joint-tight", "magnetic_sensitivity": "baseline"}[condition],
                "magnetic_start": job["magnetic_start"], "algorithm": algorithm,
                "array_job_id": job.get("array_job_id"),
                "delta_E_A_minus_B_eV": f"{deltas[phase-1]['delta_E_A_minus_B_eV']:.12f}",
                "gate": "PASSED", "notes": "derived from matched native A/B evidence"})

    index_rows=[]
    for path in sorted(output.iterdir()):
        if path.name in {"evidence-index.json", "execution-evidence"}: continue
        index_rows.append({"path":f"final/{path.name}","bytes":path.stat().st_size,"sha256":sha(path)})
    for path in sorted((output/"execution-evidence").rglob("*")):
        if path.is_file(): index_rows.append({"path":f"final/{path.relative_to(output).as_posix()}",
                                               "bytes":path.stat().st_size,"sha256":sha(path)})
    (output/"evidence-index.json").write_text(json.dumps({"artifacts":index_rows},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"source_scope":"attested_archival_replay","tasks":len(task_ids),
                      "decision":claim,"output":str(output)},ensure_ascii=False))
    return 0


def parameters_from_zip(archive: Path, task_id: str) -> dict:
    with zipfile.ZipFile(archive) as bundle:
        return parameters_from_bytes(bundle.read(f"runs/{task_id}/INCAR"))


def parameters_from_bytes(data: bytes) -> dict:
    result={}
    for line in data.decode("utf-8",errors="replace").splitlines():
        line=line.split("!",1)[0].split("#",1)[0]
        for entry in line.split(";"):
            if "=" in entry:
                key,value=entry.split("=",1);result[key.strip().upper()]=value.strip()
    return result


if __name__ == "__main__":
    raise SystemExit(main())

CCB_SOLVER_PY
python3 "$work_dir/solve.py" --reference /run/compchembench/task7-reference-inputs --outdir /app/final
