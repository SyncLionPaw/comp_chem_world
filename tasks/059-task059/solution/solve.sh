#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

cat > "$WORKDIR/fresh_native_workflow.py" <<'CASE60_FRESH_NATIVE_WORKFLOW'
#!/usr/bin/env python3
"""Build, run, collect, and source-bind a fresh Case05 VASP campaign.

This public candidate utility requires operator-provided SSH/Slurm/VASP/POTCAR
settings. It never reads historical native outputs or scoring references.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

try:
    import numpy as np
except ImportError:
    np = None
try:
    from pymatgen.io.vasp.outputs import Vasprun, Wavecar
except ImportError:
    Vasprun = Wavecar = None

CASE_ID = "case-05-first-principles-inputs"
FILES = ("POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
         "execution-receipt.json", "input-manifest.json")
COMPONENTS = ("xx", "yy", "zz", "yz", "xz", "xy")
SCHEMA_RUN_RECEIPT = "case05-execution-receipt/v1"
SCHEMA_SCHEDULER = "case05-scheduler-record/v1"
SCHEMA_PROVENANCE = "case05-submission-provenance/v1"
POTCAR_ORDER = ("Ga_d", "As")


class Stop(RuntimeError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def load_site() -> dict:
    path = Path("/root/.ssh/vasp-site.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stop("configure [ikkem.slurm] and [ikkem.engines.vasp].potcar_root in config/ikkem.toml, then rebuild the connectivity image") from exc


def utc_text(value: str) -> str:
    token = value.strip()
    if token in ("", "Unknown", "N/A"):
        raise Stop("Slurm accounting returned a missing timestamp")
    parsed = dt.datetime.fromisoformat(token.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise Stop("Slurm timestamps must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_local(args: list[str], *, input_bytes: bytes | None = None,
              timeout: int = 120, check: bool = True) -> bytes:
    result = subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        msg = result.stderr.decode("utf-8", "replace")[-3000:]
        raise Stop(f"command failed ({result.returncode}): {Path(args[0]).name}: {msg}")
    return result.stdout


def ssh(host: str, remote_command: str, *, timeout: int = 120, check: bool = True) -> bytes:
    return run_local(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
                      "bash", "-lc", remote_command], timeout=timeout, check=check)


def scp_from(host: str, remote: str, local: Path, *, timeout: int = 240) -> None:
    run_local(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               f"{host}:{remote}", str(local)], timeout=timeout)


def parse_poscar(raw: bytes) -> tuple[list[str], list[list[float]], list[str]]:
    try:
        lines = raw.decode("ascii").splitlines()
        scale = float(lines[1].split()[0])
        lattice = [[float(x) for x in lines[i].split()] for i in range(2, 5)]
        species = lines[5].split()
        counts = [int(x) for x in lines[6].split()]
    except (UnicodeError, ValueError, IndexError) as exc:
        raise Stop("GaAs.POSCAR is not a supported VASP5 structure") from exc
    if (len(species) != 2 or species != ["Ga", "As"] or len(counts) != 2 or counts != [1, 1]
            or len(lattice) != 3 or any(len(row) != 3 for row in lattice)
            or not math.isfinite(scale) or scale <= 0):
        raise Stop("task POSCAR must describe one Ga and one As in VASP5 Cartesian-cell syntax")
    coord_index = 7
    if lines[coord_index].strip().lower().startswith("s"):
        coord_index += 1
    mode = lines[coord_index].strip().lower()
    if mode.startswith("d"):
        pass
    elif not mode.startswith("c"):
        raise Stop("task POSCAR coordinates must be direct or Cartesian")
    atoms = lines[coord_index + 1:coord_index + 3]
    if len(atoms) != 2 or any(len(row.split()) < 3 for row in atoms):
        raise Stop("task POSCAR must contain two atom coordinate rows")
    # Return a normalized unit-scale POSCAR while preserving fractional positions.
    lattice = [[x * scale for x in row] for row in lattice]
    if mode.startswith("c"):
        inv = np.linalg.inv(np.asarray(lattice, dtype=float).T)
        coords = np.asarray([[float(x) for x in row.split()[:3]] for row in atoms], dtype=float)
        frac = coords @ inv.T
        suffix = [row.split()[3:] for row in atoms]
        atoms = [" ".join([*(f"{x:.16g}" for x in xyz), *tail]) for xyz, tail in zip(frac, suffix)]
    else:
        atoms = [" ".join(row.split()) for row in atoms]
    normalized = [lines[0], "1.0", *[" ".join(f"{x:.16g}" for x in row) for row in lattice],
                  "Ga As", "1 1", "Direct", *atoms]
    return normalized, lattice, atoms


def poscar_for_strain(base_lines: list[str], base_lattice: list[list[float]],
                      component: str | None = None, coordinate: float = 0.0) -> tuple[bytes, list[list[float]]]:
    strain = np.zeros((3, 3), dtype=float)
    if component:
        ij = {"xx": (0, 0), "yy": (1, 1), "zz": (2, 2),
              "yz": (1, 2), "xz": (0, 2), "xy": (0, 1)}[component]
        strain[ij] = coordinate if ij[0] == ij[1] else coordinate / 2.0
        strain[ij[::-1]] = strain[ij]
    eigenvalues, eigenvectors = np.linalg.eigh(strain)
    if np.any(1.0 + 2.0 * eigenvalues <= 0):
        raise Stop("requested Green-Lagrange strain does not define a positive metric")
    deformation_gradient = (eigenvectors * np.sqrt(1.0 + 2.0 * eigenvalues)) @ eigenvectors.T
    lattice = np.asarray(base_lattice, dtype=float) @ deformation_gradient.T
    lines = list(base_lines)
    lines[1] = "1.0"
    lines[2:5] = [" ".join(f"{x:.16g}" for x in row) for row in lattice]
    return ("\n".join(lines) + "\n").encode(), lattice.tolist()


def kpoints(mesh: tuple[int, int, int]) -> bytes:
    return (f"Automatic mesh\n0\nGamma\n{mesh[0]} {mesh[1]} {mesh[2]}\n0 0 0\n").encode()


def incar(stage_kind: str, encut: int, *, deformation: bool = False,
          relaxed_elastic: bool = False) -> bytes:
    tags = ["PREC = Accurate", f"ENCUT = {encut}", "EDIFF = 1E-8", "ISMEAR = 0", "SIGMA = 0.01",
            "LREAL = .FALSE.", "LASPH = .TRUE.", "NELM = 160", "NBANDS = 32", "GGA = PE",
            "LHFCALC = .FALSE.", "AEXX = 0", "HFSCREEN = 0", "NELECT = 18", "ISPIN = 1"]
    if deformation:
        tags += ["IBRION = -1", "NSW = 0", "LWAVE = .TRUE.", "LCHARG = .TRUE.",
                 "ICORELEVEL = 1", "LORBIT = 11", "ADDGRID = .TRUE."]
    elif relaxed_elastic:
        tags += ["IBRION = 2", "NSW = 120", "ISIF = 2", "EDIFFG = -0.0005"]
    else:
        tags += ["IBRION = 8", "NSW = 1", "ISIF = 2", "LEPSILON = .TRUE.",
                 "LPEAD = .TRUE.", "ADDGRID = .TRUE."]
    return ("\n".join(tags) + "\n").encode()


def make_specs(base_lines: list[str], base_lattice: list[list[float]]) -> list[dict]:
    specs = [{"run_id": "deformation_bulk", "stage": "deformation_bulk", "stage_kind": "deformation",
              "poscar": poscar_for_strain(base_lines, base_lattice)[0], "encut": 650, "mesh": (16,16,16),
              "deformation": True}]
    for encut, mesh, label in ((520, (16,16,16), "dfpt_520_k16"),
                               (650, (16,16,16), "dfpt_650_k16"),
                               (650, (12,12,12), "dfpt_650_k12")):
        specs.append({"run_id": label, "stage": label, "stage_kind": "dfpt",
                      "poscar": poscar_for_strain(base_lines, base_lattice)[0],
                      "encut": encut, "mesh": mesh, "deformation": False})
    for family, stage_kind, is_deformation in (("elastic", "elastic_finite_strain", False),
                                                ("deformation", "deformation", True)):
        if family == "elastic":
            specs.append({"run_id": "elastic_bulk", "stage": "elastic_bulk", "stage_kind": stage_kind,
                          "poscar": poscar_for_strain(base_lines, base_lattice)[0], "encut": 650,
                          "mesh": (16,16,16), "deformation": False, "relaxed_elastic": True})
        for component in COMPONENTS:
            for amplitude in (0.0025, 0.005):
                for sign, suffix in ((-1, "m"), (1, "p")):
                    value = sign * amplitude
                    poscar, _ = poscar_for_strain(base_lines, base_lattice, component, value)
                    label = f"{family}_{component}_{int(amplitude*10000):04d}_{suffix}"
                    specs.append({"run_id": label, "stage": label, "stage_kind": stage_kind,
                                  "poscar": poscar, "encut": 650, "mesh": (16,16,16),
                                  "deformation": is_deformation,
                                  "relaxed_elastic": family == "elastic"})
    if len(specs) != 53 or len({row["run_id"] for row in specs}) != 53:
        raise Stop("fresh run plan must contain exactly 53 unique native calculations")
    return specs


def remote_preflight(host: str, remote_root: str, potcar_root: str, vasp_cmd: str,
                     work_uuid: str) -> dict[str, dict]:
    # Paths are operator-supplied and shell-quoted; no personal config or key is read.
    cmd = (f"set -eu; test -d {shlex.quote(remote_root)}; "
           f"test -r {shlex.quote(potcar_root+'/Ga_d/POTCAR')}; "
           f"test -r {shlex.quote(potcar_root+'/As/POTCAR')}; "
           f"mkdir -p {shlex.quote(remote_root+'/'+work_uuid)}; "
           f"for x in Ga_d As; do p={shlex.quote(potcar_root)}/$x/POTCAR; "
           "h=$(sha256sum \"$p\" | awk '{print $1}'); "
           "t=$(grep -m1 -E 'TITEL[[:space:]]*=' \"$p\" | sed 's/^[[:space:]]*//'); "
           "z=$(grep -m1 -E 'ZVAL[[:space:]]*=' \"$p\" | sed -E 's/.*ZVAL[[:space:]]*=[[:space:]]*([^;]+).*/\\1/'); "
           "e=$(grep -m1 -E 'ENMAX[[:space:]]*=' \"$p\" | sed -E 's/.*ENMAX[[:space:]]*=[[:space:]]*([^;]+).*/\\1/'); "
           "printf '%s\\t%s\\t%s\\t%s\\t%s\\n' \"$x\" \"$h\" \"$t\" \"$z\" \"$e\"; done")
    raw = ssh(host, cmd, timeout=60).decode("utf-8", "strict")
    result = {}
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] not in POTCAR_ORDER or not re.fullmatch(r"[0-9a-f]{64}", fields[1]):
            raise Stop("POTCAR preflight metadata did not match its two declared potential files")
        title = fields[2].strip()
        zval = float(fields[3].strip())
        enmax = float(fields[4].strip())
        result[fields[0]] = {"element": "Ga" if fields[0] == "Ga_d" else "As",
                             "variant": fields[0], "sha256": fields[1], "title": title,
                             "zval": zval, "enmax_ev": enmax}
    if set(result) != set(POTCAR_ORDER):
        raise Stop("POTCAR preflight did not return metadata for Ga_d and As")
    if "PBE" not in " ".join(x["title"] for x in result.values()):
        raise Stop("POTCAR title metadata does not identify a PBE PAW family")
    return result


def build_batch(spec: dict, host: str, remote_root: str, potcar_root: str,
                vasp_cmd: str, account: str, partition: str) -> bytes:
    lines = ["#!/bin/bash", f"#SBATCH --job-name=c05_{spec['run_id']}", "#SBATCH --nodes=1",
             "#SBATCH --ntasks=1", "#SBATCH --cpus-per-task=2", "#SBATCH --mem=8G",
             "#SBATCH --time=00:45:00", "#SBATCH --output=slurm.stdout", "#SBATCH --error=slurm.stderr"]
    if account: lines.append(f"#SBATCH --account={account}")
    if partition: lines.append(f"#SBATCH --partition={partition}")
    lines += ["set -euo pipefail", f"cat {shlex.quote(potcar_root+'/Ga_d/POTCAR')} {shlex.quote(potcar_root+'/As/POTCAR')} > POTCAR",
              "export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1}", vasp_cmd + " > vasp.stdout 2> vasp.stderr"]
    return ("\n".join(lines) + "\n").encode()


def submit_one(host: str, remote_run: str, local_run: Path, spec: dict,
               method: dict, source_poscar_sha: str, workflow_sha: str,
               potcar_root: str, vasp_cmd: str, account: str, partition: str,
               output_root: Path) -> dict:
    remote_run_q = shlex.quote(remote_run)
    files = {"POSCAR": spec["poscar"], "INCAR": incar(spec["stage_kind"], spec["encut"],
              deformation=spec["deformation"], relaxed_elastic=spec.get("relaxed_elastic", False)),
             "KPOINTS": kpoints(spec["mesh"])}
    for name, raw in files.items(): (local_run/name).write_bytes(raw)
    batch = build_batch(spec, host, remote_run, potcar_root, vasp_cmd, account, partition)
    (local_run/"batch.slurm").write_bytes(batch)
    file_hashes = {name: sha(raw) for name, raw in files.items()}
    mesh = list(spec["mesh"])
    input_manifest = {
        "schema_version": "case05-input-manifest/v1", "case_id": CASE_ID,
        "stage": spec["stage"], "stage_kind": spec["stage_kind"], "status": "SUBMITTED",
        "workflow_sha256": workflow_sha, "source_poscar_sha256": source_poscar_sha,
        "parent_geometry_sha256": sha(files["POSCAR"]), "relaxed_geometry_sha256": None,
        "encut_ev": spec["encut"], "mesh": mesh, "method": method,
        "files": file_hashes,
    }
    manifest_raw = canonical_json(input_manifest)
    (local_run/"input-manifest.json").write_bytes(manifest_raw)
    remote = f"{remote_run}/"
    ssh(host, f"mkdir -p {remote_run_q}")
    for name in ("POSCAR", "INCAR", "KPOINTS", "input-manifest.json", "batch.slurm"):
        run_local(["scp", "-q", "-o", "BatchMode=yes", str(local_run/name), f"{host}:{remote_run}/{name}"])
    submitted = ssh(host, f"cd {remote_run_q} && sbatch --parsable batch.slurm").decode().strip().splitlines()[-1]
    job_id = submitted.split(";", 1)[0].strip()
    if not re.fullmatch(r"[0-9]{1,32}", job_id):
        raise Stop(f"Slurm returned an invalid non-array job ID for {spec['run_id']}")
    accounting = b""
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        accounting = ssh(host, f"sacct -n -P -j {job_id} --format=JobIDRaw,State,ExitCode,Start,End,ElapsedRaw,AllocCPUS,ReqMem,AllocTRES", check=False)
        rows = [line.split("|") for line in accounting.decode("utf-8", "replace").splitlines() if line.strip()]
        row = next((r for r in rows if r and r[0].split(".",1)[0] == job_id and "_" not in r[0]), None)
        if row and len(row) >= 9 and row[1].split()[0] in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "PREEMPTED"}:
            break
        time.sleep(20)
    else:
        raise Stop(f"Slurm job {job_id} did not reach a terminal state within two hours")
    state = row[1].split()[0]
    exit_code = int(row[2].split(":",1)[0])
    if state != "COMPLETED" or exit_code != 0:
        raise Stop(f"Slurm run {spec['run_id']} ended {state} with exit code {exit_code}")
    start_utc, end_utc = utc_text(row[3]), utc_text(row[4])
    wall_seconds = (dt.datetime.fromisoformat(end_utc.replace("Z", "+00:00")) -
                    dt.datetime.fromisoformat(start_utc.replace("Z", "+00:00"))).total_seconds()
    cpus = int(row[6])
    reqmem = row[7].strip()
    match = re.fullmatch(r"([0-9]+)([KMGTP])([cn]?)", reqmem, re.I)
    if not match: raise Stop(f"Slurm returned unsupported ReqMem value {reqmem!r}")
    memory_bytes = int(match[1]) * (1024 ** ("KMGTP".index(match[2].upper()) + 1))
    tres = row[8]
    gpu_match = re.search(r"(?:^|,)gres/gpu(?::[^=,]+)?=([0-9]+)", tres)
    gpus = int(gpu_match[1]) if gpu_match else 0
    scheduler = {"schema": SCHEMA_SCHEDULER, "job_id": job_id, "scheduler": "slurm",
                 "final_state": state, "allocation_id": job_id, "allocation_is_array": False,
                 "gpus": gpus, "cpus": cpus, "memory_bytes": memory_bytes,
                 "wall_seconds": wall_seconds, "exit_code": exit_code,
                 "start_utc": start_utc, "end_utc": end_utc}
    stdout = Path(local_run/"slurm.stdout"); stderr = Path(local_run/"slurm.stderr")
    native_stdout = Path(local_run/"vasp.stdout"); native_stderr = Path(local_run/"vasp.stderr")
    for remote_name, local_path in (("POSCAR",local_run/"POSCAR"), ("INCAR",local_run/"INCAR"),
            ("KPOINTS",local_run/"KPOINTS"), ("OUTCAR",local_run/"OUTCAR"),
            ("vasprun.xml",local_run/"vasprun.xml"), ("WAVECAR",local_run/"WAVECAR"),
            ("CONTCAR",local_run/"CONTCAR"), ("slurm.stdout",stdout), ("slurm.stderr",stderr),
            ("vasp.stdout",native_stdout), ("vasp.stderr",native_stderr), ("input-manifest.json",local_run/"input-manifest.json")):
        scp_from(host, f"{remote_run}/{remote_name}", local_path, timeout=900)
    output_hashes = {name: sha((local_run/name).read_bytes()) for name in ("OUTCAR", "vasprun.xml", "WAVECAR")}
    actual_inputs = {name: file_hashes[name] for name in file_hashes}
    actual_inputs["source.POSCAR"] = sha((local_run/"POSCAR").read_bytes())
    receipt_native = {"schema": SCHEMA_RUN_RECEIPT, "status": "FINISHED", "exit_code": 0,
                      "start_utc": start_utc, "end_utc": end_utc, "slurm_job_id": job_id,
                      "input_manifest_sha256": sha(manifest_raw), "actual_run_inputs": actual_inputs,
                      "native_output_sha256": output_hashes, "case_id": CASE_ID, "stage": spec["stage"]}
    receipt_raw = canonical_json(receipt_native)
    (local_run/"execution-receipt.json").write_bytes(receipt_raw)
    (local_run/"input-manifest.json").write_bytes(manifest_raw)
    run_out = output_root/"native"/"runs"/spec["run_id"]
    run_out.mkdir(parents=True, exist_ok=True)
    for name in FILES: shutil.copyfile(local_run/name, run_out/name)
    prov_dir = output_root/"native"/"provenance"/spec["run_id"]
    prov_dir.mkdir(parents=True, exist_ok=True)
    provenance_receipt = {"schema": "case05-execution-receipt/v1", "job_id": job_id,
                 "scheduler": "slurm", "allocation_id": job_id, "allocation_is_array": False,
                 "gpus": gpus, "cpus": cpus, "memory_bytes": memory_bytes,
                 "wall_seconds": wall_seconds, "exit_code": 0,
                 "batch_script_sha256": sha(batch)}
    attached = {"execution_receipt": canonical_json(provenance_receipt), "scheduler_record": canonical_json(scheduler),
                "batch_script": batch, "stdout": stdout.read_bytes(), "stderr": stderr.read_bytes(),
                "raw_scheduler_log": accounting}
    descriptors={}
    for key, raw in attached.items():
        fname = {"execution_receipt":"execution-receipt.json", "scheduler_record":"scheduler-record.json",
                 "batch_script":"batch.slurm", "stdout":"slurm.stdout", "stderr":"slurm.stderr",
                 "raw_scheduler_log":"sacct.txt"}[key]
        (prov_dir/fname).write_bytes(raw)
        descriptors[key]={"path":f"provenance/{spec['run_id']}/{fname}","bytes":len(raw),"sha256":sha(raw)}
    sched_obj=json.loads(attached["scheduler_record"])
    sched_obj["raw_scheduler_log"]=descriptors.pop("raw_scheduler_log")
    (prov_dir/"scheduler-record.json").write_bytes(canonical_json(sched_obj))
    descriptors["scheduler_record"]["sha256"]=sha((prov_dir/"scheduler-record.json").read_bytes())
    descriptors["scheduler_record"]["bytes"]=(prov_dir/"scheduler-record.json").stat().st_size
    return {"run_id":spec["run_id"],"job_id":job_id,"scheduler":sched_obj,"descriptors":descriptors,
            "run_dir":run_out,"local_run":local_run,"spec":spec,"native_receipt":receipt_native}


def verify_bulk_gap(run: dict) -> None:
    if Vasprun is None:
        raise Stop("scientific dependency pymatgen==2024.5.1 is unavailable in the task image")
    path=run["run_dir"]/"vasprun.xml"
    try: parsed=Vasprun(path,parse_eigen=True,parse_projected_eigen=False)
    except Exception as exc: raise Stop(f"PBE gap/occupation preflight could not parse native vasprun.xml: {type(exc).__name__}") from exc
    if len(parsed.eigenvalues)!=1: raise Stop("gap gate requires one non-SOC spin channel")
    eigen=np.asarray(next(iter(parsed.eigenvalues.values())),dtype=float)
    if eigen.ndim!=3 or eigen.shape[2]!=2: raise Stop("gap gate eigenvalue dimensions are unsupported")
    energies,occupations=eigen[:,:,0],eigen[:,:,1]
    if not np.all(np.isfinite(eigen)): raise Stop("gap gate contains nonfinite energies or occupations")
    if np.any(np.minimum(np.abs(occupations),np.abs(occupations-1.0))>1e-6):
        raise Stop("PBE response gate requires complete 0/1 occupations; no response runs were submitted")
    occupied=occupations>0.5; empty=~occupied
    if not np.any(occupied) or not np.any(empty): raise Stop("PBE gap gate did not find both occupied and empty states")
    fundamental=float(np.min(energies[empty])-np.max(energies[occupied]))
    direct=min(float(np.min(energies[k,~occupied[k]])-np.max(energies[k,occupied[k]]))
               for k in range(len(energies)) if np.any(occupied[k]) and np.any(~occupied[k]))
    if fundamental<=0 or direct<=0: raise Stop("PBE gap is not positive; LEPSILON response calculations were not submitted")
    gamma=[i for i,k in enumerate(parsed.actual_kpoints) if np.linalg.norm(np.asarray(k.frac_coords))<1e-9]
    if len(gamma)!=1: raise Stop("deformation proof gate requires one explicit Gamma point")
    occ_gamma=occupations[gamma[0]]
    filled=np.flatnonzero(occ_gamma>0.5)
    if len(filled)<9 or not np.all(np.abs(occ_gamma[6:9]-1)<1e-6) or abs(occ_gamma[9])>1e-6:
        raise Stop("Gamma occupied valence triplet plus empty conduction state is not complete")


def extract_mirror_proof(runs: list[dict], output_root: Path) -> dict:
    if Wavecar is None or Vasprun is None:
        raise Stop("scientific dependency pymatgen==2024.5.1 is unavailable in the task image")
    wanted={"deformation_bulk":"bulk", "deformation_xy_0050_m":"xy_m_0.005",
            "deformation_xy_0050_p":"xy_p_0.005"}
    by_id={run["run_id"]:run for run in runs}
    if set(wanted)-set(by_id): raise Stop("fresh deformation suite lacks bulk and both xy mirror endpoints")
    rows=[]
    for run_id,label in wanted.items():
        run=by_id[run_id]; wpath=run["local_run"]/"WAVECAR"
        try: wave=Wavecar(str(wpath))
        except Exception as exc: raise Stop(f"pymatgen 2024.5.1 WAVECAR extraction failed: {type(exc).__name__}") from exc
        kp=np.asarray(wave.kpoints,dtype=float)
        gamma=np.flatnonzero(np.linalg.norm(kp-np.rint(kp),axis=1)<1e-9)
        if len(gamma)!=1: raise Stop(f"{run_id}: WAVECAR must contain exactly one Gamma k point")
        ik=int(gamma[0]); g=np.asarray(wave.Gpoints[ik])
        if g.ndim!=2 or g.shape[1]!=3 or not np.all(g==np.rint(g)):
            raise Stop(f"{run_id}: WAVECAR G point list is not integer reduced coordinates")
        g=g.astype(int)
        vasprun=Vasprun(run["run_dir"]/"vasprun.xml",parse_eigen=True,parse_projected_eigen=False)
        eig=np.asarray(next(iter(vasprun.eigenvalues.values())),float)
        gamma_k=next(i for i,k in enumerate(vasprun.actual_kpoints) if np.linalg.norm(k.frac_coords)<1e-9)
        bands={}
        for band1 in (7,8,9):
            coeff=np.asarray(wave.coeffs[ik][band1-1]).reshape(-1)
            if len(coeff)!=len(g): raise Stop(f"{run_id}: WAVECAR coefficients/G-point counts disagree")
            bands[str(band1)]={"coefficients_real":coeff.real.tolist(),"coefficients_imag":coeff.imag.tolist(),
                "energy_ev":float(eig[gamma_k,band1-1,0]),"occupation":float(eig[gamma_k,band1-1,1])}
        g_raw=json.dumps(g.tolist(),separators=(",",":")).encode()
        native_manifest=json.loads((run["run_dir"]/"input-manifest.json").read_text())
        rows.append({"run_id":run_id,"role":label,
            "source_ids":[],"wavecar_sha256":run["native_receipt"]["native_output_sha256"]["WAVECAR"],
            "lattice_angstrom":native_manifest["submitted_lattice_angstrom"],
            "gpoints_integer_reduced":g.tolist(),"gpoint_order_sha256":sha(g_raw),"bands_one_based":bands})
    # Fill exact per-run source IDs after final native hashes are known.
    for row in rows:
        run=by_id[row["run_id"]]; job=run["job_id"]
        row["source_ids"]=[sha((job+"\0jobs/"+job+"/native/"+row["run_id"]+"/"+name+"\0"+
                                 sha((run["run_dir"]/name).read_bytes())).encode()) for name in FILES]
    proof={"schema":"case05-candidate-gamma-mirror-proof/v1","runs":[
        {k:v for k,v in row.items() if k!="role"} for row in rows]}
    raw=canonical_json(proof)
    if len(raw)>2*1024*1024: raise Stop("Gamma mirror proof exceeds candidate verifier size limit")
    dest=output_root/"native"/"deformation-mirror-proof.json"
    dest.write_bytes(raw)
    return {"proof":proof,"raw":raw,"run_roles":{row["role"]:row["run_id"] for row in rows}}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("/app/final"))
    parser.add_argument("--assets",type=Path,default=Path("/app/assets"))
    args=parser.parse_args()
    if np is None:
        raise Stop("scientific dependency numpy==1.26.4 is unavailable in the task image")
    site=load_site()
    host="ikkem"
    remote_root=site["job_root"]
    potcar_root=site["potcar_root"]
    vasp_cmd=shlex.quote(site["vasp_path"])
    account=site["account"]
    partition=site["partition"]
    source=(args.assets/"author/inputs/GaAs.POSCAR").read_bytes()
    base_lines,base_lattice,_=parse_poscar(source); source_sha=sha(source)
    potcars=remote_preflight(host,remote_root,potcar_root,vasp_cmd,"case05-"+uuid.uuid4().hex)
    method={"xc":"PBE","paw_family":"PBE.54","potcar_order":list(POTCAR_ORDER),
            "potentials":[potcars[name] for name in POTCAR_ORDER]}
    specs=make_specs(base_lines,base_lattice)
    uid="case05-"+uuid.uuid4().hex
    scratch=Path(tempfile.mkdtemp(prefix="case05-fresh-"))
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/"native"/"runs").mkdir(parents=True)
    runs=[]
    workflow_sha=sha(Path(__file__).read_bytes())
    try:
        # Run the deformation bulk first and reject metallic/incompletely occupied
        # PBE states before launching any DFPT response calculation.
        ordered=sorted(specs,key=lambda s:(s["run_id"]!="deformation_bulk",s["run_id"]))
        for spec in ordered:
            local=scratch/spec["run_id"];local.mkdir()
            remote=f"{remote_root.rstrip('/')}/{uid}/{spec['run_id']}"
            run=submit_one(host,remote,local,spec,method,source_sha,workflow_sha,
                           potcar_root,vasp_cmd,account,partition,args.output)
            # Record actual cell geometry directly from the exact input POSCAR.
            _,lat,_=parse_poscar(spec["poscar"])
            mpath=run["run_dir"]/"input-manifest.json"
            manifest=json.loads(mpath.read_text());manifest["submitted_lattice_angstrom"]=lat
            manifest_raw=canonical_json(manifest);mpath.write_bytes(manifest_raw)
            receipt=run["native_receipt"];receipt["input_manifest_sha256"]=sha(manifest_raw)
            receipt_raw=canonical_json(receipt);(run["run_dir"]/"execution-receipt.json").write_bytes(receipt_raw)
            # Update matching attached provenance receipts to the final native bytes.
            prov=args.output/"native"/"provenance"/spec["run_id"]
            (prov/"execution-receipt.json").write_bytes(receipt_raw)
            run["native_receipt"]=receipt
            runs.append(run)
            if spec["run_id"]=="deformation_bulk": verify_bulk_gap(run)
        # Attach scheduler documents and run order only after every actual job exists.
        provenance_runs=[]
        for run in runs:
            item={"run_id":run["run_id"],**run["descriptors"]}
            provenance_runs.append(item)
        provenance_runs.sort(key=lambda x:run_by_id(runs,x["run_id"])["scheduler"]["start_utc"])
        provenance={"schema":SCHEMA_PROVENANCE,"execution_order":[x["run_id"] for x in provenance_runs],
                    "runs":provenance_runs}
        (args.output/"native"/"provenance-manifest.json").write_bytes(canonical_json(provenance))
        links=[]
        for run in runs:
            file_links=[]
            for name in FILES:
                raw=(run["run_dir"]/name).read_bytes()
                digest=sha((run["job_id"]+"\0jobs/"+run["job_id"]+"/native/"+run["run_id"]+"/"+name+"\0"+sha(raw)).encode())
                file_links.append({"name":name,"source_id":digest,"sha256":sha(raw)})
            links.append({"run_id":run["run_id"],"files":file_links})
        (args.output/"native"/"manifest.json").write_bytes(canonical_json({"schema":"case05-native-source-links/v1","runs":links}))
        mirror=extract_mirror_proof(runs,args.output)
        # Return only run identifiers; solver reads the collected native files
        # and derives every scored result from their source-linked observations.
        (scratch/"fresh-run-index.json").write_bytes(canonical_json({"run_ids":[r["run_id"] for r in runs]}))
        print(json.dumps({"status":"FRESH_NATIVE_COLLECTION_COMPLETE","run_count":len(runs),
                          "proof_sha256":sha(mirror["raw"])},sort_keys=True))
        return 0
    finally:
        shutil.rmtree(scratch,ignore_errors=True)


def run_by_id(runs:list[dict],run_id:str)->dict:
    return next(x for x in runs if x["run_id"]==run_id)


if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(2)
CASE60_FRESH_NATIVE_WORKFLOW

cat > "$WORKDIR/native_observation_adapter_v1.py" <<'CASE05_ADAPTER_88B0C898'
#!/usr/bin/env python3
"""Read-only, provenance-bound VASP observation adapter (not a science verifier).

