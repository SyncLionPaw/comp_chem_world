#!/usr/bin/env python3
"""Native GROMACS artifact extraction for the bounded Case 08 task."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

LABELS = ("B-dt1fs", "B-dt2fs", "U-dt1fs", "U-dt2fs")
INPUTS = (
    "NVT-50ps-dt1fs.mdp", "NVT-50ps-dt2fs.mdp", "NVT.mdp", "b.gro",
    "conf_template.pdb", "remote-input-provenance.json", "topol.top", "u.gro",
)
ENERGY_KEYS = (
    "Temperature", "Potential", "Kinetic En.", "Total Energy", "Conserved En.",
    "Constr. rmsd", "T-OCB", "T-MOL", "T-Water_and_ions", "Box-X", "Box-Y", "Box-Z",
)
CSV_FIELDS = (
    "run", "time_ps", "temperature_K", "potential", "kinetic_en", "total_energy",
    "conserved_en", "constr_rmsd", "t_ocb", "t_mol", "t_water_and_ions",
    "box_x_nm", "box_y_nm", "box_z_nm", "warning_count", "water20_oh_mean_nm",
    "water20_hh_mean_nm", "water20_angle_mean_deg", "source_frame",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def native_manifest(submission: Path):
    manifest = {}
    for path in sorted((submission / "runs").rglob("*")):
        if path.is_symlink():
            raise ValueError(f"native output contains a symlink: {path}")
        if path.is_file():
            manifest[path.relative_to(submission).as_posix()] = {
                "sha256": sha256(path), "bytes": path.stat().st_size,
            }
        elif not path.is_dir():
            raise ValueError(f"native output contains a special file: {path}")
    return manifest


def canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def gro_atoms(path: Path):
    lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    n = int(lines[1].strip())
    if len(lines) < n + 3:
        raise ValueError(f"truncated GRO file: {path}")
    atoms = []
    for atom_id, line in enumerate(lines[2:2 + n], 1):
        atoms.append({
            "id": atom_id, "resid": int(line[:5]), "resname": line[5:10].strip(),
            "name": line[10:15].strip(),
            "xyz": [float(line[i:i + 8]) for i in (20, 28, 36)],
        })
    box = [float(v) for v in lines[2 + n].split()[:3]]
    if len(box) != 3 or any(v <= 0 for v in box):
        raise ValueError(f"invalid GRO box in {path}")
    return atoms, box, lines[0]


def make_index(gro: Path, output: Path) -> None:
    atoms, _, _ = gro_atoms(gro)
    selections = {
        "OCB": [a["id"] for a in atoms if a["resname"] == "OCB"],
        "MOL": [a["id"] for a in atoms if a["resname"] == "MOL"],
        "Water_and_ions": [a["id"] for a in atoms if a["resname"] in {"WAT", "Na+"}],
        "non-Water": [a["id"] for a in atoms if a["resname"] != "WAT"],
    }
    if any(not members for members in selections.values()):
        raise ValueError("initial GRO does not contain all thermostat groups")
    with output.open("w", encoding="ascii") as handle:
        for name, members in selections.items():
            handle.write(f"[ {name} ]\n")
            for start in range(0, len(members), 15):
                handle.write(" ".join(str(i) for i in members[start:start + 15]) + "\n")


def pbc_distance(a, b, box):
    d = [b[i] - a[i] - round((b[i] - a[i]) / box[i]) * box[i] for i in range(3)]
    return math.sqrt(sum(v * v for v in d))


def water20_geometry(path: Path):
    atoms, box, title = gro_atoms(path)
    waters = [a for a in atoms if a["resname"] == "WAT"]
    if len(waters) < 60:
        raise ValueError(f"fewer than 20 waters in {path}")
    oh, hh, angle = [], [], []
    for i in range(0, 60, 3):
        o, h1, h2 = waters[i:i + 3]
        if (o["name"], h1["name"], h2["name"]) != ("O", "H1", "H2"):
            raise ValueError(f"unexpected water atom order in {path}")
        d1 = pbc_distance(o["xyz"], h1["xyz"], box)
        d2 = pbc_distance(o["xyz"], h2["xyz"], box)
        dhh = pbc_distance(h1["xyz"], h2["xyz"], box)
        v1 = [h1["xyz"][j] - o["xyz"][j] for j in range(3)]
        v2 = [h2["xyz"][j] - o["xyz"][j] for j in range(3)]
        v1 = [v1[j] - round(v1[j] / box[j]) * box[j] for j in range(3)]
        v2 = [v2[j] - round(v2[j] / box[j]) * box[j] for j in range(3)]
        cosine = sum(v1[j] * v2[j] for j in range(3)) / (d1 * d2)
        oh.extend((d1, d2))
        hh.append(dhh)
        angle.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))) )
    t = re.search(r"\bt\s*=\s*([-+0-9.eE]+)", title)
    time_ps = float(t.group(1)) if t else None
    return {
        "time_ps": time_ps, "box": box,
        "oh_mean_nm": sum(oh) / len(oh), "hh_mean_nm": sum(hh) / len(hh),
        "angle_mean_deg": sum(angle) / len(angle),
    }


def read_xvg(path: Path):
    legends = {}
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r'\s*@\s+s(\d+)\s+legend\s+"(.*?)"', line)
        if match:
            legends[match.group(2)] = int(match.group(1)) + 1
        if not line.strip() or line.lstrip()[0] in "#@&":
            continue
        values = [float(value) for value in line.split()]
        if len(values) > 1:
            rows.append(values)
    if not rows:
        raise ValueError(f"no numeric energy samples in {path}")
    return legends, rows


def find_energy(legends, row, key):
    candidates = (key, key.replace(" ", ""))
    idx = next((legends[name] for name in candidates if name in legends), None)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_mdp(path: Path):
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split(";", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip().lower()] = value.strip()
    return out


def configured_run(mdp: dict):
    """Return configured endpoint using GROMACS MDP time units (ps, fs)."""
    nsteps = int(mdp["nsteps"])
    dt_fs = float(mdp["dt"])
    init_step = int(mdp.get("init-step", "0"))
    tinit_ps = float(mdp.get("tinit", "0"))
    return {
        "nsteps": nsteps, "dt_fs": dt_fs * 1000.0,
        "duration_ps": nsteps * dt_fs,
        "tinit_ps": tinit_ps,
        "start_ps": tinit_ps + init_step * dt_fs,
        "end_ps": tinit_ps + (init_step + nsteps) * dt_fs,
    }


def native_completion(run_dir: Path, configured: dict):
    log = run_dir / "md.log"
    if not log.is_file():
        return {"completed": False, "observed_step": None, "observed_time_ps": None}
    text = log.read_text(encoding="utf-8", errors="replace")
    steps = re.findall(r"(?m)^\s*(\d+)\s+[-+0-9.eE]+\s*$", text)
    completed = bool(re.search(r"(?i)Finished mdrun", text))
    observed_step = int(steps[-1]) if steps else None
    expected = configured["nsteps"] + int(round((configured["start_ps"] - float(configured.get("tinit_ps", 0))) * 1000 / configured["dt_fs"]))
    tolerance_steps = max(1, int(math.ceil(0.001 * 1000 / configured["dt_fs"])))
    completed = completed and observed_step is not None and abs(observed_step - expected) <= tolerance_steps
    observed_time = float(configured.get("tinit_ps", 0)) + observed_step * configured["dt_fs"] / 1000.0 if observed_step is not None else None
    return {"completed": completed, "observed_step": observed_step,
            "observed_time_ps": observed_time, "expected_final_step": expected}


def warning_count(run_dir: Path):
    paths = [run_dir / "md.log", run_dir / "mdrun.console.log"]
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in paths if p.is_file())
    return len(re.findall(r"(?i)\bLINCS\s+WARNING\b|\bconstraint\s+warning\b|\bNaN\b|\bnot\s+a\s+number\b", text))


def summarize(values):
    if not values:
        return {"n": 0, "mean": None, "sd_population": None}
    return {"n": len(values), "mean": sum(values) / len(values),
            "sd_population": statistics.pstdev(values)}


def frames_for_run(run_dir: Path):
    result = []
    for path in sorted(run_dir.glob("sample*.gro"), key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1))):
        result.append((path, water20_geometry(path)))
    if not result and (run_dir / "md.gro").is_file():
        path = run_dir / "md.gro"
        result.append((path, water20_geometry(path)))
    return result


def analyze(submission: Path, assets: Path, provenance: dict) -> None:
    input_hashes = {name: sha256(assets / name) for name in INPUTS}
    run_inputs, run_summaries, diag_rows, science_summaries = [], {}, [], {}
    total_ps = 0.0
    missing = []
    for label in LABELS:
        run_dir = submission / "runs" / label
        dt_fs = 1 if "dt1fs" in label else 2
        coordinate = assets / ("b.gro" if label.startswith("B-") else "u.gro")
        record = {
            "run": label, "dt_fs": dt_fs,
            "coordinate_sha256": sha256(coordinate),
            "topology_sha256": sha256(assets / "topol.top"),
        }
        for filename, key in (("topol.tpr", "tpr_sha256"), ("md.gro", "final_coordinate_sha256")):
            path = run_dir / filename
            if path.is_file():
                record[key] = sha256(path)
        if not run_dir.is_dir():
            missing.append(label)
            run_inputs.append(record)
            continue
        mdp_path = run_dir / "mdout.mdp"
        source_mdp_path = run_dir / "input.mdp"
        if mdp_path.is_file():
            actual = parse_mdp(mdp_path)
        elif source_mdp_path.is_file():
            actual = parse_mdp(source_mdp_path)
        else:
            actual = {}
        source_actual = parse_mdp(source_mdp_path) if source_mdp_path.is_file() else {}
        configured = configured_run(actual) if "nsteps" in actual and "dt" in actual else None
        if configured:
            record.update(configured)
            record["source_effective_mdp_match"] = all(
                source_actual.get(key, defaults.get(key)) == actual.get(key, defaults.get(key))
                for key, defaults in (("nsteps", {}), ("dt", {}), ("init-step", {"init-step": "0"}), ("tinit", {"tinit": "0"})))
        seed = actual.get("gen_seed")
        record["seed"] = int(seed) if seed and seed.lstrip("+-").isdigit() else None
        dump_path = run_dir / "tpr-state-dump.txt"
        if dump_path.is_file():
            vectors = []
            for kind in ("x", "v"):
                matches = re.findall(r"(?m)^\s*" + kind + r"\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}", dump_path.read_text(encoding="utf-8", errors="replace"))
                if matches:
                    vectors.append((kind, "\n".join(f"{i}:{v.strip()}" for i, v in matches)))
            for kind, content in vectors:
                record[kind + "_vector_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        xvg_path = run_dir / "energy.xvg"
        if xvg_path.is_file():
            legends, samples = read_xvg(xvg_path)
            times = [row[0] for row in samples]
            total_ps += max(times) - min(times)
            by_window = {}
            time_lo = configured["start_ps"] if configured else min(row[0] for row in samples)
            time_hi = configured["end_ps"] if configured else max(row[0] for row in samples)
            mid = (time_lo + time_hi) / 2
            windows = (("full-configured", time_lo, time_hi), ("first-half", time_lo, mid), ("second-half", mid, time_hi + 1e-9))
            for window, lo, hi in windows:
                selected = [row for row in samples if lo <= row[0] <= hi]
                by_window[window] = {
                    term: summarize([find_energy(legends, row, term) for row in selected
                                     if find_energy(legends, row, term) is not None])
                    for term in ENERGY_KEYS
                }
            run_summaries[label] = by_window
            frames = frames_for_run(run_dir)
            warnings = warning_count(run_dir)
            temperature_values = [find_energy(legends, row, "Temperature") for row in samples]
            constraint_values = [find_energy(legends, row, "Constr. rmsd") for row in samples]
            conserved_values = [find_energy(legends, row, "Conserved En.") for row in samples]
            valid_t = [v for v in temperature_values if v is not None and math.isfinite(v)]
            valid_c = [v for v in constraint_values if v is not None and math.isfinite(v)]
            valid_e = [v for v in conserved_values if v is not None and math.isfinite(v)]
            geoms = [geometry for _, geometry in frames]
            science_summaries[label] = {
                "samples": len(samples), "warning_count": warnings,
                "configured_duration_ps": configured["duration_ps"] if configured else None,
                "configured_start_ps": configured["start_ps"] if configured else None,
                "configured_end_ps": configured["end_ps"] if configured else None,
                "native_completion": native_completion(run_dir, configured) if configured else {"completed": False},
                "source_effective_mdp_match": record.get("source_effective_mdp_match", False),
                "energy_sample_start_ps": min(times),
                "energy_sample_end_ps": max(times),
                "temperature_K_min": min(valid_t) if valid_t else None,
                "temperature_K_max": max(valid_t) if valid_t else None,
                "temperature_K_mean": summarize(valid_t)["mean"],
                "constraint_rmsd_mean": summarize(valid_c)["mean"],
                "conserved_start_kj_mol": conserved_values[0] if conserved_values else None,
                "conserved_end_kj_mol": conserved_values[-1] if conserved_values else None,
                "conserved_change_kj_mol": (conserved_values[-1] - conserved_values[0]) if len(conserved_values) >= 2 else None,
                "water_oh_min_nm": min((g["oh_mean_nm"] for g in geoms), default=None),
                "water_oh_max_nm": max((g["oh_mean_nm"] for g in geoms), default=None),
                "water_hh_min_nm": min((g["hh_mean_nm"] for g in geoms), default=None),
                "water_hh_max_nm": max((g["hh_mean_nm"] for g in geoms), default=None),
                "water_angle_min_deg": min((g["angle_mean_deg"] for g in geoms), default=None),
                "water_angle_max_deg": max((g["angle_mean_deg"] for g in geoms), default=None),
                "actual_duration_ps": max(times) - min(times),
            }
            for frame_path, geometry in frames:
                t = geometry["time_ps"]
                if t is None:
                    # GROMACS sample frame names encode the sequential index; 5 ps cadence.
                    idx = int(re.search(r"(\d+)$", frame_path.stem).group(1))
                    t = idx * 5.0
                sample = min(samples, key=lambda row: abs(row[0] - t))
                values = {
                    "run": label, "time_ps": t,
                    "temperature_K": find_energy(legends, sample, "Temperature"),
                    "potential": find_energy(legends, sample, "Potential"),
                    "kinetic_en": find_energy(legends, sample, "Kinetic En."),
                    "total_energy": find_energy(legends, sample, "Total Energy"),
                    "conserved_en": find_energy(legends, sample, "Conserved En."),
                    "constr_rmsd": find_energy(legends, sample, "Constr. rmsd"),
                    "t_ocb": find_energy(legends, sample, "T-OCB"),
                    "t_mol": find_energy(legends, sample, "T-MOL"),
                    "t_water_and_ions": find_energy(legends, sample, "T-Water_and_ions"),
                    "box_x_nm": geometry["box"][0], "box_y_nm": geometry["box"][1],
                    "box_z_nm": geometry["box"][2], "warning_count": warnings,
                    "water20_oh_mean_nm": geometry["oh_mean_nm"],
                    "water20_hh_mean_nm": geometry["hh_mean_nm"],
                    "water20_angle_mean_deg": geometry["angle_mean_deg"],
                    "source_frame": str(frame_path.relative_to(submission)),
                }
                diag_rows.append(values)
            record["actual_duration_ps"] = max(times) - min(times)
        else:
            missing.append(label + ":energy.xvg")
        run_inputs.append(record)
    with (submission / "diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(diag_rows, key=lambda row: (row["run"], row["time_ps"])))
    comparison = {
        "schema": "case08-numerical-comparison/v1",
        "statistics": {"by_run_and_timeblock": run_summaries},
        "time_windows_ps": {
            label: {
                "full-configured": {"start_ps": row["configured_start_ps"],
                                    "end_ps": row["configured_end_ps"]},
                "first-half": {"start_ps": row["configured_start_ps"],
                               "end_ps": (row["configured_start_ps"] + row["configured_end_ps"]) / 2},
                "second-half": {"start_ps": (row["configured_start_ps"] + row["configured_end_ps"]) / 2,
                                "end_ps": row["configured_end_ps"]},
                "midpoint_included_in_both_halves": True,
                "window_sample_counts": {
                    name: values["Temperature"]["n"]
                    for name, values in run_summaries[label].items()
                },
            } for label, row in science_summaries.items()
        },
        "run_observations": science_summaries,
        "paired_parameter_diff": {
            state: {"same_coordinate_input": True, "same_velocity_seed_expected": 20261003,
                    "velocity_vector_hashes": {
                        f"dt{dt}fs": next((r.get("v_vector_sha256") for r in run_inputs if r["run"] == f"{state}-dt{dt}fs"), None)
                        for dt in (1, 2)
                    }} for state in ("B", "U")
        },
        "warning_counts": {label: warning_count(submission / "runs" / label) for label in LABELS},
        "geometry_method": "PBC minimum-image O-H/H-H and H-O-H angle for first 20 WAT molecules in each GROMACS sampled GRO frame; frame time read from native GRO title.",
        "limitations": [
            "Short NVT probes do not demonstrate equilibration, free energy, kinetics, or production readiness.",
            "NVT total energy is not required to be conserved; finite thermostat temperature is interpreted as a trace, not against a universal cutoff.",
            "Water geometry follows the same first 20 topology-ordered waters for each sampled frame and is a diagnostic only.",
        ],
    }
    write_json(submission / "numerical-comparison.json", comparison)
    write_json(submission / "input-audit.json", {
        "schema": "case08-input-audit/v1", "job_id": provenance["job_id"],
        "inputs": {name: {"sha256": value} for name, value in input_hashes.items()},
        "run_inputs": run_inputs,
        "missing_or_unavailable": missing,
        "paired_velocity_policy": "GROMACS gen_seed=20261003 for each paired timestep pair; actual TPR dump vector hashes retained and compared by the independent verifier.",
    })
    remote_record = dict(provenance)
    remote_record.update({
        "total_simulated_ps": total_ps,
        "total_step_time_ledger": {row["run"]: row.get("actual_duration_ps", 0.0) for row in run_inputs},
        "missing_or_unavailable_runs": missing,
        "candidate_reported_only": True,
    })
    write_json(submission / "remote-provenance.json", remote_record)
    incomplete = [label for label in LABELS if label not in science_summaries
                  or not science_summaries[label]["native_completion"].get("completed", False)
                  or not science_summaries[label].get("source_effective_mdp_match", False)]
    nonfinite = [label for label in LABELS if label in science_summaries and any(
        science_summaries[label][key] is None or not math.isfinite(science_summaries[label][key])
        for key in ("temperature_K_min", "temperature_K_max", "constraint_rmsd_mean", "conserved_change_kj_mol",
                    "water_oh_min_nm", "water_oh_max_nm", "water_hh_min_nm", "water_hh_max_nm",
                    "water_angle_min_deg", "water_angle_max_deg"))]
    warning_runs = [label for label in LABELS if science_summaries.get(label, {}).get("warning_count", 0) > 0]
    state_pairs = {}
    for state in ("B", "U"):
        one, two = science_summaries.get(f"{state}-dt1fs", {}), science_summaries.get(f"{state}-dt2fs", {})
        if one and two:
            state_pairs[state] = {
                "dt1fs_constraint_rmsd_mean": one["constraint_rmsd_mean"],
                "dt2fs_constraint_rmsd_mean": two["constraint_rmsd_mean"],
                "dt1fs_conserved_energy_change_kj_mol": one["conserved_change_kj_mol"],
                "dt2fs_conserved_energy_change_kj_mol": two["conserved_change_kj_mol"],
                "dt1fs_temperature_mean_K": one["temperature_K_mean"],
                "dt2fs_temperature_mean_K": two["temperature_K_mean"],
            }
    prefer_1fs = bool(len(state_pairs) == 2 and all(
        state_pairs[s]["dt2fs_constraint_rmsd_mean"] > state_pairs[s]["dt1fs_constraint_rmsd_mean"]
        and abs(state_pairs[s]["dt2fs_conserved_energy_change_kj_mol"]) > abs(state_pairs[s]["dt1fs_conserved_energy_change_kj_mol"])
        for s in ("B", "U")))
    comparison["paired_timestep_observations"] = state_pairs
    comparison["preferred_follow_up_timestep_fs"] = 1 if prefer_1fs else None
    write_json(submission / "numerical-comparison.json", comparison)
    evidence = []
    for label in LABELS:
        row = science_summaries.get(label)
        if not row:
            continue
        evidence.append(
            f"{label}: {row['samples']} energy samples spanning {row['actual_duration_ps']:.3f} ps "
            f"(configured {row['configured_duration_ps']:.3f} ps; energy endpoint {row['energy_sample_end_ps']:.3f} ps; "
            f"native completion step {row['native_completion'].get('observed_step')}); "
            f"temperature {row['temperature_K_min']:.3f}–{row['temperature_K_max']:.3f} K; "
            f"constraint RMSD mean {row['constraint_rmsd_mean']:.8g}; conserved-energy change {row['conserved_change_kj_mol']:+.3f} kJ/mol; "
            f"explicit constraint/numerical warning events {row['warning_count']}; first-20-water mean O–H "
            f"{row['water_oh_min_nm']:.6f}–{row['water_oh_max_nm']:.6f} nm, H–H {row['water_hh_min_nm']:.6f}–{row['water_hh_max_nm']:.6f} nm, "
            f"H–O–H {row['water_angle_min_deg']:.3f}–{row['water_angle_max_deg']:.3f} degrees."
        )
    if incomplete:
        evidence.append("Runs did not reach their configured endpoint according to native md.log step evidence: " + ", ".join(incomplete))
    if nonfinite:
        evidence.append("Missing or non-finite numeric diagnostics: " + ", ".join(nonfinite))
    if warning_runs:
        evidence.append("Runs with explicit native constraint/numerical warnings: " + ", ".join(warning_runs))
    decision = {
        "decision": "stop" if incomplete or nonfinite or warning_runs else "needs_check",
        "evidence": evidence,
        "paired_timestep_observations": state_pairs,
        "preferred_follow_up_timestep_fs": 1 if prefer_1fs else None,
        "alternative": "These NVT comparisons are descriptive over each run's configured duration, read from its effective MDP. For this observed pair, prefer 1 fs in the next bounded check when both states show larger 2 fs constraint residual means and larger absolute conserved-energy change; this is not a universal timestep or energy threshold. Stop only when a run does not reach its configured endpoint, diagnostics are non-finite, or explicit native warnings occur.",
        "inference_limits": ["No equilibration, binding free energy, kinetics, CV generality, or production claim follows from these short trajectories.", "NVT total energy is not required to be conserved; conserved-energy traces and constraint RMSD are comparative diagnostics, not universal thresholds."],
        "next_budget": {"max_nodes": 1, "max_cpus": 8, "memory_gib": 8, "walltime": "00:30:00", "max_total_simulated_ps": 200},
    }
    write_json(submission / "continuation-decision.json", decision)
    rationale = (
        "# Scientific rationale\n\n"
        "This bounded comparison tests whether changing the timestep from 1 fs to 2 fs produces visible numerical or constraint differences under the supplied G4 NVT setup. "
        f"The current native-data decision is `{decision['decision']}`; the measured per-run temperature, constraint, conserved-energy, warning, and water-geometry ranges are in numerical-comparison.json and diagnostics.csv. "
        + ("For these paired windows, 2 fs has larger mean constraint RMSD and larger absolute conserved-energy change in both B and U; prioritize 1 fs for a bounded follow-up, without treating the differences as a universal failure threshold. " if prefer_1fs else "The paired timestep metrics do not consistently favor one timestep under the observed diagnostics. ")
        + "NVT total energy is not required to be conserved, and the finite-sample temperature is not judged against a universal cutoff. "
        "Any continuation should remain within the supplied single-node, 8 CPU, 8 GiB, 30-minute and 200 ps limits.\n"
    )
    (submission / "scientific-rationale.md").write_text(rationale, encoding="utf-8")


def finalize(submission: Path, assets: Path, name: str, job_id: str, wait_exit: int):
    scheduler = json.loads((submission / "cli-scheduler.json").read_text(encoding="utf-8"))
    submitted = json.loads((submission / "cli-submission.json").read_text(encoding="utf-8"))
    receipt = scheduler.get("receipt") if isinstance(scheduler, dict) else None
    remote = json.loads((submission / "remote-provenance.json").read_text(encoding="utf-8")) if (submission / "remote-provenance.json").is_file() else {}
    remote.update({
        "schema": "case08-remote-provenance/v1", "job_id": job_id,
        "job_handle": name, "scheduler_state": scheduler.get("state"),
        "scheduler_exit_code": scheduler.get("exit_code"), "wait_command_exit_code": wait_exit,
        "scheduler_receipt": receipt, "submit_plan_sha256": submitted.get("plan_sha256"),
        "submit_snapshot_sha256": submitted.get("snapshot_sha256"),
        "trusted_runner_receipt": None,
        "trusted_association": "NOT_INTEGRATED: the runner does not provide a host-owned Case 08 execution receipt.",
    })
    if isinstance(receipt, dict):
        remote["accounting_evidence_sha256"] = canonical_sha256(receipt)
    remote["native_manifest"] = native_manifest(submission)
    remote["native_evidence_sha256"] = canonical_sha256(remote["native_manifest"])
    write_json(submission / "remote-provenance.json", remote)
    audit = json.loads((submission / "input-audit.json").read_text(encoding="utf-8")) if (submission / "input-audit.json").is_file() else {}
    audit["job_id"] = job_id
    audit["job_handle"] = name
    audit["inputs"] = {name: {"sha256": sha256(assets / name)} for name in INPUTS}
    write_json(submission / "input-audit.json", audit)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_index = sub.add_parser("index")
    p_index.add_argument("--gro", type=Path, required=True)
    p_index.add_argument("--out", type=Path, required=True)
    p_analyze = sub.add_parser("analyze")
    p_analyze.add_argument("--submission", type=Path, required=True)
    p_analyze.add_argument("--assets", type=Path, required=True)
    p_analyze.add_argument("--job-id", required=True)
    p_analyze.add_argument("--host", required=True)
    p_analyze.add_argument("--start", required=True)
    p_analyze.add_argument("--end", required=True)
    p_analyze.add_argument("--elapsed", type=int, required=True)
    p_analyze.add_argument("--cpus", required=True)
    p_analyze.add_argument("--mem", required=True)
    p_analyze.add_argument("--gmx-version", type=Path, required=True)
    p_analyze.add_argument("--source-manifest", type=Path, required=True)
    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--submission", type=Path, required=True)
    p_finalize.add_argument("--assets", type=Path, required=True)
    p_finalize.add_argument("--name", required=True)
    p_finalize.add_argument("--job-id", required=True)
    p_finalize.add_argument("--wait-exit", type=int, required=True)
    args = parser.parse_args()
    if args.command == "index":
        make_index(args.gro, args.out)
    elif args.command == "analyze":
        source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        provenance = {
            "schema": "case08-remote-provenance/v1", "job_id": args.job_id,
            "host_identity": args.host, "nodes": 1, "cpus": args.cpus,
            "memory": args.mem, "engine_version": args.gmx_version.read_text(encoding="utf-8", errors="replace").strip(),
            "start_utc": args.start, "end_utc": args.end, "process_elapsed_seconds": args.elapsed,
            "job_exit_code": None, "native_execution_artifacts": True,
            "source_manifest": source_manifest,
            "source_manifest_sha256": sha256(args.source_manifest),
        }
        analyze(args.submission, args.assets, provenance)
    else:
        finalize(args.submission, args.assets, args.name, args.job_id, args.wait_exit)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"case08_tools: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
