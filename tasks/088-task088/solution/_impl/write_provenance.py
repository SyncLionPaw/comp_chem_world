#!/usr/bin/env python3
"""Write path-and-hash provenance for a freshly executed reference workflow."""
import argparse
import hashlib
import json
import math
import os
import platform
import socket
import subprocess
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def entry(root, rel):
    p = root / rel
    if not p.is_file():
        return None
    return {"path": rel, "sha256": digest(p), "size_bytes": p.stat().st_size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--gmx", required=True)
    ap.add_argument("--python", required=True)
    a = ap.parse_args()
    root = a.root.resolve()
    native_roles = {name: name for name in (
        "production.tpr", "production.xtc", "production.edr", "production.log",
        "npt.gro", "nvt.log", "npt.log", "em.tpr", "em.gro", "em.log",
        "nvt.tpr", "nvt.gro", "nvt.edr", "nvt.cpt", "npt.tpr", "npt.edr",
        "npt.cpt", "initial.gro", "solvated.gro", "topol.runtime.top", "em.edr")}
    protocol_roles = {name: name for name in (
        "em.mdp", "nvt.mdp", "npt.mdp", "production.mdp", "topol.runtime.top")}
    protocol_roles.update({
        "science-plan.md": "science-validation/science-plan.md",
        "analysis/independent_validation.py": "analysis/independent_validation.py",
        "analysis/summarize_science_audit.py": "analysis/summarize_science_audit.py",
        "run_case01.sh": "run_case01.sh",
        "analysis/validate_npt_grompp.py": "analysis/validate_npt_grompp.py",
    })
    native = {k: entry(root, v) for k, v in native_roles.items()}
    protocol = {k: entry(root, v) for k, v in protocol_roles.items()}
    md_path=root / "final/observables.json"
    md = json.loads(md_path.read_text()) if md_path.exists() else None
    version_result = subprocess.run([a.gmx, "--version"], check=True, text=True, capture_output=True)
    version = (version_result.stdout + version_result.stderr).strip()
    validation_path = root / "science-validation/independent_validation.json"
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
    method = validation.get("method", {})
    native_facts = validation.get("native", {})
    raw_observables_sha256=digest(md_path) if md else None
    if md:
        box=native_facts.get('box_A',[])
        if len(box)!=3 or any(not math.isfinite(float(x)) or float(x)<=0 for x in box):
            raise ValueError('native analysis must report three positive box lengths in Angstrom')
        metadata=md.setdefault('method',{})
        width=float(metadata['bin_width_A^-1'])
        metadata.update(reporting_bin_width_A_inverse=width,
          fundamental_reciprocal_spacing_A_inverse_per_box_axis=[2*math.pi/float(x) for x in box],
          low_k_resolution_threshold=.95,charge_assignment='periodic_CIC',
          reciprocal_estimator='angular_mean_power_over_k2',bin_center_convention='mode_mean',
          sampling_start_ps=0.,sampling_endpoint_rule='exclusive')
        # Use the output contract's literal unit-bearing keys.
        metadata['reporting_bin_width_A^-1']=metadata.pop('reporting_bin_width_A_inverse')
        metadata['fundamental_reciprocal_spacing_A^-1_per_box_axis']=metadata.pop('fundamental_reciprocal_spacing_A_inverse_per_box_axis')
        metadata['first_nonzero_reciprocal_shell_A^-1']=min(metadata['fundamental_reciprocal_spacing_A^-1_per_box_axis'])
        obs=md['observables']
        obs['k_min_A^-1']['finite_size_resolution_A^-1']=metadata['first_nonzero_reciprocal_shell_A^-1']
        obs['k_max_A^-1']['bin_resolution_half_width_A^-1']=width/2
        obs['delta_k_A^-1'].update(baseline_chi=0.,half_height_fraction=.5,
          definition='FWHM above zero chi, at chi_max/2',crossing_method='linear interpolation of reporting-bin centers')
        md['source']['trajectory_frames']=native_facts['trajectory_frames']
        md['source']['sampled_frames']=method['frame_count']
        md['source']['sampling_interval_ps']=method['sample_period_ps']
        md['scientific_acceptance_scope']='Selected reference-method diagnostics; benchmark acceptance is decided independently by tests/verify.py.'
        md_path.write_text(json.dumps(md,indent=2)+'\n')
    result = {
        "schema": "case01-provenance-v1",
        "execution": {"status": "COMPLETED", "job_id": os.environ.get("SLURM_JOB_ID"), "hostname": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version(), "gromacs_version": version.strip(), "threads": int(os.environ.get("OMP_NUM_THREADS", "1")), "mpi_ranks": int(os.environ.get("GMX_MPI_RANKS", "1"))},
        "native_source_files": {k: v for k, v in native.items() if v is not None},
        "protocol_input_files": {k: v for k, v in protocol.items() if v is not None},
        "native_audit_artifacts": {
            role: entry(root, rel) for role, rel in {
                "trajectory_check": "logs/production-trajectory-check.txt",
                "energy_file_check": "logs/production-edr-check.txt",
                "tpr_dump": "logs/production-tpr-dump.txt",
            }.items()
        },
        "scientific_status": md.get("scientific_status") if md else "ANALYSIS_OUTPUT_MISSING",
        "scientific_gates": md.get("gates") if md else {},
        "observables_before_definition_metadata_sha256": raw_observables_sha256,
        "frame_count": native_facts.get("trajectory_frames"),
        "analysis_frames": method.get("frame_count"),
        "analysis_method": method,
        "analysis_artifacts": {name: entry(root, name) for name in (
            "science-validation/independent_validation.json", "science-validation/science_summary.json",
            "science-validation/checkpoint.npz", "science-validation/mesh_per_bin.csv",
            "science-validation/direct_modes.csv", "final/chi_k.csv", "final/observables.json")},
    }
    out = root / "final/provenance.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    # Hash the final bytes after definition metadata and provenance are written.
    final = root / "final"
    names = sorted(p.name for p in final.iterdir()
                   if p.is_file() and p.name != "SHA256SUMS")
    (final / "SHA256SUMS").write_text(
        "".join(f"{digest(final / name)}  {name}\n" for name in names))


if __name__ == "__main__":
    main()
