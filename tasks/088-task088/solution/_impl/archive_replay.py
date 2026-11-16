#!/usr/bin/env python3
"""Recompute Case01 reference outputs from the evaluator's protected 9806 archive.

This is an explicit author-only historical route. It never runs dynamics and it
never copies archived ``final/`` or ``science-validation/`` results into the
submission workspace. The Agent route remains the ordinary fresh-MD workflow.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLUTION_ROOT = HERE.parent
ARCHIVE = Path("/author_archive")


def _author_context_parts(loaded: dict) -> tuple[dict, Path]:
    """Unwrap the validator result while preserving its validated archive root."""
    if not isinstance(loaded, dict):
        raise RuntimeError("historical context loader returned an invalid result")
    document = loaded.get("context")
    archive_root = loaded.get("archive_root")
    if not isinstance(document, dict) or not isinstance(archive_root, Path):
        raise RuntimeError("historical context loader did not return its validated context and archive")
    if not document.get("canonical_package_source_sha256") or not document.get("image_id"):
        raise RuntimeError("historical context is missing its package or image identity")
    return document, archive_root


def _historical_reference_provenance(document: dict) -> dict:
    """Build the final provenance fields from the unwrapped context document."""
    archive_sha = document.get("archive_v2_sha256")
    trajectory_sha = document.get("xtc_sha256")
    if not isinstance(archive_sha, str) or not isinstance(trajectory_sha, str):
        raise RuntimeError("historical context is missing its archive or trajectory pin")
    return {
        "source": "explicit_historical_author_archive", "job_id": "9806",
        "scontrol_status": "UNKNOWN_EXPIRED", "controller_trusted": False,
        "fresh_for_agent": False, "formal_reward": None,
        "archive_v2_sha256": archive_sha, "trajectory_sha256": trajectory_sha,
    }


def _copy(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"archive replay input is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _load_author_context() -> dict:
    sys.path.insert(0, str(SOLUTION_ROOT.parent / "verifier"))
    from historical_archive import load_author_context
    return load_author_context()


def main() -> int:
    loaded_context = _load_author_context()

    # The evaluator passes these values from the immutable task snapshot and
    # resolved runtime image. Candidate-controlled environment cannot select a
    # historical route because the evaluator-only context mount is required.
    context_doc, archive_root = _author_context_parts(loaded_context)
    package_pin = os.environ.get("CASE01_CANONICAL_PACKAGE_SOURCE_SHA256")
    if not package_pin or package_pin != context_doc["canonical_package_source_sha256"]:
        raise RuntimeError("evaluator package source pin is missing or differs from author context")
    image_id = os.environ.get("CASE01_IMAGE_ID")
    if image_id != context_doc["image_id"]:
        raise RuntimeError("resolved evaluator image ID is missing or differs from author context")

    if len(sys.argv) != 2:
        raise SystemExit("usage: archive_replay.py WORKDIR")
    work = Path(sys.argv[1]).expanduser().absolute()
    if work.is_symlink() or (work.exists() and not work.is_dir()):
        raise RuntimeError("historical replay root must be a non-symlink directory")
    work.mkdir(parents=True, exist_ok=True)
    generated = ("production.tpr", "production.xtc", "production.edr", "production.log",
                 "nvt.tpr", "nvt.edr", "nvt.gro", "nvt.cpt", "npt.gro", "nvt.log", "npt.log", "production.mdp", "nvt.mdp",
                 "npt.mdp", "em.mdp", "topol.runtime.top", "initial.gro", "final",
                 "logs", "science-validation", "analysis", "preflight-evidence", "write_provenance.py")
    conflicts = [name for name in generated if (work / name).exists() or (work / name).is_symlink()]
    if conflicts:
        raise RuntimeError("historical replay refuses to overwrite existing outputs: " + ", ".join(conflicts))
    collected = archive_root / "collected"
    ancestry = archive_root / "ancestry9136"

    # Only native analysis inputs and protocol ancestry are staged. Frozen old
    # final curves, observables, checkpoints, and verifier outputs are excluded.
    inputs = {
        "production.tpr": collected / "production.tpr",
        "production.xtc": archive_root / "production.xtc",
        "production.edr": collected / "production.edr",
        "production.log": collected / "production.log",
        "nvt.tpr": collected / "nvt.tpr",
        "nvt.edr": collected / "nvt.edr",
        "nvt.gro": collected / "nvt.gro",
        "nvt.cpt": collected / "nvt.cpt",
        "npt.gro": ancestry / "npt.gro",
        "npt.log": ancestry / "npt.log",
        "nvt.log": collected / "nvt.log",
        "production.mdp": collected / "production.mdp",
        "nvt.mdp": collected / "nvt.mdp",
        "npt.mdp": ancestry / "npt.mdp",
        "em.mdp": ancestry / "em.mdp",
        "topol.runtime.top": collected / "topol.runtime.top",
        "initial.gro": ancestry / "solvated.gro",
    }
    for relative, source in inputs.items():
        _copy(source, work / relative)

    for script in sorted((HERE / "analysis").glob("*.py")):
        _copy(script, work / "analysis" / script.name)
    _copy(HERE / "write_provenance.py", work / "write_provenance.py")
    _copy(HERE / "science-plan.md", work / "science-validation/science-plan.md")
    for name in ("logs", "final", "science-validation", "analysis", "preflight-evidence"):
        (work / name).mkdir(exist_ok=True)
    # Fresh runs expose the native production and equilibration records under
    # final/ as well as the replay workspace. These are copied from the pinned
    # raw archive inputs, never from the archived final/ directory.
    for name in ("npt.gro", "npt.log", "nvt.log"):
        shutil.copyfile(work / name, work / "final" / name)
    shutil.copyfile(work / "production.log", work / "final/md_production.log")

    py = os.environ.get("PYTHON", sys.executable)
    gmx = os.environ.get("GMX", "gmx")
    threads = max(1, int(os.environ.get("OMP_NUM_THREADS", "1")))
    env = os.environ.copy()
    env.update({"CASE01_DIR": str(work), "OUTDIR": str(work / "science-validation"),
                "PLAN_FILE": str(work / "science-validation/science-plan.md"),
                "GMX": gmx, "OMP_NUM_THREADS": str(threads),
                "CASE01_FFT_WORKERS": str(threads), "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1"})
    commands = [
        [gmx, "check", "-s1", str(work / "production.tpr"), "-f", str(work / "production.xtc")],
        [gmx, "check", "-e", str(work / "production.edr")],
        [gmx, "--version"],
        [py, str(work / "analysis/audit_tpr_exclusions.py"), str(work / "production.tpr"),
         "--json", str(work / "logs/production-tpr-exclusions.json")],
        [py, str(work / "analysis/audit_tpr_settings.py"), str(work / "production.tpr"),
         "--gmx", gmx, "--kind", "production", "--json",
         str(work / "logs/production-tpr-settings.json"), "--dump",
         str(work / "logs/production-tpr-dump.txt")],
        [py, str(work / "analysis/analytic_sanity.py")],
        [py, str(work / "analysis/independent_validation.py")],
        [py, str(work / "analysis/summarize_science_audit.py")],
        [py, str(work / "write_provenance.py"), "--root", str(work), "--gmx", gmx, "--python", py],
    ]
    for index, command in enumerate(commands):
        capture = index < 3
        result = subprocess.run(command, cwd=work, env=env, text=True,
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.STDOUT if capture else None,
                                check=False)
        if result.returncode:
            if capture and result.stdout:
                print(result.stdout[-8000:], file=sys.stderr)
            raise RuntimeError(f"historical archive analysis step failed ({result.returncode}): {command[0]}")
        if capture:
            name = ("production-trajectory-check.txt", "production-edr-check.txt", "gromacs-version.txt")[index]
            (work / "logs" / name).write_text(result.stdout or "")
    import json
    provenance_path = work / "final/provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    execution = provenance.setdefault("execution", {})
    execution.update({"status": "HISTORICAL_REFERENCE_REANALYZED", "job_id": None,
                      "execution_source": "explicit_historical_author_archive",
                      "historical_reference_job_id": "9806", "agent_fresh": False,
                      "agent_reward": None})
    provenance["historical_reference"] = _historical_reference_provenance(context_doc)
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    final=work/"final"
    names=sorted(p.name for p in final.iterdir() if p.is_file() and p.name!="SHA256SUMS")
    lines=[]
    import hashlib
    for name in names:
        digest=hashlib.sha256((final/name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}\n")
    (final/"SHA256SUMS").write_text("".join(lines),encoding="utf-8")
    print("Historical archive scientific outputs were recomputed from pinned native TPR/XTC/EDR inputs.")
    print("Reference origin: historical 9806 archive; this does not establish Agent-fresh execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
