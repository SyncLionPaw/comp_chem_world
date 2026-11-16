#!/usr/bin/env python3
"""Package and analyze a candidate-produced native N2/24101 run bundle."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

MANIFEST_SHA256 = "23f77f707b9866860c48b487f59802dcde8ec9b78a2df94a29167651a4eb6576"
NATIVE_ROLES = (
    "manifest", "input", "data", "deletion_map", "source", "potential_rebomos_source",
    "potential_rebomos_derived", "potential_ilp", "potential_diagnostics",
    "potential_composite_stdout", "potential_rebo_stdout", "potential_ilp_stdout",
    "force_baseline_composite", "force_baseline_rebo", "force_baseline_ilp",
    "force_compressed_composite", "force_compressed_rebo", "force_compressed_ilp",
    "force_rebo_baseline", "force_rebo_compressed", "restart_min", "restart_equil",
    "restart_final", "eqmon", "com", "thermo_log", "stdout",
)
PROOF_FILES = {
    "native_manifest": "native-manifest.json",
    "execution_receipt": "execution-receipt.json",
    "scheduler_record": "scheduler-record.json",
    "execution_order": "execution-order.json",
    "batch_script": "batch-script.sh",
    "job_stdout": "job-stdout.txt",
    "job_stderr": "job-stderr.txt",
}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def relative_path(value, label):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label}: expected a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in ("", ".", "..") for p in path.parts):
        raise ValueError(f"{label}: path must remain below its evidence root")
    return path

def copy_evidence(source_root, final_root, rel, expected_sha, label):
    relpath = relative_path(rel, label)
    source = source_root
    for part in relpath.parts:
        source = source / part
        if source.is_symlink():
            raise ValueError(f"{label}: symlinks are not accepted")
    if not source.is_file() or digest(source) != expected_sha:
        raise ValueError(f"{label}: file missing or SHA-256 mismatch")
    target = final_root.joinpath(*relpath.parts)
    if target.exists() or target.is_symlink():
        raise ValueError(f"{label}: output path collides with an existing final artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native-root", type=Path, required=True)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True, help="APP root")
    args = ap.parse_args()
    root = args.native_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("BENCH15_MD_NATIVE_ROOT must name an existing directory")
    asset_manifest = args.assets / "n2-seed24101" / "manifest.json"
    if not asset_manifest.is_file() or digest(asset_manifest) != MANIFEST_SHA256:
        raise ValueError("locked public N2/24101 manifest is missing or changed")
    nm_path = root / PROOF_FILES["native_manifest"]
    if nm_path.is_symlink() or not nm_path.is_file():
        raise ValueError("native-manifest.json is required; no native result will be synthesized")
    native_manifest = json.loads(nm_path.read_text(encoding="utf-8"))
    if (native_manifest.get("schema") != "case05-native-execution-manifest/v1"
            or native_manifest.get("N") != 2 or native_manifest.get("seed") != 24101
            or native_manifest.get("atoms") != 7068
            or native_manifest.get("asset_manifest_sha256") != MANIFEST_SHA256):
        raise ValueError("native manifest does not bind the locked public N2/24101 input")
    roles = native_manifest.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(NATIVE_ROLES):
        raise ValueError("native manifest must list every required native evidence role")
    ranks = native_manifest.get("mpi_ranks")
    if type(ranks) is not int or not 1 <= ranks <= 10:
        raise ValueError("native manifest mpi_ranks must be an integer in the public range 1..10")

    final = args.output / "final"
    final.mkdir(parents=True, exist_ok=True)
    files = {}
    evidence = {}
    for role, record in roles.items():
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise ValueError(f"{role}: malformed native role record")
        target = copy_evidence(root, final, record["path"], record["sha256"], role)
        files[role] = target
        evidence[role] = record["path"]

    proof_paths = {}
    for role, rel in PROOF_FILES.items():
        source = root / rel
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"candidate execution evidence is missing: {rel}")
        target = copy_evidence(root, final, rel, digest(source), role)
        proof_paths[role] = target
        evidence[role] = rel
    receipt = json.loads(proof_paths["execution_receipt"].read_text(encoding="utf-8"))
    scheduler = json.loads(proof_paths["scheduler_record"].read_text(encoding="utf-8"))
    if (receipt.get("job_id") != scheduler.get("job_id")
            or receipt.get("job_id") != native_manifest.get("job_id")
            or receipt.get("allocation_id") != scheduler.get("allocation_id")
            or receipt.get("allocation_id") != native_manifest.get("allocation_id")):
        raise ValueError("receipt, scheduler record, and native manifest identities disagree")
    if receipt.get("native_manifest_sha256") != digest(proof_paths["native_manifest"]):
        raise ValueError("execution receipt does not bind native manifest bytes")
    scheduler_log = scheduler.get("raw_scheduler_log_path")
    if scheduler_log:
        target = copy_evidence(root, final, scheduler_log, scheduler.get("raw_scheduler_log_sha256"), "scheduler_log")
        evidence["scheduler_log"] = scheduler_log

    import numpy as np
    import score_reference as native
    from solve_native_modes import extract
    parsed = native.parse_layer_com(files["com"], 2)
    if len(parsed) != 50000:
        raise ValueError("native COM must contain exactly 50,000 post-initial rows")
    modes, spectra, diagnostics = extract(parsed[:, 1:].reshape(50000, 2, 3))
    files_context = [{"role": role, "path": path} for role, path in evidence.items()]
    context = {"expected_selection": {"N": 2, "seed": 24101, "atoms": 7068},
               "request_id": receipt["request_id"], "job_id": receipt["job_id"],
               "native_root": str(final), "files": files_context}
    with tempfile.TemporaryDirectory(prefix="case05-context-") as td:
        context_path = Path(td) / "analysis-context.json"
        context_path.write_text(json.dumps(context), encoding="utf-8")
        command = [sys.executable, str(Path(__file__).with_name("solve_native_modes.py")),
                   "--context", str(context_path), "--output", str(args.output)]
        subprocess.run(command, check=True)
    modes_path = final / "modes.json"
    payload = json.loads(modes_path.read_text(encoding="utf-8"))
    payload["runs"][0]["mpi_ranks"] = ranks
    modes_path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    equilibrium = final / "equilibrium.md"
    text = equilibrium.read_text(encoding="utf-8")
    equilibrium.write_text(text.replace("host-pinned native trace", "candidate-submitted native trace"), encoding="utf-8")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"native evidence analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
