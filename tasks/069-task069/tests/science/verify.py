#!/usr/bin/env python3
"""Read-only independent checks for Case 08 candidate evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

CASE_ID = "case-08-short-md-stop-go"
LABELS = ("B-dt1fs", "B-dt2fs", "U-dt1fs", "U-dt2fs")
INPUTS = (
    "NVT-50ps-dt1fs.mdp", "NVT-50ps-dt2fs.mdp", "NVT.mdp", "b.gro",
    "conf_template.pdb", "remote-input-provenance.json", "topol.top", "u.gro",
)
RUN_FILE_ALIASES = {
    "mdp": ("input.mdp", "run.mdp"),
    "coordinate": ("start.gro", "conf_in.gro"),
    "topology": ("topol.top",),
    "grompp_log": ("grompp.console.log", "grompp.out", "grompp.err", "grompp.log"),
    "mdrun_log": ("md.log", "mdrun.console.log", "mdrun.out", "mdrun.err"),
    "energy": ("energy.xvg", "md.energy.xvg", "energy-series.xvg"),
    "index": ("index.ndx",),
    "tpr_dump": ("tpr-state-dump.txt",),
    "processed_topology": ("processed.top", "processed_topology.top", "topol-processed.top"),
}
EXPECTED_STEPS = {1: 50000, 2: 25000}
MAX_RUN_PS = 50.0
MAX_TOTAL_PS = 200.0
ENERGY_TERMS = (
    "Temperature", "Potential", "Kinetic En.", "Total Energy", "Conserved En.",
    "Constr. rmsd", "T-OCB", "T-MOL", "T-Water_and_ions", "Box-X", "Box-Y", "Box-Z",
)
DIAGNOSTIC_NUMBERS = (
    "temperature_K", "potential", "kinetic_en", "total_energy", "conserved_en",
    "constr_rmsd", "t_ocb", "t_mol", "t_water_and_ions", "box_x_nm", "box_y_nm",
    "box_z_nm", "water20_oh_mean_nm", "water20_hh_mean_nm", "water20_angle_mean_deg",
)
DIAGNOSTIC_ABS_TOLERANCE = {
    "time_ps": 0.001, "temperature_K": 0.005,
    "potential": 0.01, "kinetic_en": 0.01, "total_energy": 0.01,
    "conserved_en": 0.01, "constr_rmsd": 1e-6,
    "t_ocb": 0.005, "t_mol": 0.005, "t_water_and_ions": 0.005,
    "box_x_nm": 0.002, "box_y_nm": 0.002, "box_z_nm": 0.002,
    "water20_oh_mean_nm": 0.002, "water20_hh_mean_nm": 0.002,
    "water20_angle_mean_deg": 0.5, "warning_count": 0.0,
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def digest_json_canonical(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def mdp_values(path: Path):
    values = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split(";", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip()
    return values


def effective_mdp_errors(values, dt_fs):
    errors = []
    try:
        dt_ps = float(values.get("dt", "nan"))
    except (TypeError, ValueError):
        dt_ps = math.nan
    if values.get("integrator", "").lower() != "md" or not math.isclose(dt_ps, dt_fs / 1000.0, rel_tol=0, abs_tol=1e-12):
        errors.append("integrator or timestep mismatch")
    try:
        nsteps = int(values.get("nsteps", ""))
    except (TypeError, ValueError):
        nsteps = 0
    if nsteps <= 0 or nsteps * dt_ps > MAX_RUN_PS + 1e-9:
        errors.append("step count is non-positive or exceeds the 50 ps run cap")
    if values.get("gen_vel", "no").lower() == "yes":
        try:
            int(values.get("gen_seed", ""))
        except (TypeError, ValueError):
            errors.append("velocity generation seed is not an integer")
    elif values.get("gen_vel", "no").lower() != "no":
        errors.append("gen_vel must be yes or no")
    if values.get("constraints", "").lower() != "all-bonds" or values.get("constraint-algorithm", "").lower() != "lincs":
        errors.append("constraint configuration mismatch")
    if values.get("coulombtype", "").lower() != "pme" or values.get("tcoupl", "").lower() != "v-rescale":
        errors.append("electrostatics or thermostat mismatch")
    try:
        temps = [float(v) for v in values.get("ref-t", "").split()]
    except ValueError:
        temps = []
    if len(temps) != 3 or any(not math.isfinite(v) or not math.isclose(v, 300.0, rel_tol=0, abs_tol=1e-6) for v in temps):
        errors.append("reference temperature mismatch")
    groups = values.get("tc-grps", "").split()
    if len(groups) != 3 or set(groups) != {"OCB", "MOL", "Water_and_ions"}:
        errors.append("the three required thermostat groups are missing or changed")
    return errors


def xvg_values(path: Path):
    legends, rows = {}, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r'\s*@\s+s(\d+)\s+legend\s+"(.*?)"', line)
        if match:
            legends[match.group(2).lower()] = int(match.group(1)) + 1
        if not line.strip() or line.lstrip()[0] in "#@&":
            continue
        row = [float(v) for v in line.split()]
        if any(not math.isfinite(v) for v in row):
            raise ValueError(f"non-finite energy value in {path}")
        if len(row) > 1:
            rows.append(row)
    if not rows:
        raise ValueError(f"energy series is empty: {path}")
    if any(rows[i][0] >= rows[i + 1][0] for i in range(len(rows) - 1)):
        raise ValueError(f"energy times are not strictly increasing: {path}")
    return legends, rows


def xvg_energy(legends, row, key):
    index = legends.get(key.lower())
    if index is None:
        index = legends.get(key.replace(" ", "").lower())
    return row[index] if index is not None and index < len(row) else None


def series_summary(values):
    if not values:
        return {"n": 0, "mean": None, "sd_population": None}
    return {"n": len(values), "mean": sum(values) / len(values),
            "sd_population": statistics.pstdev(values)}


def expected_energy_windows(legends, rows):
    result = {}
    windows = (("full-0-50ps", 0.0, 50.0), ("0-25ps", 0.0, 25.0),
               ("25-50ps", 25.0, 50.000001))
    for name, lower, upper in windows:
        selected = [row for row in rows if lower <= row[0] < upper]
        result[name] = {
            term: series_summary([value for row in selected
                                  for value in [xvg_energy(legends, row, term)] if value is not None])
            for term in ENERGY_TERMS
        }
    return result


def water_geometry(path: Path):
    lines, count, box = read_gro(path)
    waters = []
    for line in lines[2:2 + count]:
        if line[5:10].strip() == "WAT":
            waters.append({"name": line[10:15].strip(), "xyz": [float(line[i:i + 8]) for i in (20, 28, 36)]})
    if len(waters) < 60:
        raise ValueError(f"fewer than 20 waters in {path}")

    def vector(a, b):
        values = [b[i] - a[i] for i in range(3)]
        return [values[i] - round(values[i] / box[i]) * box[i] for i in range(3)]

    def length(v):
        return math.sqrt(sum(value * value for value in v))

    oh, hh, angles = [], [], []
    for offset in range(0, 60, 3):
        oxygen, h1, h2 = waters[offset:offset + 3]
        if (oxygen["name"], h1["name"], h2["name"]) != ("O", "H1", "H2"):
            raise ValueError(f"unexpected water atom order in {path}")
        v1, v2 = vector(oxygen["xyz"], h1["xyz"]), vector(oxygen["xyz"], h2["xyz"])
        d1, d2 = length(v1), length(v2)
        hh.append(length(vector(h1["xyz"], h2["xyz"])))
        oh.extend((d1, d2))
        cosine = sum(v1[i] * v2[i] for i in range(3)) / (d1 * d2)
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    title = lines[0]
    match = re.search(r"\bt\s*=\s*([-+0-9.eE]+)", title)
    time_ps = float(match.group(1)) if match else None
    return {"time_ps": time_ps, "box": box,
            "water20_oh_mean_nm": sum(oh) / len(oh),
            "water20_hh_mean_nm": sum(hh) / len(hh),
            "water20_angle_mean_deg": sum(angles) / len(angles)}


def sampled_frames(run_dir: Path):
    paths = list(run_dir.glob("sample*.gro"))
    paths.sort(key=lambda path: int(re.search(r"(\d+)$", path.stem).group(1)))
    if not paths and (run_dir / "md.gro").is_file():
        paths = [run_dir / "md.gro"]
    result = []
    for path in paths:
        geometry = water_geometry(path)
        if geometry["time_ps"] is None:
            idx = re.search(r"(\d+)$", path.stem)
            geometry["time_ps"] = int(idx.group(1)) * 5.0 if idx else 50.0
        result.append((path, geometry))
    return result


def log_warning_count(run_dir: Path):
    text = "\n".join((run_dir / name).read_text(encoding="utf-8", errors="replace")
                      for name in RUN_FILE_ALIASES["mdrun_log"] if (run_dir / name).is_file())
    return len(re.findall(r"(?i)\bLINCS\s+WARNING\b|\bconstraint\s+warning\b|\bNaN\b|\bnot\s+a\s+number\b", text))


def run_file(run_dir: Path, kind: str, declared=None):
    """Resolve a small public set of native-file names, without accepting arbitrary paths."""
    names = []
    if isinstance(declared, str) and declared.strip():
        rel = Path(declared)
        if not rel.is_absolute() and ".." not in rel.parts and rel.name in RUN_FILE_ALIASES[kind]:
            names.append(rel.as_posix())
    names.extend(name for name in RUN_FILE_ALIASES[kind] if name not in names)
    for name in names:
        path = run_dir / name
        if path.is_symlink():
            raise ValueError(f"native run file is a symlink: {path}")
        if path.is_file():
            try:
                path.resolve().relative_to(run_dir.resolve())
            except ValueError as exc:
                raise ValueError(f"native run file escapes its run directory: {path}") from exc
            return path
    return None


def logged_final_step_time(run_dir: Path):
    """Read the latest explicit Step/Time pair from a native mdrun log if available."""
    pairs = []
    for name in RUN_FILE_ALIASES["mdrun_log"]:
        path = run_dir / name
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines[:-1]):
                if re.search(r"\bStep\s+Time\b", line):
                    match = re.match(r"\s*(\d+)\s+([-+0-9.eE]+)\s*$", lines[i + 1])
                    if match:
                        step, time_ps = int(match.group(1)), float(match.group(2))
                        if math.isfinite(time_ps):
                            pairs.append((step, time_ps))
    return max(pairs, default=None, key=lambda item: item[0])


def max_allocations_from_budget(path: Path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*max_allocations\s*:\s*(\d+)\s*(?:#.*)?$", text)
    if not match:
        raise ValueError("public compute-budget.yaml has no integer max_allocations")
    return int(match.group(1))


def budget_integer(path: Path, key: str):
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*(\d+)\s*(?:#.*)?$", text)
    if not match:
        raise ValueError(f"public compute-budget.yaml has no integer {key}")
    return int(match.group(1))


def run_native_manifest(submission: Path):
    manifest = {}
    for path in sorted((submission / "runs").rglob("*")):
        if path.is_symlink():
            raise ValueError(f"native output contains symlink: {path}")
        if path.is_file():
            manifest[path.relative_to(submission).as_posix()] = {"sha256": digest(path), "bytes": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError(f"native output contains a special file: {path}")
    return manifest


def close_number(left, right, abs_tol=1e-8):
    return (isinstance(left, (int, float)) and isinstance(right, (int, float))
            and math.isfinite(float(left)) and math.isfinite(float(right))
            and math.isclose(float(left), float(right), rel_tol=1e-8, abs_tol=abs_tol))


def recompute_diagnostics(submission: Path, derived_energy_dir: Path | None = None):
    expected = []
    comparisons = {}
    for label in LABELS:
        run_dir = submission / "runs" / label
        energy_path = (derived_energy_dir / f"{label}.xvg") if derived_energy_dir else run_file(run_dir, "energy")
        if energy_path is None or not energy_path.is_file():
            continue
        legends, rows = xvg_values(energy_path)
        comparisons[label] = expected_energy_windows(legends, rows)
        warnings = log_warning_count(run_dir)
        for frame_path, geometry in sampled_frames(run_dir):
            time_ps = geometry["time_ps"]
            sample = min(rows, key=lambda row: abs(row[0] - time_ps))
            values = {
                "run": label, "time_ps": time_ps,
                "temperature_K": xvg_energy(legends, sample, "Temperature"),
                "potential": xvg_energy(legends, sample, "Potential"),
                "kinetic_en": xvg_energy(legends, sample, "Kinetic En."),
                "total_energy": xvg_energy(legends, sample, "Total Energy"),
                "conserved_en": xvg_energy(legends, sample, "Conserved En."),
                "constr_rmsd": xvg_energy(legends, sample, "Constr. rmsd"),
                "t_ocb": xvg_energy(legends, sample, "T-OCB"),
                "t_mol": xvg_energy(legends, sample, "T-MOL"),
                "t_water_and_ions": xvg_energy(legends, sample, "T-Water_and_ions"),
                "box_x_nm": geometry["box"][0], "box_y_nm": geometry["box"][1],
                "box_z_nm": geometry["box"][2], "warning_count": warnings,
                "water20_oh_mean_nm": geometry["water20_oh_mean_nm"],
                "water20_hh_mean_nm": geometry["water20_hh_mean_nm"],
                "water20_angle_mean_deg": geometry["water20_angle_mean_deg"],
                "source_frame": str(frame_path.relative_to(submission)),
            }
            expected.append(values)
    return expected, comparisons


def vector_hashes(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    output = {}
    for kind in ("x", "v"):
        entries = re.findall(r"(?m)^\s*" + kind + r"\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}", text)
        if entries:
            canonical = "\n".join(f"{index}:{value.strip()}" for index, value in entries)
            output[kind] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return output


def read_gro(path: Path):
    lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    atom_count = int(lines[1].strip())
    if len(lines) < atom_count + 3:
        raise ValueError(f"truncated GRO: {path}")
    box = [float(x) for x in lines[atom_count + 2].split()[:3]]
    if len(box) != 3 or any(not math.isfinite(x) or x <= 0 for x in box):
        raise ValueError(f"invalid GRO box: {path}")
    return lines, atom_count, box


def index_groups(path: Path):
    groups = {}
    current = None
    for line in path.read_text(encoding="ascii", errors="strict").splitlines():
        match = re.fullmatch(r"\s*\[\s*(.*?)\s*\]\s*", line)
        if match:
            current = match.group(1)
            if current in groups:
                raise ValueError(f"duplicate index group: {current}")
            groups[current] = []
        elif line.strip():
            if current is None:
                raise ValueError("index content appears before a group header")
            groups[current].extend(int(value) for value in line.split())
    return groups


def expected_index_groups(gro_path: Path):
    lines, count, _ = read_gro(gro_path)
    names = [line[5:10].strip() for line in lines[2:2 + count]]
    return {
        "OCB": [i for i, name in enumerate(names, 1) if name == "OCB"],
        "MOL": [i for i, name in enumerate(names, 1) if name == "MOL"],
        "Water_and_ions": [i for i, name in enumerate(names, 1) if name in {"WAT", "Na+"}],
        "non-Water": [i for i, name in enumerate(names, 1) if name != "WAT"],
    }


def check_candidate(app: Path, tests: Path):
    submission = app / "submission"
    checks = []
    failures = []
    warnings = []
    refs = read_json(tests / "refs.json")
    expected_inputs = refs.get("input_hashes", {})
    budget_path = app / "environment" / "assets" / "compute-budget.yaml"
    try:
        fingerprint_index = read_json(tests / "code-fingerprints.json")
        budget_pin = fingerprint_index.get("files", {}).get("packages/case-08-short-md-stop-go/compute-budget.yaml")
        if not budget_path.is_file() or not isinstance(budget_pin, str) or digest(budget_path) != budget_pin:
            raise RuntimeError("trusted public compute-budget.yaml is missing or differs from its code pin")
        max_allocations = max_allocations_from_budget(budget_path)
        max_cpus = budget_integer(budget_path, "cpus")
        max_gpus = budget_integer(budget_path, "gpus")
        max_nodes = budget_integer(budget_path, "nodes")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"trusted public allocation budget cannot be verified: {exc}") from exc
    for name in INPUTS:
        path = app / "environment" / "assets" / name
        expected = expected_inputs.get(f"environment/assets/{name}")
        if not path.is_file() or not expected:
            failures.append(f"required public input missing: {name}")
        elif digest(path) != expected:
            failures.append(f"public input hash mismatch: {name}")
    if not submission.is_dir():
        return {"state": "INCOMPLETE", "checks": checks,
                "failures": ["/app/submission is missing"], "warnings": []}

    required = (
        "input-audit.json", "remote-provenance.json", "diagnostics.csv",
        "numerical-comparison.json", "continuation-decision.json", "scientific-rationale.md",
    )
    for name in required:
        if not (submission / name).is_file():
            failures.append(f"missing required submission file: {name}")
    audit_path = submission / "input-audit.json"
    provenance_path = submission / "remote-provenance.json"
    comparison_path = submission / "numerical-comparison.json"
    decision_path = submission / "continuation-decision.json"
    derived_energy_dir = None
    provenance_for_reference = read_json(provenance_path) if provenance_path.is_file() else {}
    if str(provenance_for_reference.get("job_id", "")) == "3968344":
        trusted_path = tests / "evidence" / "verified-execution-3968344.json"
        reference_hashes = read_json(tests / "reference-hashes.json")
        if not trusted_path.is_file() or reference_hashes.get("tests/evidence/verified-execution-3968344.json") != digest(trusted_path):
            raise RuntimeError("private trusted execution evidence is missing or stale")
        else:
            trusted = read_json(trusted_path)
            try:
                if trusted.get("job_id") != "3968344" or trusted.get("read_only_independent_host_audit") is not True:
                    failures.append("private trusted execution identity is invalid")
                if run_native_manifest(submission) != trusted.get("native_manifest"):
                    failures.append("recovered native run files differ from independent host-audited execution")
                source_path = submission / "source-manifest.json"
                if not source_path.is_file() or digest(source_path) != trusted.get("execution_sources", {}).get("source-manifest.json"):
                    failures.append("recovered source manifest differs from independent host audit")
                energy_record = read_json(submission / "energy-extraction.json")
                if energy_record.get("job_id") != "3968344" or energy_record.get("analysis_version") != "independent-native-edr-postprocess/v1":
                    failures.append("EDR post-processing provenance is missing or inconsistent")
                if energy_record.get("source_native_manifest_sha256") != digest_json_canonical(trusted.get("native_manifest")):
                    failures.append("EDR post-processing is not bound to the audited native manifest")
                if energy_record.get("postprocess_script_sha256") != trusted.get("postprocess_script_sha256"):
                    failures.append("post-processing code differs from the pinned maintainer analysis")
                derived_energy_dir = submission / "postprocessing" / "derived-energy"
                for run, expected in trusted.get("postprocessed_energy", {}).items():
                    edr = submission / expected["edr_path"]
                    xvg = derived_energy_dir / f"{run}.xvg"
                    if not edr.is_file() or digest(edr) != expected["edr_sha256"]:
                        failures.append(f"post-processing source EDR differs from independent host audit: {run}")
                    if not xvg.is_file() or digest(xvg) != expected["xvg_sha256"]:
                        failures.append(f"derived energy series differs from private read-only extraction: {run}")
                    claimed = energy_record.get("derived_energy", {}).get(run, {})
                    if (claimed.get("xvg_sha256") != expected["xvg_sha256"] or claimed.get("xvg_bytes") != expected["xvg_bytes"]
                            or claimed.get("source_edr_path") != expected["edr_path"]
                            or claimed.get("source_edr_sha256") != expected["edr_sha256"]):
                        failures.append(f"energy extraction record differs from trusted output: {run}")
            except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise RuntimeError(f"trusted execution linkage cannot be verified: {exc}") from exc
    elif (submission / "postprocessing" / "derived-energy").exists():
        failures.append("unrecognized derived energy outputs lack a trusted execution binding")
    planned_duration = {}
    actual_duration = {}
    observed_steps = {}
    if audit_path.is_file():
        audit = read_json(audit_path)
        if not isinstance(audit.get("inputs"), dict):
            failures.append("input-audit.inputs is not an object")
        else:
            for name in INPUTS:
                expected = expected_inputs.get(f"environment/assets/{name}")
                observed = audit["inputs"].get(name)
                observed = observed.get("sha256") if isinstance(observed, dict) else observed
                if observed != expected:
                    failures.append(f"input-audit hash mismatch: {name}")
            budget_observed = audit["inputs"].get("compute-budget.yaml")
            budget_observed = budget_observed.get("sha256") if isinstance(budget_observed, dict) else budget_observed
            if budget_observed is not None and budget_path.is_file() and budget_observed != digest(budget_path):
                failures.append("input-audit hash mismatch: compute-budget.yaml")
            elif budget_observed is None:
                warnings.append("NOT_VERIFIED: input-audit omits the supplied compute-budget hash")
        run_records = audit.get("run_inputs")
        if not isinstance(run_records, list):
            failures.append("input-audit.run_inputs is not a list")
            run_records = []
        record_map = {r.get("run"): r for r in run_records if isinstance(r, dict)}
        if set(record_map) - set(LABELS):
            failures.append("input-audit contains an unknown run label")
        for label in LABELS:
            item = record_map.get(label)
            run_dir = submission / "runs" / label
            if item is None:
                failures.append(f"input-audit is missing run record: {label}")
                continue
            dt = 1 if "dt1fs" in label else 2
            expected_coord = app / "environment" / "assets" / ("b.gro" if label.startswith("B-") else "u.gro")
            input_mdp = run_file(run_dir, "mdp", item.get("mdp_file"))
            input_values = {}
            input_steps = None
            if item.get("dt_fs") != dt:
                failures.append(f"input-audit timestep differs from run label: {label}")
            if input_mdp is not None:
                try:
                    input_values = mdp_values(input_mdp)
                    failures.extend(f"input MDP {message}: {label}" for message in effective_mdp_errors(input_values, dt))
                    input_steps = int(input_values.get("nsteps", ""))
                    duration = input_steps * dt / 1000.0
                    planned_duration[label] = duration
                    if item.get("nsteps") != input_steps:
                        failures.append(f"input-audit step count differs from submitted MDP: {label}")
                    if not close_number(item.get("duration_ps"), duration, 0.001):
                        failures.append(f"input-audit configured duration differs from submitted MDP: {label}")
                    if duration > MAX_RUN_PS + 0.001:
                        failures.append(f"configured run duration exceeds 50 ps: {label}")
                    declared_mdp_hash = item.get("mdp_sha256", item.get("input_mdp_sha256"))
                    if declared_mdp_hash is not None and declared_mdp_hash != digest(input_mdp):
                        failures.append(f"input-audit MDP hash differs from submitted MDP: {label}")
                    elif declared_mdp_hash is None:
                        warnings.append(f"NOT_VERIFIED: input-audit omits submitted MDP SHA-256: {label}")
                    if input_values.get("gen_vel", "no").lower() == "yes":
                        seed = int(input_values.get("gen_seed", ""))
                        declared_seed = item.get("gen_seed", item.get("seed"))
                        if declared_seed != seed:
                            failures.append(f"input-audit velocity seed differs from submitted MDP: {label}")
                    elif item.get("seed") is not None:
                        try:
                            int(item["seed"])
                        except (TypeError, ValueError):
                            failures.append(f"input-audit seed is not an integer: {label}")
                except (OSError, ValueError, TypeError) as exc:
                    failures.append(f"submitted MDP or configured plan cannot be parsed for {label}: {exc}")
            else:
                warnings.append(f"NOT_VERIFIED: no supported submitted-MDP filename is available: {label}")
                try:
                    raw_steps = item.get("nsteps")
                    if type(raw_steps) is not int or raw_steps <= 0:
                        raise ValueError("nsteps must be a positive integer")
                    input_steps = raw_steps
                    duration = input_steps * dt / 1000.0
                    planned_duration[label] = duration
                    if not close_number(item.get("duration_ps"), duration, 0.001):
                        failures.append(f"input-audit configured duration differs from dt*nsteps: {label}")
                    if duration > MAX_RUN_PS + 0.001:
                        failures.append(f"configured run duration exceeds 50 ps: {label}")
                    warnings.append(f"NOT_VERIFIED: MDP physical settings and submitted MDP hash cannot be checked without the run file: {label}")
                except (TypeError, ValueError) as exc:
                    failures.append(f"input-audit configured plan is invalid for {label}: {exc}")
            if item.get("coordinate_sha256") != digest(expected_coord):
                failures.append(f"wrong initial coordinate provenance: {label}")
            if item.get("topology_sha256") != digest(app / "environment" / "assets" / "topol.top"):
                failures.append(f"wrong topology provenance: {label}")
            coordinate_path = run_file(run_dir, "coordinate", item.get("coordinate_file"))
            if coordinate_path is None:
                warnings.append(f"NOT_VERIFIED: no supported initial-coordinate filename is available: {label}")
            elif digest(coordinate_path) != digest(expected_coord):
                failures.append(f"run start coordinates differ from public state: {label}")
            topology_path = run_file(run_dir, "topology", item.get("topology_file"))
            if topology_path is None:
                warnings.append(f"NOT_VERIFIED: no supported submitted-topology filename is available: {label}")
            elif digest(topology_path) != digest(app / "environment" / "assets" / "topol.top"):
                failures.append(f"run topology differs from public topology: {label}")
            failure_record = run_dir / "failure.json"
            early_failure = read_json(failure_record) if failure_record.is_file() else {}
            grompp_failed = isinstance(early_failure, dict) and early_failure.get("stage") == "grompp"
            if run_file(run_dir, "grompp_log") is None:
                warnings.append(f"NOT_VERIFIED: no supported grompp log filename is available: {label}")
            grompp_exit = run_dir / "grompp.exit"
            if grompp_exit.is_file():
                try:
                    if int(grompp_exit.read_text(encoding="ascii").strip()) != 0:
                        grompp_failed = True
                except (OSError, ValueError):
                    warnings.append(f"NOT_VERIFIED: cannot parse grompp.exit: {label}")
            if grompp_failed:
                if not isinstance(early_failure.get("exit_code"), int) or early_failure["exit_code"] == 0:
                    failures.append(f"grompp failure record is invalid: {label}")
                else:
                    warnings.append({"run": label, "native_failure_record": early_failure,
                                     "review_required": "grompp failed before a native trajectory was created"})
            else:
                for filename in ("mdout.mdp", "topol.tpr"):
                    if not (run_dir / filename).is_file():
                        warnings.append(f"NOT_VERIFIED: native input/record {filename} is unavailable: {label}")
                if run_file(run_dir, "processed_topology") is None:
                    warnings.append(f"NOT_VERIFIED: processed topology is missing or unavailable: {label}")
            index_path = run_file(run_dir, "index")
            if index_path is None:
                warnings.append(f"NOT_VERIFIED: no supported index-file filename is available: {label}")
            elif coordinate_path is not None:
                try:
                    expected_groups = expected_index_groups(coordinate_path)
                    actual_groups = index_groups(index_path)
                    for group, expected_atoms in expected_groups.items():
                        if actual_groups.get(group) != expected_atoms:
                            failures.append(f"index group {group} differs from start coordinates: {label}")
                except (OSError, ValueError, UnicodeError) as exc:
                    warnings.append(f"NOT_VERIFIED: index or coordinates cannot be independently parsed for {label}: {exc}")
            mdp_path = run_dir / "mdout.mdp"
            if mdp_path.is_file():
                values = mdp_values(mdp_path)
                failures.extend(f"{message}: {label}" for message in effective_mdp_errors(values, dt))
                try:
                    if input_steps is not None and int(values.get("nsteps", "")) != input_steps:
                        failures.append(f"effective TPR step count differs from submitted MDP: {label}")
                    if (input_values.get("gen_vel", "no").lower() == "yes"
                            and int(values.get("gen_seed", "")) != int(input_values.get("gen_seed", ""))):
                        failures.append(f"effective TPR seed differs from submitted MDP: {label}")
                except (TypeError, ValueError):
                    failures.append(f"effective MDP nsteps or seed is invalid: {label}")
            elif not grompp_failed:
                warnings.append(f"NOT_VERIFIED: effective MDP is unavailable: {label}")
            dump = run_file(run_dir, "tpr_dump")
            if dump is not None:
                vectors = vector_hashes(dump)
                if not {"x", "v"}.issubset(vectors):
                    warnings.append(f"NOT_VERIFIED: TPR dump lacks parseable coordinates or velocities: {label}")
                else:
                    if item.get("x_vector_sha256") != vectors["x"] or item.get("v_vector_sha256") != vectors["v"]:
                        failures.append(f"input-audit TPR vector hash mismatch: {label}")
            elif not grompp_failed:
                warnings.append(f"NOT_VERIFIED: TPR coordinate/velocity dump unavailable: {label}")
            for ext, description in ((".edr", "energy record"), (".xtc", "trajectory"), (".cpt", "checkpoint")):
                if not any(path.is_file() for path in run_dir.glob("*" + ext)) and not failure_record.is_file():
                    warnings.append(f"NOT_VERIFIED: native {description} unavailable: {label}")
            if not any(path.is_file() for path in run_dir.glob("*.gro") if coordinate_path is None or path != coordinate_path) and not failure_record.is_file():
                warnings.append(f"NOT_VERIFIED: native final/sample GRO unavailable: {label}")
            energy_series_path = (derived_energy_dir / f"{label}.xvg") if derived_energy_dir else run_file(run_dir, "energy")
            if energy_series_path is not None and energy_series_path.is_file():
                try:
                    legends, rows = xvg_values(energy_series_path)
                    times = [row[0] for row in rows]
                    observed_duration = max(times) - min(times)
                    actual_duration[label] = observed_duration
                    if observed_duration > MAX_RUN_PS + 0.001:
                        failures.append(f"observed simulation exceeds 50 ps: {label}")
                    if max(times) > MAX_RUN_PS + 0.001:
                        failures.append(f"energy time exceeds 50 ps: {label}")
                    if label in planned_duration and observed_duration > planned_duration[label] + 0.001:
                        failures.append(f"observed simulation exceeds its configured step budget: {label}")
                    for term in ("temperature", "potential", "kinetic en.", "total energy"):
                        if term not in legends:
                            failures.append(f"energy series lacks {term}: {label}")
                    if item.get("actual_duration_ps") is not None and abs(item["actual_duration_ps"] - observed_duration) > 0.001:
                        failures.append(f"input-audit actual duration differs from energy series: {label}")
                except (OSError, ValueError, UnicodeError) as exc:
                    failures.append(f"invalid energy series {label}: {exc}")
            else:
                warnings.append(f"NOT_VERIFIED: native energy series could not be independently extracted: {label}")
            final_step_time = logged_final_step_time(run_dir)
            if final_step_time is not None and input_steps is not None:
                final_step, final_time = final_step_time
                initial_step = int(input_values.get("init-step", "0") or "0")
                initial_time = float(input_values.get("tinit", "0") or "0")
                simulated_steps = max(0, final_step - initial_step)
                run_time = max(0.0, final_time - initial_time)
                observed_steps[label] = simulated_steps
                if run_time > MAX_RUN_PS + 0.001 or simulated_steps * dt / 1000.0 > MAX_RUN_PS + 0.001:
                    failures.append(f"observed run exceeds 50 ps: {label}")
                if simulated_steps > input_steps:
                    failures.append(f"observed steps exceed the configured MDP: {label}")
                if item.get("completed_configured_steps") is True and simulated_steps != input_steps:
                    failures.append(f"reported configured-step completion conflicts with native log: {label}")
                if item.get("actual_duration_ps") is not None and not close_number(item["actual_duration_ps"], run_time, 0.001):
                    failures.append(f"input-audit actual duration differs from native log: {label}")
                actual_duration.setdefault(label, run_time)
            elif not failure_record.is_file():
                warnings.append(f"NOT_VERIFIED: native log has no parseable final step/time: {label}")
            if failure_record.is_file():
                try:
                    failure = read_json(failure_record)
                    warnings.append({"run": label, "native_failure_record": failure})
                except (OSError, ValueError):
                    failures.append(f"invalid native failure record: {label}")
        if sum(planned_duration.values()) > MAX_TOTAL_PS + 0.001:
            failures.append("configured four-run plan exceeds 200 ps total")
        if sum(actual_duration.values()) > MAX_TOTAL_PS + 0.001:
            failures.append("observed four-run simulation exceeds 200 ps total")
        for state in ("B", "U"):
            one, two = f"{state}-dt1fs", f"{state}-dt2fs"
            if (one in planned_duration and two in planned_duration
                    and not close_number(planned_duration[one], planned_duration[two], 0.001)):
                warnings.append({"state": state, "NOT_VERIFIED": "paired configured durations differ; scientific comparison must use an explicit common window"})
            if (one in actual_duration and two in actual_duration
                    and not close_number(actual_duration[one], actual_duration[two], 0.001)):
                warnings.append({"state": state, "NOT_VERIFIED": "paired observed durations differ; scientific comparison must use an explicit common window"})
        # Pairing is checked independently from the candidate's claimed hash values.
        for state in ("B", "U"):
            a = run_file(submission / "runs" / f"{state}-dt1fs", "tpr_dump")
            b = run_file(submission / "runs" / f"{state}-dt2fs", "tpr_dump")
            if a is not None and b is not None:
                va, vb = vector_hashes(a), vector_hashes(b)
                for kind in ("x", "v"):
                    if kind not in va or kind not in vb:
                        warnings.append(f"NOT_VERIFIED: paired TPR {kind} vectors cannot be parsed for {state}")
                    elif va[kind] != vb[kind]:
                        failures.append(f"paired {state} TPR {kind} vectors differ")
            else:
                warnings.append(f"NOT_VERIFIED: paired TPR coordinate/velocity vectors unavailable for {state}")
        diagnostics_path = submission / "diagnostics.csv"
        comparison_path = submission / "numerical-comparison.json"
        if diagnostics_path.is_file() and comparison_path.is_file():
            try:
                expected_rows, expected_stats = recompute_diagnostics(submission, derived_energy_dir)
                with diagnostics_path.open(newline="", encoding="utf-8") as handle:
                    observed_rows = list(csv.DictReader(handle))
                comparison = read_json(comparison_path)
                available_labels = set(LABELS)
                replayable_labels = set(expected_stats)
                if not observed_rows:
                    failures.append("diagnostics.csv contains no sampled observations")
                seen_rows = set()
                canonical_fields_seen = set()
                unsupported_fields = set()
                geometry_method = str(comparison.get("geometry_method", "")).lower()
                canonical_geometry = all(token in geometry_method for token in ("first 20", "pbc", "o-h", "h-h"))
                warning_method = str(comparison.get("postprocess_warning_method", "")).lower()
                canonical_warning = "whole-word" in warning_method and "md.log" in warning_method
                energy_columns = {
                    "temperature_K": "Temperature", "potential": "Potential",
                    "kinetic_en": "Kinetic En.", "total_energy": "Total Energy",
                    "conserved_en": "Conserved En.", "constr_rmsd": "Constr. rmsd",
                    "t_ocb": "T-OCB", "t_mol": "T-MOL", "t_water_and_ions": "T-Water_and_ions",
                }
                for index, observed in enumerate(observed_rows):
                    row_num = index + 2
                    label = observed.get("run", "")
                    if label not in LABELS:
                        failures.append(f"diagnostics.csv references an unknown run at row {row_num}")
                        continue
                    try:
                        time_ps = float(observed.get("time_ps", ""))
                    except (TypeError, ValueError):
                        failures.append(f"diagnostics.csv has invalid time_ps at row {row_num}")
                        continue
                    if not math.isfinite(time_ps) or time_ps < 0 or time_ps > MAX_RUN_PS + 0.001:
                        failures.append(f"diagnostics.csv time_ps is outside the run budget at row {row_num}")
                        continue
                    source_raw = observed.get("source_frame", "")
                    source_rel = Path(source_raw)
                    run_dir = submission / "runs" / label
                    if not source_raw:
                        failures.append(f"diagnostics.csv source_frame is empty at row {row_num}")
                        continue
                    source_path = None
                    if source_rel.is_absolute() or ".." in source_rel.parts:
                        failures.append(f"diagnostics.csv source_frame is unsafe at row {row_num}")
                        continue
                    if source_raw.startswith(f"runs/{label}/"):
                        source_path = submission / source_rel
                        if source_path.is_symlink():
                            failures.append(f"diagnostics.csv source_frame is a symlink at row {row_num}")
                            continue
                        if not source_path.is_file():
                            warnings.append("NOT_VERIFIED: one or more declared diagnostic source frames are unavailable")
                            source_path = None
                        else:
                            try:
                                source_path.resolve().relative_to(run_dir.resolve())
                            except ValueError:
                                failures.append(f"diagnostics.csv source_frame escapes its run at row {row_num}")
                                continue
                    else:
                        warnings.append("NOT_VERIFIED: non-path diagnostic source references require manual review")
                    identity = (label, time_ps, source_raw)
                    if identity in seen_rows:
                        warnings.append(f"NOT_VERIFIED: duplicate diagnostic sample at row {row_num}")
                    seen_rows.add(identity)

                    frame_values = {}
                    is_gro = source_path is not None and source_path.suffix.lower() == ".gro"
                    if is_gro:
                        try:
                            geometry = water_geometry(source_path)
                            frame_time = geometry["time_ps"]
                            if frame_time is not None and not close_number(time_ps, frame_time, DIAGNOSTIC_ABS_TOLERANCE["time_ps"]):
                                failures.append(f"diagnostics.csv time_ps differs from native frame at row {row_num}")
                            frame_values.update({
                                "time_ps": frame_time if frame_time is not None else time_ps,
                                "box_x_nm": geometry["box"][0], "box_y_nm": geometry["box"][1],
                                "box_z_nm": geometry["box"][2],
                                "water20_oh_mean_nm": geometry["water20_oh_mean_nm"],
                                "water20_hh_mean_nm": geometry["water20_hh_mean_nm"],
                                "water20_angle_mean_deg": geometry["water20_angle_mean_deg"],
                            })
                        except (OSError, ValueError, UnicodeError, ZeroDivisionError) as exc:
                            warnings.append(f"NOT_VERIFIED: cannot independently interpret diagnostic frame {source_raw}: {exc}")
                    elif source_path is not None:
                        warnings.append("NOT_VERIFIED: non-GRO diagnostic frames require manual method review")

                    energy_path = (derived_energy_dir / f"{label}.xvg") if derived_energy_dir else run_file(run_dir, "energy")
                    if energy_path is not None and energy_path.is_file():
                        legends, energy_rows = xvg_values(energy_path)
                        nearest = min(energy_rows, key=lambda row: abs(row[0] - time_ps))
                        if abs(nearest[0] - time_ps) <= DIAGNOSTIC_ABS_TOLERANCE["time_ps"]:
                            for column, term in energy_columns.items():
                                frame_values[column] = xvg_energy(legends, nearest, term)
                        else:
                            warnings.append("NOT_VERIFIED: one or more diagnostics times do not match a native energy sample")
                    else:
                        pass
                    frame_values["warning_count"] = log_warning_count(run_dir)

                    numeric_count = 0
                    for field, raw in observed.items():
                        if field in {"run", "source_frame", "method", "geometry_method", "water_selection"}:
                            continue
                        try:
                            numeric = float(raw)
                        except (TypeError, ValueError):
                            if raw not in (None, ""):
                                unsupported_fields.add(field)
                            continue
                        if not math.isfinite(numeric):
                            failures.append(f"diagnostics.csv contains non-finite {field} at row {row_num}")
                            continue
                        if field != "time_ps":
                            numeric_count += 1
                        canonical_field = {"temperature": "temperature_K"}.get(field, field)
                        if canonical_field not in DIAGNOSTIC_ABS_TOLERANCE:
                            unsupported_fields.add(field)
                            continue
                        canonical_fields_seen.add(canonical_field)
                        if canonical_field.startswith("water20_") and not canonical_geometry:
                            unsupported_fields.add(field)
                            continue
                        if canonical_field == "warning_count" and not canonical_warning:
                            unsupported_fields.add(field)
                            continue
                        expected_value = frame_values.get(canonical_field)
                        if expected_value is None:
                            warnings.append(f"NOT_VERIFIED: native recomputation unavailable for diagnostic field {field}")
                            continue
                        if not close_number(numeric, expected_value, DIAGNOSTIC_ABS_TOLERANCE[canonical_field]):
                            failures.append(f"diagnostics.csv {field} differs from native data at row {row_num}")
                    if numeric_count == 0:
                        failures.append(f"diagnostics.csv row {row_num} has no finite numeric diagnostics")
                rows_by_label = {label: 0 for label in available_labels}
                for row in observed_rows:
                    if row.get("run") in rows_by_label:
                        rows_by_label[row["run"]] += 1
                for label, count in rows_by_label.items():
                    if count == 0:
                        warnings.append(f"NOT_VERIFIED: diagnostics.csv has no rows for {label}")
                if unsupported_fields:
                    warnings.append("NOT_VERIFIED: unsupported diagnostic fields or alternate methods require manual review: "
                                    + ", ".join(sorted(unsupported_fields)))
                canonical_missing = set(DIAGNOSTIC_NUMBERS) - canonical_fields_seen
                if canonical_missing:
                    warnings.append("NOT_VERIFIED: candidate omits canonical diagnostics: " + ", ".join(sorted(canonical_missing)))

                paired = comparison.get("paired_parameter_diff")
                if not isinstance(paired, dict):
                    warnings.append("NOT_VERIFIED: paired_parameter_diff is absent or uses an unsupported structure")
                else:
                    for state in ("B", "U"):
                        evidence = paired.get(state)
                        if not isinstance(evidence, dict):
                            warnings.append(f"NOT_VERIFIED: paired parameter evidence is unavailable: {state}")
                            continue
                        if evidence.get("same_coordinate_input") is False:
                            failures.append(f"paired {state} comparison does not claim the same initial coordinates")
                        elif evidence.get("same_coordinate_input") is not True:
                            warnings.append(f"NOT_VERIFIED: paired {state} coordinate claim is missing")
                        observed_vectors = evidence.get("velocity_vector_hashes")
                        expected_vectors = {}; vectors_replayable = True
                        for dt in (1, 2):
                            dump_path = run_file(submission / "runs" / f"{state}-dt{dt}fs", "tpr_dump")
                            hashes = vector_hashes(dump_path) if dump_path is not None else {}
                            expected_vectors[f"dt{dt}fs"] = hashes.get("v")
                            if hashes.get("v") is None: vectors_replayable = False
                        if observed_vectors is not None and vectors_replayable and observed_vectors != expected_vectors:
                            failures.append(f"paired velocity hashes differ from native TPR dumps: {state}")
                        elif not vectors_replayable:
                            warnings.append(f"NOT_VERIFIED: paired {state} TPR velocity hashes cannot be independently replayed")
                        elif observed_vectors is None:
                            warnings.append(f"NOT_VERIFIED: paired {state} velocity hash claims are missing")
                statistics_obj = comparison.get("statistics")
                observed_stats = statistics_obj.get("by_run_and_timeblock") if isinstance(statistics_obj, dict) else None
                if not isinstance(observed_stats, dict):
                    warnings.append("NOT_VERIFIED: numerical-comparison statistics use a missing or unsupported layout")
                else:
                    for label in set(observed_stats) - available_labels:
                        warnings.append(f"NOT_VERIFIED: statistics use an unsupported run label: {label}")
                    for label, windows in observed_stats.items():
                        if label not in available_labels:
                            continue
                        if label not in replayable_labels:
                            warnings.append(f"NOT_VERIFIED: energy statistics cannot be replayed for {label}")
                            continue
                        if not isinstance(windows, dict):
                            failures.append(f"numerical-comparison windows are malformed: {label}")
                            continue
                        for window, terms in windows.items():
                            if window not in expected_stats.get(label, {}):
                                warnings.append(f"NOT_VERIFIED: alternate time window {label}/{window} requires manual review")
                                continue
                            if not isinstance(terms, dict):
                                failures.append(f"numerical-comparison terms are malformed: {label}/{window}")
                                continue
                            expected_terms = expected_stats[label][window]
                            for term, observed_summary in terms.items():
                                expected_summary = expected_terms.get(term)
                                if expected_summary is None:
                                    warnings.append(f"NOT_VERIFIED: unsupported comparison term {label}/{window}/{term}")
                                    continue
                                if not isinstance(observed_summary, dict):
                                    failures.append(f"numerical-comparison summary is malformed: {label}/{window}/{term}")
                                    continue
                                try:
                                    n = int(observed_summary.get("n", -1))
                                    mean = observed_summary.get("mean")
                                    sd = observed_summary.get("sd_population")
                                    if n < 0 or (mean is not None and not math.isfinite(float(mean))) or (sd is not None and (not math.isfinite(float(sd)) or float(sd) < 0)):
                                        raise ValueError("invalid n/mean/sd")
                                except (TypeError, ValueError):
                                    failures.append(f"numerical-comparison summary contains invalid numbers: {label}/{window}/{term}")
                                    continue
                                if n != expected_summary["n"]:
                                    warnings.append(f"NOT_VERIFIED: alternate sampling density for {label}/{window}/{term}")
                                    continue
                                for stat_name in ("mean", "sd_population"):
                                    expected_value = expected_summary[stat_name]
                                    observed_value = observed_summary.get(stat_name)
                                    tolerance = 0.01 if "energy" in term.lower() or term.lower() == "potential" else 0.005
                                    if expected_value is None:
                                        if observed_value is not None:
                                            failures.append(f"numerical-comparison {stat_name} should be null: {label}/{window}/{term}")
                                    elif not close_number(observed_value, expected_value, tolerance):
                                        failures.append(f"numerical-comparison {stat_name} differs from native data: {label}/{window}/{term}")
                    for label in available_labels - set(observed_stats):
                        warnings.append(f"NOT_VERIFIED: comparison statistics are missing for {label}")
            except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
                failures.append(f"cannot independently recompute diagnostics from native artifacts: {exc}")
        elif not diagnostics_path.is_file() or not comparison_path.is_file():
            failures.append("diagnostics.csv or numerical-comparison.json is missing")
        checks.append({"check": "input_native_and_paired_run_constraints", "status": "FAIL" if failures else "CHECKED"})
    else:
        failures.append("input-audit.json cannot be parsed")

    if provenance_path.is_file():
        provenance = read_json(provenance_path)
        if not provenance.get("job_id"):
            failures.append("remote-provenance.job_id is missing")
        source_path = submission / "source-manifest.json"
        source_manifest = provenance.get("source_manifest")
        source_manifest_hash = provenance.get("source_manifest_sha256")
        if source_path.is_file():
            if source_manifest_hash is not None and source_manifest_hash != digest(source_path):
                failures.append("source manifest SHA256 differs from remote provenance")
            try:
                observed_manifest = read_json(source_path)
                if isinstance(source_manifest, dict) and observed_manifest != source_manifest:
                    failures.append("remote provenance source manifest differs from retained source-manifest.json")
                elif source_manifest is not None and not isinstance(source_manifest, dict):
                    warnings.append("NOT_VERIFIED: remote source manifest uses an unsupported structure")
                if source_manifest is None or source_manifest_hash is None:
                    warnings.append("NOT_VERIFIED: retained source manifest is not fully bound by remote provenance")
            except (OSError, ValueError, UnicodeError):
                warnings.append("NOT_VERIFIED: retained source manifest cannot be parsed")
        elif source_manifest is not None or source_manifest_hash is not None:
            warnings.append("NOT_VERIFIED: provenance cites a source manifest but no retained manifest is available")
        else:
            warnings.append("NOT_VERIFIED: source-manifest.json was not supplied")
        receipt = provenance.get("scheduler_receipt")
        if not isinstance(receipt, dict):
            warnings.append("scheduler receipt missing; remote execution remains unverified")
        else:
            receipt_fields = receipt.get("fields") if isinstance(receipt.get("fields"), dict) else {}
            receipt_values = {}
            for key in ("JobIDRaw", "Partition", "State", "ExitCode"):
                nested = receipt_fields.get(key)
                flat = receipt.get(key)
                if nested is not None and flat is not None and str(nested) != str(flat):
                    failures.append(f"scheduler receipt has conflicting nested/flat {key} values")
                value = nested if nested is not None else flat
                receipt_values[key] = value
                if value is None:
                    warnings.append(f"NOT_VERIFIED: scheduler receipt omits {key}")
            receipt_job_id = receipt_values.get("JobIDRaw")
            if receipt_job_id is not None and str(receipt_job_id) != str(provenance.get("job_id")):
                failures.append("scheduler receipt job id does not match submission")
            if receipt_values.get("Partition") is not None and str(receipt_values["Partition"]).casefold() != "cpu":
                warnings.append("NOT_VERIFIED: scheduler queue name is not the familiar cpu label; queue names do not establish allocated hardware")
            if (receipt_values.get("State") is not None and provenance.get("scheduler_state") is not None
                    and str(receipt_values["State"]).casefold() != str(provenance.get("scheduler_state")).casefold()):
                failures.append("scheduler receipt state conflicts with remote provenance")
            def normalized_exit_code(value):
                if type(value) is int:
                    return f"{value}:0"
                text = str(value).strip()
                return f"{text}:0" if re.fullmatch(r"\d+", text) else text
            if (receipt_values.get("ExitCode") is not None and provenance.get("scheduler_exit_code") is not None
                    and normalized_exit_code(receipt_values["ExitCode"]) != normalized_exit_code(provenance.get("scheduler_exit_code"))):
                failures.append("scheduler receipt exit code conflicts with remote provenance")
            if ((receipt_values.get("State") is not None and receipt_values["State"] != "COMPLETED")
                    or (receipt_values.get("ExitCode") is not None and str(receipt_values["ExitCode"]) != "0:0")):
                warnings.append("scheduler reports unsuccessful or incomplete execution")
        if provenance.get("trusted_runner_receipt") is None:
            warnings.append("NOT_INTEGRATED: no runner-owned execution receipt is available")
        resources = provenance.get("resources")
        if not isinstance(resources, dict):
            warnings.append("NOT_VERIFIED: allocated hardware resources are not reported")
        else:
            for key, cap in (("cpus_allocated", max_cpus), ("gpus", max_gpus), ("nodes", max_nodes)):
                value = resources.get(key)
                if value is None:
                    warnings.append(f"NOT_VERIFIED: allocated {key} is not reported")
                    continue
                try:
                    if isinstance(value, bool) or int(value) < 0:
                        raise ValueError
                    if int(value) > cap:
                        failures.append(f"reported allocated {key} exceeds public compute budget ({cap})")
                except (TypeError, ValueError):
                    warnings.append(f"NOT_VERIFIED: allocated {key} is not an integer")
        allocation = provenance.get("allocation_accounting")
        if not isinstance(allocation, dict):
            warnings.append("NOT_VERIFIED: allocation attempt accounting was not supplied")
        else:
            stated_limit = allocation.get("stated_max_allocations_in_compute_budget")
            if stated_limit is not None:
                try:
                    if int(stated_limit) != max_allocations:
                        failures.append("reported allocation limit differs from public compute-budget.yaml")
                except (TypeError, ValueError):
                    warnings.append("NOT_VERIFIED: allocation limit claim is not numeric")
            else:
                warnings.append("NOT_VERIFIED: allocation accounting omits the public allocation limit")
            used_raw = allocation.get("allocations_actually_used")
            try:
                used = int(used_raw) if not isinstance(used_raw, bool) else None
            except (TypeError, ValueError):
                used = None
            if used is None:
                warnings.append("NOT_VERIFIED: allocation attempt count is unavailable")
            native_failure = provenance.get("native_failure_evidence")
            failed_job = native_failure.get("job_id") if isinstance(native_failure, dict) else None
            separately_reported_failed_job = allocation.get("failed_job_id")
            primary_job = str(provenance.get("job_id", ""))
            receipt_job = receipt_values.get("JobIDRaw") if isinstance(receipt, dict) else None
            if failed_job is not None and separately_reported_failed_job is not None and str(failed_job) != str(separately_reported_failed_job):
                failures.append("native failure evidence job ID conflicts with allocation accounting")
            confirmed_jobs = set()
            if receipt_job is not None and str(receipt_job) == primary_job and primary_job:
                confirmed_jobs.add(primary_job)
            if failed_job is not None and primary_job and str(failed_job) != primary_job:
                confirmed_jobs.add(str(failed_job))
            elif failed_job is not None and primary_job and str(failed_job) == primary_job and used is not None and used > 1:
                failures.append("allocation accounting claims multiple allocations but repeats the primary job ID")
            if len(confirmed_jobs) > max_allocations:
                failures.append(f"confirmed {len(confirmed_jobs)} distinct scheduler allocations exceed public max_allocations={max_allocations}")
            elif used is not None and used > max_allocations and len(confirmed_jobs) < used:
                warnings.append("NOT_VERIFIED: claimed allocation excess lacks independent distinct job-ID confirmation")
            elif used is not None and len(confirmed_jobs) >= 2 and used != len(confirmed_jobs):
                failures.append("allocation attempt count conflicts with distinct receipt/failure job IDs")
            if isinstance(native_failure, dict):
                files = native_failure.get("files")
                if isinstance(files, list):
                    for entry in files:
                        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                            warnings.append("NOT_VERIFIED: native failure file evidence has an unsupported entry")
                            continue
                        rel = Path(entry["path"])
                        path = submission / rel
                        if rel.is_absolute() or ".." in rel.parts or path.is_symlink() or not path.is_file():
                            failures.append(f"native failure evidence file is missing or unsafe: {entry['path']}")
                        elif entry.get("sha256") != digest(path):
                            failures.append(f"native failure evidence hash mismatch: {entry['path']}")
                elif files is not None:
                    warnings.append("NOT_VERIFIED: native failure evidence files use an unsupported structure")
        total_ps = provenance.get("total_simulated_ps")
        if total_ps is not None and actual_duration:
            if not isinstance(total_ps, (int, float)) or isinstance(total_ps, bool) or not math.isfinite(float(total_ps)):
                failures.append("remote-provenance total_simulated_ps is invalid")
            elif not close_number(total_ps, sum(actual_duration.values()), 0.001):
                failures.append("remote-provenance total simulated time differs from native run logs/energy")
        if actual_duration and sum(actual_duration.values()) > MAX_TOTAL_PS + 0.001:
            failures.append("observed four-run simulation exceeds 200 ps total")
        total_steps = provenance.get("total_steps")
        if total_steps is not None and len(observed_steps) == len(LABELS):
            if type(total_steps) is not int or total_steps != sum(observed_steps.values()):
                failures.append("remote-provenance total_steps differs from native run logs")
    else:
        warnings.append("remote-provenance.json missing; no current execution can be established")
    if comparison_path.is_file():
        comparison = read_json(comparison_path)
        if not isinstance(comparison.get("statistics"), dict):
            warnings.append("NOT_VERIFIED: numerical-comparison statistics are missing or unsupported")
    if decision_path.is_file():
        decision = read_json(decision_path)
        allowed = {"continue", "continue_bounded", "smaller_dt", "stop", "needs_check"}
        if decision.get("decision") not in allowed:
            failures.append("continuation decision is missing or outside the contract")
        for key in ("evidence", "alternative", "inference_limits", "next_budget"):
            if key not in decision:
                failures.append(f"continuation decision is missing {key}")
    if (submission / "scientific-rationale.md").is_file():
        text = (submission / "scientific-rationale.md").read_text(encoding="utf-8", errors="replace").lower()
        for phrase in ("equilibration", "free energy", "kinetics"):
            if phrase not in text:
                warnings.append(f"scientific rationale does not state inference limit: {phrase}")
    return {"state": "FAIL" if failures else "CHECKED", "checks": checks,
            "failures": failures, "warnings": list(dict.fromkeys(warnings))}


def main():
    from review_status import main as review_main
    return review_main()


if __name__ == "__main__":
    sys.exit(main())