The adapter emits typed native observations and source locations. It never
decides convergence quality, compares against a reference, writes artifacts,
or invokes VASP/Slurm. Missing response sections remain missing observations.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "case05.native_observation_adapter.v1"
FILES = (
    "POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
    "execution-receipt.json", "input-manifest.json",
)
LIMITS = {"vasprun.xml": 64 * 1024 * 1024, "OUTCAR": 32 * 1024 * 1024,
          "execution-receipt.json": 2 * 1024 * 1024,
          "input-manifest.json": 2 * 1024 * 1024}
LIMIT_DEFAULT = 1024 * 1024
NUMBER = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[Ee][+-]?\d+)?$")
CONSISTENCY_TAGS = {"GGA", "LHFCALC", "AEXX", "HFSCREEN", "LEPSILON", "NSW", "IBRION",
                    "ENCUT", "EDIFF", "EDIFFG", "ISPIN", "ISMEAR", "SIGMA", "IBRION",
                    "ISIF", "PREC", "NELM", "NBANDS", "ICHARG", "ISYM", "LPEAD", "LREAL"}


class AdapterError(Exception):
    """Base for a fail-closed adapter result."""


class EnvironmentInvalid(AdapterError):
    """Trusted snapshot, path, schema, dependency, or adapter capability issue."""


class CandidateNativeInvalid(AdapterError):
    """Malformed content in an otherwise hash-bound, candidate-owned native file."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite(value: float, where: str) -> float:
    if not math.isfinite(value):
        raise CandidateNativeInvalid(f"non-finite native value at {where}")
    return value


def _strict_json(data: bytes, source: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate key {key!r}")
            out[key] = value
        return out

    def bad_constant(value: str) -> None:
        raise ValueError(f"non-finite token {value}")

    def reject_nonfinite(value: Any, path: str = "$") -> None:
        if type(value) is float and not math.isfinite(value):
            raise ValueError(f"non-finite numeric value at {path}")
        if type(value) is dict:
            for key, child in value.items():
                reject_nonfinite(child, f"{path}.{key}")
        elif type(value) is list:
            for index, child in enumerate(value):
                reject_nonfinite(child, f"{path}[{index}]")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=bad_constant)
        reject_nonfinite(value)
        return value
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise EnvironmentInvalid(f"invalid trusted {source}: {exc}") from exc


def _read_stable(run_dir: Path, name: str) -> bytes:
    """Read one direct child without following symlinks and verify stable identity."""
    if name not in FILES or Path(name).name != name:
        raise EnvironmentInvalid(f"unexpected native path {name!r}")
    root = Path(run_dir).absolute()
    try:
        # Reject a symlink at the requested run-directory leaf. Resolve
        # platform-level ancestor aliases (for example macOS /var -> /private/var)
        # before checking the physical path; the opened directory itself remains
        # NOFOLLOW and is never replaced by this adapter.
        requested = os.lstat(root)
        if stat.S_ISLNK(requested.st_mode) or not stat.S_ISDIR(requested.st_mode):
            raise EnvironmentInvalid("native run directory must be a real directory, not a symlink")
        root = root.resolve(strict=True)
        cur = Path(root.anchor)
        for part in root.parts[1:]:
            cur = cur / part
            st = os.lstat(cur)
            if stat.S_ISLNK(st.st_mode):
                raise EnvironmentInvalid(f"symlink in native directory path: {cur}")
            if not stat.S_ISDIR(st.st_mode):
                raise EnvironmentInvalid(f"non-directory in native path: {cur}")
        dfd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                      getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise EnvironmentInvalid(f"native member is not a regular file: {name}")
            limit = LIMITS.get(name, LIMIT_DEFAULT)
            if before.st_size > limit:
                raise EnvironmentInvalid(f"native member exceeds adapter bound: {name}")
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dfd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
                    raise EnvironmentInvalid(f"native member changed before open: {name}")
                chunks = []
                total = 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024, limit + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > limit:
                        raise EnvironmentInvalid(f"native member exceeds adapter bound: {name}")
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=dfd, follow_symlinks=False)
                ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
                if ident(opened) != ident(after) or ident(opened) != ident(current):
                    raise EnvironmentInvalid(f"native member changed while reading: {name}")
                return b"".join(chunks)
            finally:
                os.close(fd)
        finally:
            os.close(dfd)
    except AdapterError:
        raise
    except OSError as exc:
        raise EnvironmentInvalid(f"cannot securely read native member {name}: {exc}") from exc


def _incar(data: bytes) -> dict[str, tuple[str, str]]:
    try:
        text = data.decode("ascii")
    except UnicodeError as exc:
        raise CandidateNativeInvalid("INCAR is not ASCII") from exc
    values: dict[str, tuple[str, str]] = {}
    for number, line in enumerate(text.splitlines(), 1):
        body = re.split(r"[#!]", line, maxsplit=1)[0].strip()
        if not body:
            continue
        if "=" not in body:
            raise CandidateNativeInvalid(f"unrecognized INCAR line {number}")
        key, raw = body.split("=", 1)
        key = key.strip().upper()
        raw = raw.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not raw:
            raise CandidateNativeInvalid(f"malformed INCAR assignment at line {number}")
        if key in values:
            raise CandidateNativeInvalid(f"duplicate INCAR tag {key}")
        values[key] = (raw, f"INCAR:{number}")
    return values


def _parse_float(text: str, where: str, native: bool = True) -> float:
    token = text.strip()
    if not NUMBER.fullmatch(token):
        exc = CandidateNativeInvalid if native else EnvironmentInvalid
        raise exc(f"invalid numeric token at {where}: {token!r}")
    value = float(token)
    return _finite(value, where)


def _child_named(parent: ET.Element, tag: str, name: str) -> ET.Element:
    found = [node for node in parent.findall(tag) if node.get("name") == name]
    if len(found) != 1:
        raise CandidateNativeInvalid(f"expected one {tag} name={name!r}; found {len(found)}")
    return found[0]


def _vector_rows(node: ET.Element, expected: int, where: str) -> list[list[float]]:
    rows = node.findall("./v")
    if len(rows) != expected:
        raise CandidateNativeInvalid(f"{where}: expected {expected} vectors, found {len(rows)}")
    result = []
    for idx, row in enumerate(rows):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise CandidateNativeInvalid(f"{where}[{idx}] must have 3 coordinates")
        result.append([_parse_float(x, f"{where}[{idx}]") for x in fields])
    return result


def _matrix_inverse3(rows: list[list[float]], where: str) -> list[list[float]]:
    a, b, c = rows
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise CandidateNativeInvalid(f"{where} lattice is singular")
    return [[(b[1] * c[2] - b[2] * c[1]) / det,
             (a[2] * c[1] - a[1] * c[2]) / det,
             (a[1] * b[2] - a[2] * b[1]) / det],
            [(b[2] * c[0] - b[0] * c[2]) / det,
             (a[0] * c[2] - a[2] * c[0]) / det,
             (a[2] * b[0] - a[0] * b[2]) / det],
            [(b[0] * c[1] - b[1] * c[0]) / det,
             (a[1] * c[0] - a[0] * c[1]) / det,
             (a[0] * b[1] - a[1] * b[0]) / det]]


def _poscar_initial_geometry(data: bytes, digest: str) -> dict[str, Any]:
    """Parse the bounded VASP5 POSCAR geometry used as response parent input."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise CandidateNativeInvalid("POSCAR is not ASCII") from exc
    if len(lines) < 8:
        raise CandidateNativeInvalid("POSCAR is truncated before coordinate rows")
    scale_fields = lines[1].split()
    if len(scale_fields) != 1:
        raise CandidateNativeInvalid("POSCAR scale must be a single supported scalar")
    scale = _parse_float(scale_fields[0], "POSCAR:2")
    if scale <= 0:
        raise CandidateNativeInvalid("POSCAR scale must be positive in the supported profile")
    raw_lattice = []
    for idx in range(3):
        fields = lines[2 + idx].split()
        if len(fields) != 3:
            raise CandidateNativeInvalid(f"POSCAR lattice row {idx + 1} is malformed")
        raw_lattice.append([_parse_float(value, f"POSCAR:{idx + 3}") * scale for value in fields])
    symbols = lines[5].split()
    counts_raw = lines[6].split()
    if not symbols or len(symbols) != len(counts_raw) or any(
            not re.fullmatch(r"[A-Z][a-z]?$", item) for item in symbols):
        raise CandidateNativeInvalid("POSCAR VASP5 species/count rows are malformed")
    if any(not re.fullmatch(r"[1-9][0-9]*", item) for item in counts_raw):
        raise CandidateNativeInvalid("POSCAR species counts must be positive integers")
    counts = [int(item) for item in counts_raw]
    species = [symbol for symbol, count in zip(symbols, counts) for _ in range(count)]
    line_index = 7
    if lines[line_index].strip().lower().startswith("s"):
        line_index += 1
    if line_index >= len(lines):
        raise CandidateNativeInvalid("POSCAR lacks coordinate mode")
    mode = lines[line_index].strip().lower()
    if mode.startswith("d"):
        coordinate_mode = "direct"
    elif mode.startswith(("c", "k")):
        coordinate_mode = "cartesian"
    else:
        raise CandidateNativeInvalid("POSCAR coordinate mode is unsupported")
    positions_start = line_index + 1
    if len(lines) < positions_start + len(species):
        raise CandidateNativeInvalid("POSCAR coordinate list is truncated")
    positions = []
    for idx in range(len(species)):
        fields = lines[positions_start + idx].split()
        if len(fields) < 3:
            raise CandidateNativeInvalid(f"POSCAR coordinate row {idx + 1} is malformed")
        positions.append([_parse_float(value, f"POSCAR:{positions_start + idx + 1}")
                          for value in fields[:3]])
    if coordinate_mode == "cartesian":
        inv = _matrix_inverse3(raw_lattice, "POSCAR")
        positions = [[scale * sum(row[j] * inv[j][i] for j in range(3))
                      for i in range(3)] for row in positions]
    return {"lattice": raw_lattice, "species_order": species,
            "fractional_positions": positions, "coordinate_mode": coordinate_mode,
            "native_sha256": digest,
            "raw_pointer": {"lattice_lines": [3, 4, 5], "species_line": 6,
                            "counts_line": 7, "mode_line": line_index + 1,
                            "position_lines": list(range(positions_start + 1,
                                                         positions_start + len(species) + 1))}}


def _structure_from_xml(root: ET.Element, name: str, species: list[str],
                        xml_hash: str) -> dict[str, Any] | None:
    structures = [node for node in root.findall("./structure") if node.get("name") == name]
    if len(structures) > 1:
        raise CandidateNativeInvalid(f"vasprun.xml repeats {name} structure")
    if not structures:
        return None
    structure = structures[0]
    crystal = structure.find("./crystal")
    if crystal is None:
        raise CandidateNativeInvalid(f"{name} lacks crystal")
    lattice = _vector_rows(_child_named(crystal, "varray", "basis"), 3, f"{name}/basis")
    positions_node = _child_named(structure, "varray", "positions")
    positions = []
    for idx, row in enumerate(positions_node.findall("./v")):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise CandidateNativeInvalid(f"{name}/positions[{idx}] malformed")
        positions.append([_parse_float(x, f"{name}/positions[{idx}]") for x in fields])
    if len(positions) != len(species):
        raise CandidateNativeInvalid(f"{name} position/species counts do not agree")
    return {"lattice": lattice, "species_order": list(species),
            "fractional_positions": positions, "native_sha256": xml_hash,
            "raw_pointer": {"lattice": f"/modeling/structure[@name='{name}']/crystal/varray[@name='basis']",
                            "positions": f"/modeling/structure[@name='{name}']/varray[@name='positions']",
                            "species": "/modeling/atominfo/array[@name='atoms']"}}


def _compare_parent_geometries(poscar: dict[str, Any], initial: dict[str, Any],
                               manifest: dict[str, Any]) -> dict[str, Any]:
    """Bind response reference geometry to submitted POSCAR and XML initialpos."""
    if manifest.get("stage_kind") != "elastic":
        raise CandidateNativeInvalid("IBRION=6 response geometry has an unexpected stage kind")
    if (manifest.get("source_poscar_sha256") != poscar["native_sha256"] or
            manifest.get("parent_geometry_sha256") != poscar["native_sha256"]):
        raise CandidateNativeInvalid("elastic response parent geometry is not bound to submitted POSCAR")
    if poscar["species_order"] != initial["species_order"]:
        raise CandidateNativeInvalid("submitted POSCAR and vasprun initialpos species/order differ")
    max_lattice = max(abs(poscar["lattice"][i][j] - initial["lattice"][i][j])
                      for i in range(3) for j in range(3))
    if max_lattice > 1e-7:
        raise CandidateNativeInvalid("submitted POSCAR and vasprun initialpos lattice differ")
    deltas = [abs((poscar["fractional_positions"][i][j] -
                   initial["fractional_positions"][i][j]) -
                  round(poscar["fractional_positions"][i][j] -
                        initial["fractional_positions"][i][j]))
              for i in range(len(poscar["species_order"])) for j in range(3)]
    max_fractional = max(deltas, default=0.0)
    if max_fractional > 1e-7:
        raise CandidateNativeInvalid("submitted POSCAR and vasprun initialpos fractional geometry differ")
    return {"status": "SUBMITTED_PARENT_POSCAR_MATCHES_VASPRUN_INITIALPOS",
            "scope": "response reference geometry only; finalpos remains separate observed output",
            "max_lattice_abs_difference_angstrom": max_lattice,
            "max_fractional_difference_modulo_lattice": max_fractional,
            "poscar_sha256": poscar["native_sha256"],
            "xml_sha256": initial["native_sha256"],
            "poscar_pointer": poscar["raw_pointer"],
            "xml_pointer": initial["raw_pointer"],
            "manifest_source_poscar_sha256": manifest["source_poscar_sha256"],
            "manifest_parent_geometry_sha256": manifest["parent_geometry_sha256"]}


def _xml_observations(xml_bytes: bytes, xml_hash: str,
                      input_keys: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, ValueError) as exc:
        raise CandidateNativeInvalid(f"malformed vasprun.xml: {exc}") from exc
    if root.tag != "modeling":
        raise EnvironmentInvalid("unsupported vasprun.xml root (parser capability gap)")
    generator = root.find("./generator")
    if generator is None:
        raise CandidateNativeInvalid("vasprun.xml lacks generator metadata")
    prog = _child_named(generator, "i", "program").text or ""
    version = _child_named(generator, "i", "version").text or ""
    if "vasp" not in prog.lower():
        raise EnvironmentInvalid("native XML is not a recognized VASP source")
    final = [s for s in root.findall("./structure") if s.get("name") == "finalpos"]
    if len(final) != 1:
        raise CandidateNativeInvalid(f"expected one finalpos structure; found {len(final)}")
    structure = final[0]
    crystal = structure.find("./crystal")
    if crystal is None:
        raise CandidateNativeInvalid("finalpos lacks crystal")
    basis_node = _child_named(crystal, "varray", "basis")
    lattice = _vector_rows(basis_node, 3, "finalpos/basis")
    vol_node = _child_named(crystal, "i", "volume")
    volume = _parse_float(vol_node.text or "", "finalpos/volume")
    if volume <= 0:
        raise CandidateNativeInvalid("finalpos volume must be positive")
    positions_node = _child_named(structure, "varray", "positions")
    positions = []
    for idx, row in enumerate(positions_node.findall("./v")):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise CandidateNativeInvalid(f"finalpos/positions[{idx}] malformed")
        positions.append([_parse_float(x, f"finalpos/positions[{idx}]") for x in fields])
    atom_array = root.find("./atominfo/array[@name='atoms']/set")
    if atom_array is None:
        raise CandidateNativeInvalid("vasprun.xml lacks atom species table")
    species = []
    for idx, row in enumerate(atom_array.findall("./rc")):
        cols = row.findall("./c")
        if len(cols) < 1 or not (cols[0].text or "").strip():
            raise CandidateNativeInvalid(f"atom species row {idx} malformed")
        species.append((cols[0].text or "").strip())
    if not species or len(species) != len(positions):
        raise CandidateNativeInvalid("finalpos site/species counts do not agree")
    initial_structure = _structure_from_xml(root, "initialpos", species, xml_hash)
    observations: list[dict[str, Any]] = []

    def add(field: str, value: Any, units: str, pointer: str, frame: str | None = None) -> None:
        item: dict[str, Any] = {"field": field, "value": value, "units": units,
                                "native_sha256": xml_hash, "raw_pointer": pointer}
        if frame is not None:
            item["frame"] = frame
        observations.append(item)

    add("structure.lattice", lattice, "angstrom", "/modeling/structure[@name='finalpos']/crystal/varray[@name='basis']", "Cartesian lattice vectors as rows")
    add("structure.volume", volume, "angstrom^3", "/modeling/structure[@name='finalpos']/crystal/i[@name='volume']")
    add("structure.species_order", species, "element labels", "/modeling/atominfo/array[@name='atoms']")
    add("structure.fractional_positions", positions, "fractional", "/modeling/structure[@name='finalpos']/varray[@name='positions']", "fractional coordinates in finalpos cell")
    if initial_structure is not None:
        add("structure.initial_lattice", initial_structure["lattice"], "angstrom",
            initial_structure["raw_pointer"]["lattice"], "Cartesian lattice vectors as rows")
        add("structure.initial_fractional_positions", initial_structure["fractional_positions"],
            "fractional", initial_structure["raw_pointer"]["positions"],
            "fractional coordinates in initialpos cell")
    add("structure.final_fractional_positions", positions, "fractional",
        "/modeling/structure[@name='finalpos']/varray[@name='positions']",
        "finalpos output coordinates; not the response parent geometry")

    klist = root.findall("./kpoints/varray[@name='kpointlist']/v")
    if not klist:
        raise CandidateNativeInvalid("vasprun.xml lacks kpointlist")
    kpoints = []
    kpoint_tokens = []
    for idx, row in enumerate(klist):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise CandidateNativeInvalid(f"kpointlist[{idx}] malformed")
        kpoints.append([_parse_float(x, f"kpoint[{idx}]") for x in fields])
        kpoint_tokens.append(fields)
    calculations = root.findall("./calculation")
    if not calculations:
        raise CandidateNativeInvalid("vasprun.xml has no calculation history")
    for calc_index, calculation in enumerate(calculations):
        if len(calculation.findall("./eigenvalues")) > 1:
            raise CandidateNativeInvalid(f"calculation[{calc_index + 1}] repeats eigenvalues arrays")
    final_eigs = calculations[-1].findall("./eigenvalues")
    if len(final_eigs) != 1:
        raise CandidateNativeInvalid("final calculation must contain exactly one eigenvalues array")
    eig_index = len(calculations)  # XPath element indices are one-based.
    eig_node = final_eigs[0]
    eig_root = eig_node.find("./array/set")
    if eig_root is None:
        raise CandidateNativeInvalid("eigenvalues array has no spin sets")
    spins: list[list[list[tuple[float, float]]]] = []
    energy_tokens_by_spin: list[list[list[str]]] = []
    occupation_tokens_by_spin: list[list[list[str]]] = []
    for si, spinset in enumerate(eig_root.findall("./set")):
        spin_rows: list[list[tuple[float, float]]] = []
        spin_energy_tokens: list[list[str]] = []
        spin_occupation_tokens: list[list[str]] = []
        for ki, kset in enumerate(spinset.findall("./set")):
            rows = []
            energy_tokens = []
            occupation_tokens = []
            for bi, row in enumerate(kset.findall("./r")):
                fields = (row.text or "").split()
                if len(fields) != 2:
                    raise CandidateNativeInvalid(f"eigenvalue row spin={si},k={ki},band={bi} malformed")
                energy = _parse_float(fields[0], "eigenvalue")
                occ = _parse_float(fields[1], "occupation")
                if occ < 0 or occ > 1:
                    raise CandidateNativeInvalid("VASP occupation lies outside [0,1]")
                rows.append((energy, occ))
                energy_tokens.append(fields[0])
                occupation_tokens.append(fields[1])
            if not rows:
                raise CandidateNativeInvalid("empty eigenvalue k-point set")
            spin_rows.append(rows)
            spin_energy_tokens.append(energy_tokens)
            spin_occupation_tokens.append(occupation_tokens)
        if spin_rows:
            spins.append(spin_rows)
            energy_tokens_by_spin.append(spin_energy_tokens)
            occupation_tokens_by_spin.append(spin_occupation_tokens)
    if not spins or any(len(s) != len(kpoints) for s in spins):
        raise CandidateNativeInvalid("eigenvalue spin/k-point dimensions do not match kpointlist")
    band_counts = {len(rows) for spin in spins for rows in spin}
    if len(band_counts) != 1:
        raise CandidateNativeInvalid("inconsistent eigenvalue band counts")
    fractionals = [(si, ki, bi, occ) for si, spin in enumerate(spins) for ki, bands in enumerate(spin)
                   for bi, (_, occ) in enumerate(bands) if occ not in (0.0, 1.0)]
    eig_pointer = f"/modeling/calculation[{eig_index}]/eigenvalues/array/set"
    gamma_indices = [idx for idx, point in enumerate(kpoints)
                     if all(abs(value - round(value)) <= 1e-10 for value in point)]
    gamma_value = None
    gamma_availability = "NOT_OBSERVED_NO_GAMMA_POINT"
    gamma_pointer: dict[str, Any] = {"kpointlist_entries": [], "eigenvalue_spectrum": eig_pointer}
    if len(gamma_indices) == 1:
        gamma_index = gamma_indices[0]
        gamma_pointer["kpointlist_entries"] = [
            f"/modeling/kpoints/varray[@name='kpointlist']/v[{gamma_index + 1}]"
        ]
        gamma_value = {
            "kpoint_index_0based": gamma_index,
            "fractional_coordinates": kpoints[gamma_index],
            "fractional_coordinate_tokens": kpoint_tokens[gamma_index],
            "spins": [{
                "spin_index_0based": spin_index,
                "bands": [{
                    "band_index_0based": band_index,
                    "band_index_1based": band_index + 1,
                    "energy_eV": values[gamma_index][band_index][0],
                    "energy_token_eV": energy_tokens_by_spin[spin_index][gamma_index][band_index],
                    "occupation": values[gamma_index][band_index][1],
                    "occupation_token": occupation_tokens_by_spin[spin_index][gamma_index][band_index],
                } for band_index in range(len(values[gamma_index]))],
            } for spin_index, values in enumerate(spins)]
        }
        gamma_availability = "OBSERVED_UNIQUE_GAMMA"
        gamma_pointer["spin_kpoint_spectra"] = [
            f"{eig_pointer}/set[{spin_index + 1}]/set[{gamma_index + 1}]"
            for spin_index in range(len(spins))
        ]
    elif len(gamma_indices) > 1:
        gamma_availability = "UNSUPPORTED_MULTIPLE_GAMMA_EQUIVALENTS"
        gamma_pointer["kpointlist_entries"] = [
            f"/modeling/kpoints/varray[@name='kpointlist']/v[{idx + 1}]"
            for idx in gamma_indices
        ]
    observations.append({
        "field": "band.gamma_spectrum", "value": gamma_value,
        "units": "eV and electron/state",
        "frame": "all native spin channels and bands at unique Gamma modulo reciprocal lattice vectors",
        "native_sha256": xml_hash, "raw_pointer": gamma_pointer,
        "availability": gamma_availability,
    })
    if fractionals:
        add("band.fundamental_gap", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.direct_gap", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.vbm", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.cbm", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
    else:
        occupied = [(e, s, k, b, o) for s, spin in enumerate(spins) for k, bands in enumerate(spin)
                    for b, (e, o) in enumerate(bands) if o == 1.0]
        empty = [(e, s, k, b, o) for s, spin in enumerate(spins) for k, bands in enumerate(spin)
                 for b, (e, o) in enumerate(bands) if o == 0.0]
        if not occupied or not empty:
            raise CandidateNativeInvalid("cannot identify fully occupied and empty eigenvalue states")
        vbm = max(occupied, key=lambda x: x[0])
        cbm = min(empty, key=lambda x: x[0])
        fundamental = _finite(cbm[0] - vbm[0], "fundamental gap")
        direct_candidates = []
        for si, spin in enumerate(spins):
            for ki, bands in enumerate(spin):
                occ_e = [e for e, o in bands if o == 1.0]
                emp_e = [e for e, o in bands if o == 0.0]
                if occ_e and emp_e:
                    direct_candidates.append((min(emp_e) - max(occ_e), si, ki))
        if not direct_candidates:
            raise CandidateNativeInvalid("no same-k fully occupied/empty state pairs")
        direct = min(direct_candidates)
        add("band.fundamental_gap", fundamental, "eV", eig_pointer)
        add("band.direct_gap", _finite(direct[0], "direct gap"), "eV", eig_pointer + " (same-k, same-spin extrema)")
        add("band.vbm", {"energy_ev": vbm[0], "spin_index_0based": vbm[1], "kpoint_index_0based": vbm[2], "band_index_0based": vbm[3], "occupation": vbm[4]}, "eV", eig_pointer)
        add("band.cbm", {"energy_ev": cbm[0], "spin_index_0based": cbm[1], "kpoint_index_0based": cbm[2], "band_index_0based": cbm[3], "occupation": cbm[4]}, "eV", eig_pointer)
    add("band.occupations", {"spin_count": len(spins), "kpoint_count": len(kpoints), "band_count": next(iter(band_counts)), "fractional_state_count": len(fractionals), "fractional_state_indices": [list(x[:3]) for x in fractionals]}, "electron per state", eig_pointer)
    response_obs, response_meta = _xml_response_observations(calculations, species, xml_hash)
    observations.extend(response_obs)
    incar_node = root.find("./incar")
    xml_incar = {}
    xml_incar_types: dict[str, str | None] = {}
    xml_incar_element_tags: dict[str, str] = {}
    if incar_node is not None:
        for node in list(incar_node.findall("./i")) + list(incar_node.findall("./v")):
            key = node.get("name", "").upper()
            if key in xml_incar:
                raise CandidateNativeInvalid(f"duplicate vasprun INCAR tag {key}")
            xml_incar[key] = (node.text or "").strip()
            xml_incar_types[key] = node.get("type")
            xml_incar_element_tags[key] = node.tag
    effective_parameters: dict[str, tuple[str, str | None]] = {}
    effective_parameter_pointers: dict[str, str] = {}
    consistency_keys = set(xml_incar) | set(input_keys or ()) | CONSISTENCY_TAGS
    for separator in root.findall("./parameters/separator"):
        separator_name = separator.get("name", "")
        for node in list(separator.findall("./i")) + list(separator.findall("./v")):
            key = node.get("name", "").upper()
            if not key or key not in consistency_keys:
                continue
            if key in effective_parameters:
                raise CandidateNativeInvalid(f"duplicate effective parameter {key} in vasprun.xml")
            effective_parameters[key] = ((node.text or "").strip(), node.get("type"))
            element_tag = node.tag
            effective_parameter_pointers[key] = (
                f"/modeling/parameters/separator[@name='{separator_name}']/"
                f"{element_tag}[@name='{key}']")
    for source_name, source in (("vasprun.xml/incar", xml_incar_types),
                                ("vasprun.xml/parameters", {key: pair[1] for key, pair in effective_parameters.items()})):
        for key, required_type in _REQUIRED_XML_TYPES.items():
            if key in source:
                declared = source[key]
                allowed = {"int", "integer"} if required_type == "int" else {required_type}
                if declared is None or declared.lower() not in allowed:
                    raise CandidateNativeInvalid(
                        f"{source_name} {key} must declare XML type {required_type}"
                    )
    effective_lepsilon_value = effective_parameters.get("LEPSILON", (None, None))[0]
    convergence = {"electronic": "UNKNOWN", "ionic": "NOT_RUN_OR_UNKNOWN", "ediff_marker_count": 0,
                   "warning_markers": []}
    if xml_incar.get("NSW") == "0":
        convergence["ionic"] = "NOT_RUN_BY_NSW_ZERO"
    return observations, {"vasp_version": version.strip(), "xml_incar": xml_incar,
                          "xml_incar_types": xml_incar_types,
                          "effective_parameters": effective_parameters,
                          "effective_parameter_pointers": effective_parameter_pointers,
                          "xml_parameter_sources": {
                              "incar": {key: {"raw": raw, "declared_type": xml_incar_types[key],
                                              "raw_pointer": f"/modeling/incar/{xml_incar_element_tags[key]}[@name='{key}']"}
                                        for key, raw in xml_incar.items()},
                              "parameters": {key: {"raw": raw, "declared_type": declared,
                                                   "raw_pointer": effective_parameter_pointers[key]}
                                             for key, (raw, declared) in effective_parameters.items()},
                          },
                          "effective_lepsilon": effective_lepsilon_value,
                          "response": response_meta,
                          "initial_structure": initial_structure,
                          "kpoint_count": len(kpoints), "spin_count": len(spins),
                          "band_count": next(iter(band_counts)), "convergence": convergence}


def _parse_incar_value(key: str, pair: tuple[str, str]) -> Any:
    raw, loc = pair
    if raw.upper() in ("T", ".TRUE.", "TRUE"):
        return True
    if raw.upper() in ("F", ".FALSE.", "FALSE"):
        return False
    if NUMBER.fullmatch(raw):
        return _parse_float(raw, loc, native=True)
    if "," in raw or " " in raw:
        # Keep unparsed vector/array values explicit rather than coercing them.
        return raw
    return raw.strip('"\'')


def _logical_lexeme(raw: str, where: str) -> bool:
    value = raw.strip().upper()
    if value in ("T", ".TRUE.", "TRUE"):
        return True
    if value in ("F", ".FALSE.", "FALSE"):
        return False
    raise CandidateNativeInvalid(f"{where} is not a supported logical lexeme")


_LOGICAL_TAGS = {"LEPSILON", "LHFCALC", "LSORBIT", "LNONCOLLINEAR",
                 "ADDGRID", "LASPH", "LWAVE", "LCHARG", "LUSE_VDW", "LPEAD"}
_INTEGER_TAGS = {"NSW", "IBRION", "ISPIN", "NELM", "NBANDS", "ISMEAR", "ICHARG",
                 "ISYM", "NCORE", "KPAR"}
_REQUIRED_XML_TYPES = {"LEPSILON": "logical", "LPEAD": "logical", "NSW": "int"}


def _xml_response_observations(calculations: list[ET.Element], species: list[str],
                               xml_hash: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read response arrays only from the unique final calculation structure."""
    names = ("epsilon", "epsilon_ion", "born_charges")
    found_by_calc: list[dict[str, list[ET.Element]]] = []
    for calc in calculations:
        entry = {name: [node for node in calc.iter() if node.get("name") == name]
                 for name in names}
        found_by_calc.append(entry)
    final_index = len(calculations)
    final = found_by_calc[-1]
    for index, entry in enumerate(found_by_calc[:-1], 1):
        if any(entry[name] for name in names):
            raise CandidateNativeInvalid(
                f"response arrays occur outside the unique final calculation at calculation[{index}]"
            )
    totals = {name: sum(len(entry[name]) for entry in found_by_calc) for name in names}
    if not any(totals.values()):
        return [], {"epsilon_high": None, "epsilon_ionic": None,
                    "born_effective_charges": None, "response_source_pointer": None}
    for name in names:
        if totals[name] != 1 or len(final[name]) != 1:
            raise CandidateNativeInvalid(
                f"final calculation must contain exactly one {name}; found {len(final[name])}"
            )

    def matrix(node: ET.Element, where: str) -> list[list[float]]:
        rows = node.findall("./v")
        if len(rows) != 3:
            raise CandidateNativeInvalid(f"{where} must contain exactly 3 rows")
        result = []
        for ri, row in enumerate(rows):
            fields = (row.text or "").split()
            if len(fields) != 3:
                raise CandidateNativeInvalid(f"{where}[{ri}] must contain exactly 3 values")
            result.append([_parse_float(x, f"{where}[{ri}]") for x in fields])
        return result

    high_node, ionic_node, born_node = (final[name][0] for name in names)
    expected_tags = {"epsilon": "varray", "epsilon_ion": "varray", "born_charges": "array"}
    for name, node in zip(names, (high_node, ionic_node, born_node)):
        if node.tag != expected_tags[name] or node not in calculations[-1]:
            raise CandidateNativeInvalid(
                f"final calculation {name} must be a direct {expected_tags[name]} child"
            )
    high = matrix(high_node, "final calculation epsilon")
    ionic = matrix(ionic_node, "final calculation epsilon_ion")
    dimensions = born_node.findall("./dimension")
    sets = born_node.findall("./set")
    if len(dimensions) != 1 or (dimensions[0].text or "").strip().lower() != "ion":
        raise CandidateNativeInvalid("born_charges must declare one ion dimension")
    if len(sets) != len(species) or not species:
        raise CandidateNativeInvalid("born_charges set count does not match finalpos atom count")
    born: list[list[list[float]]] = []
    for atom, node in enumerate(sets):
        born.append(matrix(node, f"final calculation born_charges ion[{atom + 1}]"))
    base = f"/modeling/calculation[{final_index}]"
    rows = [
        {"field": "dielectric.epsilon_high_xml", "value": high, "units": "dimensionless",
         "frame": "Cartesian x,y,z", "native_sha256": xml_hash,
         "raw_pointer": base + "/varray[@name='epsilon']"},
        {"field": "dielectric.epsilon_ionic_xml", "value": ionic, "units": "dimensionless",
         "frame": "Cartesian x,y,z", "native_sha256": xml_hash,
         "raw_pointer": base + "/varray[@name='epsilon_ion']"},
        {"field": "born.effective_charges_xml", "value": born, "units": "|e|",
         "frame": "atom-major, Cartesian polarization/displacement axes; atom order follows finalpos",
         "species_order": list(species), "native_sha256": xml_hash,
         "raw_pointer": base + "/array[@name='born_charges']/set"},
    ]
    return rows, {"epsilon_high": high, "epsilon_ionic": ionic,
                  "born_effective_charges": born,
                  "response_source_pointer": base}


def _normalized_tag(key: str, raw: str, declared_type: str | None, where: str) -> Any:
    value = raw.strip()
    kind = declared_type.lower() if declared_type else None
    if kind not in (None, "logical", "int", "integer", "float", "double", "string"):
        raise CandidateNativeInvalid(f"unsupported XML type {declared_type!r} for {key} at {where}")
    if key == "LREAL":
        if kind == "logical":
            return _logical_lexeme(value, f"{where} {key}")
        if kind not in (None, "string"):
            raise CandidateNativeInvalid(f"unsupported XML type {declared_type!r} for LREAL at {where}")
        token = value.strip('"\'').upper()
        if token in ("T", ".TRUE.", "TRUE"):
            return True
        if token in ("F", ".FALSE.", "FALSE"):
            return False
        if token in ("AUTO", "A"):
            return "AUTO"
        if token in ("ON", "O"):
            return "ON"
        raise CandidateNativeInvalid(f"{where} LREAL has an unsupported mode lexeme")
    if kind == "logical" or (kind is None and key in _LOGICAL_TAGS):
        return _logical_lexeme(value, f"{where} {key}")
    if kind in ("int", "integer") or (kind is None and key in _INTEGER_TAGS):
        number = _parse_float(value, f"{where} {key}")
        if not number.is_integer():
            raise CandidateNativeInvalid(f"{where} {key} must be an integer lexeme")
        return int(number)
    if kind in ("float", "double") or NUMBER.fullmatch(value):
        return _parse_float(value, f"{where} {key}")
    if kind == "string" or kind is None:
        parts = value.split()
        if len(parts) > 1 and all(NUMBER.fullmatch(part) for part in parts):
            return tuple(_parse_float(part, f"{where} {key}") for part in parts)
        normalized = value.strip('"\'').upper()
        # VASP serializes PREC=Accurate as the effective token "accura".
        if key == "PREC" and normalized == "ACCURA":
            normalized = "ACCURATE"
        return normalized
    raise CandidateNativeInvalid(f"unsupported value for {key} at {where}")


def _proven_ibrion6_nsw_expansion(layers: dict[str, dict[str, tuple[str, str | None]]],
                                  manifest: dict[str, Any], receipt: dict[str, Any],
                                  xml_parameter_pointers: dict[str, str],
                                  incar_sources: dict[str, str]) -> dict[str, Any] | None:
    """Recognize only the reviewed IBRION=6 submitted/effective NSW transition."""
    if not (manifest.get("case_id") == "case-05-first-principles-inputs" and
            receipt.get("case_id") == manifest.get("case_id") and
            manifest.get("stage") == "03_elastic_pbe" and
            manifest.get("stage_kind") == "elastic" and
            receipt.get("stage") == manifest.get("stage") and
            receipt.get("status") == "FINISHED" and receipt.get("exit_code") == 0):
        return None
    observed: dict[str, dict[str, Any]] = {}
    for layer in ("INCAR", "vasprun.xml/incar", "vasprun.xml/parameters"):
        entries = layers[layer]
        if "NSW" not in entries or "IBRION" not in entries:
            raise CandidateNativeInvalid(f"elastic IBRION=6 run lacks NSW/IBRION in {layer}")
        nsw_raw, nsw_type = entries["NSW"]
        ibrion_raw, ibrion_type = entries["IBRION"]
        observed[layer] = {
            "NSW": _normalized_tag("NSW", nsw_raw, nsw_type, layer),
            "IBRION": _normalized_tag("IBRION", ibrion_raw, ibrion_type, layer),
        }
    if any(observed[layer]["IBRION"] != 6 for layer in observed):
        raise CandidateNativeInvalid("elastic IBRION layer values differ from the reviewed IBRION=6 profile")
    if (observed["INCAR"]["NSW"] != 1 or observed["vasprun.xml/incar"]["NSW"] != 1 or
            observed["vasprun.xml/parameters"]["NSW"] != 61):
        raise CandidateNativeInvalid("elastic NSW layers differ from the reviewed 1/1/61 IBRION=6 profile")
    return {"status": "AUTHORIZED_IBRION6_EFFECTIVE_NSW_EXPANSION_OBSERVED",
            "submitted_nsw": 1,
            "xml_incar_nsw": 1,
            "xml_effective_nsw": 61,
            "ibrion": 6,
            "sources": {
                "INCAR": {key: incar_sources[key] for key in ("NSW", "IBRION")},
                "vasprun.xml/incar": {
                    key: f"/modeling/incar/i[@name='{key}']" for key in ("NSW", "IBRION")},
                "vasprun.xml/parameters": {
                    key: xml_parameter_pointers[key] for key in ("NSW", "IBRION")},
            },
            "interpretation": "effective NSW is retained as an engine parameter; it is not a count of executed ionic steps and does not qualify ionic convergence"}


def _compare_printed_tensors(label: str, xml_value: Any, outcar_value: Any,
                             outcar_quantum: float) -> dict[str, Any]:
    def flatten(value: Any) -> list[float]:
        if type(value) not in (list, tuple):
            raise CandidateNativeInvalid(f"{label} tensor shape mismatch")
        if value and type(value[0]) in (list, tuple):
            return [item for row in value for item in flatten(row)]
        return [_finite(float(item), label) for item in value]
    left, right = flatten(xml_value), flatten(outcar_value)
    if len(left) != len(right) or not left:
        raise CandidateNativeInvalid(f"{label} XML/OUTCAR tensor shape mismatch")
    delta = max(abs(a - b) for a, b in zip(left, right))
    tolerance = outcar_quantum / 2.0 + 5e-9  # XML values are printed to 8 decimals.
    if delta > tolerance:
        raise CandidateNativeInvalid(f"{label} XML/OUTCAR values conflict beyond native print precision")
    return {"status": "MATCH_WITHIN_NATIVE_PRINT_PRECISION", "max_abs_difference": delta,
            "absolute_tolerance": tolerance, "outcar_print_quantum": outcar_quantum}


def _parse_tensor_section(text: str, title: str, units: str, sha: str,
                          kind: str) -> dict[str, Any] | None:
    matches = list(re.finditer(rf"(?im)^[ \t]*{re.escape(title)}[ \t]*$", text))
    if len(matches) > 1:
        raise CandidateNativeInvalid(f"duplicate native {title} sections")
    if not matches:
        return None
    pos = matches[0].end()
    lines = text[pos:].splitlines()
    rows: list[list[float]] = []
    pointer = None
    heading_line = text.count("\n", 0, matches[0].start()) + 1
    # The supported VASP text form is three lines with exactly three numbers.
    num = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*({num})\s+({num})\s+({num})\s*$")
    for off, line in enumerate(lines[:8], 1):
        if not line.strip() or re.fullmatch(r"\s*-+\s*", line):
            continue
        m = row_re.fullmatch(line)
        if not m:
            raise CandidateNativeInvalid(f"malformed {title} tensor row {len(rows)+1}")
        rows.append([_parse_float(x, f"{title} row {len(rows)+1}") for x in m.groups()])
        if len(rows) == 3:
            pointer = f"OUTCAR:{heading_line + off}"
            break
    if len(rows) != 3:
        raise CandidateNativeInvalid(f"unrecognized {title} tensor format")
    return {"kind": kind, "tensor": rows, "units": units,
            "frame": "Cartesian x,y,z", "native_sha256": sha,
            "raw_pointer": {"section": title, "relative_line": pointer}}


def _tensor_at(text: str, match: re.Match[str], title: str, sha: str,
               kind: str) -> dict[str, Any]:
    pos = match.end()
    lines = text[pos:].splitlines()
    rows: list[list[float]] = []
    heading_line = text.count("\n", 0, match.start()) + 1
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*({number})\s+({number})\s+({number})\s*$")
    for offset, line in enumerate(lines[:8], 1):
        if not line.strip() or re.fullmatch(r"\s*-+\s*", line):
            continue
        parsed = row_re.fullmatch(line)
        if not parsed:
            raise CandidateNativeInvalid(f"malformed {title} tensor row {len(rows) + 1}")
        rows.append([_parse_float(item, f"{title} row {len(rows) + 1}")
                     for item in parsed.groups()])
        if len(rows) == 3:
            return {"kind": kind, "tensor": rows, "units": "dimensionless",
                    "frame": "Cartesian x,y,z", "native_sha256": sha,
                    "raw_pointer": {"section": title,
                                    "heading_line": heading_line,
                                    "row_lines": [heading_line + i - 1 for i in range(1, offset + 1)
                                                  if lines[i - 1].strip() and row_re.fullmatch(lines[i - 1])]}}
    raise CandidateNativeInvalid(f"unrecognized {title} tensor format")


def _born_at(text: str, match: re.Match[str], sha: str,
             atom_count: int) -> dict[str, Any]:
    heading_line = text.count("\n", 0, match.start()) + 1
    tail_text = text[match.end():]
    boundary = re.search(r"(?im)^\s*INTERNAL STRAIN TENSOR FOR ION\s+\d+", tail_text)
    if boundary is None:
        raise CandidateNativeInvalid("final OUTCAR Born block lacks following internal-strain phase boundary")
    tail = tail_text[:boundary.start()].splitlines()
    atom_headers = [(i, re.fullmatch(r"\s*ion\s+(\d+)\s*", line, re.I))
                    for i, line in enumerate(tail)]
    atom_headers = [(i, m) for i, m in atom_headers if m]
    if [int(m.group(1)) for _, m in atom_headers] != list(range(1, atom_count + 1)):
        raise CandidateNativeInvalid("OUTCAR Born ion headers do not match finalpos atom order")
    born: list[list[list[float]]] = []
    row_re = re.compile(r"\s*(\d+)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*")
    row_lines: list[list[int]] = []
    for atom_index, (start, _header) in enumerate(atom_headers, 1):
        stop = atom_headers[atom_index][0] if atom_index < atom_count else len(tail)
        rows: list[list[float]] = []
        line_refs: list[int] = []
        for offset in range(start + 1, stop):
            line = tail[offset]
            if not line.strip():
                continue
            parsed = row_re.fullmatch(line)
            if not parsed:
                # The next named section is the only allowed terminator.
                if len(rows) == 3 and re.match(r"\s*[A-Z][A-Z \-()]+", line):
                    break
                raise CandidateNativeInvalid(f"malformed OUTCAR Born row for ion {atom_index}")
            row_index = int(parsed.group(1))
            if row_index != len(rows) + 1 or row_index > 3:
                raise CandidateNativeInvalid(f"OUTCAR Born row index/order invalid for ion {atom_index}")
            rows.append([_parse_float(value, f"OUTCAR Born ion[{atom_index}]")
                         for value in parsed.groups()[1:]])
            line_refs.append(heading_line + offset)
        if len(rows) != 3:
            raise CandidateNativeInvalid(f"OUTCAR Born tensor for ion {atom_index} is incomplete")
        born.append(rows)
        row_lines.append(line_refs)
    return {"kind": "born_effective_charges", "tensor": born, "units": "|e|",
            "frame": "atom-major, Cartesian polarization/displacement axes; finalpos atom order",
            "native_sha256": sha,
            "raw_pointer": {"section": "BORN EFFECTIVE CHARGES (including local field effects)",
                            "heading_line": heading_line, "row_lines": row_lines}}


def _final_dfpt_sections(text: str, sha: str, atom_count: int) -> dict[str, Any] | None:
    high_title = "MACROSCOPIC STATIC DIELECTRIC TENSOR (including local field effects in DFT)"
    ionic_title = "MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION"
    born_title = "BORN EFFECTIVE CHARGES (including local field effects) (in |e|, cummulative output)"
    highs = list(re.finditer(rf"(?im)^[ \t]*{re.escape(high_title)}[ \t]*$", text))
    borns = list(re.finditer(rf"(?im)^[ \t]*{re.escape(born_title)}[ \t]*$", text))
    ionics = list(re.finditer(rf"(?im)^[ \t]*{re.escape(ionic_title)}[ \t]*$", text))
    if not borns and not ionics:
        return None
    if len(borns) != 1 or len(ionics) != 1 or not highs:
        raise CandidateNativeInvalid("DFPT final response must have unique electronic/Born/ionic headings")
    born_match, ionic_match = borns[0], ionics[0]
    if any(m.start() > born_match.start() for m in highs):
        raise CandidateNativeInvalid("electronic dielectric heading occurs outside final response phase")
    eligible = [m for m in highs if m.start() < born_match.start()]
    if not eligible or not born_match.start() < ionic_match.start():
        raise CandidateNativeInvalid("DFPT electronic/Born/ionic response order is incomplete")
    piezo_e = list(re.finditer(r"(?im)^[ \t]*PIEZOELECTRIC TENSOR \(including local field effects\)\s+for field in x, y, z\s+\(e\s+Angst\)[ \t]*$", text))
    piezo_c = list(re.finditer(r"(?im)^[ \t]*PIEZOELECTRIC TENSOR \(including local field effects\)\s+for field in x, y, z\s+\(C/m\^2\)[ \t]*$", text))
    internal = list(re.finditer(r"(?im)^[ \t]*INTERNAL STRAIN TENSOR FOR ION\s+(\d+)\b.*$", text))
    modes = list(re.finditer(r"(?im)^[ \t]*Eigenvectors and eigenvalues of the dynamical matrix[ \t]*$", text))
    candidates = []
    for high in eligible:
        following_e = [m for m in piezo_e if high.end() < m.start() < born_match.start()]
        following_c = [m for m in piezo_c if high.end() < m.start() < born_match.start()]
        # A final response phase is structurally identified by both named
        # piezoelectric summaries, the Born table, the internal-strain/mode
        # section, and the ionic tensor in that order. A prior high tensor
        # heading followed by a new linear-response calculation is not enough.
        if len(following_e) == 1 and len(following_c) == 1:
            e, c = following_e[0], following_c[0]
            if not high.start() < e.start() < c.start() < born_match.start():
                continue
            if any(high.start() < other.start() < born_match.start() for other in highs):
                continue
            after_internal = [m for m in internal if born_match.end() < m.start() < ionic_match.start()]
            after_modes = [m for m in modes if born_match.end() < m.start() < ionic_match.start()]
            if (len(internal) == atom_count and
                    [int(m.group(1)) for m in internal] == list(range(1, atom_count + 1)) and
                    len(after_internal) == atom_count and
                    len(after_modes) == 1 and
                    all(m.start() < after_modes[0].start() for m in after_internal)):
                candidates.append(high)
    if len(candidates) != 1:
        raise CandidateNativeInvalid("final DFPT electronic/Born/ionic phase anchor is absent or ambiguous")
    high_match = candidates[0]
    high = _tensor_at(text, high_match, high_title, sha, "epsilon_high")
    ionic = _tensor_at(text, ionic_match, ionic_title, sha, "epsilon_ionic")
    born = _born_at(text, born_match, sha, atom_count)
    return {"epsilon_high": high, "epsilon_ionic": ionic, "born_effective_charges": born,
            "ordered_phase": ["electronic_dielectric", "born_effective_charges", "ionic_dielectric"]}


def _parse_elastic_section(text: str, title: str, sha: str, kind: str) -> dict[str, Any] | None:
    starts = list(re.finditer(rf"(?im)^[ \t]*{re.escape(title)}[ \t]*$", text))
    if len(starts) > 1:
        raise CandidateNativeInvalid(f"duplicate native {title} sections")
    if not starts:
        return None
    labels = ("XX", "YY", "ZZ", "XY", "YZ", "ZX")
    heading_line = text.count("\n", 0, starts[0].start()) + 1
    tail = text[starts[0].end():].splitlines()
    dir_re = re.compile(r"^\s*Direction\s+(XX\s+YY\s+ZZ\s+XY\s+YZ\s+ZX)\s*$", re.I)
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*(XX|YY|ZZ|XY|YZ|ZX)\s+({number})\s+({number})\s+({number})\s+({number})\s+({number})\s+({number})\s*$", re.I)
    direction = None
    rows: dict[str, list[float]] = {}
    row_lines: dict[str, int] = {}
    for offset, line in enumerate(tail[:20], 1):
        dm = dir_re.fullmatch(line)
        if dm:
            direction = tuple(dm.group(1).upper().split())
            if direction != labels:
                raise CandidateNativeInvalid(f"unexpected elastic column order {direction}")
            continue
        rm = row_re.fullmatch(line)
        if rm:
            label = rm.group(1).upper()
            if label in rows:
                raise CandidateNativeInvalid(f"duplicate elastic row {label}")
            rows[label] = [_parse_float(x, f"{title}:{label}") for x in rm.groups()[1:]]
            row_lines[label] = heading_line + offset - 1
            continue
        if rows and line.strip() and not line.strip().startswith("-"):
            break
    if direction is None or tuple(rows) != labels:
        raise CandidateNativeInvalid(f"incomplete or unrecognized {title} 6x6 table")
    return {"kind": kind, "tensor": [rows[label] for label in labels], "units": "kBar",
            "native_sha256": sha, "raw_pointer": {"section": title,
            "heading_line": heading_line, "row_lines": row_lines,
            "native_voigt_order": list(labels)}}


def _outcar_observations(data: bytes, sha: str, incar: dict[str, tuple[str, str]],
                         atom_count: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        text = data.decode("ascii")
    except UnicodeError as exc:
        raise CandidateNativeInvalid("OUTCAR is not ASCII in the supported parser") from exc
    observations: list[dict[str, Any]] = []
    warnings = []
    reached = list(re.finditer(r"(?im)^\s*-+\s*aborting loop because EDIFF is reached\s*-+\s*$", text))
    not_reached = list(re.finditer(r"(?im)^\s*(?:WARNING:.*EDIFF.*not reached|reached NELM.*without reaching EDIFF).*?$", text))
    if reached and not_reached:
        state = "CONFLICTING_NATIVE_CONVERGENCE_MARKERS"
        warnings.extend({"kind": "EDIFF_REACHED", "line": text.count("\n", 0, m.start()) + 1} for m in reached)
        warnings.extend({"kind": "EDIFF_NOT_REACHED_OR_NELM", "line": text.count("\n", 0, m.start()) + 1} for m in not_reached)
    elif reached:
        state = "EDIFF_REACHED_MARKER_OBSERVED"
        warnings.extend({"kind": "EDIFF_REACHED", "line": text.count("\n", 0, m.start()) + 1} for m in reached)
    elif not_reached:
        state = "NELM_OR_EDIFF_WARNING_OBSERVED"
        warnings.extend({"kind": "EDIFF_NOT_REACHED_OR_NELM", "line": text.count("\n", 0, m.start()) + 1} for m in not_reached)
    else:
        state = "NO_RECOGNIZED_ELECTRONIC_TERMINATION_MARKER"
    observations.append({"field": "convergence.electronic_termination_observation", "value": state,
                         "units": "categorical observation", "native_sha256": sha,
                         "raw_pointer": warnings})
    stress = _force_on_cell_stress(text, sha)
    observations.append({"field": "stress.force_on_cell", "value": stress["value"],
                         "units": "kBar", "frame": "native VASP XX YY ZZ XY YZ ZX; compressive positive",
                         "native_sha256": sha, "raw_pointer": stress["raw_pointer"],
                         "native_tokens": stress["tokens"], "availability": stress["availability"]})
    ionic_relaxation = _ionic_relaxation_termination(text, sha, incar)
    observations.append({"field": "convergence.ionic_relaxation_termination",
                         "value": ionic_relaxation["value"], "units": "categorical observation",
                         "native_sha256": sha, "raw_pointer": ionic_relaxation["raw_pointer"],
                         "availability": ionic_relaxation["availability"]})
    # Parse only section names that unambiguously distinguish total and
    # clamped-ion elastic responses. No tensor stability/comparison is done.
    for title, label in (("TOTAL ELASTIC MODULI (kBar)", "relaxed_ion_total"),
                         ("ELASTIC MODULI (kBar)", "unqualified_or_clamped_native")):
        parsed = _parse_elastic_section(text, title, sha, label)
        if parsed is not None:
            matrix = parsed["tensor"]
            public_order = (0, 1, 2, 4, 5, 3)  # VASP XX YY ZZ XY YZ ZX -> XX YY ZZ YZ ZX XY
            reordered = [[matrix[i][j] for j in public_order] for i in public_order]
            gpa = [[_finite(x * 0.1, f"elastic {label}") for x in row] for row in reordered]
            observations.append({"field": f"elastic.{label}", "value": gpa, "units": "GPa",
                                 "frame": "Cartesian engineering Voigt [xx,yy,zz,yz,xz,xy]",
                                 "native_sha256": sha, "raw_pointer": parsed["raw_pointer"],
                                 "native_units": "kBar", "conversion": "0.1 GPa/kBar"})
    dielectric = []
    final_response = _final_dfpt_sections(text, sha, atom_count) if atom_count is not None else None
    if final_response is not None:
        for label in ("epsilon_high", "epsilon_ionic"):
            parsed = final_response[label]
            dielectric.append(parsed)
            observations.append({"field": f"dielectric.{label}", "value": parsed["tensor"],
                                 "units": "dimensionless", "frame": parsed["frame"],
                                 "native_sha256": sha, "raw_pointer": parsed["raw_pointer"]})
        parsed_born = final_response["born_effective_charges"]
        observations.append({"field": "born.effective_charges_outcar", "value": parsed_born["tensor"],
                             "units": "|e|", "frame": parsed_born["frame"],
                             "native_sha256": sha, "raw_pointer": parsed_born["raw_pointer"]})
    else:
        for title, label in (("MACROSCOPIC STATIC DIELECTRIC TENSOR (including local field effects in DFT)", "epsilon_high"),
                             ("MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION", "epsilon_ionic")):
            parsed = _parse_tensor_section(text, title, "dimensionless", sha, label)
            if parsed is not None:
                dielectric.append(parsed)
                observations.append({"field": f"dielectric.{label}", "value": parsed["tensor"],
                                     "units": "dimensionless", "frame": parsed["frame"],
                                     "native_sha256": sha, "raw_pointer": parsed["raw_pointer"]})
    if len(dielectric) == 2:
        static = [[_finite(dielectric[0]["tensor"][i][j] + dielectric[1]["tensor"][i][j], "static dielectric sum")
                   for j in range(3)] for i in range(3)]
        observations.append({"field": "dielectric.epsilon_static_observed_sum", "value": static,
                             "units": "dimensionless", "frame": "Cartesian x,y,z",
                             "native_sha256": sha,
                             "raw_pointer": ([dielectric[0]["raw_pointer"], dielectric[1]["raw_pointer"]]),
                             "response_phase": (final_response["ordered_phase"] if final_response else None),
                             "derivation": "componentwise sum of same-phase named electronic and ionic sections; observation only"})
    has_lepsilon = _parse_incar_value("LEPSILON", incar.get("LEPSILON", ("F", "INCAR:absent")))
    response = "NOT_REQUESTED_BY_INCAR" if has_lepsilon is False else (
        "REQUESTED_AND_BOTH_SECTIONS_OBSERVED" if len(dielectric) == 2
        else "REQUESTED_BUT_RESPONSE_SECTIONS_NOT_BOTH_OBSERVED")
    return observations, {"electronic_termination": state, "warning_markers": warnings,
                          "elastic_total_observed": any(o["field"] == "elastic.relaxed_ion_total" for o in observations),
                          "elastic_unqualified_or_clamped_observed": any(o["field"] == "elastic.unqualified_or_clamped_native" for o in observations),
                          "dielectric_response_observation": response,
                          "final_dfpt_response": final_response}


def _force_on_cell_stress(text: str, sha: str) -> dict[str, Any]:
    """Observe the last FORCE-on-cell stress row in native VASP print order."""
    starts = list(re.finditer(
        r"(?im)^\s*FORCE on cell\s*=-STRESS in cart\. coord\.\s*units\s*\(eV\):\s*$", text))
    if not starts:
        return {"value": None, "tokens": None, "raw_pointer": None,
                "availability": "NOT_OBSERVED_NO_FORCE_ON_CELL_SECTION"}
    heading = starts[-1]
    tail = text[heading.end():].splitlines()
    rows = [(offset, line) for offset, line in enumerate(tail[:32], 1)
            if re.match(r"^\s*in kB\b", line)]
    if len(rows) != 1:
        raise CandidateNativeInvalid("final FORCE-on-cell section lacks one unique in kB stress row")
    offset, row = rows[0]
    match = re.fullmatch(r"\s*in kB\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*", row)
    if match is None:
        raise CandidateNativeInvalid("final FORCE-on-cell in kB row must contain six native tokens")
    tokens = list(match.groups())
    values = [_parse_float(token, "OUTCAR FORCE-on-cell in kB") for token in tokens]
    line = text.count("\n", 0, heading.start()) + 1 + offset
    return {"value": values, "tokens": tokens,
            "raw_pointer": {"section_heading_line": text.count("\n", 0, heading.start()) + 1,
                            "stress_row_line": line, "section": "FORCE on cell =-STRESS in cart. coord."},
            "availability": "OBSERVED_FINAL_FORCE_ON_CELL"}


def _ionic_relaxation_termination(text: str, sha: str,
                                  incar: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Observe the native ionic optimizer stop and the INCAR mode that owns it."""
    marker = list(re.finditer(
        r"(?im)^\s*reached required accuracy\s*-\s*stopping structural energy minimisation\s*$", text))
    normal = list(re.finditer(r"(?im)^\s*General timing and accounting informations for this job:\s*$", text))
    exhausted = list(re.finditer(r"(?im)^.*(?:reached NELM|without reaching EDIFF|EDIFF is not reached).*$", text))
    values = {key: _parse_incar_value(key, incar.get(key, ("", "INCAR:absent")))
              for key in ("IBRION", "ISIF", "NSW")}
    valid_mode = (values["IBRION"] == 2 and values["ISIF"] == 2 and
                  type(values["NSW"]) in (int, float) and values["NSW"] > 0)
    observed = valid_mode and len(marker) == 1 and len(normal) == 1 and not exhausted
    availability = "OBSERVED_RELAXED_ION_OPTIMIZER_TERMINATION" if observed else "NOT_OBSERVED_RELAXED_ION_OPTIMIZER_TERMINATION"
    def line(match: re.Match[str]) -> int:
        return text.count("\n", 0, match.start()) + 1
    return {"value": "OBSERVED_RELAXED_ION_CONVERGENCE" if observed else "NOT_OBSERVED",
            "availability": availability,
            "raw_pointer": {"ibrion_isif_nsw": values,
                            "ionic_optimizer_stop_lines": [line(m) for m in marker],
                            "normal_termination_lines": [line(m) for m in normal],
                            "electronic_exhaustion_lines": [line(m) for m in exhausted],
                            "native_sha256": sha}}


def _core_1s_observation(data: bytes, sha: str, species_order: list[str]) -> dict[str, Any]:
    """Return the last complete native 1s site table, or an explicit absence."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise CandidateNativeInvalid("OUTCAR core source is not ASCII") from exc
    heads = [idx for idx, line in enumerate(lines)
             if "the core state eigenenergies are" in line.lower()]
    if not heads:
        return {"value": None, "availability": "NOT_OBSERVED_NO_CORE_SECTION", "raw_pointer": None}
    head = heads[-1]
    end = next((idx for idx in range(head + 1, len(lines))
                if re.match(r"^\s*E-fermi\b", lines[idx], flags=re.IGNORECASE)), None)
    if end is None:
        raise CandidateNativeInvalid("final OUTCAR core eigenenergy section lacks E-fermi terminator")
    records: dict[int, dict[str, Any]] = {}
    declaration = re.compile(r"^\s*(\d+)\s*-\s+1s\b(.*)$", flags=re.IGNORECASE)
    for idx in range(head + 1, end):
        match = declaration.match(lines[idx])
        if not match:
            continue
        site = int(match.group(1))
        tokens = match.group(2).split()
        if not tokens or site < 1 or site > len(species_order):
            raise CandidateNativeInvalid("malformed or out-of-order OUTCAR 1s core site row")
        if site in records:
            raise CandidateNativeInvalid("duplicate OUTCAR 1s core site row")
        value = _parse_float(tokens[0], f"OUTCAR:line {idx + 1} 1s core energy")
        records[site] = {"site_index_1based": site, "species": species_order[site - 1],
                         "energy_eV": value, "energy_token_eV": tokens[0],
                         "raw_line": idx + 1}
    if set(records) != set(range(1, len(species_order) + 1)):
        raise CandidateNativeInvalid("final OUTCAR core section lacks exactly one 1s energy per atom")
    return {"value": [records[idx] for idx in range(1, len(species_order) + 1)],
            "availability": "OBSERVED_COMPLETE_SITE_TABLE",
            "raw_pointer": {"section_heading_line": head + 1,
                            "site_lines": [records[idx]["raw_line"] for idx in range(1, len(species_order) + 1)],
                            "terminator_line": end + 1}}


def observe_native_run(run_dir: str | os.PathLike[str],
                       trusted_expected_sha256: dict[str, str]) -> dict[str, Any]:
    """Extract observations from a seven-file bounded snapshot.

    `trusted_expected_sha256` must come from an independently authenticated
    snapshot. Its values are never learned from candidate manifests or receipts.
    The returned object is explicitly non-scoring and is not a gate receipt.
    """
    if type(trusted_expected_sha256) is not dict or set(trusted_expected_sha256) != set(FILES):
        raise EnvironmentInvalid("trusted expected hashes must name exactly the seven adapter inputs")
    for name, digest in trusted_expected_sha256.items():
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise EnvironmentInvalid(f"invalid trusted SHA-256 for {name}")
    payload = {name: _read_stable(Path(run_dir), name) for name in FILES}
    hashes = {name: _sha(data) for name, data in payload.items()}
    mismatch = [name for name in FILES if hashes[name] != trusted_expected_sha256[name]]
    if mismatch:
        raise EnvironmentInvalid(f"snapshot hash differs from authenticated context: {', '.join(mismatch)}")
    receipt = _strict_json(payload["execution-receipt.json"], "execution receipt")
    manifest = _strict_json(payload["input-manifest.json"], "input manifest")
    if type(receipt) is not dict or type(manifest) is not dict:
        raise EnvironmentInvalid("receipt and input manifest must be JSON objects")
    if receipt.get("input_manifest_sha256") != hashes["input-manifest.json"]:
        raise EnvironmentInvalid("execution receipt does not bind input manifest bytes")
    actual_inputs = receipt.get("actual_run_inputs")
    native_outputs = receipt.get("native_output_sha256")
    if type(actual_inputs) is not dict or type(native_outputs) is not dict:
        raise EnvironmentInvalid("receipt lacks native input/output hash maps")
    for name in ("POSCAR", "INCAR", "KPOINTS"):
        if actual_inputs.get(name) != hashes[name]:
            raise EnvironmentInvalid(f"receipt does not bind {name}")
    for name in ("OUTCAR", "vasprun.xml"):
        if native_outputs.get(name) != hashes[name]:
            raise EnvironmentInvalid(f"receipt does not bind native {name}")
    manifest_files = manifest.get("files")
    if type(manifest_files) is not dict:
        raise EnvironmentInvalid("input manifest lacks its declared file hash map")
    for name in ("POSCAR", "INCAR", "KPOINTS"):
        if manifest_files.get(name) != hashes[name]:
            raise EnvironmentInvalid(f"input manifest does not bind {name}")
    if receipt.get("case_id") != manifest.get("case_id") or receipt.get("stage") != manifest.get("stage"):
        raise EnvironmentInvalid("execution receipt and input manifest identity/stage differ")
    incar = _incar(payload["INCAR"])
    xml_obs, xml_meta = _xml_observations(payload["vasprun.xml"], hashes["vasprun.xml"], set(incar))
    method = manifest.get("method")
    if type(method) is not dict:
        raise EnvironmentInvalid("input manifest lacks method descriptor")
    layers: dict[str, dict[str, tuple[str, str | None]]] = {
        "INCAR": {key: (raw, None) for key, (raw, _loc) in incar.items()},
        "vasprun.xml/incar": {key: (raw, xml_meta["xml_incar_types"].get(key))
                               for key, raw in xml_meta["xml_incar"].items()},
        "vasprun.xml/parameters": xml_meta["effective_parameters"],
    }
    nsw_transition = _proven_ibrion6_nsw_expansion(
        layers, manifest, receipt, xml_meta["effective_parameter_pointers"],
        {key: source for key, (_raw, source) in incar.items()})
    normalized: dict[str, Any] = {}
    layer_values: dict[str, dict[str, Any]] = {name: {} for name in layers}
    for layer_name, entries in layers.items():
        for key, (raw, declared_type) in entries.items():
            value = _normalized_tag(key, raw, declared_type, layer_name)
            layer_values[layer_name][key] = value
            if key in normalized:
                prior = normalized[key]
                numeric_pair = (type(prior) in (int, float) and type(value) in (int, float))
                same = (prior == value) if numeric_pair else (type(prior) is type(value) and prior == value)
                if not same:
                    if key == "NSW" and nsw_transition is not None:
                        normalized[key] = 61
                        continue
                    raise CandidateNativeInvalid(
                        f"conflicting {key} values across present input/effective layers"
                    )
            normalized[key] = value
    gga = normalized.get("GGA")
    if type(gga) is not str or not gga:
        raise CandidateNativeInvalid("INCAR GGA method is missing")
    # GGA=PE alone does not identify the functional. Require the effective
    # hybrid controls to explicitly exclude the HSE/HF contribution.
    if (gga.upper() == "PE" and normalized.get("LHFCALC") is False and
            normalized.get("AEXX") == 0.0 and normalized.get("HFSCREEN") == 0.0):
        xc = "PBE"
    else:
        xc = "UNKNOWN"
    response_requested = normalized.get("LEPSILON", False)
    if type(response_requested) is not bool:
        raise CandidateNativeInvalid("LEPSILON did not normalize to a logical value")
    response_sources = [name for name, entries in layers.items() if "LEPSILON" in entries]
    response_request_source = ", ".join(response_sources) if response_sources else \
        "not present in INCAR or vasprun.xml; no gate inferred"
    outcar_incar = dict(incar)
    outcar_incar["LEPSILON"] = ("T" if response_requested else "F", response_request_source)
    out_obs, out_meta = _outcar_observations(payload["OUTCAR"], hashes["OUTCAR"],
                                             outcar_incar, len(xml_meta["response"].get("born_effective_charges") or [])
                                             or len(next(o["value"] for o in xml_obs if o["field"] == "structure.species_order")))
    try:
        submitted_geometry = _poscar_initial_geometry(payload["POSCAR"], hashes["POSCAR"])
    except CandidateNativeInvalid:
        # Keep the generic adapter usable for native POSCAR profiles outside
        # this bounded VASP5 parser; such a run simply cannot supply these
        # optional geometry observations.
        submitted_geometry = None
    species_order = (submitted_geometry["species_order"] if submitted_geometry is not None else
                     next(o["value"] for o in xml_obs if o["field"] == "structure.species_order"))
    core_levels = _core_1s_observation(payload["OUTCAR"], hashes["OUTCAR"], species_order)
    out_obs.append({"field": "core.site_1s_eigenenergies", "value": core_levels["value"],
                    "units": "eV", "frame": "site order of submitted POSCAR species",
                    "native_sha256": hashes["OUTCAR"], "raw_pointer": core_levels["raw_pointer"],
                    "availability": core_levels["availability"]})
    response_checks: dict[str, Any] = {}
    if response_requested:
        xml_response = xml_meta["response"]
        native_response = out_meta["final_dfpt_response"]
        if any(xml_response.get(key) is None for key in
               ("epsilon_high", "epsilon_ionic", "born_effective_charges")):
            raise CandidateNativeInvalid("LEPSILON response lacks final-calculation XML dielectric/Born arrays")
        if native_response is None:
            raise CandidateNativeInvalid("LEPSILON response lacks unique ordered final OUTCAR dielectric/Born/ionic block")
        response_checks = {
            "epsilon_high": _compare_printed_tensors("epsilon_high", xml_response["epsilon_high"],
                                                       native_response["epsilon_high"]["tensor"], 1e-6),
            "epsilon_ionic": _compare_printed_tensors("epsilon_ionic", xml_response["epsilon_ionic"],
                                                        native_response["epsilon_ionic"]["tensor"], 1e-6),
            "born_effective_charges": _compare_printed_tensors(
                "born_effective_charges", xml_response["born_effective_charges"],
                native_response["born_effective_charges"]["tensor"], 1e-5),
        }
    stage_kind = manifest.get("stage_kind")
    observations = xml_obs + out_obs
    for field_name, value, units, frame, pointer in (
            ("structure.submitted_lattice", submitted_geometry["lattice"] if submitted_geometry else None,
             "angstrom", "Cartesian lattice vectors as rows", submitted_geometry["raw_pointer"] if submitted_geometry else None),
            ("structure.submitted_fractional_positions", submitted_geometry["fractional_positions"] if submitted_geometry else None,
             "fractional", "submitted POSCAR cell", submitted_geometry["raw_pointer"] if submitted_geometry else None),
            ("structure.submitted_species_order", submitted_geometry["species_order"] if submitted_geometry else None,
             "element labels", "submitted POSCAR site order", submitted_geometry["raw_pointer"] if submitted_geometry else None)):
        observations.append({"field": field_name, "value": value, "units": units, "frame": frame,
                             "native_sha256": hashes["POSCAR"], "raw_pointer": pointer,
                             "availability": "OBSERVED" if submitted_geometry else "UNSUPPORTED_POSCAR_PROFILE"})
    geometry_reference: dict[str, Any] = {"status": "NOT_APPLICABLE_TO_STAGE"}
    if stage_kind == "elastic" and normalized.get("IBRION") == 6:
        initial_geometry = xml_meta.get("initial_structure")
        if initial_geometry is None:
            raise CandidateNativeInvalid("receipt-bound IBRION=6 elastic response lacks XML initialpos geometry")
        submitted_geometry = _poscar_initial_geometry(payload["POSCAR"], hashes["POSCAR"])
        geometry_reference = _compare_parent_geometries(submitted_geometry, initial_geometry, manifest)
        final_positions = next(item for item in xml_obs if item["field"] == "structure.fractional_positions")
        geometry_reference["finalpos_observation"] = {
            "status": "PRESERVED_AS_FINAL_OUTPUT_NOT_PARENT_REFERENCE",
            "value": final_positions["value"],
            "native_sha256": final_positions["native_sha256"],
            "raw_pointer": final_positions["raw_pointer"],
        }
        observations.append({"field": "structure.response_parent_geometry_validation",
                             "value": geometry_reference,
                             "units": "dimensionless comparison summary",
                             "frame": "submitted POSCAR vs vasprun initialpos; finalpos retained separately",
                             "native_sha256": hashes["vasprun.xml"],
                             "raw_pointer": {"POSCAR": submitted_geometry["raw_pointer"],
                                             "vasprun.xml": initial_geometry["raw_pointer"]}})
    if stage_kind == "elastic":
        if not out_meta["elastic_total_observed"]:
            raise CandidateNativeInvalid("elastic native output lacks the complete TOTAL 6x6 elastic tensor")
        if out_meta["elastic_unqualified_or_clamped_observed"]:
            raise CandidateNativeInvalid("elastic native output contains an unqualified/clamped elastic tensor")
    if not any(item["field"] == "elastic.relaxed_ion_total" for item in observations):
        observations.append({"field": "elastic.relaxed_ion_total", "value": None,
                             "units": "GPa", "frame": "Cartesian engineering Voigt",
                             "native_sha256": hashes["OUTCAR"],
                             "raw_pointer": None, "availability": "SECTION_NOT_PRESENT"})
    if not response_requested:
        for key in ("epsilon_high", "epsilon_ionic", "epsilon_static"):
            observations.append({"field": f"dielectric.{key}", "value": None,
                                 "units": "dimensionless", "frame": "Cartesian x,y,z",
                                 "native_sha256": hashes["OUTCAR"], "raw_pointer": "INCAR:LEPSILON=F",
                                 "availability": "RESPONSE_NOT_REQUESTED"})
    elif out_meta["dielectric_response_observation"] == "REQUESTED_BUT_RESPONSE_SECTIONS_NOT_BOTH_OBSERVED":
        pass
    conv = xml_meta["convergence"]
    conv["electronic"] = out_meta["electronic_termination"]
    conv["ionic"] = "NOT_RUN_BY_NSW_ZERO" if incar.get("NSW", (None,))[0] == "0" else "NOT_INDEPENDENTLY_QUALIFIED"
    # Record parsed INCAR values and source locations without using them as gates.
    incar_values = {k: {"value": _parse_incar_value(k, v), "raw": v[0], "raw_type": None, "source": v[1]}
                    for k, v in sorted(incar.items())}
    return {
        "schema": SCHEMA,
        "result_class": "NATIVE_OBSERVATIONS_ONLY_NOT_SCIENCE_VERIFIED",
        "science_gate_released": False,
        "scoring_status": "NOT_EVALUATED",
        "source_hashes": hashes,
        "provenance": {
            "receipt_sha256": hashes["execution-receipt.json"],
            "manifest_sha256": hashes["input-manifest.json"],
            "receipt_status_raw": receipt.get("status"),
            "receipt_exit_code_raw": receipt.get("exit_code"),
            "slurm_job_id_raw": receipt.get("slurm_job_id"),
            "method_descriptor_raw": method,
            "paw_identity_source": "input-manifest metadata only; POTCAR body was not read",
            "trusted_context_required": True,
        },
        "method": {"engine": "VASP", "engine_version": xml_meta["vasp_version"],
                   "xc_from_incar": xc, "gga_lexeme": gga,
                   "method_manifest_xc_raw": method.get("xc"),
                   "paw_family_manifest_raw": method.get("paw_family"),
                   "method_consistency": "OBSERVATION_ONLY_NOT_AUTHENTICATED"},
        "incar_observations": incar_values,
        "xml_parameter_observations": xml_meta["xml_parameter_sources"],
        "native_dimensions": {k: xml_meta[k] for k in ("kpoint_count", "spin_count", "band_count")},
        "geometry_reference": geometry_reference,
        "observations": observations,
        "termination_observations": {"electronic": conv["electronic"], "ionic": conv["ionic"],
                                     "outcar_warning_markers": out_meta["warning_markers"],
                                     "receipt_is_not_a_science_judgment": True},
        "response_availability": {"lepsilon_requested": response_requested,
                                   "lepsilon_request_source": response_request_source,
                                   "elastic_total": "OBSERVED" if out_meta["elastic_total_observed"] else "NOT_OBSERVED",
                                   "dielectric": ("NOT_REQUESTED_BY_NATIVE_EFFECTIVE_PARAMETER" if not response_requested
                                                  else out_meta["dielectric_response_observation"])},
        "native_control_layers": {
            "values_by_source": layer_values,
            "nsw_effective_expansion": nsw_transition,
            "ionic_convergence_interpretation": (
                "NOT_INFERRED_FROM_EFFECTIVE_NSW; native OUTCAR/XML trajectory still required"
                if nsw_transition else conv["ionic"]),
        },
        "response_print_precision_crosschecks": response_checks,
        "unsupported_method": None if xc == "PBE" else {"status": "ENV_INVALID", "method": xc},
    }
CASE05_ADAPTER_88B0C898

cat > "$WORKDIR/native_solve.py" <<'CASE05_SOLVER_REUSE_NATIVE'
#!/usr/bin/env python3
"""Rebuild Case 05 outputs from fresh candidate-owned native evidence.

This module contains no reference parameters. Its parser is the source-bound
observation adapter; all reported quantities below are recomputed from native
cells, OUTCAR stresses/cores, vasprun spectra, and response tensors.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import numpy as np

HERE = Path(__file__).resolve().parent
NATIVE_FILES = ("POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
                "execution-receipt.json", "input-manifest.json")
NATIVE_BYTE_CAPS = {"POSCAR": 2*1024*1024, "INCAR": 1024*1024, "KPOINTS": 1024*1024,
                    "OUTCAR": 32*1024*1024, "vasprun.xml": 64*1024*1024,
                    "execution-receipt.json": 2*1024*1024, "input-manifest.json": 2*1024*1024}
CONTEXT_FIELDS = {"schema", "task_id", "attempt_id", "nonce", "verifier_sha256",
                  "remote_evidence_manifest_sha256", "remote_evidence_scope"}
MANIFEST_FIELDS = {"schema", "attempt_id", "collection_status", "files"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
JOB_RE = re.compile(r"^[0-9]{1,32}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
DEFORMATION_COMPONENTS = ("xx", "yy", "zz", "yz", "xz", "xy")
K_E_EV_ANGSTROM = 14.399645478
C_F_THz_PER_SQRT_EV_ANG2_AMU = 15.63330424


class Stop(RuntimeError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(path: Path, cap: int = 16 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise Stop(f"unsafe/missing JSON input: {path.name}")
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Stop(f"invalid JSON input: {path.name}") from exc


def load_adapter():
    path = HERE / "native_observation_adapter_v1.py"
    raw = path.read_bytes()
    spec = importlib.util.spec_from_file_location("case05_eval_native_adapter", path)
    if spec is None or spec.loader is None:
        raise Stop("native observation adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def native_rel_parts(job_id, rel):
    if type(job_id) is not str or not JOB_RE.fullmatch(job_id):
        raise Stop("native evidence job_id must be a numeric string")
    parts = PurePosixPath(rel).parts if type(rel) is str else ()
    if len(parts) != 5 or parts[0] != "jobs" or parts[1] != job_id or parts[2] != "native" or not RUN_RE.fullmatch(parts[3]) or parts[4] not in NATIVE_FILES:
        raise Stop("native evidence path does not join its original job_id")
    return parts


def load_inputs():
    root=Path(os.environ.get("CASE05_NATIVE_CANDIDATE_DIR", "/app/candidate-native"))
    runs_root=root/"native"/"runs"
    adapter=load_adapter()
    manifest, _=strict_json(root/"native"/"manifest.json", 2*1024*1024)
    observations={}; groups={}; all_sources=[]
    for linked in manifest.get("runs", []):
        run_id=linked["run_id"]; run_dir=runs_root/run_id
        files={name:(run_dir/name).read_bytes() for name in NATIVE_FILES}
        meta=json.loads(files["input-manifest.json"])
        receipt=json.loads(files["execution-receipt.json"]); job=receipt["slurm_job_id"]
        rows={}; expected={}
        for name,raw in files.items():
            digest=sha(raw); rel=f"jobs/{job}/native/{run_id}/{name}"
            source=sha((job+"\0"+rel+"\0"+digest).encode())
            rows[name]={"job_id":job,"path":rel,"bytes":len(raw),"sha256":digest,"source_id":source}
            expected[name]=digest; all_sources.append(source)
        native=adapter.observe_native_run(run_dir, expected)
        fields={row["field"]:row for row in native["observations"]}
        observations[run_id]={"run_id":run_id,"native":native,"fields":fields,"files":files,
                              "rows":rows,"meta":meta,"source_ids":[rows[n]["source_id"] for n in NATIVE_FILES]}
        groups[run_id]={"job_id":job,"files":files,"rows":rows}
    proof_raw=(root/"native"/"deformation-mirror-proof.json").read_bytes()
    proof=json.loads(proof_raw)
    mirror_runs={}
    roles={"deformation_bulk":"bulk","deformation_xy_0050_m":"xy_m_0.005","deformation_xy_0050_p":"xy_p_0.005"}
    for row in proof["runs"]:
        mirror_runs[roles[row["run_id"]]]=row
    return {"context":{},"manifest":{},"manifest_raw":b"","evidence_root":root,
            "groups":groups,"observations":observations,"all_sources":sorted(all_sources),
            "mirror":{"runs":mirror_runs},"mirror_receipt":{},"proof_root":root/"native",
            "proof_manifest":{},"proof_files":{"deformation-mirror-proof.json":proof_raw},
            "proof_manifest_sha256":sha(proof_raw)}

def field(record, name, value_required=True):
    row = record["fields"].get(name)
    if type(row) is not dict or (value_required and row.get("value") is None):
        raise Stop(f"native observation missing: {name}")
    return row


def all_ids(records):
    return sorted({sid for record in records for sid in record["source_ids"]})


def inv3(a):
    return np.linalg.inv(np.asarray(a, dtype=float))


def strain(bulk, current):
    f = np.asarray(current, float).T @ inv3(np.asarray(bulk, float).T)
    return 0.5 * (f.T @ f - np.eye(3))


def coord(e, name):
    ij = {"xx": (0, 0), "yy": (1, 1), "zz": (2, 2), "yz": (1, 2), "xz": (0, 2), "xy": (0, 1)}[name]
    return float(e[ij]) if ij[0] == ij[1] else float(2 * e[ij])


def endpoint(rows, lattice_key):
    base = min(rows, key=lambda r: sum(np.linalg.norm(strain(r["lattice"], o["lattice"])) ** 2 for o in rows))
    out = []
    for row in rows:
        e = strain(base["lattice"], row["lattice"])
        coords = {n: coord(e, n) for n in DEFORMATION_COMPONENTS}
        active = [(n, v) for n, v in coords.items() if abs(v) > 5e-5]
        if len(active) != 1 or any(abs(coords[n]) > 1e-5 for n in coords if n != active[0][0]):
            continue
        name, value = active[0]
        out.append({**row, "component": name, "coordinate": value,
                    "amplitude": round(abs(value), 4)})
    return base, out


def stress_tensor(raw):
    # OUTCAR force-on-cell is compressive-positive in kBar, order XX YY ZZ XY YZ ZX.
    xx, yy, zz, xy, yz, zx = [-0.1 * float(x) for x in raw]
    return np.array([[xx, xy, zx], [xy, yy, yz], [zx, yz, zz]])


def second_piola(raw, bulk_lattice, lattice):
    f = np.asarray(lattice).T @ inv3(np.asarray(bulk_lattice).T)
    return float(np.linalg.det(f)) * np.linalg.inv(f) @ stress_tensor(raw) @ np.linalg.inv(f).T


def elastic_fit(records):
    rows = []
    for r in records:
        if r["meta"].get("stage_kind") != "elastic_finite_strain":
            continue
        stress = field(r, "stress.force_on_cell")["value"]
        lattice = field(r, "structure.submitted_lattice")["value"]
        end = field(r, "convergence.ionic_relaxation_termination")["value"]
        if end != "OBSERVED_RELAXED_ION_CONVERGENCE":
            raise Stop("elastic fit source is not a native relaxed-ion calculation")
        rows.append({"r": r, "stress": stress, "lattice": lattice})
    if len(rows) != 25:
        raise Stop("expected source-complete 25-run relaxed-ion central-strain archive")
    bulk, ends = endpoint(rows, "lattice")
    pairs = {}
    for row in ends:
        pairs.setdefault((row["component"], row["amplitude"]), {})[1 if row["coordinate"] > 0 else -1] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()) or len(pairs) != 12:
        raise Stop("relaxed-ion strain endpoints do not form all six signed pairs at two amplitudes")
    matrices = {}
    amp_ids = {}
    for (name, amp), pair in pairs.items():
        minus, plus = pair[-1], pair[1]
        dx = plus["coordinate"] - minus["coordinate"]
        col = (second_piola(plus["stress"], bulk["lattice"], plus["lattice"]) -
               second_piola(minus["stress"], bulk["lattice"], minus["lattice"])) / dx
        mat = matrices.setdefault(amp, np.zeros((6, 6)))
        mat[:, DEFORMATION_COMPONENTS.index(name)] = [col[0, 0], col[1, 1], col[2, 2], col[1, 2], col[0, 2], col[0, 1]]
        amp_ids.setdefault(amp, set()).update(
            sid for side in (-1, 1) for sid in pair[side]["r"]["source_ids"])
    for source_ids in amp_ids.values():
        source_ids.update(bulk["r"]["source_ids"])
    amps = sorted(matrices)
    cmat_raw = np.mean([matrices[a] for a in amps], axis=0)
    symmetry_residual = float(np.max(np.abs(cmat_raw-cmat_raw.T)))
    # The elastic energy Hessian has major symmetry. Retain the raw residual
    # in the report and emit the source-derived symmetric part as C.
    cmat = 0.5 * (cmat_raw + cmat_raw.T)
    source = all_ids([r["r"] for r in rows])
    return cmat, matrices, amps, source, rows, {a: sorted(v) for a, v in amp_ids.items()}, symmetry_residual


def deformation(records, c_h_sign):
    rows = []
    for r in records:
        if r["meta"].get("stage_kind") != "deformation":
            continue
        g = field(r, "band.gamma_spectrum")["value"]
        bands = g["spins"][0]["bands"]
        if len(bands) < 10 or any(abs(float(bands[i]["occupation"]) - 1) > 1e-6 for i in (6, 7, 8)) or abs(float(bands[9]["occupation"])) > 1e-6:
            raise Stop("deformation Gamma edge is not the occupied triplet plus empty band")
        core = field(r, "core.site_1s_eigenenergies")["value"]
        if len(core) != 2 or [x["species"] for x in core] != ["Ga", "As"]:
            raise Stop("deformation native core rows do not follow Ga,As site order")
        lattice = field(r, "structure.submitted_lattice")["value"]
        cbm = field(r, "band.cbm")["value"]
        vbm = field(r, "band.vbm")["value"]
        if cbm["kpoint_index_0based"] != g["kpoint_index_0based"] or vbm["kpoint_index_0based"] != g["kpoint_index_0based"]:
            raise Stop("Gamma valence/conduction states do not match all-k band extrema")
        rows.append({"r": r, "gamma": g, "bands": bands, "core": core, "lattice": lattice,
                     "mean_core": sum(float(x["energy_eV"]) for x in core) / len(core)})
    if len(rows) != 25:
        raise Stop("expected all 25 source-bound deformation runs")
    bulk, ends = endpoint(rows, "lattice")
    pairs = {}
    for row in ends:
        pairs.setdefault((row["component"], row["amplitude"]), {})[1 if row["coordinate"] > 0 else -1] = row
    if len(pairs) != 12 or any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise Stop("deformation endpoints lack six-component/two-amplitude signed pairs")
    core_gauge = {"by_run": {}, "species_spread_is_diagnostic": True}
    for row in rows:
        core_gauge["by_run"][row["r"]["run_id"]] = {
            "mean_all_atom_1s_eV": row["mean_core"],
            "Ga_minus_As_core_eV": float(row["core"][0]["energy_eV"]) - float(row["core"][1]["energy_eV"])}
    electron_by_amp = {}
    electron_species_by_amp = {}
    hole_by_amp = {}
    for (name, amp), pair in pairs.items():
        minus, plus = pair[-1], pair[1]
        dx = plus["coordinate"] - minus["coordinate"]
        cbm_minus = float(minus["bands"][9]["energy_eV"]) - minus["mean_core"]
        cbm_plus = float(plus["bands"][9]["energy_eV"]) - plus["mean_core"]
        electron_by_amp.setdefault(amp, {})[name] = -(cbm_plus - cbm_minus) / dx
        species_derivatives = {}
        for species_index, species in enumerate(("Ga", "As")):
            e_minus = float(minus["bands"][9]["energy_eV"]) - float(minus["core"][species_index]["energy_eV"])
            e_plus = float(plus["bands"][9]["energy_eV"]) - float(plus["core"][species_index]["energy_eV"])
            species_derivatives[species] = -(e_plus - e_minus) / dx
        electron_species_by_amp.setdefault(amp, {})[name] = species_derivatives
        hm = sorted(float(b["energy_eV"]) - minus["mean_core"] for b in minus["bands"][6:9])
        hp = sorted(float(b["energy_eV"]) - plus["mean_core"] for b in plus["bands"][6:9])
        if name in {"xx", "yy", "zz"}:
            def doublet(v):
                ij = min(((i, j) for i in range(3) for j in range(i+1, 3)), key=lambda ij: abs(v[ij[0]]-v[ij[1]]))
                si = next(i for i in range(3) if i not in ij)
                return (sum(v[i] for i in ij) / 2, v[si])
            md, ms = doublet(hm); pd, ps = doublet(hp)
            v = sorted(((ps-ms)/dx, (pd-md)/dx, (pd-md)/dx))
        else:
            center0 = sum(sorted(float(b["energy_eV"])-bulk["mean_core"] for b in bulk["bands"][6:9])) / 3
            avg = [(a+b)/2 for a,b in zip(hm,hp)]
            v = sorted((x-center0)/amp for x in avg)
        hole_by_amp.setdefault(amp, {})[name] = v
    amp_rows = []
    for amp in sorted(electron_by_amp):
        a_rows = [sum(hole_by_amp[amp][n])/3 for n in ("xx", "yy", "zz")]
        b_rows = [min(hole_by_amp[amp][n]) - (sorted(hole_by_amp[amp][n])[1] + sorted(hole_by_amp[amp][n])[2])/2 for n in ("xx", "yy", "zz")]
        c_abs = [((max(hole_by_amp[amp][n])-min(hole_by_amp[amp][n]))/2) for n in ("xy", "xz", "yz")]
        amp_source_ids = sorted(set(bulk["r"]["source_ids"]) |
            {sid for (component, level), pair in pairs.items() if level == amp
             for endpoint_row in pair.values() for sid in endpoint_row["r"]["source_ids"]})
        amp_rows.append({"amplitude": amp, "source_ids": amp_source_ids,
                         "electron": {n: electron_by_amp[amp][n] for n in DEFORMATION_COMPONENTS},
                         "hole": {"a": sum(a_rows)/3, "b": sum(b_rows)/3,
                                  "c_signed": c_h_sign*sum(c_abs)/3}})
    species_core_sensitivity = [
        {"amplitude": amp, "component": name,
         "electron_D_by_species": electron_species_by_amp[amp][name],
         "Ga_minus_As_D_spread_eV": (electron_species_by_amp[amp][name]["Ga"] -
                                      electron_species_by_amp[amp][name]["As"])}
        for amp in sorted(electron_species_by_amp) for name in DEFORMATION_COMPONENTS]
    electron = {n: sum(row["electron"][n] for row in amp_rows)/len(amp_rows) for n in DEFORMATION_COMPONENTS}
    hole = {n: sum(row["hole"][n] for row in amp_rows)/len(amp_rows) for n in ("a", "b", "c_signed")}
    return electron, hole, amp_rows, rows, bulk, core_gauge, species_core_sensitivity


def mirror_sign(mirror, proof_receipt, records):
    runs = mirror.get("runs", {})
    if set(runs) != {"bulk", "xy_m_0.005", "xy_p_0.005"}:
        raise Stop("mirror proof does not contain the exact bulk/xy endpoints")
    # Join proof records to native receipts by the original WAVECAR output digest.
    source_rows = []
    for label, proof in runs.items():
        matches = [r for r in records if r["meta"].get("stage_kind") == "deformation" and
                   json.loads(r["files"]["execution-receipt.json"]).get("native_output_sha256", {}).get("WAVECAR") == proof.get("wavecar_sha256")]
        if len(matches) != 1:
            raise Stop(f"mirror WAVECAR does not uniquely join a trusted deformation receipt: {label}")
        source_rows.append((label, proof, matches[0]))
    by_label = {label: (proof, row) for label, proof, row in source_rows}
    bulk_lat = np.asarray(by_label["bulk"][0]["lattice_angstrom"], float)
    q = np.array([[0.,1.,0.],[1.,0.,0.],[0.,0.,1.]])
    parities = {}
    gammas = {}
    energies = {}
    for label, (proof, row) in by_label.items():
        a = np.asarray(proof["lattice_angstrom"], float)
        if not np.allclose(a, field(row,"structure.submitted_lattice")["value"], atol=1e-8, rtol=0):
            raise Stop("mirror proof lattice differs from native submitted POSCAR geometry")
        g = np.asarray(proof["gpoints_integer_reduced"], int)
        transform = np.linalg.inv(a.T) @ q @ a.T
        rounded = np.rint(transform)
        if np.max(np.abs(transform-rounded)) > 1e-8:
            raise Stop("xy mirror does not map this native reciprocal lattice integrally")
        integer = rounded.astype(np.int64)
        target = g @ integer
        index = {tuple(v): i for i,v in enumerate(g.tolist())}
        if len(index) != len(g) or any(tuple(v) not in index for v in target.tolist()):
            raise Stop("mirror reciprocal-vector map is not closed on the native plane-wave basis")
        perm = np.array([index[tuple(v)] for v in target.tolist()], int)
        band_rows = proof["bands_one_based"]
        parity = {}
        for b in (7,8,9):
            rowb = band_rows[str(b)]
            c = np.asarray(rowb["coefficients_real"], float) + 1j*np.asarray(rowb["coefficients_imag"], float)
            if c.shape != (len(g),): raise Stop("mirror coefficient/G-point lengths disagree")
            u = np.zeros_like(c); u[perm] = c
            overlap = np.vdot(c,u) / np.vdot(c,c)
            if abs(overlap.imag) > 1e-6 or min(abs(overlap.real-1), abs(overlap.real+1)) > 1e-5:
                raise Stop("native Gamma state has no resolved xy mirror parity")
            parity[b] = 1 if overlap.real > 0 else -1
            energies[(label,b)] = float(rowb["energy_ev"])
        parities[label] = parity
        # Gamma engineering shear derived from the actual submitted cell.
        e = strain(bulk_lat, a)
        gammas[label] = coord(e, "xy")
    oddm = [b for b,p in parities["xy_m_0.005"].items() if p == -1]
    oddp = [b for b,p in parities["xy_p_0.005"].items() if p == -1]
    if len(oddm) != 1 or len(oddp) != 1:
        raise Stop("split xy states do not identify one odd branch per native endpoint")
    dm = gammas["xy_p_0.005"] - gammas["xy_m_0.005"]
    slope = (energies[("xy_p_0.005", oddp[0])] - energies[("xy_m_0.005", oddm[0])]) / dm
    if not math.isfinite(slope) or abs(slope) < 1e-6:
        raise Stop("odd mirror branch native central slope is unresolved")
    return (-1 if slope > 0 else 1), {"parities": parities, "odd_branch_dE_dgamma_eV": slope,
                                      "c_H_sign": "negative" if slope > 0 else "positive",
                                      "c_H_relation": "odd branch dE/dgamma = -c_H"}


def xml_token(token):
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?", token):
        raise Stop("non-numeric token in response XML")
    value = float(token.replace("D","E").replace("d","e"))
    if not math.isfinite(value): raise Stop("nonfinite response XML number")
    m, _, exp = token.lower().replace("d","e").partition("e")
    digits = len(m.split(".",1)[1]) if "." in m else 0
    return value, 0.5*10**((int(exp) if exp else 0)-digits)


def xml_rows(node, rows, cols):
    vals=[]; rad=0.0
    for child in list(node):
        if child.tag != "v" or child.text is None: continue
        parsed=[xml_token(x) for x in child.text.split()]
        if len(parsed)!=cols: raise Stop("response XML numeric row width mismatch")
        vals.append([x[0] for x in parsed]); rad=max(rad,max(x[1] for x in parsed))
    arr=np.asarray(vals,float)
    if arr.shape!=(rows,cols) or not np.all(np.isfinite(arr)): raise Stop("response XML matrix shape/nonfinite mismatch")
    return arr,rad


# The bounded algebra below is a controlled, eval-side copy of the pure
# whole-direction envelope in author/case05/scripts/gaas_qzero_pop_diagnostic.py
# (SHA256 2d516d4bededde5f1f7a003243c311dbdcbb9831cc1760fc6f2970bfebd4aaa4).
# It consumes only the native matrices parsed below; it does not import the
# author script or its fixture/reference data.
def _upper(value, scale=1.0):
    if not math.isfinite(value):
        raise Stop("non-finite upper bound")
    cushion = 128.0 * np.finfo(float).eps * max(abs(value), abs(scale), 1.0)
    return math.nextafter(value + cushion, math.inf)


def _lower(value, scale=1.0):
    if not math.isfinite(value):
        raise Stop("non-finite lower bound")
    cushion = 128.0 * np.finfo(float).eps * max(abs(value), abs(scale), 1.0)
    return math.nextafter(value - cushion, -math.inf)


def _frobenius_upper(value):
    norm = math.hypot(*(float(x) for x in np.asarray(value, dtype=float).ravel()))
    if not math.isfinite(norm):
        raise Stop("non-finite Frobenius norm")
    return math.nextafter(norm + 128.0 * np.finfo(float).eps * max(norm, 1.0), math.inf)


def _translation_basis(masses):
    t = np.zeros((6, 3), dtype=float)
    total = float(np.sum(masses))
    for axis in range(3):
        for atom in range(2):
            t[3 * atom + axis, axis] = math.sqrt(float(masses[atom]) / total)
    return t


def _bright_lo_mean_bound(l_min, t_max, delta_lo, delta_to):
    ratio = math.nextafter(math.sqrt(2.0), math.inf) * t_max / l_min
    ratio = _upper(ratio, 1.0)
    return _upper(delta_lo + (ratio / (1.0 + ratio)) * delta_to,
                  max(delta_lo, delta_to, 1.0))


def _whole_direction_envelope(xml):
    """Conservative whole-sphere q→0 matrix/print-interval envelope."""
    born = np.asarray(xml["born"], dtype=float)
    eps = np.asarray(xml["epsilon"], dtype=float)
    masses = np.asarray(xml["masses_amu"], dtype=float)
    h = np.asarray(xml["hessian_thz2"], dtype=float)
    z = float(np.mean(np.diagonal(born, axis1=1, axis2=2)[0]))
    if not math.isfinite(z) or z <= 0:
        raise Stop("Ga Born cubic reference scale is not positive")
    born_rad = float(xml["born_rounding_radius"])
    ideal_born = np.asarray([z * np.eye(3), -z * np.eye(3)])
    delta_g_sq = 0.0
    for k in range(2):
        matrix_radius = _upper(2.0 * born_rad + math.sqrt(3.0) * born_rad,
                               2.0 * born_rad + math.sqrt(3.0) * born_rad)
        matrix_error = np.nextafter(np.abs(born[k] - ideal_born[k]) + matrix_radius, math.inf)
        mass_rad = float(xml["mass_rounding_radii"][k])
        mass_min = float(masses[k]) - mass_rad
        if mass_min <= 0:
            raise Stop("mass print interval is not strictly positive")
        norm_error = _upper(_frobenius_upper(matrix_error) / math.sqrt(mass_min) +
                            math.sqrt(3.0) * z * abs(1.0 / math.sqrt(mass_min) -
                                                      1.0 / math.sqrt(float(masses[k]))),
                            _frobenius_upper(matrix_error))
        delta_g_sq += norm_error * norm_error
    dg = _upper(math.sqrt(delta_g_sq), math.sqrt(delta_g_sq))
    g0 = z * math.sqrt(float(np.sum(1.0 / masses)))
    eps0 = float(np.trace(eps) / 3.0)
    eps_rad = float(xml["epsilon_rounding_radius"])
    eps_matrix_radius = _upper(3.0 * eps_rad, eps_rad)
    gershgorin = min(float(eps[i, i] - sum(abs(float(eps[i, j])) for j in range(3) if j != i))
                     for i in range(3))
    eps_min = _lower(gershgorin - eps_matrix_radius, abs(gershgorin))
    deps = _upper(_frobenius_upper(eps - eps0 * np.eye(3)) + eps_matrix_radius, abs(eps0))
    if eps_min <= 0 or eps0 <= 0:
        raise Stop("dielectric print interval is not positive")
    eig_h = np.asarray(xml["eigenvalues_hessian_thz2"], dtype=float)
    to_sq = float(np.mean(-eig_h[:3]))
    t = _translation_basis(masses)
    p_opt = np.eye(6) - t @ t.T
    d0 = -h
    mass_projection_radius = 0.0
    for m0 in (masses[0] - xml["mass_rounding_radii"][0], masses[0] + xml["mass_rounding_radii"][0]):
        for m1 in (masses[1] - xml["mass_rounding_radii"][1], masses[1] + xml["mass_rounding_radii"][1]):
            if m0 <= 0 or m1 <= 0:
                raise Stop("mass uncertainty reaches nonpositive values")
            corner_t = _translation_basis(np.asarray([m0, m1]))
            mass_projection_radius = max(mass_projection_radius, 2.0 * float(np.linalg.norm(corner_t - t, ord="fro")))
    mass_projection_radius = _upper(mass_projection_radius, 1.0)
    delta_d0 = _upper(_frobenius_upper(d0 - to_sq * p_opt) +
                      6.0 * float(xml["hessian_rounding_radius"]) + to_sq * mass_projection_radius,
                      abs(to_sq))
    volume = float(xml["volume_angstrom3"])
    volume_rad = float(xml["volume_rounding_radius"])
    if volume <= volume_rad or volume_rad < 0:
        raise Stop("volume print interval is not positive")
    c = C_F_THz_PER_SQRT_EV_ANG2_AMU ** 2 * 4 * math.pi * K_E_EV_ANGSTROM / volume
    c_upper = _upper(C_F_THz_PER_SQRT_EV_ANG2_AMU ** 2 * 4 * math.pi * K_E_EV_ANGSTROM / (volume-volume_rad), c)
    dc = _upper(c_upper - c, c_upper)
    delta_nac = _upper(c_upper * ((2*g0*dg+dg*dg)/eps_min + (g0*g0*deps)/(eps_min*eps0)) +
                        dc * g0*g0 / eps_min, c_upper*g0*g0/eps_min)
    delta_d = _upper(delta_d0 + delta_nac, delta_d0)
    ideal_strength = c * g0*g0 / eps0
    if to_sq <= 0 or ideal_strength <= 0 or delta_d >= min(to_sq, ideal_strength):
        raise Stop("whole-direction POP envelope does not isolate the positive optical/bright-LO subspace")
    f_to = math.sqrt(to_sq); f_lo = math.sqrt(to_sq + ideal_strength)
    f_to_min = math.nextafter(math.sqrt(to_sq-delta_d), 0.0)
    f_lo_min = math.nextafter(math.sqrt(to_sq+ideal_strength-delta_d), 0.0)
    f_lo_max = math.nextafter(math.sqrt(to_sq+ideal_strength+delta_d), math.inf)
    delta_lo = _upper(delta_d / (f_lo_min + f_lo), f_lo)
    delta_to = _upper((f_lo-f_to) + delta_d/(f_lo_min+f_lo) + delta_d/(f_to_min+f_to), f_lo)
    sin_bound = _upper(delta_d/(ideal_strength-delta_d), 1.0)
    if sin_bound >= 1:
        raise Stop("whole-direction bright eigenspace angle unresolved")
    cos_lower = math.nextafter(math.sqrt(max(0.0, 1.0-sin_bound*sin_bound)), 0.0)
    l_min = _lower((g0*cos_lower-dg)/math.sqrt(f_lo_max), g0/math.sqrt(f_lo_max))
    t_max = _upper((g0*sin_bound+dg)/math.sqrt(f_to_min), g0/math.sqrt(f_to_min))
    if l_min <= 0:
        raise Stop("whole-direction bright LO amplitude lower bound unresolved")
    return {"ideal_TO_frequency_thz": f_to, "ideal_LO_frequency_thz": f_lo,
            "LO_interval_thz": [f_lo_min, f_lo_max],
            "combined_squared_frequency_perturbation_bound_thz2": delta_d,
            "D0_to_cubic_optical_projector_bound_thz2": delta_d0,
            "NAC_full_direction_operator_bound_thz2": delta_nac,
            "born_mass_weighted_deviation_bound": dg, "epsilon_min_bound": eps_min,
            "bright_LO_amplitude_lower_bound": l_min,
            "TO_L2_amplitude_upper_bound": t_max,
            "mean_frequency_bound_thz": _bright_lo_mean_bound(l_min, t_max, delta_lo, delta_to),
            "scope": "ALL_CARTESIAN_DIRECTIONS_FOR_REPRESENTED_GAMMA_MATRICES_ONLY_NOT_SCIENCE_PASS"}


def pop_input(record):
    root=ET.fromstring(record["files"]["vasprun.xml"])
    epsnode=root.findall(".//varray[@name='epsilon']"); bornnode=root.findall(".//array[@name='born_charges']"); dynnodes=root.findall(".//dynmat")
    if len(epsnode)!=1 or len(bornnode)!=1 or len(dynnodes)!=1: raise Stop("DFPT XML lacks unique epsilon/Born/dynmat")
    eps,er=xml_rows(epsnode[0],3,3)
    sets=bornnode[0].findall("./set")
    if len(sets)!=2: raise Stop("DFPT XML must contain two ordered Born tensors")
    born=[]; br=0
    for ion in sets:
        z,zr=xml_rows(ion,3,3); born.append(z); br=max(br,zr)
    dyn=dynnodes[0]; unit=dyn.find("./i[@name='unit']")
    if unit is None or (unit.text or "").strip()!="THz^2": raise Stop("unsupported native Hessian unit")
    h,hr=xml_rows(dyn.find("./varray[@name='hessian']"),6,6)
    enode=dyn.find("./v[@name='eigenvalues']")
    if enode is None or enode.text is None: raise Stop("missing native Hessian eigenvalues")
    eig_tokens=[xml_token(x) for x in enode.text.split()]
    vals=[x[0] for x in eig_tokens]
    if len(vals)!=6: raise Stop("native Hessian eigenvalue count mismatch")
    atomtypes=root.find("./atominfo/array[@name='atomtypes']/set")
    if atomtypes is None: raise Stop("native mass block missing")
    type_rows=[[(c.text or "").strip() for c in row.findall("c")] for row in atomtypes.findall("rc")]
    if len(type_rows)!=2 or [x[1] for x in type_rows]!=["Ga","As"]: raise Stop("native mass species order is unsupported")
    mass_tokens=[xml_token(x[2]) for x in type_rows]
    masses=np.asarray([x[0] for x in mass_tokens])
    volnode=root.find(".//structure[@name='finalpos']/crystal/i[@name='volume']")
    if volnode is None or volnode.text is None: raise Stop("native DFPT volume missing")
    volume, volume_rad = xml_token(volnode.text.strip())
    envelope_input={"born":np.asarray(born),"born_rounding_radius":br,
        "epsilon":eps,"epsilon_rounding_radius":er,
        "masses_amu":masses,"mass_rounding_radii":np.asarray([x[1] for x in mass_tokens]),
        "volume_angstrom3":volume,"volume_rounding_radius":volume_rad,
        "hessian_thz2":h,"hessian_rounding_radius":hr,
        "eigenvalues_hessian_thz2":np.asarray(vals)}
    envelope=_whole_direction_envelope(envelope_input)
    return {"to_thz":envelope["ideal_TO_frequency_thz"],
            "lo_thz":envelope["ideal_LO_frequency_thz"],
            "bound_thz":envelope["mean_frequency_bound_thz"],
            "lo_interval_thz":envelope["LO_interval_thz"],
            "delta_squared_thz2":envelope["combined_squared_frequency_perturbation_bound_thz2"],
            "d0_to_cubic_operator_bound_thz2":envelope["D0_to_cubic_optical_projector_bound_thz2"],
            "nac_all_direction_operator_bound_thz2":envelope["NAC_full_direction_operator_bound_thz2"],
            "born_mass_weighted_deviation_bound":envelope["born_mass_weighted_deviation_bound"],
            "epsilon_min_bound":envelope["epsilon_min_bound"],
            "bright_LO_amplitude_lower_bound":envelope["bright_LO_amplitude_lower_bound"],
            "TO_L2_amplitude_upper_bound":envelope["TO_L2_amplitude_upper_bound"],
            "born_raw":np.asarray(born).tolist(),"epsilon_raw":eps.tolist(),"d0_raw":(-h).tolist(),
            "mass_amu":masses.tolist(),"volume_angstrom3":volume,
            "scope":envelope["scope"]}


def dielectric(records):
    rows=[]
    for r in records:
        if r["meta"].get("stage_kind")!="dfpt": continue
        hi=field(r,"dielectric.epsilon_high")["value"]
        ion=field(r,"dielectric.epsilon_ionic")["value"]
        static=field(r,"dielectric.epsilon_static_observed_sum")["value"]
        rows.append({"r":r,"high":np.asarray(hi,float),"ion":np.asarray(ion,float),"static":np.asarray(static,float)})
    if len(rows)!=3: raise Stop("expected three native DFPT dielectric settings")
    # Trusted run IDs encode the source parameters and are not science values.
    rows.sort(key=lambda x:x["r"]["meta"].get("stage", ""))
    return rows


def link_sources(records):
    return [sid for r in records for sid in r["source_ids"]]


def convergence_id(record):
    meta = record["meta"]
    encut = float(meta["encut_ev"])
    mesh = meta["mesh"]
    if len(mesh) != 3 or any(type(x) is not int or x <= 0 for x in mesh):
        raise Stop("native convergence setting lacks a supported actual three-axis k mesh")
    encut_text = str(int(encut)) if encut.is_integer() else format(encut, "g")
    method = record["native"]["method"]
    descriptor = record["native"]["provenance"]["method_descriptor_raw"]
    order = descriptor["potcar_order"]
    setting = f"{str(method['xc_from_incar']).lower()}_{encut_text}eV_{mesh[0]}x{mesh[1]}x{mesh[2]}"
    method_id = f"{method['engine']}-{method['engine_version']}/{method['xc_from_incar']}/{method['paw_family_manifest_raw']}/{'+'.join(order)}"
    return setting, method_id


def run_source_ids(record, names):
    return [record["rows"][name]["source_id"] for name in names]


def observed_delta(values):
    if values and isinstance(values[0], list):
        arrays = [np.asarray(value, dtype=float) for value in values]
        return max(float(np.max(np.abs(left-right)))
                   for i, left in enumerate(arrays) for right in arrays[i+1:])
    numbers = [float(value) for value in values]
    return max(numbers)-min(numbers)


def solve():
    data=load_inputs(); obs=data["observations"]
    records=list(obs.values())
    dfpt=[r for r in records if r["meta"].get("stage_kind")=="dfpt"]
    if len(dfpt)!=3: raise Stop("expected VASP 520/16, 650/16, 650/12 matched DFPT settings")
    # Fixed source identity selects the accepted high setting; no tabulated expected values are loaded.
    bulk=next((r for run_id,r in obs.items() if run_id=="dfpt_650_k16"),None)
    if bulk is None: raise Stop("native PBE bulk DFPT source not found")
    pbe_gap=float(field(bulk,"band.fundamental_gap")["value"])
    pbe_direct=float(field(bulk,"band.direct_gap")["value"])
    structure={"lattice_vectors_angstrom":field(bulk,"structure.lattice")["value"],
               "species_order":field(bulk,"structure.species_order")["value"],
               "fractional_positions":field(bulk,"structure.fractional_positions")["value"]}
    elastic_rows=[r for r in records if r["meta"].get("stage_kind")=="elastic_finite_strain"]
    cmat,cmats,camps,cids,_,c_amp_ids,c_symmetry_residual=elastic_fit(elastic_rows)
    dsign,dsign_detail=mirror_sign(data["mirror"],data["mirror_receipt"],records)
    if dsign != -1: raise Stop("native mirror odd-branch slope does not support negative shear H coefficient")
    de,dh,damp,drows,dbulk,core_gauge,species_core_sensitivity=deformation(records,dsign)
    d_ids=link_sources([x["r"] for x in drows])
    eps_rows=dielectric(records)
    eps_base=next((r for r in eps_rows if r["r"]["run_id"]=="dfpt_650_k16"),None)
    if eps_base is None: raise Stop("the source-compatible VASP 650/16 response baseline is missing")
    eps_hi=eps_base["high"]
    eps_static=eps_base["static"]
    eps_ids=eps_base["r"]["source_ids"]
    pop_results=[]
    for r in dfpt:
        pop_results.append({"record":r,"value":pop_input(r)})
    pop_results.sort(key=lambda x:x["record"]["meta"].get("stage", ""))
    pop_base=next((x for x in pop_results if x["record"]["run_id"]=="dfpt_650_k16"),None)
    if pop_base is None: raise Stop("the source-compatible VASP 650/16 POP baseline is missing")
    popmean=float(pop_base["value"]["lo_thz"])
    popids=pop_base["record"]["source_ids"]
    method_ids=bulk["source_ids"]
    params={"schema":"case05-parameters/v1",
            "method":{"engine":"VASP","functional":"PBE","source_ids":method_ids},
            "structure":structure,
            "pbe_bandgap":{"fundamental_eV":pbe_gap,"direct_eV":pbe_direct,"method":"PBE","source_ids":method_ids},
            "hse06_bandgap_annotation":None,
            "elastic_C_GPa":{"matrix":cmat.tolist(),"units":"GPa","voigt_order":["xx","yy","zz","yz","xz","xy"],"source_ids":cids},
            "epsilon_high":{"matrix":eps_hi.tolist(),"units":"dimensionless","source_ids":eps_ids},
            "epsilon_static":{"matrix":eps_static.tolist(),"units":"dimensionless","source_ids":eps_ids},
            "pop_frequency":{"value_THz":popmean,"mode":"LO","q_limit":"q_to_0","source_ids":popids},
            "deformation_potentials":{"energy_reference":"common_all_atom_1s",
               "strain_convention":"Cartesian Green-Lagrange strain; engineering shear gamma=2E_ij; electron D=-d(E_CBM-mean_1s)/dE; hole H=a tr(E)I+b diag(Eii-tr(E)/3)+offdiagonal(c_H*gamma)",
               "electron":{"states":[{"component":n,"value_eV":de[n]} for n in DEFORMATION_COMPONENTS],"source_ids":d_ids},
               "hole":{"states":[{"invariant":n,"symmetry_invariant_eV":dh[n]} for n in ("a","b","c_signed")],"source_ids":d_ids}}}
    method_ids={convergence_id(r)[1] for r in records if r["meta"].get("stage_kind")=="dfpt"}
    if len(method_ids)!=1: raise Stop("native response settings do not share one observed method identity")
    method_id=next(iter(method_ids))
    def conv_row(name, units, vals, tolerance):
        delta=observed_delta([value for _,value,_ in vals])
        return {"quantity":name,"units":units,"settings":[{"setting_id":key,"method_id":method_id,"value":val,"source_ids":src} for key,val,src in vals],
                "claimed_tolerance":float(tolerance),"claimed_converged":delta <= float(tolerance)}
    conv=[]
    c_norms=[float(np.linalg.norm(cmats[a],ord="fro")) for a in camps]
    max_c_entry=max(abs(float(value)) for matrix in cmats.values() for value in matrix.ravel())
    conv.append(conv_row("elastic_C_GPa","GPa",[(str(a),c_norms[i],c_amp_ids[a]) for i,a in enumerate(camps)],
                         max(3.0,0.03*max_c_entry)))
    for name in ("epsilon_high","epsilon_static"):
        key="high" if name=="epsilon_high" else "static"
        values=[r[key].tolist() for r in eps_rows]
        tol=max(0.2,0.02*max(abs(float(v)) for matrix in values for line in matrix for v in line))
        conv.append(conv_row(name,"dimensionless",[(convergence_id(r["r"])[0],r[key].tolist(),run_source_ids(r["r"],("OUTCAR",))) for r in eps_rows],tol))
    pop_values=[x["value"]["lo_thz"] for x in pop_results]
    pop_tol=max(0.1,0.02*max(abs(x) for x in pop_values))
    conv.append(conv_row("pop_frequency","THz",[(convergence_id(x["record"])[0],x["value"]["lo_thz"],run_source_ids(x["record"],("OUTCAR","vasprun.xml"))) for x in pop_results],pop_tol))
    bound_values=[x["value"]["bound_thz"] for x in pop_results]
    bound_tol=max(0.1,0.02*max(abs(x) for x in bound_values))
    conv.append(conv_row("pop_full_direction_mean_bound","THz",[(convergence_id(x["record"])[0],x["value"]["bound_thz"],run_source_ids(x["record"],("OUTCAR","vasprun.xml"))) for x in pop_results],bound_tol))
    electron_amp_values=[max(abs(v) for v in row["electron"].values()) for row in damp]
    conv.append(conv_row("electron_deformation","eV",[(str(row["amplitude"]),electron_amp_values[i],row["source_ids"]) for i,row in enumerate(damp)],
                         max(0.2,0.05*max(abs(x) for x in electron_amp_values))))
    hole_amp_values=[max(abs(v) for v in row["hole"].values()) for row in damp]
    conv.append(conv_row("hole_deformation","eV",[(str(row["amplitude"]),hole_amp_values[i],row["source_ids"]) for i,row in enumerate(damp)],
                         max(0.2,0.05*max(abs(x) for x in hole_amp_values))))
    pbe_gaps=[(r, float(field(r,"band.fundamental_gap")["value"]), float(field(r,"band.direct_gap")["value"])) for r in dfpt]
    gap_sources=lambda r: run_source_ids(r,("OUTCAR","vasprun.xml"))
    conv.append(conv_row("pbe_bandgap","eV",[(convergence_id(r)[0],fund,gap_sources(r)) for r,fund,_ in pbe_gaps],0.03))
    conv.append(conv_row("pbe_direct_gap","eV",[(convergence_id(r)[0],direct,gap_sources(r)) for r,_,direct in pbe_gaps],0.03))
    convergence={"schema":"case05-convergence/v1","quantities":conv}
    output=Path(os.environ.get("CASE05_FINAL_DIR","/app/final"))
    if output.exists() or output.is_symlink(): raise Stop("final output path already exists or is a symlink; refusing to replace it")
    (output/"native"/"runs").mkdir(parents=True)
    shutil.copytree(Path(os.environ.get("CASE05_NATIVE_CANDIDATE_DIR", "/app/candidate-native")) / "native" / "provenance",
                    output/"native"/"provenance")
    shutil.copyfile(Path(os.environ.get("CASE05_NATIVE_CANDIDATE_DIR", "/app/candidate-native")) / "native" / "provenance-manifest.json",
                    output/"native"/"provenance-manifest.json")
    native_runs=[]
    for run_id,r in sorted(obs.items()):
        links=[]
        target=output/"native"/"runs"/run_id; target.mkdir(parents=True)
        for name in NATIVE_FILES:
            row=r["rows"][name]; raw=r["files"][name]
            (target/name).write_bytes(raw)
            links.append({"name":name,"source_id":row["source_id"],"sha256":row["sha256"]})
        native_runs.append({"run_id":run_id,"files":links})
    (output/"native"/"manifest.json").write_text(json.dumps({"schema":"case05-native-source-links/v1","runs":native_runs},sort_keys=True,separators=(",",":"))+"\n")
    (output/"native"/"deformation-mirror-proof.json").write_bytes(
        data["proof_files"]["deformation-mirror-proof.json"])
    (output/"parameters.json").write_text(json.dumps(params,sort_keys=True,allow_nan=False,indent=2)+"\n")
    (output/"convergence.json").write_text(json.dumps(convergence,sort_keys=True,allow_nan=False,indent=2)+"\n")
    gauge_row=core_gauge["by_run"][dbulk["r"]["run_id"]]
    response_rows=[{"setting":convergence_id(r["r"])[0],"epsilon_high":r["high"].tolist(),
                    "epsilon_static":r["static"].tolist()} for r in eps_rows]
    pbe_gap_rows=[{"setting":convergence_id(r)[0],"fundamental_eV":fund,"direct_eV":direct}
                  for r,fund,direct in pbe_gaps]
    pbe_gap_deltas={key:observed_delta([row[key] for row in pbe_gap_rows])
                    for key in ("fundamental_eV","direct_eV")}
    report=("# GaAs fresh native calculation\n\n"
       "This bundle was rebuilt from the fresh VASP runs and candidate-owned Gamma mirror-coefficient proof recorded below. It is source-derived diagnostic output; it makes no Oracle, scoring-readiness, or final-release claim.\n\n"
       f"PBE fundamental and direct gaps by native all-k DFPT setting: `{json.dumps(pbe_gap_rows,sort_keys=True,separators=(',',':'))}`. Maximum setting differences are `{json.dumps(pbe_gap_deltas,sort_keys=True,separators=(',',':'))}` eV; parameters.json selects the source-bound 650/16 setting.\n\n"
       f"Response tensors by native setting: `{json.dumps(response_rows,sort_keys=True,separators=(',',':'))}`. Actual cross-setting differences are computed from these values in convergence.json.\n\n"
       f"POP q→0 ideal LO frequencies and full-direction mean-frequency bounds by setting: `{json.dumps([(x['record']['run_id'],x['value']['lo_thz'],x['value']['bound_thz']) for x in pop_results],separators=(',',':'))}`. The reported parameter uses the native 650/16 LO frequency; convergence.json includes frequency and bound rows. The bound covers the represented Gamma matrix intervals over all Cartesian directions only.\n\n"
       f"The common all-atom-1s reference at the native deformation bulk is {gauge_row['mean_all_atom_1s_eV']:.9g} eV; Ga-minus-As core-site difference {gauge_row['Ga_minus_As_core_eV']:.9g} eV is retained as a gauge diagnostic. The full six-component electron and three cubic hole invariants at both strain amplitudes are `{json.dumps(damp,sort_keys=True,separators=(',',':'))}`. Per-amplitude, per-component Ga-only and As-only CBM deformation derivatives and their species spreads are `{json.dumps(species_core_sensitivity,sort_keys=True,separators=(',',':'))}`; these gauge-sensitivity diagnostics do not replace the accepted common-mean reference or define a failure gate.\n\n"
       f"The hole shear invariant uses fresh native Gamma mirror-state parity and central odd-branch slope: `{json.dumps(dsign_detail,sort_keys=True,separators=(',',':'))}`. Candidate-owned coefficient and source links are recorded in `native/deformation-mirror-proof.json`; each WAVECAR identity joins its fresh execution receipt.\n\n"
       f"The reported elastic C is the symmetric part of the source-derived two-amplitude mean; maximum raw major-symmetry residual is {c_symmetry_residual:.8g} GPa. Raw C matrices at amplitudes `{json.dumps({str(a):cmats[a].tolist() for a in camps},separators=(',',':'))}` GPa; elementwise second-minus-first matrix difference `{json.dumps((cmats[camps[1]]-cmats[camps[0]]).tolist(),separators=(',',':'))}` GPa. The amplitude values and endpoint source IDs are also represented in convergence.json.\n\n"
       "Convergence rows report actual setting values and do not assert convergence. Independent references remain partial; no overall scientific PASS or scorer readiness is claimed.\n")
    (output/"report.md").write_text(report)
    print(json.dumps({"status":"DERIVED_FROM_TRUSTED_NATIVE_INPUTS","output":str(output),"native_runs":len(native_runs),"source_ids":len(data["all_sources"]),"mirror_sign":dsign_detail},sort_keys=True))


if __name__ == "__main__":
    try:
        solve()
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(2)
CASE05_SOLVER_REUSE_NATIVE

python3 "$WORKDIR/fresh_native_workflow.py" --output /app/candidate-native --assets /app/assets
CASE05_NATIVE_CANDIDATE_DIR=/app/candidate-native python3 "$WORKDIR/native_solve.py"
