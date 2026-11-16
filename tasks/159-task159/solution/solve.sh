#!/usr/bin/env bash
""":"
if [[ "${1:-}" == "--lmp-wrapper" ]]; then
  shift
set -Eeuo pipefail
: "${CASE08_REAL_LMP:?CASE08_REAL_LMP is required}"
: "${CASE08_SOLVE:?CASE08_SOLVE is required}"
: "${CASE08_PYTHON:?CASE08_PYTHON is required}"
args=("$@")
infile=""
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "-in" ]]; then
    if (( i+1 >= ${#args[@]} )); then echo 'missing -in path' >&2; exit 2; fi
    infile="${args[$((i+1))]}"
    inarg=$((i+1))
    break
  fi
done
if [[ -z "$infile" ]]; then
  # Calphy's verified preflight calls exactly `lmp -h`. Reject every other
  # no-input invocation so no MD command can bypass instrumentation.
  if (( ${#args[@]} == 1 )) && [[ "${args[0]}" == "-h" ]]; then
    exec "$CASE08_REAL_LMP" -h
  fi
  echo 'refusing LAMMPS invocation without -in (only Calphy -h preflight is allowed)' >&2
  exit 2
fi
[[ -f "$infile" ]] || { echo "LAMMPS input missing: $infile" >&2; exit 2; }
case08_dir="$(cd "$(dirname "$infile")" && pwd)"
stem="$(basename "$infile")"
manifest="$case08_dir/case08-instrumentation.jsonl"
seq_file="$case08_dir/.case08-invocation-sequence"
exec 9>"$case08_dir/.case08-invocation-sequence.lock"
flock 9
seq=0
[[ -f "$seq_file" ]] && read -r seq < "$seq_file"
seq=$((seq+1))
printf '%s\n' "$seq" > "$seq_file"
flock -u 9
invocation_id="$(printf '%08d' "$seq")-$(date -u +%Y%m%dT%H%M%S.%N)-$$"
outfile="$case08_dir/${stem%.lmp}.case08-instrumented.${invocation_id}.lmp"
logarchive="$case08_dir/${stem%.lmp}.case08-native.${invocation_id}.log"
threshold="${CASE08_FACE_THRESHOLD:-10.5}"
interval="${CASE08_THERMO_INTERVAL:-100}"
"$CASE08_PYTHON" "$CASE08_SOLVE" --kernel --instrument-native --input "$infile" --output "$outfile" --manifest "$manifest" --min-face-A "$threshold" --thermo-interval "$interval" --invocation-id "$invocation_id" --native-log "$logarchive"
args[$inarg]="$outfile"
# Keep Calphy's canonical -log destination intact; snapshot it after the call.
logarg=-1
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "-log" ]]; then logarg=$((i+1)); break; fi
done
if (( logarg >= 1 )); then
  if (( logarg >= ${#args[@]} )); then echo 'missing -log path' >&2; exit 2; fi
  source_log="${args[$logarg]}"
else
  source_log="log.lammps"
fi
before="$case08_dir/case08-before.${invocation_id}.json"
"$CASE08_PYTHON" "$CASE08_SOLVE" --kernel --wrapper-snapshot "$before" "$case08_dir"
started_utc="$(date -u +%FT%TZ)"
started_mono="$($CASE08_PYTHON -c 'import time; print(time.monotonic())')"
set +e
"$CASE08_REAL_LMP" "${args[@]}"
rc=$?
set -e
completed_mono="$($CASE08_PYTHON -c 'import time; print(time.monotonic())')"
completed_utc="$(date -u +%FT%TZ)"
set +e
"$CASE08_PYTHON" "$CASE08_SOLVE" --kernel --wrapper-receipt "$case08_dir/case08-execution.${invocation_id}.json" "$invocation_id" "$rc" "$source_log" "$logarchive" "$CASE08_REAL_LMP" "$before" "$started_utc" "$completed_utc" "$started_mono" "$completed_mono" "$case08_dir" "${args[@]}"
receipt_writer_rc=$?
set -e
rm -f "$before"
if (( receipt_writer_rc != 0 )); then exit 2; fi
exit "$rc"
fi
exec python3 "$0" "$@"
":"""
#!/usr/bin/env python3
from __future__ import annotations
"""Single-file Case-05 candidate campaign entry; native driver integration is staged."""
import argparse, base64, datetime, hashlib, json, math, os, re, shutil, signal, socket, struct, sys, subprocess, tempfile, threading, time, uuid, shlex
from pathlib import Path
from typing import Any

_HPC_BROKER_SOCKET=Path('/run/bench24-159/hpc.sock')
_HPC_PUBLIC_ATTEMPT=Path('/run/bench24-159/public-attempt.json')


def _wrapper_snapshot(args):
    if len(args) != 2:
        raise SystemExit("wrapper snapshot expects destination and case directory")
    dest, root = Path(args[0]), Path(args[1])
    records = {}
    for pattern in ('*.data', '*.dat', '*.dump', '*.lammpstrj', '*.restart*', 'calphy.restart*'):
        for path in root.glob(pattern):
            if path.is_file():
                records[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    dest.write_text(json.dumps(records, sort_keys=True) + "\n")
    return 0

def _wrapper_receipt(args):
    if len(args) < 12:
        raise SystemExit("wrapper receipt has incomplete native invocation metadata")
    dest=Path(args[0]); invocation=args[1]; rc=int(args[2]); source_log=Path(args[3]); archive_log=Path(args[4])
    if not source_log.is_absolute(): source_log=Path.cwd()/source_log
    if source_log.is_file():
        archive_log.parent.mkdir(parents=True,exist_ok=True)
        tmp=archive_log.with_suffix(archive_log.suffix+".tmp")
        tmp.write_bytes(source_log.read_bytes()); tmp.replace(archive_log)
    real_lmp=args[5]; before_path=Path(args[6]); started_utc=args[7]; completed_utc=args[8]
    started_mono=float(args[9]); completed_mono=float(args[10]); root=Path(args[11]); argv=args[12:]
    def file_record(path):
        p=Path(path)
        return {"path":str(p.resolve()),"exists":p.is_file(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,"bytes":p.stat().st_size if p.is_file() else None}
    parent=archive_log.parent
    dumps=sorted(parent.glob(f"*.{invocation}.run*.lammpstrj"))
    before=json.loads(before_path.read_text()) if before_path.is_file() else {}
    archive_root=parent/"case08-native-snapshots"/invocation; changed=[]
    for pattern in ('*.data','*.dat','*.dump','*.lammpstrj','*.restart*','calphy.restart*'):
        for path in sorted(root.glob(pattern)):
            if not path.is_file(): continue
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if before.get(str(path.resolve()))==digest: continue
            target=archive_root/path.relative_to(root); target.parent.mkdir(parents=True,exist_ok=True)
            tmp_target=target.with_suffix(target.suffix+".tmp"); shutil.copyfile(path,tmp_target); tmp_target.replace(target)
            changed.append({"source":str(path.resolve()),"archive":file_record(target),"source_sha256":digest,"provenance":"changed_or_created_during_this_invocation"})
    instrumented=Path(str(archive_log).replace('.case08-native.', '.case08-instrumented.').replace('.log','.lmp'))
    expected_runs=sum(1 for line in instrumented.read_text(errors='replace').splitlines() if line.startswith('print "CASE08_RUN_BEGIN segment=')) if instrumented.is_file() else None
    integrity_errors=[]
    if not archive_log.is_file(): integrity_errors.append('native log archive missing')
    if expected_runs is None or expected_runs!=len(dumps): integrity_errors.append(f'expected {expected_runs} structural dumps, observed {len(dumps)}')
    data={"invocation_id":invocation,"native_returncode":rc,"wrapper_integrity_rc":2 if integrity_errors else 0,"started_utc":started_utc,"completed_utc":completed_utc,"elapsed_seconds":completed_mono-started_mono,"command_argv":[real_lmp,*argv],"native_log_source":file_record(source_log),"native_log_archive":file_record(archive_log),"expected_run_count":expected_runs,"instrumented_structural_dumps":[file_record(path) for path in dumps],"changed_native_output_snapshots":changed,"integrity_errors":integrity_errors}
    tmp=dest.with_suffix(dest.suffix+".tmp")
    tmp.write_text(json.dumps(data,indent=2)+"\n")
    tmp.replace(dest)
    if integrity_errors: print('; '.join(integrity_errors),file=sys.stderr)
    return 2 if integrity_errors else 0

ASSET_ROOT = Path(os.environ.get("CASE06_ASSET_ROOT", "/app/inputs/candidate-runtime"))
NATIVE_INPUTS = ASSET_ROOT / "native_inputs"
CANDIDATE_SCOPE_SHA256 = "5bcf114ae92b71c6527140c69b44b1c0a168a56337cf3dd522d6678231377903"
POTENTIAL_SHA = "c8f00d8f0cbc131b0298b79260ba8098975624363c9d178223e51e48f025e97a"
PHASES = ("alpha_quartz", "coesite")
DIRECTIONS = ("forward", "backward")
ATOM_COUNTS = {"alpha_quartz": 576, "coesite": 384}

class Stop(RuntimeError):
    pass

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def current_method_identity() -> dict:
    """Bind this merged entry point, rather than historical helper filenames."""
    source = Path(__file__).resolve()
    if not source.is_file():
        raise Stop("packaged solve entry point is unavailable")
    files = []
    for path in sorted(ASSET_ROOT.rglob("*")):
        if path.is_symlink():
            raise Stop(f"candidate runtime asset is a symlink: {path.relative_to(ASSET_ROOT)}")
        if path.is_file():
            files.append({"path": path.relative_to(ASSET_ROOT).as_posix(),
                          "size_bytes": path.stat().st_size, "sha256": sha(path)})
    if not files:
        raise Stop("candidate runtime asset inventory is empty")
    inventory_bytes = (json.dumps(files, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {"schema": "case06-packaged-method-identity/v1",
            "entrypoint": source.name, "entrypoint_sha256": sha(source),
            "asset_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
            "assets": files}

def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

def load_public_scope() -> dict:
    """Public single-state contract; private author seeds remain grader-only."""
    return {"temperature_K": 600, "pressure_bar": 20000,
            "phases": {"alpha_quartz": 576, "coesite": 384},
            "candidate_roles": ["B", "R", "S", "D"],
            "max_direction_attempts": 16, "max_md_steps": 600000,
            "active_time_limit_seconds": 43200}

def preflight_static() -> dict:
    scope = load_public_scope()
    method_identity = current_method_identity()
    potential = NATIVE_INPUTS / "SiOx_potential.yace"
    if not potential.is_file() or sha(potential) != POTENTIAL_SHA:
        raise Stop("task-packaged SiOx Hamiltonian is missing or differs from its frozen SHA")
    for phase, atoms in ATOM_COUNTS.items():
        structure = NATIVE_INPUTS / ("alpha_quartz-576.data" if phase == "alpha_quartz" else "coesite-384.data")
        if not structure.is_file():
            raise Stop(f"task-packaged {phase} candidate structure is missing")
    scope_path = ASSET_ROOT / "candidate-scope.json"
    if not scope_path.is_file() or sha(scope_path) != CANDIDATE_SCOPE_SHA256:
        raise Stop("public candidate scope projection is missing or differs from its frozen SHA")
    scope_doc = json.loads(scope_path.read_text(encoding="utf-8"))
    geometry = json.loads((NATIVE_INPUTS / "geometry-manifest.json").read_text(encoding="utf-8"))
    if (scope_doc.get("schema") != "case06-candidate-public-scope/v1"
            or geometry.get("matrix_sha256") != scope_doc.get("source_matrix_sha256")
            or scope_doc.get("candidate_roles") != ["B", "R", "S", "D"]):
        raise Stop("public scope does not bind the registered candidate geometry and roles")
    registration_path = NATIVE_INPUTS / "candidate-seed-registration.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    if (registration.get("schema") != "case06-candidate-seed-registration/v1"
            or set(registration.get("candidate_roles", {})) != {"B", "R", "S", "D"}
            or '"A"' in registration_path.read_text(encoding="utf-8")):
        raise Stop("candidate seed registration is incomplete or exposes a grader-only role")
    result = {"schema": "case06-single-solve-preflight/v1", "status": "STATIC_INPUTS_VERIFIED",
              "native_md_executed": False, "potential_sha256": POTENTIAL_SHA,
              "candidate_roles": ["B", "R", "adaptive_D_or_S"], "direction_count": 12,
              "A_role": "independent reference retained separately by the environment; not recomputed by preflight",
              "method_identity": method_identity,
              "public_scope": scope, "preflight_method": "read-only public inputs and fixed source bytes"}
    return result

def _delta(role_rows):
    by={(x['phase'],x['direction']):x for x in role_rows}
    if set(by)!={(p,d) for p in PHASES for d in DIRECTIONS}: raise Stop('adaptive rule requires all four role curves with finite G')
    g={k:float(v['g_eV_per_atom']) for k,v in by.items()}
    if not all(math.isfinite(x) for x in g.values()): raise Stop('adaptive estimator has nonfinite Gibbs values')
    mid=((g['coesite','forward']+g['coesite','backward'])-(g['alpha_quartz','forward']+g['alpha_quartz','backward']))/2
    h=(abs(g['coesite','forward']-g['coesite','backward'])+abs(g['alpha_quartz','forward']-g['alpha_quartz','backward']))/2
    return mid,h

def choose_adaptive(matrix,dirs,setup_states):
    b=[x for x in dirs if x['replicate']=='B']; r=[x for x in dirs if x['replicate']=='R']
    db,hb=_delta(b); dr,hr=_delta(r); H=max(hb,hr); R=abs(db-dr)
    b_pass=all(setup_states.get(('B',p),{}).get('status')=='PASS' for p in PHASES)
    if H>R:
        if not b_pass: return {'status':'STOP','selected_component':None,'H_eV_per_atom':H,'R_eV_per_atom':R,'reason':'duration indicated but both B 16k sources did not PASS'}
        selected='D'; rejected='S: not selected because preregistered hysteresis proxy H exceeds repeat proxy R'
    else:
        selected='S'; rejected='D: not selected because H<=R; size is the frozen feasible information-gain default'
    return {'status':'FROZEN','selected_component':'duration' if selected=='D' else 'size','selected_role':selected,
            'deltaG_mid_B_eV_per_atom':db,'deltaG_mid_R_eV_per_atom':dr,'H_B_eV_per_atom':hb,
            'H_R_eV_per_atom':hr,'H_eV_per_atom':H,'R_eV_per_atom':R,'source_role_rows':[x['run_id'] for x in b+r],
            'rejected_alternative':rejected,'not_a_95_percent_CI':True,
            'unselected_systematic_status':'UNKNOWN','b_source_pass':b_pass}

def _candidate_ecal(dirs,decision):
    b=[x for x in dirs if x['replicate']=='B'];r=[x for x in dirs if x['replicate']=='R']; sr=[x for x in dirs if x['replicate']==decision['selected_role']]
    db,hb=_delta(b);dr,hr=_delta(r);ds,_=_delta(sr)
    return max(hb,hr)+abs(db-dr)+abs(ds-db)

def candidate_kernel_entry(matrix: dict, directions: list[dict], setup_states: dict) -> dict:
    """Run the unchanged B/R hysteresis rule and return the selected D/S route."""
    return choose_adaptive(matrix, directions, setup_states)


def _hpc_helper_root() -> Path:
    roots=sorted(path.parent.parent for path in Path("/opt/skills").glob("*/scripts/submit.py"))
    if len(roots)!=1: raise FileNotFoundError("image must provide exactly one supported HPC submission helper")
    return roots[0]

def _hpc_config(selection: dict) -> dict:
    resource=selection["resources"];part=selection["partition"];target=selection["target_name"]
    memory=f"{resource['memory_mb']}M";gpus=resource['gpus'];cpus=resource['cpus']
    limits={"enabled":True,"max_nodes":1,"max_ntasks":1,"max_ntasks_per_node":1,
        "max_cpus_per_task":cpus,"max_total_cpus":cpus,"max_gpus_per_node":gpus,
        "max_total_gpus":gpus,"max_memory_per_node":memory,"max_total_memory":memory,
        "max_walltime":"12:00:00"}
    return {"targets":{target:{"backend":"slurm","host":selection["resource_id"],
        "resource_class":"gpu" if gpus else "cpu","partition":part,"allowed_partitions":[part],
        "base_dir":selection["remote_base"],"snapshot_max_age_seconds":900,
        "transfer_timeout":300,"partition_limits":{part:limits}}}}

def _resource_selection(args) -> dict:
    if not args.resource_id or not args.partition:
        raise ValueError("HPC execution requires an authorized --resource-id and selected --partition")
    return {"resource_id":args.resource_id,"backend":"slurm","partition":args.partition,
        "remote_base":args.remote_base,
        "runtime":{"python":args.remote_python,"lmp":args.remote_lmp,"modules":args.module or []},
        "resources":{"nodes":1,"ntasks":1,"cpus":args.cpus,"memory_mb":args.memory_mb,
            "gpus":args.gpus,"wall_seconds":args.wall_seconds}}

def _remote_campaign_command(selection: dict, workdir: str, attempt_id: str, asset: str,
                             solve: str, allocation_seconds: int, check_runtime: bool=False) -> str:
    runtime=selection["runtime"]
    parts=["set -eu"]
    if runtime.get("modules"):
        parts.append('if [ -d "$HOME/modulefiles" ]; then module use "$HOME/modulefiles"; fi')
    for module in runtime.get("modules",[]): parts.append("module load "+shlex.quote(module))
    parts += [
        "cd "+shlex.quote(workdir),
        "mkdir -p acceptance",
        "printf 'started_utc=%s\\njob_id=%s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"${SLURM_JOB_ID:-}\" > acceptance/job-start.txt",
        "trap 'rc=$?; printf \"ended_utc=%s\\nexit_code=%s\\njob_id=%s\\n\" \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$rc\" \"${SLURM_JOB_ID:-}\" > acceptance/job-finish.txt' EXIT",
        "export CASE06_ASSET_ROOT="+shlex.quote(asset),
        "export CASE08_REAL_LMP="+shlex.quote(runtime["lmp"]),
        "export CASE159_LAMMPS_SHA256="+shlex.quote(runtime["lmp_sha256"]),
        "export CASE08_PYTHON="+shlex.quote(runtime["python"]),
        "export CASE08_SOLVE="+shlex.quote(solve),
        "export PATH="+shlex.quote(str(Path(runtime["python"]).parent))+":$PATH",
        "export OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1",
    ]
    if check_runtime:
        parts.append("exec "+shlex.quote(runtime["python"])+" "+shlex.quote(solve)+" --kernel --check-runtime")
    else:
        parts += [
            "allocation_seconds="+str(allocation_seconds),
            "remaining_seconds=$((allocation_seconds - 300))",
            "if (( remaining_seconds <= 0 )); then printf 'ATTEMPT_DEADLINE_EXPIRED\\n' >&2; exit 75; fi",
            "export CASE06_TRIAL_ID="+shlex.quote(attempt_id)+" CASE06_REFERENCE_ACTIVE_SECONDS=0",
            "export CASE06_REMAINING_ACTIVE_SECONDS=$remaining_seconds",
            "export CASE06_ATTEMPT_DEADLINE_EPOCH=$(( $(date -u +%s) + remaining_seconds ))",
            "timeout --signal=TERM --kill-after=30s \"${remaining_seconds}s\" "+shlex.quote(runtime["python"])+" "+shlex.quote(solve)+" --kernel --run --outputs outputs",
        ]
    return "bash -lc "+shlex.quote(" && ".join(parts))

def _hpc_task_root(output: Path, trial: str) -> Path:
    """Private per-trial helper copy keeps config and state out of shared image paths."""
    source=_hpc_helper_root()
    if not (source/"scripts"/"submit.py").is_file():
        raise FileNotFoundError("image HPC helper is unavailable")
    dest=output/".bench24-task159-hpc"/trial/"helper-root"
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns("submit-job.json",".submit-job","__pycache__",".git"))
    return dest

def _hpc_record_for_job(output: Path, job: str) -> dict | None:
    for result_path in sorted((output/".bench24-task159-hpc").glob("*/result.json"),reverse=True):
        try: record=json.loads(result_path.read_text(encoding="utf-8"))
        except Exception: continue
        if job in (record.get("job_id"),record.get("trial_name"),record.get("job_name"),record.get("helper_job_name")):
            return record
    return None

def _hpc_helper_for_job(output: Path, job: str) -> Path:
    record=_hpc_record_for_job(output,job)
    if record:
        root=Path(record.get("helper_root", ""))
        if (root/"scripts"/"submit.py").is_file(): return root
    return _hpc_helper_root()

def _hpc_invoke(args: list[str], *, cwd: Path, timeout: int=180, selection: dict | None=None, admission_id: str | None=None) -> subprocess.CompletedProcess:
    helper = cwd / "scripts" / "submit.py"
    if not helper.is_file():
        raise FileNotFoundError(f"image HPC helper is unavailable: {helper}")
    attempt_path=_HPC_PUBLIC_ATTEMPT
    if attempt_path.is_symlink() or not attempt_path.is_file():
        raise RuntimeError('root-owned HPC broker attempt binding is unavailable')
    attempt=json.loads(attempt_path.read_text(encoding='utf-8'))
    trial=cwd.parent.name
    payload=json.dumps({'schema':'case06-hpc-broker-request/v1','attempt_id':attempt.get('attempt_id'),
        'trial_name':trial,'args':args,'selection':selection,'admission_id':admission_id},sort_keys=True,separators=(',',':')).encode()
    if len(payload)>1_000_000: raise RuntimeError('HPC broker request exceeds its fixed size limit')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(timeout+30);client.connect(str(_HPC_BROKER_SOCKET))
        client.sendall(struct.pack('!I',len(payload))+payload)
        header=b''
        while len(header)<4:
            block=client.recv(4-len(header))
            if not block: raise RuntimeError('HPC broker returned a truncated response header')
            header+=block
        response_size=struct.unpack('!I',header)[0]
        if response_size<=0 or response_size>1_000_000: raise RuntimeError('HPC broker response size is invalid')
        chunks=[];remaining=response_size
        while remaining:
            block=client.recv(remaining)
            if not block: raise RuntimeError('HPC broker returned a truncated response')
            chunks.append(block);remaining-=len(block)
    response=json.loads(b''.join(chunks))
    if not isinstance(response,dict) or type(response.get('returncode')) is not int:
        raise RuntimeError('HPC broker response schema is invalid')
    state_b64=response.get('helper_state_base64')
    helper_job_name=response.get('helper_job_name')
    if helper_job_name is not None and (not isinstance(helper_job_name,str) or not re.fullmatch(r'bench24-task159-[a-f0-9]{12}-[0-9]{2}',helper_job_name)):
        raise RuntimeError('HPC broker returned an invalid root helper logical name')
    if state_b64 is not None:
        try:
            state_raw=base64.b64decode(state_b64,validate=True);state_doc=json.loads(state_raw)
        except Exception as exc: raise RuntimeError('HPC broker returned malformed helper state') from exc
        if helper_job_name is None or state_doc.get('name')!=helper_job_name: raise RuntimeError('HPC broker helper state logical name differs from its root binding')
        state_dir=cwd/'.submit-job'
        if state_dir.is_symlink(): raise RuntimeError('local helper state destination cannot be a symlink')
        state_dir.mkdir(mode=0o700,exist_ok=True)
        state_path=state_dir/f'{helper_job_name}.json'
        if state_path.is_symlink(): raise RuntimeError('local helper state file cannot be a symlink')
        temp=state_path.with_name(state_path.name+'.tmp-'+uuid.uuid4().hex)
        temp.write_bytes(state_raw);os.chmod(temp,0o600);os.replace(temp,state_path)
    completed=subprocess.CompletedProcess(args,response['returncode'],str(response.get('stdout','')),str(response.get('stderr','')))
    completed.helper_job_name=helper_job_name
    completed.selection=response.get('selection')
    completed.admission_id=response.get('admission_id')
    return completed

def _hpc_dry_run(selection: dict, output: Path) -> dict:
    source=_hpc_helper_root();helper=source/"scripts"/"submit.py"
    if not helper.is_file(): return {"status":"NOT_RUN","reason":"image-bundled HPC helper is unavailable"}
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    trial=f"bench24-task159-runtime-check-{stamp.lower()}-{uuid.uuid4().hex[:6]}"
    record_dir=output/".bench24-task159-hpc"/trial;record_dir.mkdir(parents=True,exist_ok=False)
    root=_hpc_task_root(output,trial)
    probe_args=["probe","--host",selection["resource_id"],"--partition",selection["partition"],"--json","--detail"]
    probe=_hpc_invoke(probe_args,cwd=root,timeout=240,selection=selection)
    record={"schema":"case06-hpc-helper-plan/v1","native_md_executed":False,"submit_called":False,
        "trial_name":trial,"helper_root":str(root),"helper_state_dir":str(root/".submit-job")}
    if probe.returncode:
        record.update({"status":"NOT_RUN","reason":"HPC resource/runtime probe failed","probe_exit_code":probe.returncode,
            "probe_stderr_sha256":hashlib.sha256(probe.stderr.encode()).hexdigest()})
        write_json(record_dir/"result.json",record);return record
    selected=probe.selection;admission=probe.admission_id
    if not isinstance(selected,dict) or not admission:
        raise RuntimeError("root broker did not return its frozen resource admission")
    try:snapshot=json.loads(probe.stdout)
    except Exception:
        record.update({"status":"BLOCKED","reason":"HPC resource probe did not return valid JSON"})
        write_json(record_dir/"result.json",record);return record
    snapshot_sha=snapshot.get("snapshot_sha256")
    if (snapshot.get("host") not in (None,selected["resource_id"])
            or snapshot.get("request_partition") not in (None,selected["partition"])
            or not isinstance(snapshot_sha,str) or len(snapshot_sha)!=64):
        record.update({"status":"BLOCKED","reason":"HPC probe lacks selected endpoint/partition/hash identity"})
        write_json(record_dir/"result.json",record);return record
    probe_path=record_dir/"probe.json";probe_path.write_text(probe.stdout,encoding="utf-8")
    stage=record_dir/"payload";stage.mkdir()
    shutil.copy2(Path(__file__).resolve(),stage/"solve.sh")
    shutil.copytree(ASSET_ROOT.resolve(),stage/"assets"/"candidate-runtime")
    reason=record_dir/"reason.txt";reason.write_text("Task 159 resource/runtime qualification dry-run.\n",encoding="utf-8")
    attempt=json.loads(_HPC_PUBLIC_ATTEMPT.read_text(encoding="utf-8"));attempt_id=attempt["attempt_id"]
    remote_base=selected["remote_base"]
    workdir=remote_base+"/"+attempt_id+"/"+trial;solve=workdir+"/solve.sh";asset=workdir+"/assets/candidate-runtime"
    command=_remote_campaign_command(selected,workdir,attempt_id,asset,solve,selected["resources"]["wall_seconds"],True)
    res=selected["resources"];wall=res["wall_seconds"]
    base=["submit","--target",selected["target_name"],"--name",trial,"--cmd",command,"--reason-file",str(reason),
        "--probe-snapshot",str(probe_path),"--snapshot-sha256",snapshot_sha,"--src",str(stage),"--workdir",workdir,
        "--partition",selected["partition"],"--nodes",str(res["nodes"]),"--ntasks",str(res["ntasks"]),
        "--ntasks-per-node",str(res["ntasks"]),"--cpus",str(res["cpus"]),"--mem",f"{res['memory_mb']}M",
        "--gpus",str(res["gpus"]),"--time",f"{wall//3600:02d}:{wall%3600//60:02d}:{wall%60:02d}","--dry-run"]
    dry=_hpc_invoke(base,cwd=root,timeout=300,selection=selected,admission_id=admission)
    record.update({"status":"DRY_RUN" if dry.returncode==0 else "BLOCKED","selection":selected,
        "admission_id":admission,"helper_job_name":getattr(dry,"helper_job_name",None) or trial,
        "remote_workdir":workdir,"snapshot_sha256":snapshot_sha,"probe_file":str(probe_path),
        "payload_file_count":sum(1 for x in stage.rglob("*") if x.is_file()),"dry_run_exit_code":dry.returncode,
        "dry_run_stdout":dry.stdout[-3000:],"dry_run_stderr_sha256":hashlib.sha256(dry.stderr.encode()).hexdigest()})
    write_json(record_dir/"result.json",record);return record
def _hpc_submit_candidate(selection: dict, output: Path) -> dict:
    """Root-admit one selected resource, then dry-run and submit the frozen command."""
    record={"schema":"case06-hpc-candidate-submit/v1","native_md_executed":None,"submit_called":False}
    try:
        public=json.loads(_HPC_PUBLIC_ATTEMPT.read_text(encoding="utf-8"))
        if public.get("schema")!="case06-native-main-clock-public/v1": raise ValueError("unsupported public capture")
        attempt_id=str(public["attempt_id"])
    except (OSError,KeyError,TypeError,ValueError):
        return {**record,"status":"BLOCKED","reason":"root-captured attempt identity is unavailable"}
    root_source=_hpc_helper_root();helper=root_source/"scripts"/"submit.py"
    if not helper.is_file(): return {**record,"status":"NOT_RUN","reason":"image-bundled HPC helper is unavailable"}
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    trial=f"bench24-task159-{stamp.lower()}-{uuid.uuid4().hex[:8]}"
    record_dir=output/".bench24-task159-hpc"/trial;record_dir.mkdir(parents=True,exist_ok=False)
    root=_hpc_task_root(output,trial)
    probe_args=["probe","--host",selection["resource_id"],"--partition",selection["partition"],"--json","--detail"]
    probe=_hpc_invoke(probe_args,cwd=root,timeout=240,selection=selection)
    if probe.returncode:
        result={**record,"status":"NOT_RUN","reason":"selected endpoint/resource/runtime qualification failed",
            "probe_exit_code":probe.returncode,"probe_stderr_sha256":hashlib.sha256(probe.stderr.encode()).hexdigest()}
        write_json(record_dir/"result.json",result);return result
    selected=probe.selection;admission=probe.admission_id
    if not isinstance(selected,dict) or not isinstance(admission,str) or not re.fullmatch(r"[0-9a-f]{32}",admission):
        raise RuntimeError("root broker did not return a frozen admission for the selected resource")
    try:snapshot=json.loads(probe.stdout)
    except Exception:
        result={**record,"status":"BLOCKED","reason":"fresh helper probe was not JSON"};write_json(record_dir/"result.json",result);return result
    snapshot_sha=snapshot.get("snapshot_sha256")
    if (snapshot.get("host") not in (None,selected["resource_id"])
            or snapshot.get("request_partition") not in (None,selected["partition"])
            or not isinstance(snapshot_sha,str) or len(snapshot_sha)!=64):
        result={**record,"status":"BLOCKED","reason":"probe endpoint/partition/canonical snapshot identity is invalid"};write_json(record_dir/"result.json",result);return result
    probe_path=record_dir/"probe.json";probe_path.write_text(probe.stdout,encoding="utf-8")
    stage=record_dir/"payload";stage.mkdir()
    shutil.copy2(Path(__file__).resolve(),stage/"solve.sh")
    shutil.copytree(ASSET_ROOT.resolve(),stage/"assets"/"candidate-runtime")
    reason=record_dir/"reason.txt";reason.write_text("Task 159 candidate single-state campaign; no grader-only A data.\n",encoding="utf-8")
    remote_base=selected["remote_base"];workdir=remote_base+"/"+attempt_id+"/"+trial
    solve=workdir+"/solve.sh";asset=workdir+"/assets/candidate-runtime"
    res=selected["resources"];wall=min(res["wall_seconds"],max(0,(int(public["deadline_monotonic_ns"])-time.monotonic_ns())//1_000_000_000-300))
    if wall<=0: return {**record,"status":"NOT_RUN","reason":"no bounded active allocation time remains"}
    runtime_selection={**selected,"resources":{**res,"wall_seconds":wall}}
    command=_remote_campaign_command(runtime_selection,workdir,attempt_id,asset,solve,wall,False)
    wall_text=f"{wall//3600:02d}:{wall%3600//60:02d}:{wall%60:02d}"
    target=selected["target_name"]
    base=["submit","--target",target,"--name",trial,"--cmd",command,"--reason-file",str(reason),
        "--probe-snapshot",str(probe_path),"--snapshot-sha256",snapshot_sha,"--src",str(stage),"--workdir",workdir,
        "--partition",selected["partition"],"--nodes",str(res["nodes"]),"--ntasks",str(res["ntasks"]),
        "--ntasks-per-node",str(res["ntasks"]),"--cpus",str(res["cpus"]),"--mem",f"{res['memory_mb']}M",
        "--gpus",str(res["gpus"]),"--time",wall_text]
    dry=_hpc_invoke(base+["--dry-run"],cwd=root,timeout=300,selection=selected,admission_id=admission)
    if dry.returncode:
        result={**record,"status":"NOT_RUN","reason":"matching helper dry-run rejected selected command",
            "trial_name":trial,"selection":selected,"admission_id":admission,"remote_workdir":workdir,
            "snapshot_sha256":snapshot_sha,"dry_run_exit_code":dry.returncode,"dry_run_stdout":dry.stdout[-3000:],
            "dry_run_stderr_sha256":hashlib.sha256(dry.stderr.encode()).hexdigest()}
        write_json(record_dir/"result.json",result);return result
    submitted=_hpc_invoke(base,cwd=root,timeout=300,selection=selected,admission_id=admission)
    try: parsed=json.loads(submitted.stdout)
    except Exception: parsed={}
    job_id=parsed.get("job_id") or parsed.get("jobid") or parsed.get("id")
    result={**record,"status":"SUBMITTED" if submitted.returncode==0 and job_id else "SUBMIT_UNKNOWN",
        "submit_called":True,"submit_exit_code":submitted.returncode,"trial_name":trial,"selection":selected,
        "admission_id":admission,"job_id":job_id,"remote_workdir":workdir,"snapshot_sha256":snapshot_sha,
        "probe_file":str(probe_path),"payload_file_count":sum(1 for x in stage.rglob("*") if x.is_file()),
        "dry_run_stdout":dry.stdout[-3000:],"submit_stdout":submitted.stdout[-5000:],
        "submit_stderr_sha256":hashlib.sha256(submitted.stderr.encode()).hexdigest(),
        "helper_state_dir":str(root/".submit-job"),"helper_root":str(root),
        "helper_job_name":getattr(submitted,"helper_job_name",None) or trial}
    write_json(record_dir/"result.json",result);return result
def _hpc_lifecycle(mode: str, job: str, output: Path, poll: int, timeout: int,
                  search_root: Path | None=None) -> dict:
    lookup_root=search_root or output
    saved=_hpc_record_for_job(lookup_root,job)
    root=_hpc_helper_for_job(lookup_root,job)
    helper_job=(saved.get("helper_job_name") or saved.get("trial_name") or saved.get("job_name")
                if saved else job)
    if mode not in {"status","wait","collect","cancel"}: raise ValueError("unsupported HPC lifecycle action")
    record={"schema":"case06-hpc-lifecycle/v1","action":mode,"job":job,
            "helper_job_name":helper_job,"job_id":saved.get("job_id") if saved else job,
            "native_md_executed":None}
    if mode=="collect":
        if output.exists(): return {**record,"status":"BLOCKED","reason":"collect destination already exists"}
        output.parent.mkdir(parents=True,exist_ok=True)
        cmd=["collect","--job",helper_job,"--dest",str(output),"--allow-unsuccessful"]
    elif mode=="status": cmd=["status","--job",helper_job]
    elif mode=="cancel": cmd=["cancel","--job",helper_job]
    else: cmd=["wait","--job",helper_job,"--poll",str(poll),"--timeout",str(timeout)]
    try: result=_hpc_invoke(cmd,cwd=root,timeout=max(timeout+60,120) if mode=="wait" else 300, selection=saved.get("selection") if saved else None, admission_id=saved.get("admission_id") if saved else None)
    except InterruptedError: raise
    except Exception as exc:return {**record,"status":"NOT_RUN","reason":f"{type(exc).__name__}"}
    record.update({"status":"OK" if result.returncode==0 else "FAILED","exit_code":result.returncode,
        "stdout":result.stdout[-8000:],"stderr_sha256":hashlib.sha256(result.stderr.encode()).hexdigest()})
    raw_dir=(search_root or output)/".bench24-task159-hpc"/"lifecycle-raw"
    raw_dir.mkdir(parents=True,exist_ok=True)
    raw_path=raw_dir/f"{time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())}-{mode}-{uuid.uuid4().hex[:8]}.stdout"
    raw_path.write_bytes(result.stdout.encode("utf-8"))
    record["stdout_path"]=str(raw_path)
    record["stdout_sha256"]=hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if mode=="collect" and result.returncode==0: record["collected_path"]=str(output)
    record_root=(search_root or output)/".bench24-task159-hpc"/"lifecycle"
    record_root.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    record_path=record_root/f"{stamp}-{mode}-{uuid.uuid4().hex[:8]}.json"
    record["record_path"]=str(record_path)
    record_path.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return record

def _hpc_stdout_json(record: dict) -> dict | None:
    path=Path(record.get("stdout_path",""))
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=record.get("stdout_sha256"):
        return None
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError): return None
    return value if isinstance(value,dict) else None

def _hpc_state_for_trial(trial_dir: Path) -> tuple[str | None, dict | None, Path | None]:
    try:
        saved=json.loads((trial_dir/"result.json").read_text(encoding="utf-8"))
        helper_job=saved.get("helper_job_name") or saved.get("trial_name")
        state_path=Path(saved["helper_root"])/".submit-job"/f"{helper_job}.json"
        state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
        return helper_job,state,state_path if state_path.is_file() else None
    except (OSError,ValueError,KeyError,TypeError):
        return None,None,None

def _hpc_find_sacct_receipt(value: Any) -> dict | None:
    if isinstance(value,dict):
        if str(value.get("schema",value.get("receipt_schema",""))).endswith("slurm-sacct-receipt/v1") and isinstance(value.get("sacct_rows_base64"),str):
            return value
        for key in ("receipt","sacct_receipt","scheduler_receipt","terminal_receipt","result","state"):
            found=_hpc_find_sacct_receipt(value.get(key))
            if found:return found
        for key in ("results","records"):
            rows=value.get(key)
            if isinstance(rows,list):
                for row in rows:
                    found=_hpc_find_sacct_receipt(row)
                    if found:return found
    return None

def _hpc_validate_sacct(receipt: dict, job: str) -> dict:
    if not str(receipt.get("schema",receipt.get("receipt_schema",""))).endswith("slurm-sacct-receipt/v1"):
        raise ValueError("helper did not provide the pinned sacct receipt schema")
    raw=base64.b64decode(receipt["sacct_rows_base64"],validate=True)
    raw_sha=hashlib.sha256(raw).hexdigest()
    if raw_sha!=receipt.get("sacct_rows_sha256"):raise ValueError("sacct raw row bytes fail SHA binding")
    lines=[line for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(lines)!=1:raise ValueError("sacct receipt must contain one allocation row")
    cols=lines[0].split("|")
    if len(cols)!=9:raise ValueError("sacct row must contain nine columns")
    fields={"JobIDRaw":cols[0].strip(),"Partition":cols[1].strip(),"AllocTRES":cols[3].strip(),
            "Elapsed":cols[5].strip(),"State":cols[7].strip(),"ExitCode":cols[8].strip()}
    if any(str(receipt.get(k," ")).strip()!=v for k,v in fields.items()):
        raise ValueError("sacct receipt fields differ from the hash-bound raw row")
    if fields["JobIDRaw"]!=str(job):raise ValueError("sacct receipt belongs to another Slurm job")
    if fields["State"].upper() not in ("COMPLETED","FAILED","CANCELLED","TIMEOUT"):
        raise ValueError("sacct allocation state is not terminal")
    if not re.fullmatch(r"\d+:\d+",fields["ExitCode"]):raise ValueError("sacct exit code is malformed")
    match=re.fullmatch(r"(?:(\d+)-)?(\d{1,3}):(\d{2}):(\d{2})",fields["Elapsed"])
    if not match:raise ValueError("sacct elapsed time is malformed")
    days,hours,minutes,seconds=(int(x) if x else 0 for x in match.groups())
    fields.update({"elapsed_seconds":days*86400+hours*3600+minutes*60+seconds,
                   "exit_code_int":int(fields["ExitCode"].split(":",1)[0]),"raw_rows_sha256":raw_sha})
    return fields

def _hpc_output_manifest(outputs: Path) -> dict:
    files=[]
    for path in sorted(outputs.rglob("*")):
        if path.is_file() and path.name not in ("outputs-manifest.json","summary.json","campaign-evidence.json"):
            files.append({"path":path.relative_to(outputs).as_posix(),"sha256":sha(path),"size_bytes":path.stat().st_size})
    return {"schema":"case06-campaign-output-manifest/v1","files":files}

def _hpc_bind_collected_attempt(outputs: Path, collection: Path, trial_dir: Path,
                                helper_job: str, job_id: str, wait: dict, status: dict) -> dict:
    """Bind collector-returned batch timestamps to a hash-verified terminal sacct receipt."""
    starts=list(collection.rglob("job-start.txt"));finishes=list(collection.rglob("job-finish.txt"))
    if len(starts)!=1 or len(finishes)!=1:
        return {"status":"UNKNOWN","reason":"batch-shell start/EXIT-trap records are absent or ambiguous"}
    try:
        start_src,finish_src=starts[0],finishes[0]
        sf=dict(line.split("=",1) for line in start_src.read_text(encoding="utf-8").splitlines() if "=" in line)
        ef=dict(line.split("=",1) for line in finish_src.read_text(encoding="utf-8").splitlines() if "=" in line)
        start=datetime.datetime.fromisoformat(sf["started_utc"].replace("Z","+00:00"))
        end=datetime.datetime.fromisoformat(ef["ended_utc"].replace("Z","+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end<start:raise ValueError("invalid batch UTC interval")
        if sf.get("job_id")!=str(job_id) or ef.get("job_id")!=str(job_id):raise ValueError("batch records bind a different job")
        wait_obj=_hpc_stdout_json(wait);status_obj=_hpc_stdout_json(status)
        _, helper_state, _ = _hpc_state_for_trial(trial_dir)
        receipt=(_hpc_find_sacct_receipt(wait_obj) or _hpc_find_sacct_receipt(status_obj)
                 or _hpc_find_sacct_receipt(helper_state))
        if not receipt:raise ValueError("wait/status/helper state has no terminal sacct receipt")
        sacct=_hpc_validate_sacct(receipt,str(job_id))
        shell_rc=int(ef["exit_code"])
        if shell_rc!=sacct["exit_code_int"]:raise ValueError("batch exit status differs from sacct ExitCode")
        if (sacct["State"].upper()=="COMPLETED")!=(shell_rc==0):raise ValueError("batch exit and sacct state disagree")
        elapsed=(end-start).total_seconds()
        if abs(elapsed-sacct["elapsed_seconds"])>max(120.0,.05*max(elapsed,sacct["elapsed_seconds"])):
            raise ValueError("batch-shell interval and sacct Elapsed differ materially")
    except Exception as exc:
        return {"status":"UNKNOWN","reason":f"terminal scheduler source is incomplete or inconsistent ({type(exc).__name__})"}

    provenance=outputs/"provenance";provenance.mkdir(parents=True,exist_ok=True)
    kernel_start=provenance/"outer-job-start.txt"
    if kernel_start.is_file():shutil.copy2(kernel_start,provenance/"controller-observed-start.txt")
    copied_start=provenance/"outer-job-start.txt";copied_finish=provenance/"outer-job-finish.txt"
    shutil.copy2(start_src,copied_start);shutil.copy2(finish_src,copied_finish)
    def ref(path):return {"path":path.relative_to(outputs).as_posix(),"sha256":sha(path)}
    helper_stdout_refs={}
    for label,record in (("wait",wait),("status",status)):
        raw=Path(record.get("stdout_path",""))
        if raw.is_file() and hashlib.sha256(raw.read_bytes()).hexdigest()==record.get("stdout_sha256"):
            target=provenance/f"hpc-{label}-stdout.bin";shutil.copy2(raw,target)
            helper_stdout_refs[label]=ref(target)
    helper_state=None
    _,state_obj,state_path=_hpc_state_for_trial(trial_dir)
    if state_path and state_path.is_file():
        state_target=provenance/"hpc-helper-state.json";shutil.copy2(state_path,state_target);helper_state=ref(state_target)
    terminal={"schema":"case06-batch-shell-terminal-binding/v1","job_id":str(job_id),
        "state":sacct["State"].upper(),"exit_code":sacct["exit_code_int"],
        "started_utc":sf["started_utc"],"ended_utc":ef["ended_utc"],
        "elapsed_seconds":sacct["elapsed_seconds"],"timestamp_origin":"batch_shell_observed",
        "batch_shell_start_ref":ref(copied_start),"batch_shell_finish_ref":ref(copied_finish),
        "sacct_receipt":receipt,"sacct_raw_rows_sha256":sacct["raw_rows_sha256"],
        "helper_stdout_refs":helper_stdout_refs,"helper_state_ref":helper_state}
    for value in (wait_obj,status_obj,state_obj):
        if isinstance(value,dict) and isinstance(value.get("resource_evidence"),dict):
            terminal["resource_evidence"]=value["resource_evidence"];break
    terminal_path=provenance/"outer-job-terminal.json";write_json(terminal_path,terminal)
    terminal_ref=ref(terminal_path);elapsed=(end-start).total_seconds();reserve=0.0

    resource_path=outputs/"resource-receipt.json";resource=json.loads(resource_path.read_text(encoding="utf-8"))
    execution=resource.setdefault("execution",{})
    reference_active=execution.get("reference_active_seconds")
    if isinstance(reference_active,bool) or not isinstance(reference_active,(int,float)) or not math.isfinite(float(reference_active)) or reference_active < 0:
        raise RuntimeError("host reference active interval is absent from candidate resource receipt")
    reference_active=float(reference_active)
    total_active=reference_active+elapsed
    clock_path=outputs/"campaign-clock.json";clock=json.loads(clock_path.read_text(encoding="utf-8"))
    clock.update({"scheduler_job_id":str(job_id),"outer_job_finish_status":"COLLECTED_AND_HASH_BOUND",
        "outer_job_finish_ref":terminal_ref,"candidate_active_elapsed_seconds":elapsed,
        "reference_active_seconds":reference_active,"active_elapsed_seconds":total_active,
        "active_limit_remaining_seconds":max(0.0,43200.0-total_active)})
    write_json(clock_path,clock);clock_ref=ref(clock_path)
    remaining=max(0.0,43200.0-total_active)
    execution.update({"active_elapsed_seconds":total_active,"candidate_active_elapsed_seconds":elapsed,
        "reference_active_seconds":reference_active,"active_unlocated_reserve_seconds":reserve,
        "active_limit_remaining_seconds":remaining,
        "source":"host reference interval plus batch-shell-observed candidate allocation, cross-checked against hash-bound sacct Elapsed",
        "controller_clock":clock_ref,"outer_job_start":ref(copied_start),
        "outer_job_finish_status":"COLLECTED_AND_HASH_BOUND","outer_job_finish_ref":terminal_ref,
        "extra_active_interval_sources":[]})
    write_json(resource_path,resource);resource_ref=ref(resource_path)
    summary_path=outputs/"summary.json"
    if summary_path.is_file():
        summary=json.loads(summary_path.read_text(encoding="utf-8"));summary["active_elapsed_seconds"]=total_active
        summary["active_runtime_cap_seconds"]=43200;summary["remaining_budget"]={**summary.get("remaining_budget",{}),"active_seconds":remaining}
        summary["campaign_clock"]=clock_ref;summary["resource_receipt"]=resource_ref;write_json(summary_path,summary)
    allocation_path=outputs/"allocation_log.json"
    if allocation_path.is_file():
        allocation=json.loads(allocation_path.read_text(encoding="utf-8"));budget=allocation.get("budget")
        if isinstance(budget,dict):budget.update({"active_elapsed_seconds":total_active,
            "candidate_active_elapsed_seconds":elapsed,"reference_active_seconds":reference_active,
            "active_limit_seconds":43200,"active_limit_remaining_seconds":remaining,
            "active_unlocated_reserve_seconds":reserve})
        write_json(allocation_path,allocation)
    evidence_path=outputs/"campaign-evidence.json"
    if evidence_path.is_file():
        evidence=json.loads(evidence_path.read_text(encoding="utf-8"));budget=evidence.get("budget")
        if isinstance(budget,dict):budget.update({"active_elapsed_seconds":total_active,
            "candidate_active_elapsed_seconds":elapsed,"reference_active_seconds":reference_active,
            "active_limit_seconds":43200,"active_limit_remaining_seconds":remaining,
            "active_unlocated_reserve_seconds":reserve})
        evidence["resource_receipt"]=resource_ref
        manifest_path=outputs/"outputs-manifest.json";write_json(manifest_path,_hpc_output_manifest(outputs))
        evidence["candidate_manifest"]=ref(manifest_path);write_json(evidence_path,evidence)
        write_json(manifest_path,_hpc_output_manifest(outputs))
    else:write_json(outputs/"outputs-manifest.json",_hpc_output_manifest(outputs))
    return {"status":"BOUND","terminal_receipt":terminal_ref,"state":sacct["State"].upper(),
            "elapsed_seconds":elapsed,"reference_active_seconds":reference_active,
            "total_active_seconds":total_active,"job_id":str(job_id)}

def _hpc_cancel_owned_submission(submission: dict, outputs: Path) -> dict:
    """Cancel only the exact logical job created by this solve invocation."""
    trial=submission.get("trial_name")
    job=str(submission.get("job_id") or "")
    if (not trial or not job or submission.get("status")!="SUBMITTED"
            or submission.get("submit_called") is not True):
        return {"status":"NOT_RUN","reason":"submission is not an identity-bound owned job"}
    trial_dir=outputs/".bench24-task159-hpc"/str(trial)
    try:
        saved=json.loads((trial_dir/"result.json").read_text(encoding="utf-8"))
        helper_job=submission.get("helper_job_name")
        if (saved.get("trial_name")!=trial or saved.get("helper_job_name")!=helper_job
                or not isinstance(helper_job,str) or str(saved.get("job_id"))!=job
                or saved.get("submit_called") is not True or saved.get("status")!="SUBMITTED"):
            raise ValueError("saved submission identity does not match this trial")
        state_job,state,_=_hpc_state_for_trial(trial_dir)
        if (state_job!=helper_job or not isinstance(state,dict) or state.get("name")!=helper_job
                or str(state.get("job_id"))!=job):
            raise ValueError("helper state does not bind the root logical name and numeric job id")
        receipt=_hpc_find_sacct_receipt(state)
        if receipt is not None:
            _hpc_validate_sacct(receipt,job)
            return {"status":"NOT_RUN","reason":"owned job already has a terminal scheduler receipt"}
        record=_hpc_lifecycle("cancel",trial,outputs,1,60,outputs)
        record["job_id"]=job
        return record
    except Exception as exc:
        return {"status":"BLOCKED","reason":f"owned-job cancellation could not be safely bound ({type(exc).__name__})"}

def _hpc_reference_run_submitted(selection: dict, outputs: Path,
                                 poll: int, timeout: int, submission: dict) -> dict:
    """Wait for one already-submitted job, then collect its hash-bound result."""
    job=submission.get("job_id")
    if submission.get("status")!="SUBMITTED" or not job:
        return {"status":submission.get("status","NOT_RUN"),"submission":submission,
                "candidate_outputs_collected":False}
    deadline_epoch=int(json.loads(_HPC_PUBLIC_ATTEMPT.read_text(encoding="utf-8"))["deadline_epoch"])
    if not deadline_epoch:
        return {"status":"BLOCKED","job_id":job,"submission":submission,
                "candidate_outputs_collected":False,"reason":"host-bound attempt deadline is unavailable"}
    wait_budget=min(604800, max(timeout, int(deadline_epoch-time.time()-240)))
    wait=_hpc_lifecycle("wait",job,outputs,poll,wait_budget,outputs)
    status_remaining=max(1, min(604800, int(deadline_epoch-time.time()-60)))
    status_budget=min(300, status_remaining)
    status=_hpc_lifecycle("status",job,outputs,poll,status_budget,outputs)
    control_root=outputs/".bench24-task159-hpc"
    trial_dir=None
    if control_root.is_dir():
        for candidate in sorted(control_root.iterdir()):
            result_path=candidate/"result.json"
            if not candidate.is_dir() or not result_path.is_file(): continue
            try: saved=json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError,ValueError): continue
            if saved.get("job_id")==job:
                trial_dir=candidate
                break
    if trial_dir is None:
        return {"status":"COLLECT_BLOCKED","job_id":job,"submission":submission,"wait":wait,"status_check":status,
                "reason":"trial helper state could not be resolved"}
    try:
        wait_obj=_hpc_stdout_json(wait);status_obj=_hpc_stdout_json(status)
        _,helper_state,_=_hpc_state_for_trial(trial_dir)
        terminal_sacct=(_hpc_find_sacct_receipt(wait_obj) or _hpc_find_sacct_receipt(status_obj)
                        or _hpc_find_sacct_receipt(helper_state))
        if not terminal_sacct:raise ValueError("terminal sacct receipt absent")
        _hpc_validate_sacct(terminal_sacct,str(job))
    except Exception as exc:
        cancellation=_hpc_cancel_owned_submission(submission,outputs)
        return {"schema":"case06-hpc-reference-run/v1","status":"TERMINAL_UNKNOWN",
            "job_id":job,"submission":submission,"wait":wait,"status_check":status,
            "candidate_outputs_collected":False,"cancellation":cancellation,
            "reason":f"terminal scheduler state unavailable ({type(exc).__name__}); no collection attempted"}
    collection=trial_dir/"collected"
    collect=_hpc_lifecycle("collect",job,collection,poll,timeout,outputs)
    result={"schema":"case06-hpc-reference-run/v1","status":"COLLECTED" if collect.get("status")=="OK" else "COLLECT_FAILED",
            "job_id":job,"submission":submission,"wait":wait,"status_check":status,"collect":collect,
            "candidate_outputs_collected":False}
    if collect.get("status")!="OK": return result
    evidence=next(iter(collection.rglob("campaign-evidence.json")),None)
    if evidence is None: return {**result,"status":"COLLECTED_WITHOUT_CANDIDATE_EVIDENCE"}
    collected_root=evidence.parent
    outputs.mkdir(parents=True,exist_ok=True)
    existing=list(outputs.iterdir())
    control_root=outputs/".bench24-task159-hpc"
    control_entries={path.name:path for path in control_root.iterdir()} if control_root.is_dir() and not control_root.is_symlink() else {}
    allowed_names={trial_dir.name}
    lifecycle_ok=True
    for name in ("lifecycle", "lifecycle-raw"):
        path=control_entries.get(name)
        if path is None:
            continue
        if (not path.is_dir() or path.is_symlink()
                or any(not child.is_file() or child.is_symlink() for child in path.iterdir())):
            lifecycle_ok=False
            break
        allowed_names.add(name)
    allowed_control=(control_root.is_dir() and not control_root.is_symlink() and lifecycle_ok
        and set(control_entries)==allowed_names)
    if any(item.name!=".bench24-task159-hpc" for item in existing) or (existing and not allowed_control):
        return {**result,"status":"COLLECTED_BUT_OUTPUT_DESTINATION_NOT_EMPTY"}
    for item in collected_root.iterdir():
        target_path=outputs/item.name
        if item.is_dir():shutil.copytree(item,target_path)
        elif item.is_file():shutil.copy2(item,target_path)
    saved_submission=json.loads((trial_dir/"result.json").read_text(encoding="utf-8"))
    helper_job=saved_submission.get("helper_job_name") or saved_submission.get("trial_name")
    binding=_hpc_bind_collected_attempt(outputs,collection,trial_dir,helper_job,str(job),wait,status)
    result.update({"candidate_outputs_collected":True,"outputs":str(outputs),
                   "candidate_status":json.loads((outputs/"summary.json").read_text()).get("status") if (outputs/"summary.json").is_file() else "UNKNOWN",
                   "terminal_binding":binding,
                   "status":"COLLECTED" if binding.get("status")=="BOUND" else "COLLECTED_TERMINAL_UNKNOWN"})
    record_path=trial_dir/"result.json"
    write_json(record_path,{**json.loads(record_path.read_text()),"job_id":job,"wait":wait,"status_check":status,"collect":collect})
    return result

def _hpc_reference_run(selection: dict, outputs: Path, poll: int, timeout: int) -> dict:
    """Submit once and ensure interruption can cancel only that bound job."""
    submission=_hpc_submit_candidate(selection,outputs)
    if submission.get("status")!="SUBMITTED":
        return {"status":submission.get("status","NOT_RUN"),"submission":submission,
                "candidate_outputs_collected":False}
    previous=None
    installed=False
    if threading.current_thread() is threading.main_thread():
        previous=signal.getsignal(signal.SIGTERM)
        def interrupt(signum, frame):
            raise InterruptedError(f"solve interrupted by signal {signum}")
        signal.signal(signal.SIGTERM,interrupt)
        installed=True
    try:
        return _hpc_reference_run_submitted(selection,outputs,poll,timeout,submission)
    except BaseException:
        _hpc_cancel_owned_submission(submission,outputs)
        raise
    finally:
        if installed:
            signal.signal(signal.SIGTERM,previous)

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Task 159 candidate solve; local preflight uses only the Python standard library.")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--outputs", type=Path, default=Path(os.environ.get("CASE06_OUTPUTS", "outputs")))
    parser.add_argument("--run", action="store_true", help="fresh-probe, dry-run, and submit the candidate campaign through the bundled HPC helper")
    parser.add_argument("--hpc-submit", action="store_true", help="same as --run; submits one candidate campaign after fresh probe and dry-run")
    parser.add_argument("--hpc-dry-run", action="store_true", help="probe the bundled helper and dry-run a no-MD remote runtime check")
    parser.add_argument("--resource-id", help="root-authorized SSH alias selected for this attempt")
    parser.add_argument("--partition", help="partition selected for this attempt")
    parser.add_argument("--remote-base", default=None, help="optional directory under the selected account home")
    parser.add_argument("--remote-python", default=None, help="optional absolute Python path; otherwise discovered from the selected endpoint")
    parser.add_argument("--remote-lmp", default=None, help="optional absolute LAMMPS path; otherwise discovered from the selected endpoint")
    parser.add_argument("--module", action="append", default=[], help="module token loaded on the selected endpoint (repeatable)")
    parser.add_argument("--cpus", type=int, default=1)
    parser.add_argument("--memory-mb", type=int, default=8192)
    parser.add_argument("--gpus", type=int, choices=(0,1), default=1)
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--hpc-status", metavar="JOB")
    parser.add_argument("--hpc-wait", metavar="JOB")
    parser.add_argument("--hpc-collect", metavar="JOB")
    parser.add_argument("--collect-dest", type=Path)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--wait-timeout", type=int, default=604800)
    args = parser.parse_args(argv)
    default_full_run = not (args.preflight or args.hpc_dry_run or args.hpc_submit or args.run
        or args.hpc_status or args.hpc_wait or args.hpc_collect)
    needs_selection = bool(default_full_run or args.hpc_dry_run or args.hpc_submit or args.run)
    selection=None
    if needs_selection:
        try: selection=_resource_selection(args)
        except Exception as exc: parser.error(str(exc))
    if default_full_run:
        args.run = True
    if args.hpc_submit:
        result = _hpc_submit_candidate(selection, args.outputs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status") == "SUBMITTED" else 2
    if args.hpc_dry_run:
        record=_hpc_dry_run(selection,args.outputs)
        print(json.dumps(record,indent=2,ensure_ascii=False))
        return 0 if record.get("status")=="DRY_RUN" else 2
    for mode,job in (("status",args.hpc_status),("wait",args.hpc_wait),("collect",args.hpc_collect)):
        if job:
            if mode=="collect" and args.collect_dest is None:
                print(json.dumps({"status":"BLOCKED","reason":"--hpc-collect requires --collect-dest"}))
                return 2
            dest=args.collect_dest if mode=="collect" else args.outputs
            record=_hpc_lifecycle(mode,job,dest,args.poll_seconds,args.wait_timeout,args.outputs)
            print(json.dumps(record,indent=2,ensure_ascii=False))
            return 0 if record.get("status")=="OK" else 2
    try:
        if args.run:
            result=preflight_static()
            if default_full_run:
                run_result=_hpc_reference_run(selection,args.outputs,args.poll_seconds,args.wait_timeout)
                print(json.dumps(run_result,indent=2,ensure_ascii=False))
                return 0 if run_result.get("candidate_outputs_collected") else 2
            submission=_hpc_submit_candidate(selection,args.outputs)
            print(json.dumps(submission,indent=2,ensure_ascii=False))
            return 0 if submission.get("status")=="SUBMITTED" else 2
        result = preflight_static()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        result = {"schema": "case06-single-solve-preflight/v1", "status": "BLOCKED", "native_md_executed": False,
                  "reason": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2

if "--kernel" in sys.argv:

    # Direct source merge: campaign_adapter.py; namespace prefix ca_
    """Production facade from the global controller to the reviewed Calphy driver.

    All gate decisions are delegated to the payload's independent source replay API.
    Missing replay APIs or source references are UNKNOWN and stop the campaign.
    """
    import hashlib as ca_hashlib, importlib.util as ca_importlib, json as ca_json, os as ca_os, shutil as ca_shutil, subprocess as ca_subprocess, sys as ca_sys, types as ca_types, types as fc_types
    from pathlib import Path as ca_Path
    ca_HERE = ca_Path(__file__).resolve().parent
    ca_PAYLOAD = ASSET_ROOT
    ca_MATRIX_SHA = '58599733bcecb0017d0863e1054ba9311858f8e6b986713af064be737e5c5d9e'
    ca__ZERO_CACHE = {}

    def ca_sha(p):
        h = ca_hashlib.sha256()
        with ca_Path(p).open('rb') as f:
            for b in iter(lambda : f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    def ca_ref(p, root):
        p = ca_Path(p).resolve()
        root = ca_Path(root).resolve()
        try:
            return {'path': p.relative_to(root).as_posix(), 'sha256': ca_sha(p)}
        except ValueError:
            raise RuntimeError(f'artifact escapes output root: {p}')

    def ca__load(name, path=None):
        """Direct namespace access to definitions merged into this source file."""
        if name == 'case06_fullcell_driver':
            return ca_types.SimpleNamespace(validate_run0_prerequisite=drv_validate_run0_prerequisite,
                prepare_one_phase=drv_prepare_one_phase, run_one_fe_cycle=drv_run_one_fe_cycle,
                _state_from_ready_record=drv__state_from_ready_record)
        if name == 'case06_native_zero_md':
            return ca_types.SimpleNamespace(main=zero_main, run_case=zero_run_case)
        raise RuntimeError(f'unsupported direct merged namespace: {name}')

    def ca__require_candidate_role(role):
        if role == 'A' and ca_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') == '1':
            return
        if role not in {'B', 'R', 'S', 'D'}:
            raise RuntimeError('candidate solve supports only B/R/adaptive D-or-S; A requires the host-owned private worker')

    def ca__prepare_role_tree(run_root, role):
        root = ca_Path(run_root).resolve()
        native = root / 'native_inputs'
        native.mkdir(parents=True, exist_ok=True)
        for p in (ca_PAYLOAD / 'native_inputs').iterdir():
            if p.is_file():
                ca_shutil.copy2(p, native / p.name)
        (root / 'acceptance').mkdir(parents=True, exist_ok=True)
        ca__require_candidate_role(role)
        if role == 'D':
            raise RuntimeError('duration route reuses B pre-FE state and must not create a fresh setup')
        registry = ca_json.loads((ca_PAYLOAD / 'native_inputs' / 'candidate-seed-registration.json').read_text())
        source_matrix_sha = ca_json.loads((ca_PAYLOAD / 'candidate-scope.json').read_text())['source_matrix_sha256']
        if role == 'A':
            if ca_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') != '1':
                raise RuntimeError('A role is available only to the host-owned private worker')
            seeds = ca_json.loads(ca_os.environ['CASE06_AUTHOR_SEEDS'])
            if set(seeds) != {'alpha_quartz', 'coesite'} or len({int(x) for x in seeds.values()}) != 2:
                raise RuntimeError('author seed registration must contain two distinct phase seeds')
            template = native / 'input-template-A.json'
            source_template = native / 'input-template.json'
            doc = ca_json.loads(source_template.read_text())
            doc['role'] = 'A'
            for phase_index, phase in enumerate(('alpha_quartz', 'coesite')):
                calc = doc['calculations'][phase_index]
                calc['md']['seed'] = int(seeds[phase])
                calc['pair_style'] = 'pace product'
                calc['md']['cmdargs'] = ''
                calc['md']['init_commands'] = ['atom_style atomic']
            template.write_text(ca_json.dumps(doc, indent=2, sort_keys=True) + '\n')
            template_ref = {'path': template.name, 'sha256': ca_sha(template)}
        else:
            template_ref = registry['templates'][role]
            template = native / template_ref['path']
            if not template.is_file() or ca_sha(template) != template_ref['sha256']:
                raise RuntimeError('candidate role template differs from its frozen seed registry')
            seeds = registry['candidate_roles'][role]
        role_registration = {'schema':'case06-role-seed-registration/v1','role':role,
            'matrix_sha256':source_matrix_sha,'runtime_template_path':str(template.relative_to(root)),
            'runtime_template_sha256':ca_sha(template),
            'input_sha256':ca_sha(template),
            'phases':[{'phase':phase,'master_seed':int(seeds[phase])}
                      for phase in ('alpha_quartz','coesite')]}
        (native / f'seed-registration-{role}.json').write_text(
            ca_json.dumps(role_registration,indent=2,sort_keys=True)+'\n')
        return root

    def ca__runtime(template, run_root, role):
        root = ca__prepare_role_tree(run_root, role)
        template = ca_Path(template)
        registered = root / 'native_inputs' / f'input-template-{role}.json'
        if role == 'A':
            source_template = root / 'native_inputs' / 'input-template.json'
            if (template.name != 'input-template.json' or not template.is_file()
                    or ca_sha(template) != ca_sha(source_template) or not registered.is_file()):
                raise RuntimeError('private A renderer must use its registered phase-seed/CPU template')
            template = registered
        elif template.resolve() != registered.resolve():
            ca_shutil.copy2(template, registered)
            template = registered
        wrapper = ca_os.environ.get('CASE08_WRAPPER')
        if not wrapper:
            raise RuntimeError('CASE08_WRAPPER is required for guarded production execution')
        potential = root / 'native_inputs' / 'SiOx_potential.yace'
        out = root / 'native_inputs' / f'input-{role}.yaml'
        cfg_main(['--template', str(registered), '--out', str(out), '--run-root', str(root), '--wrapper', wrapper, '--potential', str(potential)])
        doc = ca_json.loads((out.parent / 'runtime-input-provenance.json').read_text())
        if doc.get('runtime_input_sha256') != ca_sha(out):
            raise RuntimeError('rendered runtime input receipt hash mismatch')
        return (root, out)

    def ca__proof_for_role(run_root, role):
        root = ca_Path(run_root).resolve()
        dest = root / 'acceptance' / 'native-zero-md-regression.json'
        if dest.is_file():
            return dest
        source = ca_Path(ca_os.environ.get('CASE06_SHARED_RUN_ROOT', '')) / 'B' / 'acceptance'
        source_proof = source / 'native-zero-md-regression.json'
        if not source_proof.is_file():
            raise RuntimeError('shared guarded native run-0 proof is missing')
        origin = source_proof.parent.parent
        source_proof_doc = ca_json.loads(source_proof.read_text())
        for tree in ('native-run0', 'provenance'):
            src = origin / tree
            dst = root / tree
            if src.exists() and (not dst.exists()):
                ca_shutil.copytree(src, dst)
        ca_shutil.copy2(source_proof, dest)
        return dest

    def ca__zero_call_rows(proof, phase, root, first=False):
        out = []
        if not first:
            return out
        doc = ca_json.loads(proof.read_text())
        for ph in ('alpha_quartz', 'coesite'):
            comps = doc['phases'][ph]['comparisons']
            calls = [comps['raw_to_gauge']['base_call'], comps['raw_to_gauge']['target_call'], comps['base_to_size']['base_call'], comps['base_to_size']['target_call']]
            seen = set()
            for call in calls:
                for (pathkey, hashkey, target) in (('original_input_path', 'original_input_sha256', 'original_input'), ('instrumented_input_path', 'instrumented_input_sha256', 'executed_input'), ('native_log_path', 'native_log_sha256', 'native_log'), ('execution_receipt_path', 'execution_receipt_sha256', 'execution_receipt')):
                    p = (root / call[pathkey]).resolve()
                    if not p.is_file() or ca_sha(p) != call[hashkey]:
                        raise RuntimeError('native run-0 artifact hash mismatch')
                iid = ca_json.loads((root / call['execution_receipt_path']).read_text()).get('invocation_id')
                if iid in seen:
                    continue
                seen.add(iid)
                out.append({'invocation_id': iid, 'native_returncode': 0, 'wrapper_integrity_rc': 0, 'phase': ph, 'segment_kind': 'run0', 'original_input': {'path': call['original_input_path'], 'sha256': call['original_input_sha256']}, 'executed_input': {'path': call['instrumented_input_path'], 'sha256': call['instrumented_input_sha256']}, 'native_log': {'path': call['native_log_path'], 'sha256': call['native_log_sha256']}, 'execution_receipt': {'path': call['execution_receipt_path'], 'sha256': call['execution_receipt_sha256']}, 'binary_provenance_ref': call.get('binary_provenance_ref'), 'native_outputs': []})
        return out

    def ca_run_zero_md_pair(*, role, phase, run_root, runtime_input, stage, upper_steps=None, atoms=None, **_):
        ca__require_candidate_role(role)
        root = ca_Path(run_root).resolve()
        shared = ca_Path(ca_os.environ.get('CASE06_SHARED_RUN_ROOT', root.parent)).resolve()
        ca_os.environ['CASE06_SHARED_RUN_ROOT'] = str(shared)
        ca__prepare_role_tree(root, role)
        proof = root / 'acceptance' / 'native-zero-md-regression.json'
        shared_proof = shared / 'B' / 'acceptance' / 'native-zero-md-regression.json'
        first = not proof.is_file() and (not shared_proof.is_file())
        if first:
            binary = ca_os.environ.get('CASE08_REAL_LMP')
            wrapper = ca_os.environ.get('CASE08_WRAPPER')
            if not binary or not wrapper:
                raise RuntimeError('pinned native binary and guarded wrapper are required')
            zero = ca__load('case06_native_zero_md')
            zero.main(['--work-root', str(root), '--wrapper', wrapper, '--native-binary', binary, '--potential', str(root / 'native_inputs' / 'SiOx_potential.yace'), '--output', str(proof), '--role', role])
        else:
            proof = ca__proof_for_role(root, role)
        driver = ca__load('case06_fullcell_driver')
        driver.validate_run0_prerequisite(proof)
        calls = ca__zero_call_rows(proof, phase, root, first=first)
        if first:
            ca__ZERO_CACHE['proof_sha256'] = ca_sha(proof)
        return {'native': True, 'cached_native_evidence': not first, 'native_invocations': calls, 'gate': {'status': 'PASS', 'evidence_kind': 'native', 'schema': 'case06-native-zero-md-regression/v1', 'proof': ca_ref(proof, root), 'proof_sha256': ca_sha(proof), 'phase': phase}}

    def ca__verifier():
        return ca_types.SimpleNamespace(review_setup_sources=audit_review_setup_sources,
            review_cycle_sources=audit_review_cycle_sources)

    def ca_review_setup(*, outputs, setup_row, native_ledger, role=None, phase=None, reference_root=None):
        v = ca__verifier()
        fn = getattr(v, 'review_setup_sources', None)
        if not callable(fn):
            raise RuntimeError('independent verifier lacks review_setup_sources; setup is UNKNOWN')
        refroot = reference_root or (ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else None)
        row = dict(setup_row)
        row['role'] = {'B': 'baseline', 'R': 'independent_repeat', 'S': 'adaptive_size', 'D': 'adaptive_duration', 'A': 'independent_reference'}.get(role or row.get('role'), row.get('role'))
        result = fn(ca_Path(outputs), row, native_ledger, reference_root=refroot)
        return result

    def ca_review_fe(*, call, role, phase, cycle_id):
        v = ca__verifier()
        fn = getattr(v, 'review_cycle_sources', None)
        if not callable(fn):
            raise RuntimeError('independent verifier lacks review_cycle_sources; FE cycle is UNKNOWN')
        result = fn(ca_Path(ca_os.environ['CASE06_OUTPUTS']), call['integration_cycle'], call['phase_setup'], call.get('global_native_ledger', {}), reference_root=ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else None)
        if result.get('status') != 'PASS':
            return result
        return result

    def ca_source_gate(*, role, phase, parent_state):
        review = parent_state.get('source_review')
        if not isinstance(review, dict) or review.get('status') != 'PASS':
            return {'schema': 'case06-v2-source-gate/v1', 'status': 'UNKNOWN', 'role': role, 'phase': phase}
        ready = parent_state.get('ready_state_path')
        snapshot = parent_state.get('snapshot_path')
        if not ready or not snapshot:
            return {'schema': 'case06-v2-source-gate/v1', 'status': 'UNKNOWN', 'role': role, 'phase': phase}
        rp = ca_Path(ready)
        sp = ca_Path(snapshot)
        return {'schema': 'case06-v2-source-gate/v1', 'status': 'PASS', 'role': role, 'phase': phase, 'ready_state_sha256': ca_sha(rp), 'prepared_snapshot': {'path': str(sp), 'sha256': ca_sha(sp)}, 'gate_results': {x.get('name', x.get('check', 'gate')): x.get('status') for x in review.get('checks', [])}}

    def ca__scan_native_invocations(folder, run_root, output_root, source_root=None):
        """Collect every wrapper call, even when a later raw gate is UNKNOWN."""
        rows = []
        source_root = ca_Path(source_root or run_root).resolve()
        run_root = ca_Path(run_root).resolve()

        def source_ref(path):
            p = ca_Path(path).resolve()
            return ca_ref(p, source_root) if p.is_relative_to(source_root) else {'path': str(p), 'sha256': ca_sha(p)}
        for manifest in sorted(ca_Path(folder).rglob('case08-instrumentation.jsonl')):
            for line in manifest.read_text(errors='replace').splitlines():
                if not line.strip():
                    continue
                rec = ca_json.loads(line)
                iid = rec.get('invocation_id')
                if not iid:
                    raise RuntimeError('instrumentation row without immutable invocation_id')
                execution = manifest.parent / f'case08-execution.{iid}.json'
                if not execution.is_file():
                    raise RuntimeError(f'wrapper invocation {iid} lacks execution receipt')
                event = ca_json.loads(execution.read_text())
                arc = event.get('native_log_archive', {})
                log = ca_Path(arc.get('path', ''))
                if not log.is_file():
                    raise RuntimeError(f'wrapper invocation {iid} lacks archived native log')
                log_text = log.read_text(errors='replace')
                begins = __import__('re').findall('^CASE08_RUN_BEGIN segment=(\\S+) index=(\\d+) planned_steps=(\\d+) start_step=(-?\\d+)\\s*$', log_text, __import__('re').M)
                ends = __import__('re').findall('^CASE08_RUN_END segment=(\\S+) index=(\\d+) planned_steps=(\\d+) end_step=(-?\\d+)\\s*$', log_text, __import__('re').M)
                loops = __import__('re').findall('^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$', log_text, __import__('re').M)
                run_plan = rec.get('run_plan', [])
                plan_match = len(begins) == len(ends) == len(loops) == len(run_plan) and all((int(b[1]) == i and b[0] == e[0] and (b[1] == e[1]) and (b[2] == e[2]) and (int(b[2]) == int(lp[0])) and (int(e[3]) - int(b[3]) == int(lp[0])) and (int(run_plan[i - 1].get('planned_steps', -1)) == int(lp[0])) for (i, (b, e, lp)) in enumerate(zip(begins, ends, loops), 1)))
                original = ca_Path(rec['original_path'])
                executed = ca_Path(rec['instrumented_path'])
                orig_runs = list(map(int, __import__('re').findall('^\\s*run\\s+(\\d+)\\s*$', original.read_text(errors='replace'), __import__('re').M | __import__('re').I)))
                exec_runs = list(map(int, __import__('re').findall('^\\s*run\\s+(\\d+)\\s*$', executed.read_text(errors='replace'), __import__('re').M | __import__('re').I)))
                plan_match = bool(plan_match and orig_runs == [int(x[0]) for x in loops] and (exec_runs == [int(x[0]) for x in loops]))
                normalized = manifest.parent / f'case06-adapter-execution.{iid}.json'
                normalized_doc = {'schema': 'case06-native-invocation-receipt/v1', 'invocation_id': iid, 'native_returncode': event.get('native_returncode'), 'wrapper_integrity_rc': event.get('wrapper_integrity_rc'), 'manifest_run_plan_match': plan_match, 'original_input_sha256': ca_sha(original), 'executed_input_sha256': ca_sha(executed), 'native_log_sha256': ca_sha(log), 'wrapper_receipt': str(execution), 'wrapper_receipt_sha256': ca_sha(execution)}
                normalized.write_text(ca_json.dumps(normalized_doc, indent=2, sort_keys=True) + '\n')
                native_outputs = []
                for changed in event.get('changed_native_output_snapshots', []):
                    a = changed.get('archive', {})
                    p = ca_Path(a.get('path', ''))
                    if p.is_file():
                        native_outputs.append(dict(ca_ref(p, output_root), namespace='author_reference' if ca_Path(run_root).resolve().is_relative_to(ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']).resolve()) else 'candidate'))
                    native = ca_Path(changed.get('native_path', changed.get('source', '')))
                    if native.is_file():
                        native_digest = changed.get('native_sha256', changed.get('source_sha256'))
                        if native_digest is not None and ca_sha(native) != native_digest:
                            raise RuntimeError(f'native output source hash differs from its wrapper receipt: {native}')
                        native_outputs.append(dict(ca_ref(native, output_root), namespace='author_reference' if ca_Path(run_root).resolve().is_relative_to(ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']).resolve()) else 'candidate'))
                for dump in event.get('instrumented_structural_dumps', []):
                    p = ca_Path(dump.get('path', ''))
                    if p.is_file():
                        native_outputs.append(dict(ca_ref(p, output_root), namespace='author_reference' if ca_Path(run_root).resolve().is_relative_to(ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']).resolve()) else 'candidate'))
                rows.append({'invocation_id': iid, 'native_returncode': event.get('native_returncode'), 'wrapper_integrity_rc': event.get('wrapper_integrity_rc'), 'original_input': source_ref(original), 'executed_input': source_ref(executed), 'native_log': source_ref(log), 'execution_receipt': source_ref(normalized), 'native_outputs': native_outputs})
        ids = [r['invocation_id'] for r in rows]
        if len(ids) != len(set(ids)):
            raise RuntimeError('duplicate native invocation ID found in scanned wrapper receipts')
        return rows

    def ca_collect_partial_native_invocations(*, role, run_root, phase=None, **_):
        ca__require_candidate_role(role)
        """Best-effort exception-path scan; the durable pre-call reservation covers unknown tails."""
        root = ca_Path(run_root).resolve()
        evidence_root = ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else ca_Path(ca_os.environ['CASE06_OUTPUTS'])
        return ca__scan_native_invocations(root, root, evidence_root, source_root=root)

    def ca__copy_calphy_identity(run_root, role):
        source = ca_Path(run_root) / 'calphy-source-identity.json'
        if not source.is_file():
            return None
        output = ca_Path(ca_os.environ['CASE06_OUTPUTS']) / 'provenance' / 'calphy-source-identity.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            if ca_sha(output) != ca_sha(source):
                raise RuntimeError('installed Calphy identity differs between phase runtimes')
        else:
            ca_shutil.copy2(source, output)
        if ca_sha(output) != ca_sha(source):
            raise RuntimeError('copied Calphy source identity SHA mismatch')
        return ca_ref(output, ca_Path(ca_os.environ['CASE06_OUTPUTS']))

    def ca_prepare_one_phase(*, role, phase, run_root, runtime_input, source_receipt, upper_steps=None, atoms=None, global_native_ledger=None, **_):
        ca__require_candidate_role(role)
        (root, runtime) = ca__runtime(runtime_input, run_root, role)
        proof = ca__proof_for_role(root, role)
        driver = ca__load('case06_fullcell_driver')
        prior = ca_Path.cwd()
        try:
            result = driver.prepare_one_phase(runtime, root, role, phase, source_receipt=source_receipt)
        except Exception as exc:
            ca__copy_calphy_identity(root, role)
            exc.native_started = any(ca_Path(root).rglob('case08-instrumentation.jsonl'))
            evidence_root = ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else ca_Path(ca_os.environ['CASE06_OUTPUTS'])
            try:
                exc.partial_native_invocations = ca__scan_native_invocations(root, root, evidence_root)
            except Exception as scan_exc:
                exc.partial_native_scan_error = str(scan_exc)
            raise
        finally:
            ca_os.chdir(prior)
        ca__copy_calphy_identity(root, role)
        if result.get('phase') != phase or result.get('role') != role:
            raise RuntimeError('driver preparation identity mismatch')
        evidence_root = ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else ca_Path(ca_os.environ['CASE06_OUTPUTS'])
        invocations = ca__scan_native_invocations(root / result['setup_folder'], root, evidence_root)
        setup_row = result.get('setup_record')
        if not isinstance(setup_row, dict):
            setup_row = {}
        gates = setup_row.get('scientific_gates', {})
        control_root = ca_Path(ca_os.environ['CASE06_OUTPUTS']) / 'phase-controls'
        control_index = control_root / 'source-index.json'
        descriptor_calibration = control_root / 'descriptor-calibration.json'
        if not control_index.is_file() or not descriptor_calibration.is_file():
            raise RuntimeError('task-packaged phase-control source records are missing')
        gates['phase_structure'] = dict(gates.get('phase_structure', {}))
        gates['phase_structure']['control_index'] = dict(ca_ref(control_index, ca_Path(ca_os.environ['CASE06_OUTPUTS'])), namespace='candidate')
        gates['phase_structure']['descriptor_calibration'] = dict(ca_ref(descriptor_calibration, ca_Path(ca_os.environ['CASE06_OUTPUTS'])), namespace='candidate')
        fixed = gates.get('fixed_h_nvt', {}) if isinstance(gates, dict) else {}
        if isinstance(fixed, dict):
            gates.setdefault('temperature', {'raw_source': fixed.get('raw_source'), 'source_invocation': fixed.get('temperature_source_invocation', fixed.get('source_invocation'))})
            gates.setdefault('fixed_h_msd', {'raw_source': fixed.get('trajectory'), 'source_invocation': fixed.get('source_invocation')})
        setup_row['scientific_gates'] = gates

        def normalize(obj):
            if isinstance(obj, dict):
                out = {k: normalize(v) for (k, v) in obj.items()}
                if isinstance(out.get('path'), str) and isinstance(out.get('sha256'), str):
                    p = ca_Path(out['path'])
                    if not p.is_absolute() and out.get('namespace') not in ('candidate', 'author_reference'):
                        p = root / p
                    if p.is_file():
                        out.update(ca_ref(p, evidence_root))
                        out['namespace'] = 'author_reference' if role == 'A' else 'candidate'
                return out
            if isinstance(obj, list):
                return [normalize(x) for x in obj]
            return obj
        setup_row = normalize(setup_row)
        snap = root / result['setup_snapshot_path'] if result.get('setup_snapshot_path') else None
        ready = root / result['ready_state_path'] if result.get('ready_state_path') else None
        ready_doc = ca_json.loads(ready.read_text()) if ready and ready.is_file() else {}
        snapshot_gate = {'status': 'UNKNOWN'}
        if snap and snap.is_file() and ca_os.environ.get('CASE08_REAL_LMP') and ca_os.environ.get('CASE08_WRAPPER'):
            zero = ca__load('case06_native_zero_md')
            zero_root = root / 'native-run0-snapshot'
            zero_root.mkdir(parents=True, exist_ok=True)
            obs = zero_run_case(snap, root / 'native_inputs' / 'SiOx_potential.yace', ca_Path(ca_os.environ['CASE08_WRAPPER']), ca_Path(ca_os.environ['CASE08_REAL_LMP']), zero_root, role, phase, 'prepared-snapshot', root, int(atoms or ready_doc.get('atoms', 0)))
            proof_path = root / obs['prepared_snapshot_run0_proof_path']
            proof_doc = ca_json.loads(proof_path.read_text())
            for key in ('execution_receipt', 'native_log', 'native_dump', 'native_observation', 'parsed_state'):
                item = proof_doc.get(key)
                if isinstance(item, dict) and isinstance(item.get('path'), str):
                    p = ca_Path(item['path'])
                    p = p if p.is_absolute() else root / p
                    if not p.is_file() or ca_sha(p) != item.get('sha256'):
                        raise RuntimeError(f'prepared snapshot run0 proof {key} artifact missing or changed')
                    if key == 'execution_receipt':
                        receipt_doc = ca_json.loads(p.read_text())
                        wrapper_ref = receipt_doc.get('wrapper_receipt')
                        if isinstance(wrapper_ref, dict) and isinstance(wrapper_ref.get('path'), str):
                            wrapper_path = ca_Path(wrapper_ref['path'])
                            wrapper_path = wrapper_path if wrapper_path.is_absolute() else root / wrapper_path
                            if not wrapper_path.is_file() or ca_sha(wrapper_path) != wrapper_ref.get('sha256'):
                                raise RuntimeError('prepared run0 normalized receipt wrapper source is missing or changed')
                            receipt_doc['wrapper_receipt'] = dict(ca_ref(wrapper_path, evidence_root), namespace='author_reference' if role == 'A' else 'candidate')
                            p.write_text(ca_json.dumps(receipt_doc, indent=2, sort_keys=True) + '\n')
                    item.update(ca_ref(p, evidence_root))
                    item['namespace'] = 'author_reference' if role == 'A' else 'candidate'
            proof_path.write_text(ca_json.dumps(proof_doc, indent=2, sort_keys=True) + '\n')
            c = obs['native_call']
            iid = ca_json.loads((root / c['execution_receipt_path']).read_text()).get('invocation_id')
            native_outputs = []
            for name in ('observation_path', 'force_dump_path', 'native_snapshot_state_path', 'prepared_snapshot_run0_proof_path'):
                p = root / obs[name]
                native_outputs.append(dict(ca_ref(p, evidence_root), namespace='author_reference' if role == 'A' else 'candidate'))
            inv = {'invocation_id': iid, 'native_returncode': 0, 'wrapper_integrity_rc': 0, 'original_input': {'path': c['original_input_path'], 'sha256': c['original_input_sha256']}, 'executed_input': {'path': c['instrumented_input_path'], 'sha256': c['instrumented_input_sha256']}, 'native_log': {'path': c['native_log_path'], 'sha256': c['native_log_sha256']}, 'execution_receipt': {'path': c['execution_receipt_path'], 'sha256': c['execution_receipt_sha256']}, 'binary_provenance_ref': c.get('binary_provenance_ref'), 'native_outputs': native_outputs}
            invocations.append(inv)
            snapshot_gate = {'status': 'PASS', 'evidence_kind': 'native_run0', 'step': obs['step'], 'atom_count': obs['atom_count'], 'snapshot_sha256': ca_sha(snap), 'observation': native_outputs[0], 'force_dump': native_outputs[1], 'parsed_native_state': native_outputs[2], 'raw_source': native_outputs[3], 'native_snapshot_state_match': obs['native_snapshot_state_match']}
            setup_row.setdefault('scientific_gates', {})['run0_snapshot'] = {'raw_source': native_outputs[3]}
        state = {'schema': 'case06-admitted-phase-state/v1', 'setup_id': (setup_row or {}).get('setup_id', f'{role}-{phase}'), 'role': role, 'phase': phase, 'atoms': int(atoms or (1152 if role == 'S' and phase == 'alpha_quartz' else 768 if role == 'S' else 576 if phase == 'alpha_quartz' else 384)), 'master_seed': int((setup_row or {}).get('master_seed', 0)), 'status': result.get('status'), 'setup_record': setup_row or {'setup_id': f'{role}-{phase}', 'role': role, 'phase': phase, 'warm_ancestry_required': True, 'invocation_segments': []}, 'snapshot_path': str(snap) if snap else None, 'snapshot_sha256': result.get('setup_snapshot_sha256'), 'ready_state_path': str(ready) if ready else None, 'pre_fe_numpy_rng_state': result.get('pre_fe_numpy_rng_state'), 'snapshot_run0_gate': snapshot_gate}
        driver_state = drv__state_from_ready_record(ready_doc) if ready_doc else None
        state['pre_fe_numpy_rng_state'] = driver_state
        state['gate_sha256'] = None
        return {'native': True, 'native_invocations': invocations, 'gate': {'status': 'PASS', 'evidence_kind': 'native'}, 'admitted_phase_state': state}

    def ca_run_one_fe_cycle(*, role, phase, run_root, admitted_phase_state, cycle_id, switching_steps, pre_fe_numpy_rng_state, upper_steps=None, atoms=None, **_):
        ca__require_candidate_role(role)
        root = ca_Path(run_root).resolve()
        role_for_runtime = 'B' if role == 'D' else role
        source_root = root
        ready = admitted_phase_state.get('ready_state_path')
        permit_state = admitted_phase_state
        if role == 'D':
            ca__prepare_role_tree(root, 'B')
            source_root = ca_Path(ca_os.environ['CASE06_SHARED_RUN_ROOT']) / 'B'
            source_inputs = source_root / 'native_inputs'
            for name in ('input-B.yaml', 'runtime-input-provenance.json'):
                p = source_inputs / name
                if p.is_file():
                    ca_shutil.copy2(p, root / 'native_inputs' / name)
            source_ready = ca_Path(ready).resolve()
            if not source_ready.is_file():
                raise RuntimeError('D matched-ancestry ready state is missing')
            d_sim = root / source_ready.parent.name
            d_sim.mkdir(parents=True, exist_ok=False)
            ca_shutil.copy2(source_ready, d_sim / source_ready.name)
            source_ready_doc = ca_json.loads(source_ready.read_text())
            snapshot_name = source_ready_doc.get('equilibrated_snapshot', 'conf.equilibration.data')
            source_snapshot = source_ready.parent / snapshot_name
            if not source_snapshot.is_file() or ca_sha(source_snapshot) != source_ready_doc.get('equilibrated_snapshot_sha256'):
                raise RuntimeError('D matched-ancestry pre-FE snapshot hash is absent or changed')
            ca_shutil.copy2(source_snapshot, d_sim / snapshot_name)
            ready = d_sim / source_ready.name
            permit_state = dict(admitted_phase_state, ready_state_path=str(ready), snapshot_path=str(d_sim / snapshot_name), snapshot_sha256=ca_sha(d_sim / snapshot_name))
        runtime = root / 'native_inputs' / f'input-{role_for_runtime}.yaml'
        if role == 'D':
            runtime = root / 'native_inputs' / 'input-B.yaml'
        gate = ca_source_gate(role=role, phase=phase, parent_state=permit_state)
        if role == 'D':
            data = ca_json.loads(runtime.read_text())
            for row in data['calculations']:
                row['n_switching_steps'] = 40000
            runtime = root / 'native_inputs' / 'input-D.yaml'
            runtime.write_text(ca_json.dumps(data, indent=2, sort_keys=True) + '\n')
        driver = ca__load('case06_fullcell_driver')
        prior = ca_Path.cwd()
        try:
            ca_os.chdir(root)
            numeric_cycle = int(str(cycle_id).rsplit('-', 1)[-1])
            try:
                result = driver.run_one_fe_cycle(runtime, ca_Path(ready), gate, numeric_cycle, role=role, numpy_rng_state=pre_fe_numpy_rng_state)
            except Exception as exc:
                exc.native_started = any(ca_Path(ready).parent.rglob('case08-instrumentation.jsonl'))
                try:
                    exc.partial_native_invocations = ca__scan_native_invocations(ca_Path(ready).parent, root, ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else ca_Path(ca_os.environ['CASE06_OUTPUTS']))
                except Exception as scan_exc:
                    exc.partial_native_scan_error = str(scan_exc)
                raise
        finally:
            ca_os.chdir(prior)
        if result.get('role') != role:
            raise RuntimeError('driver FE cycle identity mismatch')
        cycle_path = ca_Path(result['cycle_path'])
        cycle = dict(result['integration_cycle'])
        cycle['setup_id'] = admitted_phase_state['setup_id']
        evidence_root = ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else ca_Path(ca_os.environ['CASE06_OUTPUTS'])
        native_source_root = root

        def normalize_cycle(obj):
            if isinstance(obj, dict):
                out = {k: normalize_cycle(v) for (k, v) in obj.items()}
                if isinstance(out.get('path'), str) and isinstance(out.get('sha256'), str):
                    p = ca_Path(out['path'])
                    if not p.is_absolute():
                        p = cycle_path.parent / p
                    if p.is_file():
                        out.update(ca_ref(p, evidence_root))
                        out['namespace'] = 'author_reference' if role == 'A' else 'candidate'
                return out
            if isinstance(obj, list):
                return [normalize_cycle(x) for x in obj]
            return obj
        cycle = normalize_cycle(cycle)
        invocations = ca__scan_native_invocations(cycle_path.parent, root, evidence_root, source_root=native_source_root)
        invocations = [x for x in invocations if x['invocation_id'] in {r.get('invocation_id') for r in result.get('native_invocations', [])}]
        return {'native': True, 'native_invocations': invocations, 'integration_cycle': cycle, 'driver_result': result, 'phase_setup': admitted_phase_state.get('setup_record'), 'admitted_phase_state': admitted_phase_state, 'global_native_ledger': _.get('global_native_ledger', {}), 'gate': {'status': 'UNKNOWN', 'evidence_kind': 'native'}}

    def ca_extract_cycle(call, *, direction, role, phase, cycle_id):
        v = ca__verifier()
        fn = getattr(v, 'reconstruct_direction', None)
        if not callable(fn):
            raise RuntimeError('independent verifier lacks reconstruct_direction; G is UNKNOWN')
        cycle = call['integration_cycle']
        setup = call['phase_setup']
        state = call['admitted_phase_state']
        ready = ca_json.loads(ca_Path(state['ready_state_path']).read_text())
        gates = setup.get('scientific_gates', {})
        npt = gates.get('npt_primary', {})
        mh = gates.get('mean_h', {})
        switch_rows = [x for x in cycle.get('invocation_segments', []) if x.get('segment_kind') == 'fe_switch' and x.get('leg') == direction]
        if len(switch_rows) != 1:
            raise RuntimeError(f'{cycle_id}/{direction} lacks one source-bound switch segment')
        curve = cycle.get('actual_forward_curve' if direction == 'forward' else 'actual_backward_curve')
        if not isinstance(curve, dict):
            raise RuntimeError('native cycle omitted raw direction TI curve')
        nref = npt.get('source_invocation')
        sref = switch_rows[0]
        row = {'run_id': f'{role}-{phase}-{direction}', 'role': {'B': 'baseline', 'R': 'independent_repeat', 'S': 'adaptive_size', 'D': 'adaptive_duration', 'A': 'independent_reference'}[role], 'phase': phase, 'direction': direction, 'replicate': role, 'T_K': 600, 'P_bar': 20000, 'atoms': int(state['atoms']), 'cell_atoms': int(state['atoms']), 'seed': str(state['master_seed']), 'lambda_curve': curve, 'einstein_endpoint': setup.get('snapshot'), 'mean_h': mh.get('derived_source'), 'mean_h_native_source': npt.get('raw_source'), 'mean_h_source_invocation': nref, 'mean_cell_matrix_A': ready.get('mean_cell_matrix_A'), 'mean_cell_volume_A3': ready.get('mean_cell_volume_A3'), 'npt_start_step': 1000, 'discard_steps': 1000, 'switch_steps': int(cycle.get('positive_run_steps', [0, 20000])[1]), 'switch_source_invocation': {k: sref[k] for k in ('invocation_id', 'run_index', 'segment_kind', 'native_segment_name')}, 'switch_run_index': int(sref['run_index']), 'spring_constants_eV_per_A2': [2.0, 4.0], 'element_to_type': {'O': 1, 'Si': 2}, 'hamiltonian_sha256': 'c8f00d8f0cbc131b0298b79260ba8098975624363c9d178223e51e48f025e97a'}
        ledger = call.get('global_native_ledger', {})
        replay = {'invocations': {str(x['invocation_id']): x for x in ledger.get('native_invocations', []) if x.get('invocation_id')}}
        output_root = ca_Path(ca_os.environ['CASE06_OUTPUTS'])
        reference_root = ca_Path(ca_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else None
        reconstructed = fn(output_root, row, source_root=reference_root, ledger=replay)
        g = float(reconstructed['G_eV_per_atom'])
        attempt = {'source_reconstruction': reconstructed, 'switch_source_invocation': row['switch_source_invocation'], 'run_index': int(sref['run_index']), 'status': 'RAW_RECONSTRUCTED_G'}
        campaign = {**row, 'g_eV_per_atom': g, 'G_eV_per_atom': g, 'cell_atoms': int(state['atoms']), 'equilibration_steps': 16000, 'window_start': 0.0, 'window_end': 1.0, 'uncertainty_eV_per_atom': 'UNKNOWN', 'reason': 'G raw-reconstructed from native TI/work, full-H, endpoint and YACE sources; finite warm-bias precision remains UNKNOWN', 'source_reconstruction': reconstructed}
        return {'direction_attempt': attempt, 'campaign_direction': campaign, 'status': 'PASS'}

    # Direct source merge: fullcell_driver.py; namespace prefix drv_
    """Case-06 single-state-v2 bounded full-cell Calphy 2.1.2 campaign driver.

    The source-gated entrypoints prepare a phase and can run one explicitly
    permitted bidirectional FE cycle. Scientific admission remains independent
    and FE is refused unless a source-bound PASS permit is supplied.
    """
    import csv as drv_csv, hashlib as drv_hashlib, importlib as drv_importlib, json as drv_json, math as drv_math, os as drv_os, re as drv_re, sys as drv_sys
    from pathlib import Path as drv_Path
    from importlib.metadata import version as drv_package_version
    import numpy as drv_np
    from scipy.stats import t as drv_t
    from calphy.solid import Solid as drv_Solid
    import calphy.solid as drv_solid_module
    drv_HERE = drv_Path(__file__).resolve().parent
    drv_PAYLOAD = ASSET_ROOT
    drv_EXPECTED = drv_json.loads('{"wheel_sha256":"778558c99d29c8299c987efd61d004f67a016f96f520879ae82429519e2e86bb","calphy_python_sources":{"calphy/__init__.py":"03658f322c64cf59ecc2c8845b56a0565d6addb87dd5814857f3d628392b0da1","calphy/alchemy.py":"ec294863d4aca6357d2661d2ea4cb3c77a7c6b3c28a161681b6fdd0dbab77dc5","calphy/clitools.py":"06718198819c0ae9dddb4813c33b2dab0ceeb4952c3f992ae473351332be4e9f","calphy/composition_transformation.py":"997ac48982142c2ad3f89433cd61586c9d27733990d4d731e8375e9d7d1f86ac","calphy/errors.py":"e617acb068891b9bef86ce1a55c23a451e6c26ec2b3d2dd208af816412c5349d","calphy/helpers.py":"961cf04b946033e21a4da49cc5ea4c37b395f8628ba63d8619dea409ccb55fb7","calphy/input.py":"77e4bed599820b3a90b13b6ac436e23788913e2815bd64d048167d9c48f54239","calphy/integrators.py":"612ab63c3634a804c46c739c82bc5b28f9f36dc9e0dc72b412f498f6fee8d14d","calphy/kernel.py":"c30a95d999d99e7dd87adea32fcf61082ed052631006f817f10ea1b45de98e43","calphy/library_runner.py":"c0eb20c1d1e2b950be3714a42bf379b2e71078018effa36b16e953dcd7dc4c53","calphy/liquid.py":"8f7cb02b5629d15f0c116fb7b8994907975e7e3b5093b35c97db5b0ad9130218","calphy/phase.py":"0240507a76de503e54c51b8daadfe8d7ece983ba87a614ca15588258955f694b","calphy/phase_diagram.py":"3f7596a4959d64454974be1f9c054f09be4334c454933bee8e17052a44f610ec","calphy/postprocessing.py":"6e919c1b19d6274b4c44870eac453a49d89df9a0ef48a83942838c5b7937114e","calphy/queuekernel.py":"7de36743e743a871f1cb29c79a60ffa24eeb77a9e9ad741e44897d6311f1cbf7","calphy/range_scan.py":"c5abd1c45c89f486c525648b380a069428445d05ec47205266e704d0e5dd60e3","calphy/routines.py":"b35abc796b50f4e077ffd9ef0f4268ca447b641890d76d81967e47f24ba19261","calphy/runner.py":"685fd749580f95dce868b676339f4714490d50c8c792154951a1be3a1c366352","calphy/scheduler.py":"01ac58ff2b6c4c5ca55109c8a48b01c1fbad67cec16448f47cc0ae8aef158461","calphy/solid.py":"f395b2de41aea6dcd2dd3ae1025c51fa8f1e1dc7ffcac9ae6a1792dab9eb3dc4","calphy/splines.py":"9c6040d981d85780c555c8f8cb621493d7fa41df50d4c5bc1464756aec9a3230","calphy/utils.py":"5281c0126c33b588c1aeb6ca50626ee19e341858eac748fe0c5479bb7ed67649"}}')
    drv_IDENTITY_SHA256 = None
    drv_EXPLICIT_FIXED_H_NVT_STEPS = 5000
    drv_POWER_V2_PROTOCOL = 'case08-fullcell-prep-power/v2'
    drv_RAMP_STEPS = 1000
    drv_NPT_START_STEP = 1000
    drv_NPT_END_STEP = 11000
    drv_NPT_SAMPLE_CADENCE = 100
    drv_FIXED_H_CADENCE = 20

    def drv_sha(path: drv_Path) -> str:
        h = drv_hashlib.sha256()
        with path.open('rb') as stream:
            for part in iter(lambda : stream.read(1 << 20), b''):
                h.update(part)
        return h.hexdigest()

    class drv_ScientificGateStop(RuntimeError):
        """A recorded scientific ambiguity that is distinct from native failure."""

    def drv_validate_installed_sources() -> dict:
        root = drv_Path(drv_importlib.import_module('calphy').__file__).resolve().parent
        observed = {}
        errors = []
        for (rel, expected) in drv_EXPECTED['calphy_python_sources'].items():
            path = root / drv_Path(rel).relative_to('calphy')
            actual = drv_sha(path) if path.is_file() else None
            observed[rel] = actual
            if actual != expected:
                errors.append({'source': rel, 'expected_sha256': expected, 'actual_sha256': actual})
        installed_version = drv_package_version('calphy')
        receipt = {'schema': 'case08-calphy-source-identity/v1', 'version': installed_version, 'wheel_sha256': drv_EXPECTED['wheel_sha256'], 'installed_package_path': str(root), 'expected_files': len(observed), 'observed_file_sha256': observed, 'errors': errors, 'pass': not errors}
        (drv_Path.cwd() / 'calphy-source-identity.json').write_text(drv_json.dumps(receipt, indent=2) + '\n')
        if errors:
            raise RuntimeError('installed Calphy source does not match the frozen 2.1.2 wheel')
        if installed_version != '2.1.2':
            raise RuntimeError(f'unexpected Calphy version {installed_version}')
        return receipt

    def drv_matrix(row):
        return drv_np.array([[row['lx'], 0.0, 0.0], [row['xy'], row['ly'], 0.0], [row['xz'], row['yz'], row['lz']]], float)

    def drv_minimum_face_height(H):
        (a, b, c) = drv_np.asarray(H, float)
        vol = abs(float(drv_np.linalg.det(H)))
        areas = (drv_np.linalg.norm(drv_np.cross(b, c)), drv_np.linalg.norm(drv_np.cross(c, a)), drv_np.linalg.norm(drv_np.cross(a, b)))
        if not drv_math.isfinite(vol) or vol <= 0 or any((not drv_math.isfinite(x) or x <= 0 for x in areas)):
            return float('nan')
        return min((vol / x for x in areas))

    def drv_block_ci(a):
        a = drv_np.asarray(a, float)
        return (float(a.mean()), float(drv_t.ppf(0.975, len(a) - 1) * a.std(ddof=1) / drv_np.sqrt(len(a))))

    def drv_geyer_ess(a):
        a = drv_np.asarray(a, float)
        x = a - a.mean()
        var = float(drv_np.mean(x * x))
        if var <= 0:
            return float(len(a))
        rho = [1.0]
        for lag in range(1, len(a) // 2):
            rho.append(float(drv_np.dot(x[:-lag], x[lag:]) / ((len(a) - lag) * var)))
        tau = 0.5
        for i in range(1, len(rho) - 1, 2):
            pair = rho[i] + rho[i + 1]
            if pair <= 0:
                break
            tau += pair
        return float(min(len(a), len(a) / (2 * tau)))

    def drv_read_frames(path: drv_Path):
        lines = path.read_text(errors='replace').splitlines()
        i = 0
        frames = []
        while i < len(lines):
            if lines[i].strip() != 'ITEM: TIMESTEP':
                i += 1
                continue
            try:
                step = int(lines[i + 1])
                n = int(lines[i + 3])
                hdr = lines[i + 4]
                if 'xy xz yz' not in hdr:
                    raise ValueError('not triclinic')
                xb = list(map(float, lines[i + 5].split()))
                yb = list(map(float, lines[i + 6].split()))
                zb = list(map(float, lines[i + 7].split()))
                (xy, xz, yz) = (xb[2], yb[2], zb[2])
                xl = xb[0] - min(0.0, xy, xz, xy + xz)
                xh = xb[1] - max(0.0, xy, xz, xy + xz)
                yl = yb[0] - min(0.0, yz)
                yh = yb[1] - max(0.0, yz)
                H = drv_np.array([[xh - xl, 0, 0], [xy, yh - yl, 0], [xz, yz, zb[1] - zb[0]]], float)
                col = lines[i + 8].split()[2:]
                ids = []
                typ = []
                pos = []
                image = []
                velocities = []
                for row in lines[i + 9:i + 9 + n]:
                    v = row.split()
                    d = dict(zip(col, v))
                    ids.append(int(d['id']))
                    typ.append(int(d['type']))
                    pos.append([float(d[k]) for k in ('x', 'y', 'z')])
                    image.append([int(d[k]) for k in ('ix', 'iy', 'iz')] if all((k in d for k in ('ix', 'iy', 'iz'))) else [0, 0, 0])
                    velocities.append([float(d[k]) for k in ('vx', 'vy', 'vz')] if all((k in d for k in ('vx', 'vy', 'vz'))) else [float('nan')] * 3)
                order = drv_np.argsort(ids)
                frames.append({'step': step, 'H': H, 'ids': drv_np.asarray(ids)[order], 'types': drv_np.asarray(typ)[order], 'xyz': drv_np.asarray(pos)[order], 'image': drv_np.asarray(image)[order], 'velocity': drv_np.asarray(velocities)[order], 'has_image_flags': all((k in col for k in ('ix', 'iy', 'iz'))), 'has_velocities': all((k in col for k in ('vx', 'vy', 'vz')))})
                i += 9 + n
            except (ValueError, IndexError, KeyError):
                i += 1
        return frames

    def drv_normalize_repeated_frames(frames, tolerance_A=2e-12):
        """Retain raw frames; return a derived view collapsing only same-step physical aliases.

        Cell matrices must be unimodularly equivalent; full image-unwrapped positions,
        IDs/types, and velocities must agree within serialization precision.
        """
        normalized = []
        aliases = []
        for frame in frames:
            if not normalized or int(frame['step']) != int(normalized[-1]['step']):
                if normalized and int(frame['step']) < int(normalized[-1]['step']):
                    raise RuntimeError('native dump timestep moved backwards')
                normalized.append(frame)
                continue
            ref = normalized[-1]
            H = drv_np.asarray(ref['H'], float)
            H2 = drv_np.asarray(frame['H'], float)
            basis = H2 @ drv_np.linalg.inv(H)
            integer = drv_np.rint(basis)
            if not drv_np.allclose(basis, integer, rtol=0, atol=1e-10) or abs(round(drv_np.linalg.det(integer))) != 1 or abs(abs(drv_np.linalg.det(H2)) - abs(drv_np.linalg.det(H))) > 1e-09 * abs(drv_np.linalg.det(H)):
                raise RuntimeError(f"same-step native frames at {frame['step']} are not periodic basis aliases")
            if not drv_np.array_equal(frame['ids'], ref['ids']) or not drv_np.array_equal(frame['types'], ref['types']):
                raise RuntimeError(f"same-step native frames at {frame['step']} differ in IDs/types")
            p = drv_np.asarray(frame['xyz']) + drv_np.asarray(frame['image']) @ H2
            q = drv_np.asarray(ref['xyz']) + drv_np.asarray(ref['image']) @ H
            delta = (p - q) @ drv_np.linalg.inv(H)
            delta -= drv_np.rint(delta)
            cart = delta @ H
            if drv_np.max(drv_np.linalg.norm(cart, axis=1)) > tolerance_A:
                raise RuntimeError(f"same-step native frames at {frame['step']} differ in periodic Cartesian coordinates")
            if frame['has_velocities'] != ref['has_velocities'] or (frame['has_velocities'] and (not drv_np.allclose(frame['velocity'], ref['velocity'], rtol=0, atol=2e-12))):
                raise RuntimeError(f"same-step native frames at {frame['step']} differ in velocities")
            aliases.append({'step': int(frame['step']), 'kept_frame_index': len(normalized) - 1, 'alias_frame_index': len(normalized) + len(aliases), 'basis_transform_integer': integer.astype(int).tolist(), 'max_periodic_cartesian_delta_A': float(drv_np.max(drv_np.linalg.norm(cart, axis=1)))})
        return (normalized, aliases)

    def drv_read_lammps_data(path: drv_Path):
        lines = path.read_text(errors='replace').splitlines()
        bounds = {}
        tilt = (0.0, 0.0, 0.0)
        atoms = []
        in_atoms = False
        for line in lines:
            v = line.split()
            if len(v) >= 4 and v[2:4] == ['xlo', 'xhi']:
                bounds['x'] = (float(v[0]), float(v[1]))
            elif len(v) >= 4 and v[2:4] == ['ylo', 'yhi']:
                bounds['y'] = (float(v[0]), float(v[1]))
            elif len(v) >= 4 and v[2:4] == ['zlo', 'zhi']:
                bounds['z'] = (float(v[0]), float(v[1]))
            elif len(v) >= 6 and v[3:6] == ['xy', 'xz', 'yz']:
                tilt = tuple(map(float, v[:3]))
            elif line.strip().startswith('Atoms'):
                in_atoms = True
            elif in_atoms and (not line.strip()):
                if atoms:
                    in_atoms = False
            elif in_atoms and len(v) in (5, 8) and v[0].isdigit():
                try:
                    atoms.append((int(v[0]), int(v[1]), [float(x) for x in v[2:5]]))
                except ValueError:
                    pass
        if len(bounds) != 3 or not atoms:
            raise RuntimeError(f'cannot parse atomic LAMMPS data {path}')
        lo = [bounds[k][0] for k in ('x', 'y', 'z')]
        hi = [bounds[k][1] for k in ('x', 'y', 'z')]
        H = drv_np.array([[hi[0] - lo[0], 0, 0], [tilt[0], hi[1] - lo[1], 0], [tilt[1], tilt[2], hi[2] - lo[2]]], float)
        atoms.sort()
        xyz = drv_np.asarray([a[2] for a in atoms])
        xyz -= drv_np.asarray(lo)
        return {'step': 0, 'H': H, 'ids': drv_np.asarray([a[0] for a in atoms]), 'types': drv_np.asarray([a[1] for a in atoms]), 'xyz': xyz}

    def drv_graph(frame):
        oxygen = drv_np.flatnonzero(frame['types'] == 1)
        silicon = drv_np.flatnonzero(frame['types'] == 2)
        H = frame['H']
        inv = drv_np.linalg.inv(H)
        frac = frame['xyz'] @ inv
        shifts = drv_np.array([[a, b, c] for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)])
        edges = set()
        gaps = []
        for si in silicon:
            delta = frac[oxygen] - frac[si]
            center = drv_np.rint(delta)
            d = (delta[:, None, :] - center[:, None, :] - shifts[None, :, :]) @ H
            r = drv_np.sqrt(drv_np.min(drv_np.sum(d * d, axis=2), axis=1))
            order = drv_np.argsort(r)
            gaps.append(float(r[order[4]] - r[order[3]]))
            for j in order[:4]:
                edges.add((int(frame['ids'][si]), int(frame['ids'][oxygen[j]])))
        return (edges, min(gaps))

    def drv_npt_sample_windows(rows):
        """Frozen v2 dense primary: 1000 target-NPT rows; mean-H uses final 900."""
        if len(rows) != 1000 or len({int(r['step']) for r in rows}) != 1000:
            raise RuntimeError(f'expected exactly 1000 dense full-cell NPT observations, found {len(rows)}')
        steps = [int(r['step']) for r in rows]
        if steps[0] != 1010 or steps[-1] != 11000 or any((steps[i + 1] - steps[i] != 10 for i in range(999))):
            raise RuntimeError('v2 NPT primary must be exactly 1000 points at 1010..11000/10')
        retained = [r for r in rows if int(r['step']) >= 2010]
        if len(retained) != 900 or int(retained[0]['step']) != 2010 or int(retained[-1]['step']) != 11000:
            raise RuntimeError('v2 mean-H window must contain exactly 900 dense points, 2010..11000')
        return (1000, rows, retained)

    def drv_geometry_record_for_runtime(phase: str, atoms: int, lattice: str, source_root: drv_Path | None=None):
        """Resolve the active Calculation lattice to its exact role geometry row."""
        geometry_path = drv_PAYLOAD / 'native_inputs/geometry-manifest.json'
        geometry = drv_json.loads(geometry_path.read_text())
        if geometry.get('schema') != 'case06-public-periodic-quotient/v1' or geometry.get('matrix_sha256') != drv_json.loads((drv_PAYLOAD / 'candidate-scope.json').read_text()).get('source_matrix_sha256'):
            raise RuntimeError('runtime geometry manifest is not bound to the current matrix')
        rows = [r for r in geometry.get('structures', []) if r.get('phase') == phase]
        if len(rows) != 1:
            raise RuntimeError(f'geometry manifest must contain exactly one {phase} source record')
        rec = rows[0]
        name = drv_Path(str(lattice)).name
        candidates = []
        if name == rec.get('data') and int(rec.get('atoms', -1)) == int(atoms):
            candidates.append((rec['data'], rec['data_sha256'], 'base'))
        size = rec.get('size_supercell', {})
        if name == drv_Path(str(size.get('path', ''))).name and int(size.get('atoms', -1)) == int(atoms):
            candidates.append((size['path'], size['sha256'], 'size'))
        if len(candidates) != 1:
            raise RuntimeError(f'active runtime lattice {name!r}/{atoms} is not uniquely registered for phase {phase}')
        (rel, digest, role) = candidates[0]
        path = drv_Path(source_root).resolve() / drv_Path(rel).name if source_root is not None else drv_PAYLOAD / 'native_inputs' / drv_Path(rel).name
        if not path.is_file() or drv_sha(path) != digest:
            raise RuntimeError(f'active {role} geometry input hash mismatch: {path}')
        return (geometry, rec, {'path': path, 'sha256': digest, 'role': role, 'atoms': int(atoms)})

    def drv_analyze_npt(folder: drv_Path, phase: str, atoms: int, target_pressure: float, temperature: float, master_seed: int, input_path: drv_Path, source_sha: dict):
        thermo = folder / 'case06-npt-fullcell-10step.dat'
        raw = []
        for line in thermo.read_text(errors='replace').splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            try:
                raw.append([float(x) for x in line.split()])
            except ValueError:
                continue
        if any((len(row) != 15 for row in raw)):
            raise RuntimeError(f'dense primary NPT sample has unexpected column count in {thermo}')
        if any((not drv_np.all(drv_np.isfinite(row)) or not float(row[0]).is_integer() for row in raw)):
            raise RuntimeError(f'non-finite observable or non-integer native step in {thermo}')
        dense_path = folder / 'case06-npt-fullcell-100step.dat'
        alias = []
        for line in dense_path.read_text(errors='replace').splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            try:
                alias.append([float(x) for x in line.split()])
            except ValueError:
                continue
        if any((len(r) != 15 or not drv_np.all(drv_np.isfinite(r)) or not float(r[0]).is_integer() for r in alias)):
            raise RuntimeError('100-step alias contains malformed, nonfinite, or non-integer full-tensor rows')
        def normalize_start_boundary(values, cadence, first, last, count, label):
            expected = list(range(first, last + cadence, cadence))
            steps = [int(r[0]) for r in values]
            if steps == expected and len(values) == count:
                return (values, None)
            if steps == [first - cadence] + expected and len(values) == count + 1:
                return (values[1:], values[0])
            raise RuntimeError(f'{label} must be exactly {count} full-tensor rows on {first}..{last}/{cadence}, optionally preceded by one initial boundary row')
        raw, dense_boundary = normalize_start_boundary(raw, 10, 1010, 11000, 1000, 'dense primary NPT sample')
        alias, alias_boundary = normalize_start_boundary(alias, 100, 1100, 11000, 100, '100-step alias')
        if (dense_boundary is None) != (alias_boundary is None):
            raise RuntimeError('dense primary and 100-step alias disagree on the presence of the initial boundary row')
        if dense_boundary is not None and not drv_np.allclose(dense_boundary, alias_boundary, rtol=0, atol=1e-08):
            raise RuntimeError('dense primary and 100-step alias initial boundary rows disagree')
        cols = ['step', 'lx', 'ly', 'lz', 'xy', 'xz', 'yz', 'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz', 'temp']
        rows = [dict(zip(cols, r)) for r in raw]
        primary_by_step = {int(r[0]): r for r in raw}
        if any((int(r[0]) not in primary_by_step or not drv_np.allclose(r[1:], primary_by_step[int(r[0])][1:], rtol=0, atol=1e-08) for r in alias)):
            raise RuntimeError('100-step alias disagrees with dense NPT primary')
        for r in rows:
            H = drv_matrix(r)
            face = drv_minimum_face_height(H)
            if not drv_math.isfinite(face) or face <= 10.5:
                raise RuntimeError(f"native full-cell thermo violates minimum face-height guard at step {int(r['step'])}")
        (npt_start_step, window_rows, retained_h_rows) = drv_npt_sample_windows(rows)
        mean_h_path = folder / 'case06-npt-mean-h900.csv'
        mean_h_fields = ['step', 'lx_A', 'ly_A', 'lz_A', 'xy_A', 'xz_A', 'yz_A', 'press_bar', 'pxx_bar', 'pyy_bar', 'pzz_bar', 'pxy_bar', 'pxz_bar', 'pyz_bar', 'temperature_K']
        with mean_h_path.open('w', newline='') as f:
            writer = drv_csv.writer(f)
            writer.writerow(mean_h_fields)
            for r in retained_h_rows:
                writer.writerow([int(r['step']), *(r[k] for k in cols[1:])])
        blocks = {k: drv_np.asarray([r[k] for r in window_rows]).reshape(5, 200).mean(axis=1) for k in cols[1:]}
        stats = {}
        for (k, v) in blocks.items():
            (mean, ci) = drv_block_ci(v)
            (tail, tailci) = drv_block_ci(v[-3:])
            early = drv_np.asarray(v[:2])
            late = drv_np.asarray(v[-2:])
            drift = float(late.mean() - early.mean())
            (v1, v2) = (early.var(ddof=1) / 2, late.var(ddof=1) / 2)
            se = drv_math.sqrt(v1 + v2)
            df = (v1 + v2) ** 2 / (v1 * v1 + v2 * v2) if v1 * v1 + v2 * v2 else 2
            driftci = float(drv_t.ppf(0.975, df) * se)
            stats[k] = {'block_means': v.tolist(), 'mean': mean, 'ci95': ci, 'tail3_mean': tail, 'tail3_ci95': tailci, 'last2_minus_first2_mean': drift, 'last2_minus_first2_ci95': driftci}
        ess = drv_geyer_ess(drv_np.asarray([r['press'] for r in window_rows]))
        Hmean = drv_np.mean(drv_np.asarray([drv_matrix(r) for r in retained_h_rows]), axis=0)
        cellblocks = drv_np.asarray([drv_np.mean([drv_matrix(r) for r in retained_h_rows[i * 180:(i + 1) * 180]], axis=0) for i in range(5)])
        Hdev = cellblocks - Hmean
        stress = drv_np.array([[stats['pxx']['tail3_mean'] - target_pressure, stats['pxy']['tail3_mean'], stats['pxz']['tail3_mean']], [stats['pxy']['tail3_mean'], stats['pyy']['tail3_mean'] - target_pressure, stats['pyz']['tail3_mean']], [stats['pxz']['tail3_mean'], stats['pyz']['tail3_mean'], stats['pzz']['tail3_mean'] - target_pressure]])
        strain = drv_np.asarray([drv_np.linalg.solve(Hmean, h) - drv_np.eye(3) for h in cellblocks[-3:]])
        strain_abs = drv_np.max(drv_np.abs(strain), axis=0)
        vol_per_atom = float(drv_np.linalg.det(Hmean) / atoms)
        shape_bound_meV = 0.0006241509 * vol_per_atom * float(drv_np.sum((drv_np.abs(stress) + drv_np.array([[stats[k]['tail3_ci95'] for k in ('pxx', 'pxy', 'pxz')], [stats['pxy']['tail3_ci95'], stats['pyy']['tail3_ci95'], stats['pyz']['tail3_ci95']], [stats['pxz']['tail3_ci95'], stats['pyz']['tail3_ci95'], stats['pzz']['tail3_ci95']]])) * strain_abs))
        gates = {}
        p = stats['press']
        gates['full_pressure_ci'] = abs(p['mean'] - target_pressure) + p['ci95'] < 500
        gates['tail_pressure_ci'] = abs(p['tail3_mean'] - target_pressure) + p['tail3_ci95'] < 500
        gates['pressure_drift_ci'] = abs(p['last2_minus_first2_mean']) + p['last2_minus_first2_ci95'] < 500
        gates['pressure_ess_ge_10'] = ess >= 10
        gates['shear_tail_ci_contains_zero'] = all((abs(stats[k]['tail3_mean']) <= stats[k]['tail3_ci95'] for k in ('pxy', 'pxz', 'pyz')))
        temp_ess = drv_geyer_ess(drv_np.asarray([r['temp'] for r in window_rows]))
        gates['temperature_full_ci_includes_target'] = stats['temp']['mean'] - stats['temp']['ci95'] <= temperature <= stats['temp']['mean'] + stats['temp']['ci95']
        gates['temperature_ess_ge_10'] = temp_ess >= 10
        gates['temperature_drift_ci_contains_zero'] = abs(stats['temp']['last2_minus_first2_mean']) <= stats['temp']['last2_minus_first2_ci95']
        hrows = [drv_matrix(r) for r in rows]
        tilt_jumps = [max(abs(hrows[i + 1][1, 0] - hrows[i][1, 0]) / max(abs(hrows[i][0, 0]), 1e-12), abs(hrows[i + 1][2, 0] - hrows[i][2, 0]) / max(abs(hrows[i][0, 0]), 1e-12), abs(hrows[i + 1][2, 1] - hrows[i][2, 1]) / max(abs(hrows[i][1, 1]), 1e-12)) for i in range(len(hrows) - 1)]
        no_flip = not any((x >= 0.5 for x in tilt_jumps))
        gates['no_suspected_triclinic_basis_flip'] = no_flip
        dump = folder / 'case08-npt-phase.dump'
        raw_frames = drv_read_frames(dump)
        (frames, frame_aliases) = drv_normalize_repeated_frames(raw_frames)
        if len(frames) != 101 or any((frames[i + 1]['step'] - frames[i]['step'] != 100 for i in range(len(frames) - 1))) or int(frames[0]['step']) != npt_start_step or (int(frames[-1]['step']) != int(rows[-1]['step'])):
            raise RuntimeError('power-v2 target NPT trajectory must contain all 101 frames from step 1000 through 11000')
        if any((not frame['has_image_flags'] or not frame['has_velocities'] for frame in frames)):
            raise RuntimeError('target NPT dump must retain image flags and velocities')
        for f in frames:
            face = drv_minimum_face_height(f['H'])
            if not drv_math.isfinite(face) or face <= 10.5:
                raise RuntimeError(f"native phase dump violates minimum face-height guard at step {int(f['step'])}")
        runtime_doc = drv_json.loads(input_path.read_text())
        matching = []
        for calcrow in runtime_doc.get('calculations', []):
            lattice = str(calcrow.get('lattice', ''))
            nm = drv_Path(lattice).name
            phase_match = 'alpha_quartz' in nm if phase == 'alpha_quartz' else 'coesite' in nm
            atom_match = drv_re.search('-(\\d+)\\.data$', nm)
            if phase_match and atom_match and (int(atom_match.group(1)) == atoms):
                matching.append(lattice)
        if len(matching) != 1:
            raise RuntimeError(f'runtime input does not uniquely bind {phase}/{atoms} geometry')
        (geometry, ref, geometry_source) = drv_geometry_record_for_runtime(phase, atoms, matching[0], drv_Path(input_path).resolve().parent)
        geometry_path = drv_PAYLOAD / 'native_inputs/geometry-manifest.json'
        initial = geometry_source['path']
        reference = drv_read_lammps_data(initial)
        if len(reference['ids']) != atoms or len(drv_np.unique(reference['ids'])) != atoms:
            raise RuntimeError(f'prepared {phase} reference atom IDs/count are invalid')
        (base_edges, gap) = drv_graph(reference)
        retained_edge_fractions = []
        new = []
        gaps = []
        id_mismatch = []
        for f in frames:
            if not drv_np.array_equal(f['ids'], reference['ids']) or not drv_np.array_equal(f['types'], reference['types']):
                id_mismatch.append(int(f['step']))
            (e, g) = drv_graph(f)
            retained_edge_fractions.append(len(base_edges & e) / len(base_edges))
            new.append(len(e - base_edges))
            gaps.append(g)
        gates['phase_bond_id_topology'] = min(retained_edge_fractions) == 1.0 and max(new) == 0
        gates['phase_atom_ids_match_reference'] = not id_mismatch
        gates['phase_fourth_fifth_gap_positive'] = min(gaps) > 0
        ref_record = None
        old_shape_diagnostic = None
        old_shape_note = 'legacy FE cell file not available'
        if ref_record:
            hfe = drv_np.asarray(ref_record['matrix_A'], float)
            heq = drv_np.mean(cellblocks[-3:], axis=0)
            estrain = drv_np.asarray([drv_np.linalg.solve(h, hfe) - drv_np.eye(3) for h in cellblocks[-3:]])
            emean = estrain.mean(axis=0)
            eci = drv_t.ppf(0.975, 2) * estrain.std(axis=0, ddof=1) / drv_np.sqrt(3)
            residual = stress
            stressci = drv_np.array([[stats['pxx']['tail3_ci95'], stats['pxy']['tail3_ci95'], stats['pxz']['tail3_ci95']], [stats['pxy']['tail3_ci95'], stats['pyy']['tail3_ci95'], stats['pyz']['tail3_ci95']], [stats['pxz']['tail3_ci95'], stats['pyz']['tail3_ci95'], stats['pzz']['tail3_ci95']]])
            old_shape_diagnostic = 0.0006241509 * float(drv_np.linalg.det(heq) / atoms) * float(drv_np.sum((drv_np.abs(residual) + stressci) * (drv_np.abs(emean) + eci)))
            old_shape_note = 'linear residual-stress × strain diagnostic versus immutable old 8904 FE endpoint; not a free-energy bound and requires independent FEP/BAR/TI evidence'
        instrumentation = folder / 'case08-instrumentation.jsonl'
        invocation_records = []
        seed_commands = {'velocity': [], 'langevin': []}
        if instrumentation.is_file():
            for line in instrumentation.read_text().splitlines():
                if not line.strip():
                    continue
                rec = drv_json.loads(line)
                inst = drv_Path(rec.get('instrumented_path', ''))
                if inst.is_file():
                    for rawline in inst.read_text(errors='replace').splitlines():
                        text = rawline.strip()
                        if text.lower().startswith('velocity '):
                            seed_commands['velocity'].append({'invocation_id': rec.get('invocation_id'), 'command': text})
                        if text.lower().startswith('fix ') and 'langevin' in text.lower():
                            seed_commands['langevin'].append({'invocation_id': rec.get('invocation_id'), 'command': text})
                invocation = rec.get('invocation_id')
                execution = folder / f'case08-execution.{invocation}.json' if invocation else None
                event = drv_json.loads(execution.read_text()) if execution and execution.is_file() else None
                invocation_records.append({'invocation_id': invocation, 'original_path': rec.get('original_path'), 'original_sha256': rec.get('original_sha256'), 'instrumented_path': rec.get('instrumented_path'), 'instrumented_sha256': rec.get('instrumented_sha256'), 'execution_receipt_path': str(execution) if execution else None, 'execution_receipt_sha256': drv_sha(execution) if execution and execution.is_file() else None, 'native_log_archive': event.get('native_log_archive') if event else None, 'native_rc': event.get('native_returncode') if event else None})
        invocation_records = drv__integration_invocation_refs(folder, set())
        potential_path = None
        try:
            pair_coeff = drv_json.loads(input_path.read_text())['calculations'][0]['pair_coeff']
            pair_fields = pair_coeff.split() if isinstance(pair_coeff, str) else list(pair_coeff)
            potential_path = drv_Path(str(pair_fields[2]))
        except Exception:
            pass
        local_potential = drv_PAYLOAD / 'native_inputs' / potential_path.name if potential_path else None
        if local_potential is None or not local_potential.is_file():
            raise RuntimeError(f'cannot resolve packaged potential matching runtime pair_coeff path: {potential_path}')
        potential_record = {'runtime_path': str(potential_path), 'packaged_path': str(local_potential), 'sha256': drv_sha(local_potential)}
        (folder / 'case08-mean-cell-thermo.csv').write_text('step,lx_A,ly_A,lz_A,xy_A,xz_A,yz_A\n' + ''.join((','.join((str(r[k]) for k in ('step', 'lx', 'ly', 'lz', 'xy', 'xz', 'yz'))) + '\n' for r in retained_h_rows)))
        receipt = {'schema': 'case08-npt-admission/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phase': phase, 'temperature_K': temperature, 'pressure_bar': target_pressure, 'atoms': atoms, 'npt_start_step': npt_start_step, 'npt_end_step': int(rows[-1]['step']), 'discard_steps': 1000, 'retained_steps': 9000, 'retained_sample_count': len(retained_h_rows), 'retained_sample_steps': [int(retained_h_rows[0]['step']), int(retained_h_rows[-1]['step'])], 'contiguous_blocks': 5, 'samples_per_block': 200, 'pressure_temperature_sample_count': len(window_rows), 'protocol': drv_POWER_V2_PROTOCOL, 'retained_edge_fraction_frame_count': len(retained_edge_fractions), 'analysis_interval_sample_count': len(window_rows), 'raw_thermo_sample_count': len(rows), 'cadence_steps': 10, 'mean_h_source_path': str(thermo), 'mean_h_source_sha256': drv_sha(thermo), 'mean_h_source_row_steps': [int(retained_h_rows[0]['step']), int(retained_h_rows[-1]['step'])], 'mean_h_source_cadence_steps': 10, 'alias_100step_path': str(dense_path), 'alias_100step_sha256': drv_sha(dense_path), 'alias_100step_sample_count': len(alias), 'alias_100step_cadence_steps': 100, 'alias_100step_is_primary_gate': False, 'five_2000_step_blocks_dense_primary': stats, 'pressure_ess_dense_10step_samples': ess, 'temperature_ess_dense_10step_samples': temp_ess, 'mean_cell_matrix_A': Hmean.tolist(), 'mean_cell_volume_A3': float(drv_np.linalg.det(Hmean)), 'mean_h_thermo_path': str(mean_h_path), 'mean_h_thermo_sha256': drv_sha(mean_h_path), 'mean_h_valid_for_remap': no_flip, 'mean_h_invalid_reason': None if no_flip else 'suspected triclinic basis flip; raw elementwise mean is not used', 'phase_reference_path': str(initial), 'phase_reference_sha256': drv_sha(initial), 'phase_reference_id_count': len(reference['ids']), 'phase_reference_role': geometry_source['role'], 'phase_reference_geometry_record': {**geometry_source, 'path': str(geometry_source['path'])}, 'phase_reference_geometry_manifest_path': str(geometry_path), 'phase_reference_geometry_manifest_sha256': drv_sha(geometry_path), 'phase_trajectory_path': str(dump), 'phase_trajectory_sha256': drv_sha(dump), 'phase_raw_frame_count': len(raw_frames), 'phase_frames': len(frames), 'phase_periodic_alias_normalization': frame_aliases, 'phase_id_mismatch_steps': id_mismatch, 'temperature_full_mean_K': stats['temp']['mean'], 'temperature_full_ci95_K': stats['temp']['ci95'], 'temperature_tail3_mean_K': stats['temp']['tail3_mean'], 'temperature_tail3_ci95_K': stats['temp']['tail3_ci95'], 'phase_minimum_4_to_5_gap_A': min(gaps), 'phase_minimum_retained_edge_fraction': min(retained_edge_fractions), 'phase_maximum_new_edges': max(new), 'new_meanH_cell_block_scatter_sensitivity_meV_per_atom': shape_bound_meV, 'legacy_old_fe_cell_shape_linear_diagnostic_meV_per_atom': old_shape_diagnostic, 'legacy_old_fe_cell_shape_source': ref_record, 'legacy_old_fe_cell_shape_note': old_shape_note, 'legacy_old_fe_cell_shape_interpretation': 'linear_diagnostic_not_free_energy_bound', 'max_stepwise_tilt_jump_fraction_of_cell_edge': max(tilt_jumps), 'calphy_version': drv_package_version('calphy'), 'master_seed': master_seed, 'native_velocity_and_langevin_seed_commands': seed_commands, 'runtime_input_path': str(input_path), 'runtime_input_sha256': drv_sha(input_path), 'potential': potential_record, 'driver_source_path': str(drv_Path(__file__)), 'driver_source_sha256': drv_sha(drv_Path(__file__)), 'native_command_transcript_path': str(instrumentation), 'native_command_transcript_sha256': drv_sha(instrumentation) if instrumentation.is_file() else None, 'native_invocation_records': invocation_records, 'scientific_gates': {'npt_primary': {'raw_source': drv__artifact_ref(thermo), 'row_selection': {'first_step': 1010, 'last_step': 11000, 'cadence_steps': 10, 'rows': 1000}, 'source_invocation': drv__output_invocation_ref(invocation_records, thermo, 10000, 'setup_npt_primary')}, 'mean_h': {'raw_source': drv__artifact_ref(thermo), 'derived_source': drv__artifact_ref(mean_h_path), 'row_selection': {'first_step': 2010, 'last_step': 11000, 'cadence_steps': 10, 'rows': 900}, 'source_invocation': drv__output_invocation_ref(invocation_records, thermo, 10000, 'setup_npt_mean_h')}, 'fixed_h_nvt': {'raw_source': drv__artifact_ref(folder / 'case08-fixedH-thermo.dat'), 'trajectory': drv__artifact_ref(folder / 'case08-fixedH-msd.dump'), 'row_selection': {'first_step': 11000, 'last_step': 16000, 'cadence_steps': 20, 'temperature_rows': 250, 'dump_frames': 251}, 'source_invocation': drv__output_invocation_ref(invocation_records, folder / 'case08-fixedH-msd.dump', 5000, 'setup_fixed_h_nvt')}}, 'spring_msd_plateau': 'PENDING_STAGE_SETUP_ANALYSIS', 'phase_rdf_and_angle_comparison': 'PENDING_STAGE_SETUP_ANALYSIS', 'geometry_manifest_path': str(geometry_path), 'geometry_manifest_sha256': drv_sha(geometry_path), 'source_hashes': source_sha, 'gate_checks': gates, 'npt_local_observational_checks': 'PASS' if all(gates.values()) else 'UNKNOWN_SCIENTIFIC_GATE', 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'fe_started': False, 'notes': 'Per-phase pressure/phase gates do not admit legacy FE. Any old-FE cell-shape linear diagnostics require independent free-energy evidence; spring/MSD, RDF, angles and run0 parity remain review evidence. Prepare-only mode stops after the selected setup(s).'}
        (folder / 'case08-npt-admission.json').write_text(drv_json.dumps(receipt, indent=2) + '\n')
        return receipt

    def drv_integrated_autocorrelation_time(values):
        x = drv_np.asarray(values, float)
        x = x - x.mean()
        var = float(drv_np.mean(x * x))
        if len(x) < 3 or var <= 0:
            return 1.0
        rho = [1.0]
        for lag in range(1, len(x)):
            rho.append(float(drv_np.dot(x[:-lag], x[lag:]) / ((len(x) - lag) * var)))
        tau = 0.5
        for i in range(1, len(rho) - 1, 2):
            pair = rho[i] + rho[i + 1]
            if pair <= 0:
                break
            tau += pair
        return max(0.5, min(len(x), tau))

    def drv_hac_slope_ci(x, y):
        x = drv_np.asarray(x, float)
        y = drv_np.asarray(y, float)
        X = drv_np.column_stack((drv_np.ones(len(x)), x))
        inv = drv_np.linalg.inv(X.T @ X)
        beta = inv @ (X.T @ y)
        resid = y - X @ beta
        n = len(y)
        lag = max(1, int(drv_math.floor(4 * (n / 100) ** (2 / 9))))
        meat = drv_np.zeros((2, 2))
        for t0 in range(n):
            xt = X[t0] * resid[t0]
            meat += drv_np.outer(xt, xt)
        for ell in range(1, min(lag, n - 1) + 1):
            weight = 1 - ell / (lag + 1)
            for t0 in range(ell, n):
                cross = drv_np.outer(X[t0] * resid[t0], X[t0 - ell] * resid[t0 - ell])
                meat += weight * (cross + cross.T)
        cov = inv @ meat @ inv
        se = drv_math.sqrt(max(0, float(cov[1, 1])))
        return (float(beta[1]), se, lag)

    def drv_analyze_fixed_h_vibrations(folder: drv_Path, phase: str, atoms: int, target_temperature: float, runtime_calc):
        """Raw finite-lag MSD and temperature diagnostics for continuous 5k NVT."""
        spring_raw = []
        spring_frames = []
        spring_aliases = []
        all_frames = drv_read_frames(folder / 'case08-fixedH-msd.dump')
        (frames, frame_aliases) = drv_normalize_repeated_frames(all_frames)
        if len(frames) != 251 or int(frames[0]['step']) != 11000 or int(frames[-1]['step']) != 16000 or any((frames[i + 1]['step'] - frames[i]['step'] != 20 for i in range(250))):
            raise RuntimeError('v2 fixed-H NVT must contain 251 frames from step 11000 through 16000 at 20-step cadence')
        if any((not f['has_image_flags'] or not f['has_velocities'] for f in frames)):
            raise RuntimeError('power-v2 canonical dump must retain image flags and velocities')
        npt = drv_json.loads((folder / 'case08-npt-admission.json').read_text())
        if npt.get('protocol') != drv_POWER_V2_PROTOCOL or int(npt['npt_end_step']) != 11000:
            raise RuntimeError('power-v2 NPT admission source/version mismatch')
        H0 = frames[0]['H']
        ids0 = frames[0]['ids']
        types0 = frames[0]['types']
        if len(ids0) != atoms or len(drv_np.unique(ids0)) != atoms or (not drv_np.allclose(H0, drv_np.asarray(npt['mean_cell_matrix_A']), rtol=0, atol=1e-06)):
            raise RuntimeError('fixed-H v2 endpoint identity or mean-H mismatch')
        if not drv_np.all(drv_np.isfinite(H0)) or drv_np.linalg.det(H0) <= 0:
            raise RuntimeError('invalid fixed-H matrix')
        face_heights = []
        unwrapped = []
        inv = drv_np.linalg.inv(H0)
        first = frames[0]['xyz'] + frames[0]['image'] @ H0
        for (i, f) in enumerate(frames):
            if not drv_np.array_equal(f['ids'], ids0) or not drv_np.array_equal(f['types'], types0) or (not drv_np.allclose(f['H'], H0, rtol=0, atol=1e-06)):
                raise RuntimeError(f"power-v2 fixed-H identity/cell changed at {f['step']}")
            face = drv_minimum_face_height(f['H'])
            face_heights.append(face)
            if not drv_math.isfinite(face) or face <= 10.5:
                raise RuntimeError('fixed-H minimum face-height guard failed')
            coords = f['xyz'] + f['image'] @ H0
            if i == 0:
                unwrapped.append(coords)
                continue
            delta = coords - unwrapped[-1]
            frac = delta @ inv
            frac -= drv_np.rint(frac)
            step = frac @ H0
            if not drv_np.allclose(step, delta, atol=0.001, rtol=0):
                raise RuntimeError(f"image continuity mismatch at {f['step']}")
            unwrapped.append(coords)
        unwrapped = drv_np.asarray(unwrapped)
        mass_by_type = {i + 1: float(v) for (i, v) in enumerate(runtime_calc.mass)}
        masses = drv_np.asarray([mass_by_type[int(t0)] for t0 in types0])
        msum = float(masses.sum())
        original_lattice = getattr(runtime_calc, '_original_lattice', None)
        if not isinstance(original_lattice, str) or not original_lattice:
            raise RuntimeError('Calphy runtime Calculation lacks its immutable original lattice basename')
        (_, phase_ref, reference_source) = drv_geometry_record_for_runtime(phase, atoms, original_lattice, drv_Path(runtime_calc.inputfile).resolve().parent)
        ref = drv_read_lammps_data(reference_source['path'])
        (base_edges, _) = drv_graph(ref)
        edges = []
        gaps = []
        for f in frames:
            (e, g) = drv_graph(f)
            edges.append(e)
            gaps.append(g)
        topology_ok = all((e == base_edges for e in edges))
        threshold = (min(gaps) / 2) ** 2
        lag_results = {}
        origin_series = {}
        for lag_steps in (2000, 3000):
            lag = lag_steps // drv_FIXED_H_CADENCE
            vals_by_type = {}
            for (typ, label) in ((1, 'O'), (2, 'Si')):
                inds = drv_np.flatnonzero(types0 == typ)
                vals = []
                for origin in range(0, len(frames) - lag):
                    delta = unwrapped[origin + lag] - unwrapped[origin]
                    com = drv_np.einsum('a,ad->d', masses, delta) / msum
                    corrected = delta - com
                    vals.append(float(drv_np.mean(drv_np.einsum('ad,ad->a', corrected[inds], corrected[inds]))))
                vals = drv_np.asarray(vals)
                tau = drv_integrated_autocorrelation_time(vals)
                neff = min(float(len(vals)), len(vals) / (2 * tau))
                se = float(vals.std(ddof=1) / drv_math.sqrt(max(neff, 1)))
                upper = float(vals.mean() + drv_t.ppf(0.975, max(1, neff - 1)) * se)
                vals_by_type[label] = {'origins': len(vals), 'effective_sample_size': neff, 'mean_msd_A2': float(vals.mean()), 'upper95_A2': upper, 'mean_gate': bool(neff >= 10 and upper < threshold)}
                origin_series[label, lag_steps] = vals
            lag_results[str(lag_steps)] = vals_by_type
        growth = {}
        for label in ('O', 'Si'):
            paired = origin_series[label, 3000] - origin_series[label, 2000][:len(origin_series[label, 3000])]
            tau = drv_integrated_autocorrelation_time(paired)
            neff = min(float(len(paired)), len(paired) / (2 * tau))
            se = float(paired.std(ddof=1) / drv_math.sqrt(max(neff, 1)))
            upper = float(paired.mean() + drv_t.ppf(0.975, max(1, neff - 1)) * se)
            growth[label] = {'paired_origins': len(paired), 'effective_sample_size': neff, 'mean_A2': float(paired.mean()), 'upper95_A2': upper, 'gate': bool(neff >= 10 and upper < threshold)}
        thermo = folder / 'case08-fixedH-thermo.dat'
        temps = []
        for line in thermo.read_text().splitlines() if thermo.is_file() else []:
            v = line.split()
            try:
                if len(v) >= 2:
                    temps.append((int(v[0]), float(v[1])))
            except ValueError:
                continue
        canonical = [(step, temp) for (step, temp) in temps if 11000 < step <= 16000]
        if len(canonical) != 250 or canonical[0][0] != 11020 or canonical[-1][0] != 16000 or any((canonical[i + 1][0] - canonical[i][0] != 20 for i in range(249))):
            raise RuntimeError('v2 fixed-H NVT requires exactly 250 temperature records at 11020..16000')

        def temp_summary(arr):
            arr = drv_np.asarray(arr, float)
            tau = drv_integrated_autocorrelation_time(arr)
            neff = min(float(len(arr)), len(arr) / (2 * tau))
            se = float(arr.std(ddof=1) / drv_math.sqrt(max(neff, 1)))
            mean = float(arr.mean())
            ci = float(drv_t.ppf(0.975, max(1, neff - 1)) * se)
            return {'n': len(arr), 'ess': neff, 'mean_K': mean, 'ci95_K': ci, 'covers_target': bool(mean - ci <= target_temperature <= mean + ci)}
        all_t = drv_np.asarray([v for (_, v) in canonical])
        a = drv_np.asarray([v for (_, v) in canonical[:125]])
        b = drv_np.asarray([v for (_, v) in canonical[125:]])
        (ta, tb) = (temp_summary(a), temp_summary(b))
        tf = temp_summary(all_t)
        half_delta = tb['mean_K'] - ta['mean_K']
        half_se = drv_math.sqrt((ta['ci95_K'] / drv_t.ppf(0.975, max(1, ta['ess'] - 1))) ** 2 + (tb['ci95_K'] / drv_t.ppf(0.975, max(1, tb['ess'] - 1))) ** 2)
        half_ci = float(drv_t.ppf(0.975, max(1, min(ta['ess'], tb['ess']) - 1)) * half_se)
        t_ok = bool(tf['ess'] >= 20 and ta['ess'] >= 10 and (tb['ess'] >= 10) and tf['covers_target'] and ta['covers_target'] and tb['covers_target'] and (abs(half_delta) <= half_ci))
        return {'schema': 'case08-fixedH-msd-review/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phase': phase, 'atoms': atoms, 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'spring_interval_steps': None, 'canonical_nvt_interval_steps': [11000, 16000], 'canonical_temperature_observations': 250, 'spring_raw_frame_count': len(spring_raw), 'spring_frame_count': len(spring_frames), 'spring_periodic_alias_normalization': spring_aliases, 'canonical_raw_frame_count': len(all_frames), 'canonical_frame_count': len(frames), 'canonical_frame_steps': [11000, 16000], 'canonical_periodic_alias_normalization': frame_aliases, 'cadence_steps': 20, 'reference_H_A': H0.tolist(), 'minimum_face_height_A': min(face_heights), 'phase_graph_unchanged': topology_ok, 'minimum_4_to_5_gap_A': min(gaps), 'msd_threshold_A2': threshold, 'msd_lag_results': lag_results, 'same_origin_growth_3k_minus_2k': growth, 'temperature_full': tf, 'temperature_first_half': ta, 'temperature_second_half': tb, 'temperature_half_difference_K': half_delta, 'temperature_half_difference_ci95_K': half_ci, 'temperature_gate_observed': t_ok, 'fe_started': False, 'interpretation': 'Raw-recomputed finite-lag and temperature diagnostics only; scientific admission remains UNKNOWN pending review.'}

    class drv_FullCellSolid(drv_Solid):
        """Versioned Case-06 20-kbar full-cell preparation and guarded FE adapter."""

        def fix_nose_hoover(self, lmp, temp_start_factor=1.0, temp_end_factor=1.0, press_start_factor=1.0, press_end_factor=1.0, stage=0, ensemble='npt'):
            if ensemble != 'npt' or self.iso != 'tri':
                raise RuntimeError('v2 requires the pinned tri NPT coupling')
            cmd = 'fix              nh1 all npt temp %f %f %f %s %f %f %f flip no' % (temp_start_factor * self.calc._temperature, temp_end_factor * self.calc._temperature, self.calc.md.thermostat_damping[stage], self.iso, press_start_factor * self.calc._pressure, press_end_factor * self.calc._pressure, self.calc.md.barostat_damping[stage])
            lmp.command(cmd)

        def run_finite_pressure_equilibration(self, lmp):
            if self.calc._qtb or self.calc.equilibration_control != 'nose-hoover':
                raise RuntimeError('power-v2 requires the preregistered Nose-Hoover ramp')
            if int(self.calc.md.n_small_steps) != drv_RAMP_STEPS:
                raise RuntimeError('power-v2 ramp must be exactly 1000 steps')
            lmp.command('velocity all create %f %d' % (0.25 * self.calc._temperature, drv_np.random.randint(1, 10000)))
            self.fix_nose_hoover(lmp, temp_start_factor=0.25, temp_end_factor=1.0, stage=0)
            lmp.command('thermo_style custom step temp press pxx pyy pzz pxy pxz pyz vol lx ly lz xy xz yz')
            lmp.command('thermo 100')
            lmp.command('run 1000')
            self.unfix_nose_hoover(lmp)
            lmp.sync()

        def run_pressure_convergence(self, lmp):
            lmp.command('variable c_lx equal lx')
            lmp.command('variable c_ly equal ly')
            lmp.command('variable c_lz equal lz')
            lmp.command('variable c_xy equal xy')
            lmp.command('variable c_xz equal xz')
            lmp.command('variable c_yz equal yz')
            lmp.command('variable c_press equal press')
            lmp.command('variable c_temp equal temp')
            lmp.command('variable c_pxx equal pxx')
            lmp.command('variable c_pyy equal pyy')
            lmp.command('variable c_pzz equal pzz')
            lmp.command('variable c_pxy equal pxy')
            lmp.command('variable c_pxz equal pxz')
            lmp.command('variable c_pyz equal pyz')
            lmp.command('fix case08_dense_npt all ave/time 10 1 10 v_c_lx v_c_ly v_c_lz v_c_xy v_c_xz v_c_yz v_c_press v_c_pxx v_c_pyy v_c_pzz v_c_pxy v_c_pxz v_c_pyz v_c_temp file case06-npt-fullcell-10step.dat format " %.16g"')
            lmp.command('fix case08_fullcell all ave/time 100 1 100 v_c_lx v_c_ly v_c_lz v_c_xy v_c_xz v_c_yz v_c_press v_c_pxx v_c_pyy v_c_pzz v_c_pxy v_c_pxz v_c_pyz v_c_temp file case06-npt-fullcell-100step.dat format " %.16g"')
            lmp.command('dump case08_npt all custom 100 case08-npt-phase.dump id type x y z ix iy iz vx vy vz')
            lmp.command('dump_modify case08_npt sort id format float %.16g first yes')
            self.fix_nose_hoover(lmp)
            lmp.command('thermo_style custom step temp press pxx pyy pzz pxy pxz pyz vol lx ly lz xy xz yz')
            lmp.command('thermo 100')
            lmp.command('run 10000')
            lmp.sync()
            lmp.command('undump case08_npt')
            lmp.sync()
            lmp.command('unfix case08_fullcell')
            lmp.command('unfix case08_dense_npt')
            self.unfix_nose_hoover(lmp)
            lmp.sync()
            source = {drv_Path(__file__).name: drv_sha(drv_Path(__file__)), 'calphy-source-map.json': drv_hashlib.sha256(drv_json.dumps(drv_EXPECTED, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
            phase = getattr(self, '_case06_phase', None)
            if phase not in {'alpha_quartz', 'coesite'}:
                raise RuntimeError('immutable phase tag was not bound before Calphy folder creation')
            admission = drv_analyze_npt(drv_Path.cwd(), phase, int(self.natoms), float(self.calc._pressure), float(self.calc._temperature), int(self.calc.md.seed), drv_Path(str(self.calc.inputfile)), source)
            receipt = drv_json.loads((drv_Path.cwd() / 'case08-npt-admission.json').read_text())
            failed_local = [k for (k, v) in receipt.get('gate_checks', {}).items() if v is not True]
            if failed_local:
                self.lammps_close(lmp=lmp)
                raise drv_ScientificGateStop('UNKNOWN_SCIENTIFIC_GATE: NPT native admission checks not all met; stopped before mean-H remap/NVT: ' + ','.join(failed_local))
            self._case08_full_cell = drv_np.asarray(receipt['mean_cell_matrix_A'], float)
            self._case08_full_cell_volume = receipt['mean_cell_volume_A3']
            self.lx = float(self._case08_full_cell[0, 0])
            self.ly = float(self._case08_full_cell[1, 1])
            self.lz = float(self._case08_full_cell[2, 2])
            self.xy = float(self._case08_full_cell[1, 0])
            self.xz = float(self._case08_full_cell[2, 0])
            self.yz = float(self._case08_full_cell[2, 1])
            self.vol = self._case08_full_cell_volume
            self.volatom = self.vol / self.natoms
            self.rho = self.natoms / self.vol
            h = self._case08_full_cell
            if receipt['gate_checks'].get('no_suspected_triclinic_basis_flip'):
                lmp.command('run 0')
                lmp.command('print "NPT_PRE_REMAP $(step:%.0f) $(lx:%.12g) $(ly:%.12g) $(lz:%.12g) $(xy:%.12g) $(xz:%.12g) $(yz:%.12g) $(vol:%.12g) $(pe:%.12g)" file case08-npt-remap-parity.dat screen no')
                lmp.command('change_box all x final 0 %.12g y final 0 %.12g z final 0 %.12g xy final %.12g xz final %.12g yz final %.12g remap units box' % (h[0, 0], h[1, 1], h[2, 2], h[1, 0], h[2, 0], h[2, 1]))
                lmp.command('run 0')
                lmp.command('print "NPT_POST_REMAP $(step:%.0f) $(lx:%.12g) $(ly:%.12g) $(lz:%.12g) $(xy:%.12g) $(xz:%.12g) $(yz:%.12g) $(vol:%.12g) $(pe:%.12g)" append case08-npt-remap-parity.dat screen no')
            lmp.command('run 0')
            lmp.command('dump case08_fixedH all custom 20 case08-fixedH-msd.dump id type x y z ix iy iz vx vy vz')
            lmp.command('dump_modify case08_fixedH sort id format float %.16g first yes')
            lmp.command('fix case08_fixedH_temp all ave/time 20 1 20 v_c_temp file case08-fixedH-thermo.dat format " %.16g"')

        def start_equilibration_dump(self, lmp, filename='traj.equilibration.dat'):
            pass

        def stop_equilibration_dump(self, lmp):
            lmp.sync()
            lmp.command('undump case08_fixedH')
            lmp.command('unfix case08_fixedH_temp')
            lmp.sync()

        def run_spring_constant_convergence(self, lmp):
            k = [float(x) for x in self.calc.spring_constants]
            if k != [2.0, 4.0] or len(k) != self.calc.n_elements:
                raise RuntimeError('v2 requires the frozen spring constants [2,4] in O/Si order')
            lmp.command('fix              3 all nvt temp %f %f %f' % (self.calc._temperature, self.calc._temperature, self.calc.md.thermostat_damping[1]))
            import calphy.helpers as helpers
            helpers.compute_msd(lmp, self.calc)
            lmp.command('run 5000')
            lmp.sync()
            self.k = self.calc.spring_constants
            self.logger.info('Used frozen v2 spring constants [2,4] over continuous 5k fixed-H NVT')
            lmp.command('unfix 3')

        def run_averaging(self):
            damping = float(self.calc.md.thermostat_damping[1])
            timestep = float(self.calc.md.timestep)
            n_equilibration = int(self.calc.n_equilibration_steps)
            warm_start_steps = max(1, min(n_equilibration, int(round(10 * damping / timestep))))
            spring_steps = int(self.calc.md.n_small_steps)
            source_warm = int(self._warm_start_steps(npt=False))
            if source_warm != warm_start_steps:
                raise RuntimeError(f'Calphy Solid warm-start method returned {source_warm}; frozen formula gives {warm_start_steps}')
            if warm_start_steps != 1000 or drv_EXPLICIT_FIXED_H_NVT_STEPS != 5000 or spring_steps != 1000:
                raise RuntimeError(f'v2 setup/warm budget changed: warm={warm_start_steps}, continuous_fixed_H_NVT={drv_EXPLICIT_FIXED_H_NVT_STEPS}, configured_n_small_steps={spring_steps}')
            if 1000 + 10000 + drv_EXPLICIT_FIXED_H_NVT_STEPS + 2 * warm_start_steps > 20000:
                raise RuntimeError('per-phase 16k preparation plus two FE warm starts exceeds 20k ancestor cap')
            super().run_averaging()
            directory = drv_Path(self.simfolder)
            admission = drv_json.loads((directory / 'case08-npt-admission.json').read_text())
            try:
                fixedh = drv_analyze_fixed_h_vibrations(directory, admission['phase'], int(self.natoms), float(self.calc._temperature), self.calc)
            except Exception as exc:
                fixedh = {'schema': 'case08-fixedH-msd-review/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phase': admission['phase'], 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'error': f'{type(exc).__name__}: {exc}', 'fe_started': False}
            (directory / 'case08-fixedH-msd-review.json').write_text(drv_json.dumps(fixedh, indent=2) + '\n')
            setup_invocations = drv__integration_invocation_refs(directory, set())
            setup_segments = drv__attribute_setup_segments(setup_invocations, [drv_RAMP_STEPS, drv_NPT_END_STEP - drv_NPT_START_STEP, drv_EXPLICIT_FIXED_H_NVT_STEPS])
            retained_files = {name: {'path': str((directory / name).resolve()), 'sha256': drv_sha(directory / name), 'size_bytes': (directory / name).stat().st_size} for name in ('conf.equilibration.data', 'case08-npt-admission.json', 'case06-npt-fullcell-100step.dat', 'case06-npt-fullcell-10step.dat', 'case08-npt-phase.dump', 'case06-npt-mean-h900.csv', 'case08-mean-cell-thermo.csv', 'case08-npt-remap-parity.dat', 'case08-fixedH-msd.dump', 'case08-fixedH-thermo.dat', 'case08-fixedH-msd-review.json', 'case08-pre-averaging-rng-checkpoint.json', 'traj.equilibration_stage2.dat', 'msd.dat') if (directory / name).is_file()}
            state = {'schema': 'case08-fullcell-ready-state/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phase': admission['phase'], 'role': getattr(self, '_case06_role', None), 'simfolder': str(directory), 'atoms': int(self.natoms), 'geometry_reference': {'path': str(drv_Path(self._case06_geometry_reference).resolve().relative_to(drv_Path(self._case06_run_root).resolve())), 'sha256': drv_sha(drv_Path(self._case06_geometry_reference)), 'atoms': int(self.natoms)}, 'status': admission['status'], 'fe_started': False, 'admission_receipt': 'case08-npt-admission.json', 'admission_sha256': drv_sha(directory / 'case08-npt-admission.json'), 'equilibrated_snapshot': 'conf.equilibration.data', 'equilibrated_snapshot_sha256': drv_sha(directory / 'conf.equilibration.data'), 'mean_cell_matrix_A': admission['mean_cell_matrix_A'], 'mean_cell_volume_A3': admission['mean_cell_volume_A3'], 'spring_constants': drv_np.asarray(self.k).tolist(), 'master_seed': int(self.calc.md.seed), 'numpy_rng_state': {'bit_generator': drv_np.random.get_state()[0], 'state': drv_np.random.get_state()[1].tolist(), 'position': int(drv_np.random.get_state()[2]), 'has_gauss': int(drv_np.random.get_state()[3]), 'cached_gaussian': float(drv_np.random.get_state()[4])}, 'calphy_source_identity_sha256': drv_IDENTITY_SHA256, 'native_setup_files': retained_files, 'native_invocations': setup_invocations, 'invocation_segments': setup_segments, 'scientific_gates': {'npt_primary': admission.get('scientific_gates', {}).get('npt_primary'), 'mean_h': admission.get('scientific_gates', {}).get('mean_h'), 'fixed_h_nvt': {'raw_source': drv__artifact_ref(directory / 'case08-fixedH-thermo.dat'), 'trajectory': drv__artifact_ref(directory / 'case08-fixedH-msd.dump'), 'source_invocation': drv__output_invocation_ref(setup_invocations, directory / 'case08-fixedH-msd.dump', drv_EXPLICIT_FIXED_H_NVT_STEPS, 'setup_fixed_h_nvt'), 'temperature_source_invocation': drv__output_invocation_ref(setup_invocations, directory / 'case08-fixedH-thermo.dat', drv_EXPLICIT_FIXED_H_NVT_STEPS, 'setup_fixed_h_nvt'), 'row_selection': {'first_step': drv_NPT_END_STEP, 'last_step': drv_NPT_END_STEP + drv_EXPLICIT_FIXED_H_NVT_STEPS, 'cadence_steps': drv_FIXED_H_CADENCE, 'temperature_rows': drv_EXPLICIT_FIXED_H_NVT_STEPS // drv_FIXED_H_CADENCE, 'dump_frames': drv_EXPLICIT_FIXED_H_NVT_STEPS // drv_FIXED_H_CADENCE + 1}}}, 'fixed_h_vibration_review': 'case08-fixedH-msd-review.json', 'fixed_h_vibration_review_sha256': drv_sha(directory / 'case08-fixedH-msd-review.json'), 'pre_averaging_rng_checkpoint': 'case08-pre-averaging-rng-checkpoint.json', 'pre_averaging_rng_checkpoint_sha256': drv_sha(directory / 'case08-pre-averaging-rng-checkpoint.json'), 'resolved_calphy_fe_warm_start': {'method': 'Solid._warm_start_steps(npt=False), cross-checked against the frozen source formula', 'n_equilibration_steps': n_equilibration, 'thermostat_damping_ps': damping, 'timestep_ps': timestep, 'warm_start_steps_per_fe_direction': warm_start_steps, 'calphy_native_warm_start_method_result': source_warm, 'spring_steps': spring_steps, 'explicit_fixed_H_nvt_steps': drv_EXPLICIT_FIXED_H_NVT_STEPS, 'separate_spring_md_steps': 0, 'configured_n_small_steps_not_executed_as_spring_run': spring_steps, 'preparation_actual_planned_steps': 16000, 'warm_start_steps_per_complete_FE_cycle': warm_start_steps, 'warm_start_blocks_per_complete_FE_cycle': 2, 'warm_steps_for_two_duration_cycles': 4 * warm_start_steps, 'preparation_plus_two_duration_cycles_warm_steps': 16000 + 4 * warm_start_steps, 'within_20000_step_two_duration_ancestor_cap': 16000 + 4 * warm_start_steps <= 20000}, 'spring_msd_plateau': 'PENDING_OFFLINE_REVIEW', 'rdf_and_angle_fingerprint': 'PENDING_OFFLINE_REVIEW', 'driver_source_path': str(drv_Path(__file__)), 'driver_source_sha256': drv_sha(drv_Path(__file__))}
            (directory / 'case08-fullcell-ready-state.json').write_text(drv_json.dumps(state, indent=2) + '\n')

        def run_integration(self, iteration=1):
            permit = getattr(self, '_case06_phase_permit', None)
            if not isinstance(permit, dict) or permit.get('status') != 'PASS' or permit.get('schema') != 'case06-v2-source-gate/v1':
                raise RuntimeError('FE cycle refused: source-bound case06-v2-source-gate/v1 PASS is required')
            if permit.get('phase') != self._case06_phase or permit.get('role') != self._case06_role:
                raise RuntimeError('FE cycle permit phase/role does not match the live Calphy calculation')
            gate_results = permit.get('gate_results')
            if not isinstance(gate_results, dict) or not gate_results or any((v != 'PASS' for v in gate_results.values())):
                raise RuntimeError('FE cycle permit has missing or non-PASS source gates')
            runtime_springs = [float(x) for x in getattr(self.calc, 'spring_constants', [])]
            if runtime_springs != [2.0, 4.0] or len(runtime_springs) != int(self.calc.n_elements):
                raise RuntimeError('FE cycle requires the source-registered O/Si spring constants [2,4]')
            live_springs = [float(x) for x in self.k] if self.k is not None else None
            if live_springs is None:
                self.k = list(runtime_springs)
            elif live_springs != runtime_springs:
                raise RuntimeError('live Calphy spring constants differ from the validated runtime input')
            snapshot = drv_Path(permit.get('prepared_snapshot', {}).get('path', ''))
            if not snapshot.is_file() or drv_sha(snapshot) != permit.get('prepared_snapshot', {}).get('sha256'):
                raise RuntimeError('FE cycle permit prepared snapshot missing or hash changed')
            if snapshot.resolve() != drv_Path(self.simfolder, 'conf.equilibration.data').resolve():
                raise RuntimeError('FE cycle source is not the immutable pre-FE equilibration snapshot')
            expected = drv_np.asarray(self._case08_full_cell, float)
            cycle_rng_sha = drv__numpy_state_sha()
            prior_invocation_ids = drv__integration_invocation_ids(drv_Path.cwd())
            previous = drv_solid_module.ph.remap_box
            previous_create = drv_solid_module.ph.create_object
            proxies = []
            original_start = self._integration_start_configuration
            source_snapshot = str(snapshot.resolve())
            self._case06_cycle_id = int(iteration)
            self._case06_warm_reviews = []
            self._case06_forward_review = None

            def create_observed(calc, directory):
                native = previous_create(calc, directory)
                proxy = drv__WarmObservationProxy(native, self, int(iteration))
                proxies.append(proxy)
                return proxy

            def remap_full(lmp, *_args, **_kwargs):
                audit = drv_Path.cwd() / f'case08-fe-remap-parity-{iteration}.dat'
                lmp.command('run 0')
                lmp.command(f'print "PRE $(step:%.0f) $(lx:%.12g) $(ly:%.12g) $(lz:%.12g) $(xy:%.12g) $(xz:%.12g) $(yz:%.12g) $(vol:%.12g) $(pe:%.12g)" file {audit} screen no')
                lmp.command('change_box all x final 0 %.12g y final 0 %.12g z final 0 %.12g xy final %.12g xz final %.12g yz final %.12g remap units box' % (expected[0, 0], expected[1, 1], expected[2, 2], expected[1, 0], expected[2, 0], expected[2, 1]))
                lmp.command('run 0')
                lmp.command(f'print "POST $(step:%.0f) $(lx:%.12g) $(ly:%.12g) $(lz:%.12g) $(xy:%.12g) $(xz:%.12g) $(yz:%.12g) $(vol:%.12g) $(pe:%.12g)" append {audit} screen no')
                return lmp
            try:
                drv_solid_module.ph.remap_box = remap_full
                drv_solid_module.ph.create_object = create_observed
                self._integration_start_configuration = lambda _iteration: source_snapshot
                result = super().run_integration(iteration)
                expected_runs = [int(self._warm_start_steps(npt=False)), int(self.calc._n_switching_steps), int(self._warm_start_steps(npt=False)), int(self.calc._n_switching_steps)]
                if len(proxies) != 1 or proxies[0].positive_runs != expected_runs:
                    raise RuntimeError(f'native FE cycle positive run plan differs: {[p.positive_runs for p in proxies]}')
                invocation_refs = drv__integration_invocation_refs(drv_Path.cwd(), before=prior_invocation_ids)
                invocation_segments = drv__attribute_cycle_segments(invocation_refs, expected_runs)
                proxies[0].finalize(invocation_segments)
                self._case06_warm_reviews = proxies[0].reviews
                forward = drv__review_lambda_curve(drv_Path.cwd() / f'forward_{iteration}.dat', phase=self._case06_phase, role=self._case06_role, cycle_id=int(iteration), direction='forward', switch_steps=expected_runs[1])
                backward = drv__review_lambda_curve(drv_Path.cwd() / f'backward_{iteration}.dat', phase=self._case06_phase, role=self._case06_role, cycle_id=int(iteration), direction='backward', switch_steps=expected_runs[3])
                physical_review = next((r for r in self._case06_warm_reviews if r.get('endpoint') == 'physical_lambda0'), {})
                einstein_review = next((r for r in self._case06_warm_reviews if r.get('endpoint') == 'einstein_lambda1'), {})
                warm_local = len(self._case06_warm_reviews) == 2 and physical_review.get('hard_integrity_status') == 'PASS_WARM_RAW_INTEGRITY_REVIEW_REQUIRED' and (physical_review.get('physical_phase_check', {}).get('status') == 'PASS_PHYSICAL_WARM_STRUCTURE_REVIEW_REQUIRED') and (einstein_review.get('hard_integrity_status') == 'PASS_WARM_RAW_INTEGRITY_REVIEW_REQUIRED')
                lambda_local = forward.get('status') == backward.get('status') == 'PASS_NATIVE_LAMBDA_GRID_REVIEW_REQUIRED'
                warm_segments = [x for x in invocation_segments if x['segment_kind'].startswith('fe_warm_')]
                for warm in self._case06_warm_reviews:
                    endpoint = warm.get('endpoint')
                    kind = 'fe_warm_physical' if endpoint == 'physical_lambda0' else 'fe_warm_einstein'
                    warm['invocation_segments'] = [x for x in warm_segments if x['segment_kind'] == kind]
                    warm['source_invocations'] = sorted({x['invocation_id'] for x in warm['invocation_segments']})
                    warm['raw_source'] = {'path': str((drv_Path.cwd() / warm['path']).resolve()), 'sha256': warm.get('raw_path_sha256')}
                    if len(warm['invocation_segments']) == 1:
                        selected = warm['invocation_segments'][0]
                        warm['source_invocation'] = {k: selected[k] for k in ('invocation_id', 'run_index', 'segment_kind', 'native_segment_name')}
                        warm['source_input'] = selected['original_input']
                        warm['source_script'] = selected['executed_input']
                    else:
                        warm['source_invocation'] = {'status': 'UNKNOWN_SOURCE_BINDING', 'reason': 'warm segment did not map to one native run event'}
                    if warm.get('phase_dump_path'):
                        key = 'physical_dump' if warm.get('endpoint') == 'physical_lambda0' else 'trajectory'
                        warm[key] = {'path': str((drv_Path.cwd() / warm['phase_dump_path']).resolve()), 'sha256': warm.get('phase_dump_sha256')}
                    warm['review_status_is_non_authorizing'] = True
                warm_by = {'physical_lambda0': next((x for x in self._case06_warm_reviews if x.get('endpoint') == 'physical_lambda0'), None), 'einstein_lambda1': next((x for x in self._case06_warm_reviews if x.get('endpoint') == 'einstein_lambda1'), None)}

                def warm_ref(item, key):
                    if not item:
                        return {'status': 'UNKNOWN_SOURCE_BINDING', 'reason': 'warm observation was not captured'}
                    value = item.get(key)
                    if isinstance(value, dict):
                        return value
                    return {'status': 'UNKNOWN_SOURCE_BINDING', 'reason': f'{key} artifact reference absent'}

                def warm_source_record(item, key):
                    if not item:
                        return {'raw_source': warm_ref(item, key), 'source_invocation': {'status': 'UNKNOWN_SOURCE_BINDING'}}
                    return {'raw_source': warm_ref(item, key), 'source_invocation': warm_ref(item, 'source_invocation')}
                warm_sources = {'physical_lambda0': {'temperature': warm_source_record(warm_by['physical_lambda0'], 'raw_source'), 'trajectory': warm_source_record(warm_by['physical_lambda0'], 'physical_dump'), 'source_input': warm_source_record(warm_by['physical_lambda0'], 'source_input'), 'source_script': warm_source_record(warm_by['physical_lambda0'], 'source_script')}, 'einstein_lambda1': {'temperature': warm_source_record(warm_by['einstein_lambda1'], 'raw_source'), 'spring': warm_source_record(warm_by['einstein_lambda1'], 'raw_source'), 'trajectory': warm_source_record(warm_by['einstein_lambda1'], 'trajectory'), 'source_input': warm_source_record(warm_by['einstein_lambda1'], 'source_input'), 'source_script': warm_source_record(warm_by['einstein_lambda1'], 'source_script')}, 'interpretation': 'raw warm evidence only; each local review is non-authorizing until independent source review'}
                cycle = {'schema': 'case06-integration-cycle/v1', 'phase': self._case06_phase, 'role': self._case06_role, 'cycle_id': int(iteration), 'prepared_snapshot_path': str(snapshot), 'prepared_snapshot_sha256': drv_sha(snapshot), 'phase_permit_sha256': drv_hashlib.sha256(drv_json.dumps(permit, sort_keys=True).encode()).hexdigest(), 'numpy_rng_state_before_cycle_sha256': cycle_rng_sha, 'positive_run_steps': expected_runs, 'actual_forward_curve': {'path': f'forward_{iteration}.dat', 'sha256': drv_sha(drv_Path.cwd() / f'forward_{iteration}.dat')}, 'actual_backward_curve': {'path': f'backward_{iteration}.dat', 'sha256': drv_sha(drv_Path.cwd() / f'backward_{iteration}.dat')}, 'forward_lambda_review': forward, 'backward_lambda_review': backward, 'warm_observations': self._case06_warm_reviews, 'warm_sources': warm_sources, 'native_invocations': invocation_refs, 'invocation_segments': invocation_segments, 'native_invocation_refs': invocation_refs, 'local_warm_checks': 'PASS' if warm_local else 'UNKNOWN_OR_NOT_MET', 'local_lambda_grid_checks': 'PASS' if lambda_local else 'UNKNOWN_OR_NOT_MET', 'status': 'CYCLE_NATIVE_COMPLETE_REVIEW_REQUIRED' if warm_local and lambda_local else 'CYCLE_NATIVE_COMPLETE_SCIENCE_UNKNOWN', 'fe_authorized': False}
                target = drv_Path.cwd() / f'case06-integration-cycle-{iteration}.json'
                target.write_text(drv_json.dumps(cycle, indent=2, allow_nan=False) + '\n')
                self._case06_last_cycle_receipt = {'path': target.name, 'sha256': drv_sha(target)}
                return result
            except BaseException as exc:
                if proxies:
                    try:
                        proxies[0].close()
                        proxies[0].rotate_logs('integration')
                    except Exception:
                        pass
                failure = {'schema': 'case06-integration-cycle/v1', 'phase': getattr(self, '_case06_phase', 'unknown'), 'role': getattr(self, '_case06_role', 'unknown'), 'cycle_id': int(iteration), 'status': 'NATIVE_OR_SCIENTIFIC_STOP', 'fe_authorized': False, 'error_type': type(exc).__name__, 'error': str(exc), 'positive_run_steps': proxies[0].positive_runs if proxies else [], 'warm_observations': proxies[0].reviews if proxies else []}
                target = drv_Path.cwd() / f'case06-integration-cycle-{iteration}.json'
                target.write_text(drv_json.dumps(failure, indent=2, allow_nan=False) + '\n')
                self._case06_last_cycle_receipt = {'path': target.name, 'sha256': drv_sha(target)}
                raise
            finally:
                drv_solid_module.ph.remap_box = previous
                drv_solid_module.ph.create_object = previous_create
                self._integration_start_configuration = original_start

    def drv__numpy_state_sha(state=None):
        state = drv_np.random.get_state() if state is None else state
        serial = {'bit_generator': state[0], 'state': drv_np.asarray(state[1], dtype=drv_np.uint32).tolist(), 'position': int(state[2]), 'has_gauss': int(state[3]), 'cached_gaussian': float(state[4])}
        return drv_hashlib.sha256(drv_json.dumps(serial, sort_keys=True).encode()).hexdigest()

    def drv__integration_invocation_refs(folder: drv_Path, before: set[str]):
        refs = []
        manifest = folder / 'case08-instrumentation.jsonl'
        if not manifest.is_file():
            return refs
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            rec = drv_json.loads(line)
            invocation = rec.get('invocation_id')
            if not invocation or invocation in before:
                continue
            execution = folder / f'case08-execution.{invocation}.json'
            event = drv_json.loads(execution.read_text()) if execution.is_file() else {}
            original = drv_Path(rec['original_path'])
            instrumented = drv_Path(rec['instrumented_path'])
            native_log = event.get('native_log_archive', {})
            log_path = drv_Path(native_log.get('path', '')) if native_log else drv_Path()
            run_segments = []
            if log_path.is_file():
                log_text = log_path.read_text(errors='replace')
                begin_re = drv_re.compile('^CASE08_RUN_BEGIN segment=(\\S+) index=(\\d+) planned_steps=(\\d+) start_step=(-?\\d+)\\s*$', drv_re.M)
                end_re = drv_re.compile('^CASE08_RUN_END segment=(\\S+) index=(\\d+) planned_steps=(\\d+) end_step=(-?\\d+)\\s*$', drv_re.M)
                loop_re = drv_re.compile('^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$', drv_re.M)
                begins = list(begin_re.finditer(log_text))
                ends = list(end_re.finditer(log_text))
                loops = list(loop_re.finditer(log_text))
                if len(begins) == len(ends) == len(loops):
                    for (b, e, l) in zip(begins, ends, loops):
                        bm = b.groups()
                        em = e.groups()
                        lm = l.groups()
                        run_segments.append({'native_segment_name': bm[0], 'run_index': int(bm[1]), 'planned_steps': int(bm[2]), 'start_step': int(bm[3]), 'actual_steps': int(lm[0]), 'atom_count': int(lm[1]), 'end_step': int(em[3]), 'event_order_valid': b.start() < l.start() < e.start() and bm[0] == em[0] and (bm[1] == em[1]) and (bm[2] == em[2]) and (int(em[3]) - int(bm[3]) == int(lm[0]))})

            def ref(path, digest=None):
                path = drv_Path(path)
                return {'path': str(path.resolve()), 'sha256': digest or (drv_sha(path) if path.is_file() else None)}
            changed = []
            for item in event.get('changed_native_output_snapshots', []):
                arc = item.get('archive', {})
                changed.append({'native_path': item.get('source', item.get('path')), 'native_sha256': item.get('source_sha256', item.get('sha256')), 'archive_path': arc.get('path'), 'archive_sha256': arc.get('sha256'), 'archive_bytes': arc.get('bytes')})
            refs.append({'invocation_id': invocation, 'original_input': ref(original, rec.get('original_sha256')), 'executed_input': ref(instrumented, rec.get('instrumented_sha256')), 'execution_receipt': ref(execution, drv_sha(execution) if execution.is_file() else None), 'native_log': ref(log_path, native_log.get('sha256')) if native_log else None, 'native_returncode': event.get('native_returncode'), 'wrapper_integrity_rc': event.get('wrapper_integrity_rc'), 'changed_native_output_snapshots': changed, 'run_segments': run_segments})
        return refs

    def drv__artifact_ref(path: drv_Path):
        path = drv_Path(path).resolve()
        return {'path': str(path), 'sha256': drv_sha(path) if path.is_file() else None, 'namespace': 'candidate'}

    def drv__output_invocation_ref(invocations, path: drv_Path, planned_steps: int, segment_kind: str):
        """Return an exact wrapper-output and native-run binding, or explicit UNKNOWN."""
        path = drv_Path(path).resolve()
        digest = drv_sha(path) if path.is_file() else None
        matches = []
        for inv in invocations:
            output = any((x.get('native_path') and drv_Path(x['native_path']).resolve() == path and (x.get('native_sha256') == digest) for x in inv.get('changed_native_output_snapshots', [])))
            if not output:
                continue
            for seg in inv.get('run_segments', []):
                if int(seg.get('actual_steps', -1)) == int(planned_steps):
                    matches.append({'invocation_id': inv['invocation_id'], 'run_index': int(seg['run_index']), 'segment_kind': segment_kind, 'native_segment_name': seg['native_segment_name']})
        if len(matches) != 1:
            return {'status': 'UNKNOWN_SOURCE_BINDING', 'reason': f'expected one wrapper output binding, found {len(matches)}', 'path': str(path), 'sha256': digest, 'planned_steps': planned_steps, 'segment_kind': segment_kind}
        return matches[0]

    def drv__attribute_cycle_segments(invocations, expected_positive_steps):
        """Bind native run markers to the four positive F/B-cycle stages in order."""
        positive = []
        all_segments = []
        for inv in invocations:
            for seg in inv.get('run_segments', []):
                if seg.get('event_order_valid') is not True or seg.get('actual_steps') != seg.get('planned_steps'):
                    raise RuntimeError(f"native run marker/Loop mismatch in {inv.get('invocation_id')}")
                item = {'invocation_id': inv['invocation_id'], 'run_index': int(seg['run_index']), 'native_segment_name': seg['native_segment_name'], 'planned_steps': int(seg['planned_steps']), 'actual_steps': int(seg['actual_steps']), 'atom_count': int(seg['atom_count']), 'start_step': int(seg['start_step']), 'end_step': int(seg['end_step']), 'native_log': inv.get('native_log'), 'original_input': inv.get('original_input'), 'executed_input': inv.get('executed_input'), 'execution_receipt': inv.get('execution_receipt')}
                if item['actual_steps'] > 0:
                    positive.append(item)
                else:
                    item['segment_kind'] = 'run0'
                all_segments.append(item)
        if [x['actual_steps'] for x in positive] != list(map(int, expected_positive_steps)):
            raise RuntimeError(f"native positive Loop sequence differs from cycle plan: {[x['actual_steps'] for x in positive]}")
        kinds = ('fe_warm_physical', 'fe_switch', 'fe_warm_einstein', 'fe_switch')
        legs = ('forward', 'forward', 'backward', 'backward')
        for (i, item) in enumerate(positive):
            item['segment_kind'] = kinds[i]
            item['leg'] = legs[i]
            item['native_positive_ordinal'] = i
        return all_segments

    def drv__attribute_setup_segments(invocations, expected_positive_steps):
        positive = []
        rows = []
        for inv in invocations:
            for seg in inv.get('run_segments', []):
                item = {'invocation_id': inv['invocation_id'], 'run_index': int(seg['run_index']), 'native_segment_name': seg['native_segment_name'], 'planned_steps': int(seg['planned_steps']), 'actual_steps': int(seg['actual_steps']), 'start_step': int(seg['start_step']), 'end_step': int(seg['end_step']), 'atom_count': int(seg['atom_count']), 'native_log': inv.get('native_log'), 'original_input': inv.get('original_input'), 'executed_input': inv.get('executed_input'), 'execution_receipt': inv.get('execution_receipt'), 'event_order_valid': seg.get('event_order_valid') is True}
                if item['actual_steps'] > 0:
                    positive.append(item)
                else:
                    item['segment_kind'] = 'run0'
                rows.append(item)
        observed = [x['actual_steps'] for x in positive]
        valid = observed == list(map(int, expected_positive_steps)) and all((x['event_order_valid'] for x in rows))
        kinds = ('setup_ramp', 'setup_npt_primary', 'setup_fixed_h_nvt')
        for (i, item) in enumerate(positive):
            item['segment_kind'] = kinds[i] if valid else 'UNCLASSIFIED_POSITIVE'
            item['native_positive_ordinal'] = i
        return {'status': 'SOURCE_LEDGER_RECONCILED' if valid else 'UNKNOWN_NATIVE_LEDGER', 'expected_positive_steps': list(map(int, expected_positive_steps)), 'observed_positive_steps': observed, 'segments': rows, 'issues': [] if valid else ['native positive Loop sequence did not exactly match 1000 ramp, 10000 NPT, 5000 fixed-H NVT']}

    def drv__setup_record_from_ready(ready_path: drv_Path, run_root: drv_Path):
        ready_path = drv_Path(ready_path)
        ready = drv_json.loads(ready_path.read_text())
        phase = ready.get('phase')
        role = ready.get('role')
        seed = ready.get('master_seed')
        snap = ready_path.parent / ready.get('equilibrated_snapshot', '')
        return {'setup_id': f'{role}-{phase}-{seed}', 'phase': phase, 'role': role, 'master_seed': seed, 'atoms': ready.get('atoms'), 'geometry_reference': ready.get('geometry_reference'), 'snapshot': {'path': str(snap.resolve()), 'sha256': drv_sha(snap) if snap.is_file() else None, 'namespace': 'candidate'}, 'snapshot_path': str(snap.resolve()), 'snapshot_sha256': drv_sha(snap) if snap.is_file() else None, 'scientific_gates': ready.get('scientific_gates', {}), 'native_invocations': ready.get('native_invocations', []), 'invocation_segments': ready.get('invocation_segments', {}).get('segments', []), 'setup_status': ready.get('status', 'UNKNOWN_SCIENTIFIC_GATE'), 'fe_authorized': False, 'ancestry_note': 'one fresh 16k setup; shared warm segments are added by campaign cycle ledger exactly once'}

    def drv__integration_invocation_ids(folder: drv_Path) -> set[str]:
        manifest = folder / 'case08-instrumentation.jsonl'
        if not manifest.is_file():
            return set()
        found = set()
        for line in manifest.read_text().splitlines():
            if line.strip():
                value = drv_json.loads(line).get('invocation_id')
                if value:
                    found.add(value)
        return found

    def drv_validate_run0_prerequisite(proof_path: drv_Path | None=None):
        """Fail before positive MD unless frozen numeric run-0 comparisons pass.

        The receipt is produced by the guarded native run-0 stage.  Its PE/force
        values are observations, never inferred from geometry or a planned call.
        """
        proof_path = drv_Path.cwd() / 'acceptance' / 'native-zero-md-regression.json' if proof_path is None else drv_Path(proof_path)
        if not proof_path.is_absolute():
            proof_path = drv_Path.cwd() / proof_path
        proof_path = proof_path.resolve()
        if not proof_path.is_file():
            raise RuntimeError('guarded native run-0 energy/force receipt missing; no positive MD may start')
        proof = drv_json.loads(proof_path.read_text())
        if proof.get('schema') != 'case06-native-zero-md-regression/v1' or proof.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY':
            raise RuntimeError('native run-0 numeric-regression schema/status is not accepted')
        matrix = drv_json.loads((drv_PAYLOAD / 'candidate-scope.json').read_text())
        criterion = matrix.get('native_zero_md_numeric_regression')
        if not isinstance(criterion, dict) or criterion.get('threshold_adaptation_after_data') is not False:
            raise RuntimeError('frozen native zero-MD numeric-regression criteria missing')
        expected = {'alpha_quartz': drv_sha(drv_PAYLOAD / 'native_inputs/alpha_quartz-576.data'), 'coesite_original': drv_sha(drv_PAYLOAD / 'native_inputs/coesite-384.source.data'), 'coesite_aligned': drv_sha(drv_PAYLOAD / 'native_inputs/coesite-384.data'), 'potential': drv_sha(drv_PAYLOAD / 'native_inputs/SiOx_potential.yace')}
        author_worker = drv_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') == '1'
        expected['native_binary'] = (drv_os.environ.get('CASE06_AUTHOR_BINARY_SHA') if author_worker
                                     else os.environ.get("CASE159_LAMMPS_SHA256", '434e1de023b260ef427495a257b6ad0ec995f27cfa1a8129d9089c6100dceb68'))
        if author_worker and not expected['native_binary']:
            raise RuntimeError('author CPU provider binary SHA is not host-pinned')
        if proof.get('source_hashes') != expected:
            raise RuntimeError('native run-0 regression does not bind current structures, public YACE, and pinned binary')
        phases = proof.get('phases')
        if not isinstance(phases, dict) or set(phases) != {'alpha_quartz', 'coesite'}:
            raise RuntimeError('native run-0 regression must cover both phases')
        geometry_path = drv_PAYLOAD / 'native_inputs/geometry-manifest.json'
        geometry = drv_json.loads(geometry_path.read_text())
        if geometry.get('schema') != 'case06-public-periodic-quotient/v1' or geometry.get('matrix_sha256') != matrix.get('source_matrix_sha256'):
            raise RuntimeError('run-0 site maps are not bound to the current source-derived geometry and frozen matrix')
        root = proof_path.parent.parent.resolve()

        def artifact(rec, path_key, sha_key):
            rel = rec.get(path_key)
            digest = rec.get(sha_key)
            if not isinstance(rel, str) or not isinstance(digest, str) or (not drv_re.fullmatch('[0-9a-f]{64}', digest)):
                raise RuntimeError(f'native run-0 artifact reference missing: {path_key}/{sha_key}')
            path = (root / rel).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                raise RuntimeError('native run-0 artifact escapes job root')
            if not path.is_file() or drv_sha(path) != digest:
                raise RuntimeError(f'native run-0 artifact missing/hash mismatch: {rel}')
            return path

        def finite_number(value, label):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (not drv_math.isfinite(float(value))):
                raise RuntimeError(f'nonfinite/missing numeric native run-0 value: {label}')
            return float(value)
        pe_abs = float(criterion['base_total_PE_absolute_tolerance_eV'])
        pe_rel = float(criterion['base_total_PE_relative_tolerance'])
        force_abs = float(criterion['per_atom_force_vector_absolute_tolerance_eV_per_A'])
        force_rel = float(criterion['per_atom_force_vector_relative_tolerance'])
        if pe_abs != 1e-06 or pe_rel != 1e-10 or force_abs != 1e-08 or (force_rel != 1e-10):
            raise RuntimeError('numeric run-0 criteria differ from the registered frozen values')
        expected_atoms = {'alpha_quartz': 576, 'coesite': 384}
        for (phase, rec) in phases.items():
            n = expected_atoms[phase]
            if rec.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY' or rec.get('base_atom_count') != n:
                raise RuntimeError(f'{phase} native run-0 regression is not admitted or has wrong base atom count')
            mapping = rec.get('site_map')
            if not isinstance(mapping, dict):
                raise RuntimeError(f'{phase} source-derived site map is missing')
            map_path = artifact(mapping, 'path', 'sha256')
            if mapping.get('base_atom_count') != n or mapping.get('target_atom_count') != 2 * n or mapping.get('mapping_unique_bijective') is not True:
                raise RuntimeError(f'{phase} base-to-size site map does not prove a unique determinant-two correspondence')
            map_doc = drv_json.loads(map_path.read_text())
            map_pairs = map_doc.get('site_pairs')
            if not isinstance(map_pairs, list) or len(map_pairs) != 2 * n:
                raise RuntimeError(f'{phase} site-map artifact must enumerate both target copies for every base site')
            pair_keys = set()
            base_counts = {}
            target_ids = set()
            for pair in map_pairs:
                bid = pair.get('base_atom_id')
                tid = pair.get('target_atom_id')
                if isinstance(bid, bool) or not isinstance(bid, int) or (not 1 <= bid <= n) or isinstance(tid, bool) or (not isinstance(tid, int)) or (tid in target_ids):
                    raise RuntimeError(f'{phase} site-map artifact has invalid or duplicated IDs')
                target_ids.add(tid)
                base_counts[bid] = base_counts.get(bid, 0) + 1
                pair_keys.add((bid, tid))
            if set(base_counts) != set(range(1, n + 1)) or any((count != 2 for count in base_counts.values())):
                raise RuntimeError(f'{phase} site-map artifact is not a two-copy bijection over base sites')
            geom_rec = next((x for x in geometry.get('structures', []) if x.get('phase') == phase), None)
            expected_pairs = geom_rec.get('size_supercell', {}).get('site_pairs') if isinstance(geom_rec, dict) else None
            if not isinstance(expected_pairs, list) or map_pairs != expected_pairs:
                raise RuntimeError(f'{phase} native run-0 site map differs from the source-derived geometry manifest')
            comparisons = rec.get('comparisons')
            if not isinstance(comparisons, dict) or set(comparisons) != {'raw_to_gauge', 'base_to_size'}:
                raise RuntimeError(f'{phase} run-0 receipt lacks raw/gauge and base/size comparisons')
            for (label, cmprec) in comparisons.items():
                if cmprec.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY':
                    raise RuntimeError(f'{phase}/{label} numerical comparison did not pass')
                if cmprec.get('native_command_count') != 2 or cmprec.get('run_steps') != [0, 0]:
                    raise RuntimeError(f'{phase}/{label} does not bind two native run-0 calls')
                for prefix in ('base', 'target'):
                    call = cmprec[f'{prefix}_call']
                    log_path = artifact(call, 'native_log_path', 'native_log_sha256')
                    observation = cmprec.get(f'{prefix}_observation')
                    if not isinstance(observation, dict):
                        raise RuntimeError(f'{phase}/{label}/{prefix} parsed native observation is missing')
                    artifact(observation, 'observation_path', 'observation_sha256')
                    artifact(observation, 'force_dump_path', 'force_dump_sha256')
                    if call.get('native_returncode') != 0:
                        raise RuntimeError(f'{phase}/{label}/{prefix} native run-0 failed')
                    if call.get('wrapper_integrity_rc') != 0:
                        raise RuntimeError(f'{phase}/{label}/{prefix} native wrapper integrity failed')
                    artifact(call, 'original_input_path', 'original_input_sha256')
                    artifact(call, 'instrumented_input_path', 'instrumented_input_sha256')
                    artifact(call, 'execution_receipt_path', 'execution_receipt_sha256')
                    log_text = log_path.read_text(errors='replace')
                    begins = drv_re.findall('^CASE08_RUN_BEGIN segment=(\\S+) index=(\\d+) planned_steps=(\\d+) start_step=(-?\\d+)\\s*$', log_text, drv_re.M)
                    ends = drv_re.findall('^CASE08_RUN_END segment=(\\S+) index=(\\d+) planned_steps=(\\d+) end_step=(-?\\d+)\\s*$', log_text, drv_re.M)
                    loops = drv_re.findall('^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$', log_text, drv_re.M)
                    call_atoms = 2 * n if label == 'base_to_size' and prefix == 'target' else n
                    if len(begins) != 1 or len(ends) != 1 or len(loops) != 1 or (begins[0][1:3] != ('1', '0')) or (ends[0][1:3] != ('1', '0')) or (begins[0][0] != ends[0][0]) or (int(begins[0][3]) != 0) or (int(ends[0][3]) != 0) or (int(loops[0][0]) != 0) or (int(loops[0][1]) != call_atoms):
                        raise RuntimeError(f'{phase}/{label}/{prefix} native log does not prove one ordered zero-step call with {call_atoms} atoms')
                    if call.get('native_atom_count') != call_atoms or call.get('native_step') != 0:
                        raise RuntimeError(f'{phase}/{label}/{prefix} observation metadata has the wrong native atom count/step')
                    if not log_text.find('CASE08_RUN_BEGIN ') < log_text.find('Loop time ') < log_text.find('CASE08_RUN_END '):
                        raise RuntimeError(f'{phase}/{label}/{prefix} native run-0 event order is invalid')
                base = cmprec['base']
                target = cmprec['target']
                ub = finite_number(base.get('pe_eV'), f'{phase}/{label}/base PE')
                ut = finite_number(target.get('pe_eV'), f'{phase}/{label}/target PE')
                nb = base.get('atom_count')
                nt = target.get('atom_count')
                if nb != n or nt not in (n, 2 * n):
                    raise RuntimeError(f'{phase}/{label} run-0 atom count mismatch')
                if label == 'raw_to_gauge' and nt != n:
                    raise RuntimeError(f'{phase} gauge comparison must preserve atom count')
                if label == 'base_to_size' and nt != 2 * n:
                    raise RuntimeError(f'{phase} size comparison must have determinant-two atom count')
                pe_delta = ut / nt - ub / nb if nt == 2 * n else ut - ub
                pe_limit = max(pe_abs, pe_rel * abs(ub)) / n if nt == 2 * n else max(pe_abs, pe_rel * abs(ub))
                if abs(pe_delta) > pe_limit:
                    raise RuntimeError(f'{phase}/{label} native PE numerical regression failed')
                force_map = cmprec.get('force_site_map')
                force_rows = cmprec.get('force_comparisons')
                if not isinstance(force_map, dict) or not isinstance(force_rows, list):
                    raise RuntimeError(f'{phase}/{label} mapped per-site force evidence is missing')
                fm_path = artifact(force_map, 'path', 'sha256')
                fm_doc = drv_json.loads(fm_path.read_text())
                fm_pairs = fm_doc.get('site_pairs')
                if not isinstance(fm_pairs, list):
                    raise RuntimeError(f'{phase}/{label} force map lacks explicit site pairs')
                fm_keys = {(p.get('base_atom_id'), p.get('target_atom_id')) for p in fm_pairs}
                expected_fm_keys = set(pair_keys) if label == 'base_to_size' else {(i, i) for i in range(1, n + 1)}
                if fm_keys != expected_fm_keys:
                    raise RuntimeError(f'{phase}/{label} force map is not the source-derived identity/size map')
                expected_force_rows = n if label == 'raw_to_gauge' else 2 * n
                if len(force_rows) != expected_force_rows:
                    raise RuntimeError(f'{phase}/{label} must compare every mapped target-site force, including both size-cell copies')
                seen_target = set()
                base_multiplicity = {}
                for row in force_rows:
                    atom_id = row.get('base_atom_id')
                    target_id = row.get('target_atom_id', atom_id)
                    if isinstance(atom_id, bool) or not isinstance(atom_id, int) or (not 1 <= atom_id <= n):
                        raise RuntimeError('invalid base atom in force comparison')
                    if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id in seen_target:
                        raise RuntimeError('duplicate/invalid target atom in force comparison')
                    if (atom_id, target_id) not in fm_keys:
                        raise RuntimeError(f'{phase}/{label} force row is not present in the hashed site map')
                    seen_target.add(target_id)
                    base_multiplicity[atom_id] = base_multiplicity.get(atom_id, 0) + 1
                    fb = drv_np.asarray(row.get('base_force_eV_per_A'), float)
                    ft = drv_np.asarray(row.get('target_force_eV_per_A'), float)
                    if fb.shape != (3,) or ft.shape != (3,) or (not drv_np.isfinite(fb).all()) or (not drv_np.isfinite(ft).all()):
                        raise RuntimeError(f'{phase}/{label} force vector missing or non-finite')
                    delta = float(drv_np.linalg.norm(ft - fb))
                    limit = max(force_abs, force_rel * max(float(drv_np.linalg.norm(fb)), float(drv_np.linalg.norm(ft))))
                    if delta > limit:
                        raise RuntimeError(f'{phase}/{label} mapped force regression failed at atom {atom_id}')
                if set(base_multiplicity) != set(range(1, n + 1)) or any((v != (1 if label == 'raw_to_gauge' else 2) for v in base_multiplicity.values())):
                    raise RuntimeError(f'{phase}/{label} force map does not cover every base site with the required multiplicity')
        return proof

    def drv__state_from_ready_record(record):
        raw = record['numpy_rng_state']
        return (raw['bit_generator'], drv_np.asarray(raw['state'], dtype=drv_np.uint32), int(raw['position']), int(raw['has_gauss']), float(raw['cached_gaussian']))

    def drv__warm_window_review(path: drv_Path, *, phase: str, role: str, cycle_id: int, endpoint: str, expected_start_step: int):
        """Validate the native 50-row warm window; report temperature precision separately."""
        if not path.is_file():
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'warm observation file missing', 'path': path.name}
        rows = []
        for line in path.read_text(errors='replace').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            fields = line.split()
            try:
                values = [float(x) for x in fields]
            except ValueError:
                return {'schema': 'case06-fe-warm-observation-review/v1', 'phase': phase, 'role': role, 'cycle_id': cycle_id, 'endpoint': endpoint, 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'hard_integrity_status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': f'malformed non-comment warm observation row {len(rows) + 1}', 'path': path.name}
            if not values or not all((drv_math.isfinite(x) for x in values)):
                raise RuntimeError(f'non-finite warm observation row in {path}')
            if not values[0].is_integer():
                raise RuntimeError(f'noninteger native timestep in {path}')
            rows.append(values)
        if any((len(r) != 6 for r in rows)):
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': f'expected six columns per warm row; found row widths {[len(r) for r in rows]}', 'path': path.name, 'observed_rows': len(rows)}
        all_rows = rows
        steps = [int(r[0]) for r in rows]
        expected = list(range(int(expected_start_step) + 20, int(expected_start_step) + 1001, 20))
        if len(rows) == 51 and steps == [int(expected_start_step)] + expected:
            rows = rows[1:]
            steps = steps[1:]
        if len(rows) != 50 or steps != expected:
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'warm rows do not match native Loop start+20..start+1000 at cadence20', 'path': path.name, 'observed_steps': [steps[0], steps[-1]] if steps else []}
        arr = drv_np.asarray(rows, float)
        temp = arr[:, 1]
        lam = arr[:, 2]
        pe = arr[:, 3]
        spring_o = arr[:, 4]
        spring_si = arr[:, 5]
        target_lambda = 0.0 if endpoint == 'physical_lambda0' else 1.0
        lambda_ok = bool(drv_np.max(drv_np.abs(drv_np.asarray(all_rows, float)[:, 2] - target_lambda)) <= 1e-10)
        if not lambda_ok:
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'native warm lambda does not stay at registered endpoint', 'path': path.name, 'lambda_min': float(lam.min()), 'lambda_max': float(lam.max()), 'expected_lambda': target_lambda}

        def summary(values):
            values = drv_np.asarray(values, float)
            tau = drv_integrated_autocorrelation_time(values)
            ess = min(float(len(values)), len(values) / (2 * tau))
            mean = float(values.mean())
            se = float(values.std(ddof=1) / drv_math.sqrt(max(ess, 1)))
            ci = float(drv_t.ppf(0.975, max(1, ess - 1)) * se)
            return {'n': len(values), 'ess': ess, 'mean': mean, 'ci95': ci, 'covers_600K': bool(mean - ci <= 600 <= mean + ci)}
        full = summary(temp)
        first = summary(temp[:25])
        second = summary(temp[25:])
        drift = second['mean'] - first['mean']
        se = drv_math.sqrt((first['ci95'] / drv_t.ppf(0.975, max(1, first['ess'] - 1))) ** 2 + (second['ci95'] / drv_t.ppf(0.975, max(1, second['ess'] - 1))) ** 2)
        drift_ci = float(drv_t.ppf(0.975, max(1, min(first['ess'], second['ess']) - 1)) * se)
        temperature_diagnostics = {'full_ess_ge_20': full['ess'] >= 20, 'first_half_ess_ge_10': first['ess'] >= 10, 'second_half_ess_ge_10': second['ess'] >= 10, 'full_ci_covers_600K': full['covers_600K'], 'first_half_ci_covers_600K': first['covers_600K'], 'second_half_ci_covers_600K': second['covers_600K'], 'half_difference_ci_contains_zero': abs(drift) <= drift_ci}
        hard_checks = {'all_observations_finite': bool(drv_np.isfinite(arr).all()), 'lambda_endpoint_constant': lambda_ok, 'source_loop_start_bound': True, 'spring_energy_columns_finite': bool(drv_np.isfinite(arr[:, 4:6]).all())}
        temperature_status = 'DIAGNOSTIC_PASS' if all(temperature_diagnostics.values()) else 'UNKNOWN_TEMPERATURE_PRECISION'
        return {'schema': 'case06-fe-warm-observation-review/v1', 'phase': phase, 'role': role, 'cycle_id': cycle_id, 'endpoint': endpoint, 'path': path.name, 'rows': len(rows), 'columns': ['step', 'Tcm_K', 'lambda', 'PE_eV_per_atom', 'O_spring_group_total_eV', 'Si_spring_group_total_eV'], 'temperature_full': full, 'temperature_first_half': first, 'temperature_second_half': second, 'half_difference_K': drift, 'half_difference_ci95_K': drift_ci, 'pe_eV_per_atom_range': [float(pe.min()), float(pe.max())], 'O_spring_group_total_eV_range': [float(spring_o.min()), float(spring_o.max())], 'Si_spring_group_total_eV_range': [float(spring_si.min()), float(spring_si.max())], 'column_energy_semantics': {'PE_eV_per_atom': 'Calphy dU1 = pe/atoms; per-atom energy', 'O_spring_group_total_eV': 'Calphy dU2 = f_ff1; group-total spring energy in eV', 'Si_spring_group_total_eV': 'Calphy dU3 = f_ff2; group-total spring energy in eV'}, 'gate_checks': hard_checks, 'temperature_diagnostics': temperature_diagnostics, 'temperature_precision_status': temperature_status, 'finite_warm_bias_status': 'UNKNOWN_UNMEASURED', 'hard_integrity_status': 'PASS_WARM_RAW_INTEGRITY_REVIEW_REQUIRED' if all(hard_checks.values()) else 'UNKNOWN_SCIENTIFIC_GATE', 'status': 'PASS_WARM_RAW_INTEGRITY_REVIEW_REQUIRED' if all(hard_checks.values()) else 'UNKNOWN_SCIENTIFIC_GATE', 'interpretation': 'Raw native endpoint integrity is distinct from temperature precision; favorable diagnostics do not bound finite-time warm bias.'}

    class drv__WarmObservationProxy:
        """Observe stock Calphy run boundaries without changing its force dynamics."""

        def __init__(self, inner, job, cycle_id):
            self.inner = inner
            self.job = job
            self.cycle_id = cycle_id
            self.positive_runs = []
            self.pending = None
            self.reviews = []
            self.completed = []
            self.warm_path = None
            self.warm_dump = None
            self.phase = job._case06_phase
            self.role = job._case06_role
            self.n_warm = int(job._warm_start_steps(npt=False))
            if self.n_warm != 1000:
                raise RuntimeError(f'frozen FE warm block must be 1000, observed {self.n_warm}')

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def _start_warm(self, endpoint):
            if endpoint == 'physical_lambda0':
                self.warm_path = drv_Path.cwd() / f'case06-warm-physical-{self.cycle_id}.dat'
                self.warm_dump = drv_Path.cwd() / f'case06-warm-physical-{self.cycle_id}.dump'
                dump_id = f'case06_warm_dump_{self.cycle_id}'
                self.inner.command(f'dump {dump_id} all custom 20 {self.warm_dump.name} id type x y z ix iy iz vx vy vz')
                self.inner.command(f'dump_modify {dump_id} sort id format float %.16g first yes')
                self.pending = {'endpoint': endpoint, 'fix_id': f'case06_warm_obs_{self.cycle_id}_physical', 'dump_id': dump_id, 'path': self.warm_path, 'dump_path': self.warm_dump}
            else:
                self.warm_path = drv_Path.cwd() / f'case06-warm-einstein-{self.cycle_id}.dat'
                self.warm_dump = drv_Path.cwd() / f'case06-warm-einstein-{self.cycle_id}.dump'
                dump_id = f'case06_warm_dump_{self.cycle_id}'
                self.inner.command(f'dump {dump_id} all custom 20 {self.warm_dump.name} id type x y z ix iy iz vx vy vz')
                self.inner.command(f'dump_modify {dump_id} sort id format float %.16g first yes')
                self.pending = {'endpoint': endpoint, 'fix_id': f'case06_warm_obs_{self.cycle_id}_einstein', 'dump_id': None, 'path': self.warm_path, 'dump_path': self.warm_dump}
                self.pending['dump_id'] = dump_id
            fix = self.pending['fix_id']
            self.inner.command(f'fix {fix} all ave/time 20 1 20 c_Tcm v_lambda v_dU1 v_dU2 v_dU3 file {self.warm_path.name} format " %.16g"')

        def _finish_warm(self):
            if not self.pending:
                return
            self.inner.command(f"unfix {self.pending['fix_id']}")
            if self.pending['dump_id']:
                self.inner.command(f"undump {self.pending['dump_id']}")
            self.pending['positive_run_index'] = len(self.positive_runs) - 1
            self.completed.append(self.pending.copy())
            self.pending = None

        def finalize(self, invocation_segments):
            if self.pending:
                self._finish_warm()
            by_ordinal = {x['native_positive_ordinal']: x for x in invocation_segments if x.get('actual_steps', 0) > 0}
            for item in self.completed:
                warm_path = drv_Path(item['path'])
                dump_path = drv_Path(item['dump_path']) if item.get('dump_path') else None
                segment = by_ordinal.get(item['positive_run_index'])
                if segment is None or segment.get('actual_steps') != self.n_warm:
                    review = {'schema': 'case06-fe-warm-observation-review/v1', 'phase': self.phase, 'role': self.role, 'cycle_id': self.cycle_id, 'endpoint': item['endpoint'], 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'no exact native Loop segment binds this warm observation'}
                    self.reviews.append(review)
                    continue
                start_step = int(segment['start_step'])
                review = drv__warm_window_review(warm_path, phase=self.phase, role=self.role, cycle_id=self.cycle_id, endpoint=item['endpoint'], expected_start_step=start_step)
                review.update({'endpoint': item['endpoint'], 'positive_run_index': item['positive_run_index'], 'native_segment_start_step': start_step, 'native_segment_end_step': int(segment['end_step']), 'path': warm_path.name, 'raw_path_sha256': drv_sha(warm_path) if warm_path.is_file() else None, 'source_script_contract': {'fix_id': item['fix_id'], 'fix_command': f'''fix {item['fix_id']} all ave/time 20 1 20 c_Tcm v_lambda v_dU1 v_dU2 v_dU3 file {warm_path.name} format " %.16g"''', 'thermo_observation_cadence_steps': 20, 'expected_rows': 50}})
                if dump_path:
                    review['phase_dump_path'] = dump_path.name
                    review['phase_dump_sha256'] = drv_sha(dump_path) if dump_path.is_file() else None
                    if item['endpoint'] == 'physical_lambda0' and review['hard_integrity_status'] == 'PASS_WARM_RAW_INTEGRITY_REVIEW_REQUIRED':
                        try:
                            review['physical_phase_check'] = drv__review_physical_warm_dump(dump_path, self.phase, expected_start_step=start_step, reference_path=self.job._case06_geometry_reference)
                        except Exception as exc:
                            review['physical_phase_check'] = {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': f'{type(exc).__name__}: {exc}'}
                        if review['physical_phase_check'].get('status') != 'PASS_PHYSICAL_WARM_STRUCTURE_REVIEW_REQUIRED':
                            review['hard_integrity_status'] = 'UNKNOWN_SCIENTIFIC_GATE'
                            review['status'] = 'UNKNOWN_SCIENTIFIC_GATE'
                    elif item['endpoint'] == 'einstein_lambda1':
                        review['einstein_anchor_check'] = {'status': 'PENDING_ANCHORED_COORDINATE_REPLAY', 'reason': 'requires independent source-bound comparison to the native Einstein anchor and per-species spring-energy reconstruction', 'trajectory_path': dump_path.name, 'trajectory_sha256': drv_sha(dump_path) if dump_path.is_file() else None}
                        review['hard_endpoint_review_status'] = 'PENDING_ANCHORED_COORDINATE_REPLAY'
                self.reviews.append(review)
            self.completed = []

        def command(self, command):
            text = ' '.join(command.split())
            low = text.lower()
            if low.startswith('run '):
                tokens = low.split()
                if len(tokens) < 2 or not tokens[1].isdigit():
                    raise RuntimeError(f'FE cycle contains an unbudgetable run command: {text}')
                steps = int(tokens[1])
                index = len(self.positive_runs)
                if steps > 0 and steps == self.n_warm and (index in (0, 2)):
                    endpoint = 'physical_lambda0' if index == 0 else 'einstein_lambda1'
                    self._start_warm(endpoint)
                if steps > 0:
                    self.positive_runs.append(steps)
                return self.inner.command(command)
            if low.startswith('fix f4 all print') and 'forward_' in low and self.pending:
                self._finish_warm()
            if low.startswith('pair_modify compute yes') and self.pending:
                self._finish_warm()
            return self.inner.command(command)

    def drv__review_lambda_curve(path: drv_Path, *, phase, role, cycle_id, direction, switch_steps):
        if not path.is_file():
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'native TI curve missing'}
        data = []
        for line in path.read_text(errors='replace').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            try:
                row = [float(x) for x in line.split()]
            except ValueError:
                continue
            if not row or not all((math.isfinite(x) for x in row)):
                raise RuntimeError(f'nonfinite native TI row: {path}')
            data.append(row)
        if len(data) != switch_steps + 1 or any((len(r) != 4 for r in data)):
            return {'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': 'native TI curve row count/width mismatch', 'rows': len(data)}
        lam = drv_np.asarray([r[-1] for r in data])
        (start, end) = (0.0, 1.0) if direction == 'forward' else (1.0, 0.0)
        monotone = bool(drv_np.all(drv_np.diff(lam) >= -1e-12) if end > start else drv_np.all(drv_np.diff(lam) <= 1e-12))
        valid = bool(abs(lam[0] - start) <= 1e-12 and abs(lam[-1] - end) <= 1e-12 and monotone)
        return {'schema': 'case06-native-lambda-grid-review/v1', 'phase': phase, 'role': role, 'cycle_id': cycle_id, 'direction': direction, 'path': path.name, 'sha256': drv_sha(path), 'rows': len(data), 'expected_rows': switch_steps + 1, 'lambda_start': float(lam[0]), 'lambda_end': float(lam[-1]), 'monotone': monotone, 'status': 'PASS_NATIVE_LAMBDA_GRID_REVIEW_REQUIRED' if valid else 'UNKNOWN_SCIENTIFIC_GATE'}

    def drv__review_physical_warm_dump(path: drv_Path, phase: str, expected_start_step: int, reference_path: drv_Path):
        (frames, aliases) = drv_normalize_repeated_frames(drv_read_frames(path))
        expected = list(range(int(expected_start_step), int(expected_start_step) + 1001, 20))
        if len(frames) != 51 or [int(f['step']) for f in frames] != expected:
            raise RuntimeError('physical lambda-0 warm dump must bind exact native Loop start..start+1000/20 (51 frames)')
        ref_path = drv_Path(reference_path).resolve()
        if not ref_path.is_file():
            raise RuntimeError('active role-specific geometry reference missing')
        reference = drv_read_lammps_data(ref_path)
        (base_edges, gap) = drv_graph(reference)
        if len(reference['ids']) != len(frames[0]['ids']):
            raise RuntimeError('warm dump atom count differs from its active role-specific source geometry')
        edge_fractions = []
        gaps = []
        new_edges = []
        faces = []
        for frame in frames:
            if not drv_np.array_equal(frame['ids'], reference['ids']) or not drv_np.array_equal(frame['types'], reference['types']):
                raise RuntimeError(f"physical lambda-0 warm IDs/types changed at {frame['step']}")
            (edges, frame_gap) = drv_graph(frame)
            face = drv_minimum_face_height(frame['H'])
            edge_fractions.append(len(base_edges & edges) / len(base_edges))
            new_edges.append(len(edges - base_edges))
            gaps.append(frame_gap)
            faces.append(face)
        checks = {'all_original_nearest4_edges_retained': min(edge_fractions) == 1.0, 'no_new_nearest4_edges': max(new_edges) == 0, 'all_fourth_fifth_gaps_positive': min(gaps) > 0, 'all_face_heights_gt_10_5_A': min(faces) > 10.5}
        return {'schema': 'case06-physical-lambda0-warm-phase-review/v1', 'status': 'PASS_PHYSICAL_WARM_STRUCTURE_REVIEW_REQUIRED' if all(checks.values()) else 'UNKNOWN_SCIENTIFIC_GATE', 'phase': phase, 'path': path.name, 'sha256': drv_sha(path), 'frames': len(frames), 'frame_aliases': aliases, 'geometry_reference_path': ref_path.name, 'geometry_reference_sha256': drv_sha(ref_path), 'reference_min_gap_A': gap, 'minimum_observed_gap_A': min(gaps), 'minimum_face_height_A': min(faces), 'minimum_edge_fraction': min(edge_fractions), 'maximum_new_edges': max(new_edges), 'gate_checks': checks}

    def drv__validate_calphy_lattice_copy(calc, source_path: drv_Path, atom_count: int, run_root: drv_Path) -> drv_Path:
        """Verify Calphy 2.1.2's constructor-renamed copy against the source bytes."""
        source_path = drv_Path(source_path).resolve()
        run_root = drv_Path(run_root).resolve()
        generated = run_root / f'{calc.create_identifier()}.{calc.kernel}.data'
        if getattr(calc, '_original_lattice', None) != source_path.name or int(getattr(calc, '_natoms', -1)) != int(atom_count) or drv_Path(str(getattr(calc, 'lattice', ''))).resolve() != generated or (generated.parent != run_root) or (not generated.is_file()) or (drv_sha(generated) != drv_sha(source_path)):
            raise RuntimeError(f"Calphy constructor-generated lattice copy is not the exact registered source: original={getattr(calc, '_original_lattice', None)!r}, atoms={getattr(calc, '_natoms', None)!r}, calc_lattice={getattr(calc, 'lattice', None)!r}, expected={str(generated)!r}, copy_exists={generated.is_file()}, copy_sha={(drv_sha(generated) if generated.is_file() else None)}, source_sha={(drv_sha(source_path) if source_path.is_file() else None)}")
        return generated

    def drv_prepare_one_phase(runtime_input_path: drv_Path, run_root: drv_Path, role: str, phase: str, source_receipt: dict | None=None):
        """Run one registered fresh setup after the campaign's paired run-0 barrier.

        This entry point deliberately does not admit FE.  The caller must review the
        returned source-bound receipts before requesting the other phase or any FE.
        """
        import os, yaml
        from calphy.input import Calculation, _to_none
        runtime_input_path = drv_Path(runtime_input_path).resolve()
        run_root = drv_Path(run_root).resolve()
        if role not in {'B', 'R', 'S', 'A'} or phase not in {'alpha_quartz', 'coesite'}:
            raise RuntimeError('one-phase setup requires a registered B/R/S/A role and phase')
        os.chdir(run_root)
        run0_path = run_root / 'acceptance/native-zero-md-regression.json'
        run0 = drv_validate_run0_prerequisite(run0_path)
        if source_receipt is not None:
            receipt_sha = None
            if isinstance(source_receipt, dict):
                if 'gate' in source_receipt:
                    gate = source_receipt.get('gate')
                    if isinstance(gate, dict):
                        nested_sha = gate.get('proof_sha256', gate.get('run0_proof_sha256'))
                        direct_sha = source_receipt.get('proof_sha256', source_receipt.get('run0_proof_sha256'))
                        if direct_sha is not None and nested_sha is not None and direct_sha != nested_sha:
                            raise RuntimeError('phase source receipt contains conflicting proof SHA values')
                        receipt_sha = nested_sha
                else:
                    receipt_sha = source_receipt.get('proof_sha256', source_receipt.get('run0_proof_sha256'))
            if receipt_sha != drv_sha(run0_path):
                raise RuntimeError('phase source receipt does not bind the validated job-local zero-MD proof')
        source_identity = drv_validate_installed_sources()
        identity_sha = drv_sha(run_root / 'calphy-source-identity.json')
        registration_path = run_root / 'native_inputs' / f'seed-registration-{role}.json'
        if not registration_path.is_file():
            raise RuntimeError(f'role registration missing: {registration_path}')
        registration = drv_json.loads(registration_path.read_text())
        if registration.get('schema') != 'case06-role-seed-registration/v1' or registration.get('role') != role or registration.get('matrix_sha256') != drv_json.loads((drv_PAYLOAD / 'candidate-scope.json').read_text()).get('source_matrix_sha256'):
            raise RuntimeError('role/seed registration does not bind this frozen matrix')
        runtime_prov = runtime_input_path.parent / 'runtime-input-provenance.json'
        if not runtime_prov.is_file():
            raise RuntimeError('rendered runtime input provenance missing')
        provenance = drv_json.loads(runtime_prov.read_text())
        template_path = run_root / registration['runtime_template_path']
        if provenance.get('template_sha256') != registration.get('runtime_template_sha256') or not template_path.is_file() or drv_sha(template_path) != registration.get('runtime_template_sha256') or (provenance.get('runtime_input_sha256') != drv_sha(runtime_input_path)):
            raise RuntimeError('rendered input does not derive from its role-bound registered template')
        raw = yaml.safe_load(runtime_input_path.read_text())
        matching = []
        for row in raw.get('calculations', []):
            name = drv_Path(str(row.get('lattice', ''))).name
            found = 'alpha_quartz' if name.startswith('alpha_quartz-') else 'coesite' if name.startswith('coesite-') else None
            if found == phase:
                matching.append(row)
        if len(matching) != 1:
            raise RuntimeError(f'runtime input must contain exactly one {phase} calculation')
        data = dict(matching[0])
        seed_rows = {x['phase']: int(x['master_seed']) for x in registration.get('phases', [])}
        if int(data.get('md', {}).get('seed', -1)) != seed_rows.get(phase):
            raise RuntimeError('runtime native master seed differs from the registered phase seed')
        atom_match = drv_re.fullmatch(f'{drv_re.escape(phase)}-(\\d+)\\.data', drv_Path(str(data['lattice'])).name)
        if not atom_match:
            raise RuntimeError('runtime lattice basename is not a canonical registered source')
        atoms = int(atom_match.group(1))
        (_, _, geo_source) = drv_geometry_record_for_runtime(phase, atoms, str(data['lattice']), run_root / 'native_inputs')
        source_path = (run_root / 'native_inputs' / drv_Path(str(data['lattice'])).name).resolve()
        if drv_sha(source_path) != geo_source['sha256']:
            raise RuntimeError('runtime lattice path/hash differs from role-independent source geometry manifest')
        data['inputfile'] = str(runtime_input_path)
        if 'pressure' in data:
            data['pressure'] = _to_none(data['pressure'])
        calc = Calculation(**data)
        generated = drv__validate_calphy_lattice_copy(calc, source_path, atoms, run_root)
        sim = drv_Path(calc.create_folders()).resolve()
        parsed_source = drv_read_lammps_data(source_path)
        parsed_generated = drv_read_lammps_data(generated) if generated.is_file() else None
        if getattr(calc, '_original_lattice', None) != source_path.name or generated.parent != run_root or parsed_generated is None or (not drv_np.array_equal(parsed_source['ids'], parsed_generated['ids'])) or (not drv_np.array_equal(parsed_source['types'], parsed_generated['types'])) or (not drv_np.array_equal(parsed_source['H'], parsed_generated['H'])) or (not drv_np.array_equal(parsed_source['xyz'], parsed_generated['xyz'])):
            raise RuntimeError('Calphy generated input copy is not an exact registered geometry copy')
        job = drv_FullCellSolid(calculation=calc, simfolder=str(sim), log_to_screen=False)
        job._case06_phase = phase
        job._case06_role = role
        job._case06_geometry_reference = source_path
        job._case06_run_root = run_root
        rng = drv_np.random.get_state()
        checkpoint = {'schema': 'case06-pre-averaging-rng-checkpoint/v2', 'phase': phase, 'role': role, 'master_seed': int(calc.md.seed), 'runtime_input_path': str(runtime_input_path.relative_to(run_root)), 'runtime_input_sha256': drv_sha(runtime_input_path), 'source_geometry_path': str(source_path.relative_to(run_root)), 'source_geometry_sha256': drv_sha(source_path), 'calphy_source_identity_sha256': identity_sha, 'driver_source_sha256': drv_sha(drv_Path(__file__)), 'numpy_rng_state': {'bit_generator': rng[0], 'state': rng[1].tolist(), 'position': int(rng[2]), 'has_gauss': int(rng[3]), 'cached_gaussian': float(rng[4])}, 'scope_note': 'NumPy checkpoint is not proof of native LAMMPS Langevin restart equivalence.'}
        cp = sim / 'case08-pre-averaging-rng-checkpoint.json'
        cp.write_text(drv_json.dumps(checkpoint, indent=2) + '\n')
        previous = drv_Path.cwd()
        status = 'UNKNOWN_SCIENTIFIC_GATE'
        reason = None
        try:
            os.chdir(sim)
            job.run_averaging()
        except drv_ScientificGateStop as exc:
            reason = str(exc)
        finally:
            os.chdir(previous)
        admission = sim / 'case08-npt-admission.json'
        ready = sim / 'case08-fullcell-ready-state.json'
        admission_sha = drv_sha(admission) if admission.is_file() else None
        if admission.is_file():
            rec = drv_json.loads(admission.read_text())
            status = rec.get('status', 'UNKNOWN_SCIENTIFIC_GATE')
            reason = reason or rec.get('mean_h_invalid_reason')
        out = {'schema': 'case06-one-phase-preparation-result/v1', 'phase': phase, 'role': role, 'status': status, 'reason': reason, 'run0_parity_path': str((run_root / 'acceptance/native-zero-md-regression.json').relative_to(run_root)), 'run0_parity_sha256': drv_sha(run_root / 'acceptance/native-zero-md-regression.json'), 'runtime_input_path': str(runtime_input_path.relative_to(run_root)), 'runtime_input_sha256': drv_sha(runtime_input_path), 'seed_registration_path': str(registration_path.relative_to(run_root)), 'seed_registration_sha256': drv_sha(registration_path), 'setup_folder': str(sim.relative_to(run_root)), 'setup_snapshot_path': str((sim / 'conf.equilibration.data').relative_to(run_root)) if (sim / 'conf.equilibration.data').is_file() else None, 'setup_snapshot_sha256': drv_sha(sim / 'conf.equilibration.data') if (sim / 'conf.equilibration.data').is_file() else None, 'admission_path': str(admission.relative_to(run_root)) if admission.is_file() else None, 'admission_sha256': admission_sha, 'ready_state_path': str(ready.relative_to(run_root)) if ready.is_file() else None, 'ready_state_sha256': drv_sha(ready) if ready.is_file() else None, 'pre_averaging_rng_checkpoint_path': str(cp.relative_to(run_root)), 'pre_averaging_rng_checkpoint_sha256': drv_sha(cp), 'planned_md_steps': 16000, 'actual_md_steps': None, 'actual_atom_steps': None, 'fe_authorized': False, 'native_setup_invocations_pending_replay': True, 'source_identity_sha256': identity_sha, 'native_invocations': drv_json.loads(ready.read_text()).get('native_invocations', []) if ready.is_file() else [], 'setup_record': drv__setup_record_from_ready(ready, run_root) if ready.is_file() else None, 'native_zero_md_numeric_regression_receipt_sha256': drv_sha(run0_path)}
        dest = sim / 'case06-one-phase-preparation-result.json'
        dest.write_text(drv_json.dumps(out, indent=2, allow_nan=False) + '\n')
        out['result_path'] = str(dest.relative_to(run_root))
        out['result_sha256'] = drv_sha(dest)
        return out

    def drv_run_one_fe_cycle(runtime_input_path: drv_Path, ready_state_path: drv_Path, phase_permit: dict, cycle_id: int, *, role: str, numpy_rng_state=None):
        """Execute one source-bound Calphy invocation (complete F+B cycle).

        A cycle consumes two direction attempts. It is callable only with a PASS
        permit produced by the external source/science review and never creates a
        new preparation or replaces that permit with local status inference.
        """
        from calphy.input import Calculation, _to_none
        runtime_input_path = drv_Path(runtime_input_path).resolve()
        ready_state_path = drv_Path(ready_state_path).resolve()
        if role not in {'B', 'R', 'S', 'A', 'D'}:
            raise RuntimeError('unsupported integration role')
        if not isinstance(phase_permit, dict) or phase_permit.get('schema') != 'case06-v2-source-gate/v1' or phase_permit.get('status') != 'PASS' or (phase_permit.get('role') != role):
            raise RuntimeError('FE cycle requires an external source-bound role/phase PASS permit')
        if not ready_state_path.is_file():
            raise RuntimeError('phase ready-state receipt missing')
        ready = drv_json.loads(ready_state_path.read_text())
        phase = phase_permit.get('phase')
        if phase not in {'alpha_quartz', 'coesite'} or ready.get('phase') != phase or ready.get('fe_started') is not False:
            raise RuntimeError('ready-state phase or FE-start status differs from source permit')
        if ready.get('schema') != 'case08-fullcell-ready-state/v2' or drv_sha(ready_state_path) != phase_permit.get('ready_state_sha256'):
            raise RuntimeError('ready-state source hash/schema does not match permit')
        expected_ready_role = 'B' if role == 'D' else role
        if ready.get('role') != expected_ready_role:
            raise RuntimeError('ready-state role/seed ancestry differs from the requested campaign role')
        snapshot = ready_state_path.parent / ready.get('equilibrated_snapshot', '')
        snap_ref = phase_permit.get('prepared_snapshot', {})
        if not snapshot.is_file() or drv_sha(snapshot) != ready.get('equilibrated_snapshot_sha256') or snap_ref.get('sha256') != drv_sha(snapshot):
            raise RuntimeError('prepared FE snapshot missing or changed')
        data = drv_json.loads(runtime_input_path.read_text())
        rows = []
        for row in data.get('calculations', []):
            name = drv_Path(str(row.get('lattice', ''))).name
            found = 'alpha_quartz' if name.startswith('alpha_quartz-') else 'coesite' if name.startswith('coesite-') else None
            if found == phase:
                rows.append(row)
        if len(rows) != 1:
            raise RuntimeError('cycle runtime input must contain exactly one phase calculation')
        calc_data = dict(rows[0])
        reg_role = 'B' if role == 'D' else role
        run_root = ready_state_path.parent.parent.resolve()
        registration_path = run_root / 'native_inputs' / f'seed-registration-{reg_role}.json'
        if not registration_path.is_file():
            raise RuntimeError('cycle role seed/source registration missing')
        registration = drv_json.loads(registration_path.read_text())
        reg_seed = {x['phase']: int(x['master_seed']) for x in registration.get('phases', [])}.get(phase)
        if reg_seed is None or int(calc_data.get('md', {}).get('seed', -1)) != reg_seed:
            raise RuntimeError('cycle master seed differs from the registered phase/role source')
        registered_springs = [float(x) for x in calc_data.get('spring_constants', [])]
        ready_springs = [float(x) for x in ready.get('spring_constants', [])]
        if registered_springs != [2.0, 4.0] or ready_springs != registered_springs:
            raise RuntimeError('FE runtime input and admitted ready-state must bind spring constants [2,4]')
        if 'pressure' in calc_data:
            calc_data['pressure'] = _to_none(calc_data['pressure'])
        calc_data['inputfile'] = str(runtime_input_path)
        geometry_name = drv_Path(str(calc_data.get('lattice', ''))).name
        atom_match = drv_re.fullmatch(f'{drv_re.escape(phase)}-(\\d+)\\.data', geometry_name)
        if not atom_match:
            raise RuntimeError('FE runtime lattice is not a registered source basename')
        atoms = int(atom_match.group(1))
        source_path = (run_root / 'native_inputs' / geometry_name).resolve()
        (_, _, geometry_source) = drv_geometry_record_for_runtime(phase, atoms, geometry_name, run_root / 'native_inputs')
        if source_path != geometry_source['path'] or not source_path.is_file():
            raise RuntimeError('FE runtime source geometry differs from the registered immutable source')
        original_cwd = drv_Path.cwd()
        try:
            drv_os.chdir(run_root)
            calc = Calculation(**calc_data)
            drv__validate_calphy_lattice_copy(calc, source_path, atoms, run_root)
        finally:
            drv_os.chdir(original_cwd)
        runtime_springs = [float(x) for x in getattr(calc, 'spring_constants', [])]
        if runtime_springs != [2.0, 4.0] or ready_springs != runtime_springs or len(runtime_springs) != int(calc.n_elements):
            raise RuntimeError('FE runtime input and admitted ready-state must bind spring constants [2,4]')
        sim = ready_state_path.parent.resolve()
        job = drv_FullCellSolid(calculation=calc, simfolder=str(sim), log_to_screen=False)
        job.k = list(runtime_springs)
        job._case06_phase = phase
        job._case06_role = role
        geometry_ref = ready.get('geometry_reference', {})
        if not isinstance(geometry_ref, dict) or not geometry_ref.get('path'):
            raise RuntimeError('ready-state lacks the source-bound runtime geometry reference')
        job._case06_run_root = ready_state_path.parent.parent.resolve()
        job._case06_geometry_reference = (job._case06_run_root / geometry_ref['path']).resolve()
        if not job._case06_geometry_reference.is_file() or drv_sha(job._case06_geometry_reference) != geometry_ref.get('sha256') or int(geometry_ref.get('atoms', -1)) != int(ready.get('atoms', -2)):
            raise RuntimeError('ready-state role/phase geometry source is missing, changed, or has the wrong atom count')
        job._case08_full_cell = drv_np.asarray(ready['mean_cell_matrix_A'], float)
        job._case08_full_cell_volume = float(ready['mean_cell_volume_A3'])
        job.lx = float(job._case08_full_cell[0, 0])
        job.ly = float(job._case08_full_cell[1, 1])
        job.lz = float(job._case08_full_cell[2, 2])
        job.xy = float(job._case08_full_cell[1, 0])
        job.xz = float(job._case08_full_cell[2, 0])
        job.yz = float(job._case08_full_cell[2, 1])
        job.vol = job._case08_full_cell_volume
        job.volatom = job.vol / float(job._natoms)
        job.rho = float(job._natoms) / job.vol
        recorded_state = drv__state_from_ready_record(ready)
        state = recorded_state if numpy_rng_state is None else numpy_rng_state
        drv_np.random.set_state(state)
        state_sha = drv__numpy_state_sha()
        if state_sha != drv__numpy_state_sha(recorded_state):
            raise RuntimeError('cycle NumPy RNG state differs from the source-bound prepared snapshot checkpoint')
        job._case06_phase_permit = phase_permit
        previous = drv_Path.cwd()
        try:
            drv_os.chdir(sim)
            job.run_integration(int(cycle_id))
            job.thermodynamic_integration()
            cycle_path = sim / f'case06-integration-cycle-{int(cycle_id)}.json'
            cycle = drv_json.loads(cycle_path.read_text())
            ti = {'schema': 'case06-calphy-ti-cycle-summary/v1', 'phase': phase, 'role': role, 'cycle_id': int(cycle_id), 'status': 'RAW_CALPHY_RESULT_REVIEW_REQUIRED', 'fe_authorized': False, 'einstein_reference_total_eV': float(job.fref), 'einstein_crystal_total_eV': float(job.feinstein), 'center_of_mass_total_eV': float(job.fcm), 'calphy_bidirectional_work_total_eV': float(job.w), 'dissipation_total_eV': float(job.qdiss), 'dissipation_error_total_eV': float(job.ferr), 'pv_total_eV': float(job.pv), 'free_energy_total_eV': float(job.fe), 'mean_cell_matrix_A': drv_np.asarray(job._case08_full_cell, float).tolist(), 'mean_cell_volume_A3': float(job._case08_full_cell_volume), 'atoms': int(job._natoms), 'forward_curve': cycle.get('actual_forward_curve'), 'backward_curve': cycle.get('actual_backward_curve'), 'calphy_version': drv_package_version('calphy'), 'calphy_source_identity_sha256': drv_sha(drv_Path.cwd().parent / 'calphy-source-identity.json') if (drv_Path.cwd().parent / 'calphy-source-identity.json').is_file() else None, 'interpretation': 'stock Calphy aggregate over both legs; direction-specific work/G must be replayed independently from raw curves'}
            ti_path = sim / f'case06-calphy-ti-cycle-{int(cycle_id)}.json'
            ti_path.write_text(drv_json.dumps(ti, indent=2, allow_nan=False) + '\n')
            cycle['calphy_ti_summary'] = {'path': ti_path.name, 'sha256': drv_sha(ti_path)}
            cycle_path.write_text(drv_json.dumps(cycle, indent=2, allow_nan=False) + '\n')
        finally:
            drv_os.chdir(previous)
        cycle_path = sim / f'case06-integration-cycle-{int(cycle_id)}.json'
        if not cycle_path.is_file():
            raise RuntimeError('Calphy cycle returned without a cycle receipt')
        cycle = drv_json.loads(cycle_path.read_text())
        if cycle.get('phase') != phase or cycle.get('role') != role or cycle.get('fe_authorized') is not False:
            raise RuntimeError('native cycle receipt identity/status mismatch')
        return {'schema': 'case06-one-fe-cycle-result/v1', 'phase': phase, 'role': role, 'cycle_id': int(cycle_id), 'logical_direction_attempts': 2, 'cycle_path': str(cycle_path), 'cycle_sha256': drv_sha(cycle_path), 'prepared_snapshot_sha256': drv_sha(snapshot), 'ready_state_sha256': drv_sha(ready_state_path), 'phase_permit_sha256': drv_hashlib.sha256(drv_json.dumps(phase_permit, sort_keys=True).encode()).hexdigest(), 'numpy_rng_state_before_cycle_sha256': state_sha, 'positive_md_steps': sum(cycle.get('positive_run_steps', [])), 'actual_atom_steps': None, 'native_invocations': cycle.get('native_invocation_refs', []), 'integration_cycle': cycle, 'calphy_ti_summary': cycle.get('calphy_ti_summary'), 'status': cycle.get('status'), 'fe_authorized': False}

    def drv_main():
        global drv_IDENTITY_SHA256
        import argparse, os, yaml
        from calphy.input import Calculation, _to_none
        parser = argparse.ArgumentParser()
        parser.add_argument('-i', '--input', required=True)
        parser.add_argument('--run0-proof', type=drv_Path, default=drv_Path.cwd() / 'acceptance' / 'native-zero-md-regression.json')
        args = parser.parse_args()
        drv_validate_run0_prerequisite(args.run0_proof)
        identity = drv_validate_installed_sources()
        drv_IDENTITY_SHA256 = drv_sha(drv_Path.cwd() / 'calphy-source-identity.json')
        raw = yaml.safe_load(drv_Path(args.input).read_text())
        geometry = drv_json.loads((drv_PAYLOAD / 'native_inputs/geometry-manifest.json').read_text())
        coe = next((x for x in geometry.get('structures', []) if x.get('phase') == 'coesite'), None)
        if geometry.get('schema') != 'case06-public-periodic-quotient/v1' or not coe or (not coe.get('basis_gauge')) or (coe['basis_gauge'].get('determinant') != 1) or (coe['basis_gauge'].get('gauged_data_sha256') != drv_sha(drv_PAYLOAD / 'native_inputs/coesite-384.data')) or (coe['basis_gauge'].get('native_run0_energy_force_parity') != 'REQUIRED_BEFORE_POSITIVE_MD'):
            raise RuntimeError('public-derived coesite gauge geometry/hash receipt missing or inconsistent')
        run_root = drv_Path.cwd().resolve()
        input_path = drv_Path(args.input).resolve()
        phase_rows = []
        setup_per_phase = 1000 + 10000 + drv_EXPLICIT_FIXED_H_NVT_STEPS
        setup_steps = setup_per_phase * len(raw['calculations'])
        setup_atomsteps = 0
        for item in raw['calculations']:
            match = __import__('re').search('-(\\d+)\\.data$', drv_Path(item['lattice']).name)
            if not match:
                raise RuntimeError(f"cannot infer atom count from frozen input lattice {item['lattice']}")
            setup_atomsteps += setup_per_phase * int(match.group(1))
        registration_path = drv_PAYLOAD / 'native_inputs' / f"seed-registration-{raw.get('role', 'B')}.json"
        registration = drv_json.loads(registration_path.read_text())
        if registration.get('matrix_sha256') != geometry.get('matrix_sha256'):
            raise RuntimeError('role seed registration and public geometry were derived from different frozen matrices')
        role = registration.get('role')
        if role not in {'B', 'R', 'S', 'A'}:
            raise RuntimeError(f'unsupported setup role in seed registration: {role}')
        if registration.get('input_sha256') != drv_sha(input_path):
            raise RuntimeError('runtime input differs from fresh phase seed registration')
        seeds = {r['phase']: int(r['master_seed']) for r in registration['phases']}
        if set(seeds) != {'alpha_quartz', 'coesite'} or len(raw['calculations']) != 2:
            raise RuntimeError('v2 proposal phase/seed inventory differs')
        for (kernel, data) in enumerate(raw['calculations']):
            phase = 'alpha_quartz' if 'alpha_quartz' in drv_Path(data['lattice']).name else 'coesite' if 'coesite' in drv_Path(data['lattice']).name else 'unknown'
            if phase == 'unknown' or int(data['md']['seed']) != seeds.get(phase) or float(data['pressure']) != 20000 or (float(data['temperature']) != 600):
                raise RuntimeError('runtime phase, master seed, temperature, or 20k pressure differs from the frozen matrix')
            if phase == 'unknown':
                raise RuntimeError('runtime input has unrecognized source phase')
            source_name = drv_Path(str(data['lattice'])).name
            (_, geometry_record, geometry_source) = drv_geometry_record_for_runtime(phase, int(drv_re.search('-(\\d+)\\.data$', source_name).group(1)), source_name)
            if geometry_source['sha256'] != drv_sha(drv_PAYLOAD / 'native_inputs' / source_name):
                raise RuntimeError('runtime template lattice is not bound to the source-derived geometry manifest')
            data['kernel'] = kernel
            data['inputfile'] = str(input_path)
            if 'pressure' in data:
                data['pressure'] = _to_none(data['pressure'])
            immutable_phase = phase
            immutable_source = drv_Path(str(data['lattice'])).resolve()
            immutable_source_sha = drv_sha(immutable_source)
            calc = Calculation(**data)
            generated = drv__validate_calphy_lattice_copy(calc, immutable_source, int(geometry_source['atoms']), run_root)
            sim = drv_Path(calc.create_folders()).resolve()
            job = drv_FullCellSolid(calculation=calc, simfolder=str(sim), log_to_screen=False)
            job._case06_phase = immutable_phase
            job._case06_role = role
            job._case06_geometry_reference = immutable_source
            job._case06_run_root = run_root
            original_parsed = drv_read_lammps_data(immutable_source)
            generated_parsed = drv_read_lammps_data(generated) if generated.is_file() else None
            if getattr(calc, '_original_lattice', None) != immutable_source.name or not generated.is_file() or generated.parent != run_root or (generated_parsed is None) or (len(generated_parsed['ids']) != int(geometry_source['atoms'])) or (not drv_np.array_equal(generated_parsed['ids'], original_parsed['ids'])) or (not drv_np.array_equal(generated_parsed['types'], original_parsed['types'])) or (not drv_np.array_equal(generated_parsed['H'], original_parsed['H'])) or (not drv_np.array_equal(generated_parsed['xyz'], original_parsed['xyz'])):
                raise RuntimeError('Calphy generated lattice source identity/atom count is not valid')
            rng = drv_np.random.get_state()
            pre_state = {'schema': 'case08-pre-averaging-rng-checkpoint/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phase': phase, 'role': role, 'master_seed': int(calc.md.seed), 'runtime_input_path': str(input_path), 'runtime_input_sha256': drv_sha(input_path), 'driver_source_path': str(drv_Path(__file__)), 'driver_source_sha256': drv_sha(drv_Path(__file__)), 'calphy_source_identity_sha256': drv_IDENTITY_SHA256, 'numpy_rng_state': {'bit_generator': rng[0], 'state': rng[1].tolist(), 'position': int(rng[2]), 'has_gauss': int(rng[3]), 'cached_gaussian': float(rng[4])}, 'scope_note': 'Checkpoint records NumPy master stream before averaging; it does not establish restart equivalence for native LAMMPS Langevin or completed MD.'}
            (sim / 'case08-pre-averaging-rng-checkpoint.json').write_text(drv_json.dumps(pre_state, indent=2) + '\n')
            os.chdir(sim)
            try:
                job.run_averaging()
            except drv_ScientificGateStop as exc:
                receipt = drv_json.loads((drv_Path.cwd() / 'case08-npt-admission.json').read_text())
                phase_rows.append({'setup_id': f"{role}-{receipt['phase']}", 'role': role, 'phase': receipt['phase'], 'simfolder': str(drv_Path.cwd()), 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'reason': str(exc), 'admission_receipt_sha256': drv_sha(drv_Path.cwd() / 'case08-npt-admission.json'), 'ready_state_sha256': None})
            else:
                receipt = drv_json.loads((drv_Path.cwd() / 'case08-npt-admission.json').read_text())
                phase_rows.append({'setup_id': f"{role}-{receipt['phase']}", 'role': role, 'phase': receipt['phase'], 'simfolder': str(drv_Path.cwd()), 'status': receipt['status'], 'admission_receipt_sha256': drv_sha(drv_Path.cwd() / 'case08-npt-admission.json'), 'ready_state_sha256': drv_sha(drv_Path.cwd() / 'case08-fullcell-ready-state.json')})
            os.chdir(run_root)
        shape_values = []
        for item in phase_rows:
            rp = drv_Path(item['simfolder']) / 'case08-npt-admission.json'
            if rp.is_file():
                val = drv_json.loads(rp.read_text()).get('legacy_old_fe_cell_shape_linear_diagnostic_meV_per_atom')
                if val is not None:
                    shape_values.append(float(val))
        shape_sum = sum(shape_values) if len(shape_values) == 2 else None
        pair = {'schema': 'case08-fullcell-pair-admission/v2', 'protocol': drv_POWER_V2_PROTOCOL, 'phases': phase_rows, 'status': 'UNKNOWN_SCIENTIFIC_GATE', 'fe_started': False, 'actual_prepare_md_steps': None, 'planned_prepare_upper_md_steps': setup_steps, 'planned_prepare_atom_steps': setup_atomsteps, 'planned_post_review_switching_md_steps': 2 * sum((int(c['n_switching_steps']) for c in raw['calculations'])), 'planned_post_review_switching_atom_steps': 2 * sum((int(c['n_switching_steps']) * int(drv_re.search('-(\\d+)\\.data$', drv_Path(c['lattice']).name).group(1)) for c in raw['calculations'])), 'planned_post_review_warmstart_md_steps': 4000 * len(raw['calculations']), 'planned_post_review_warmstart_atom_steps': 4000 * sum((int(drv_re.search('-(\\d+)\\.data$', drv_Path(c['lattice']).name).group(1)) for c in raw['calculations'])), 'planned_post_review_fe_plus_warmstart_upper_md_steps': 2 * sum((int(c['n_switching_steps']) for c in raw['calculations'])) + 4000 * len(raw['calculations']), 'planned_post_review_fe_plus_warmstart_atom_steps': 2 * sum((int(c['n_switching_steps']) * int(drv_re.search('-(\\d+)\\.data$', drv_Path(c['lattice']).name).group(1)) for c in raw['calculations'])) + 4000 * sum((int(drv_re.search('-(\\d+)\\.data$', drv_Path(c['lattice']).name).group(1)) for c in raw['calculations'])), 'planned_post_review_fe_plus_warmstart_unknown_reason': None, 'legacy_shape_linear_diagnostic_sum_meV_per_atom': shape_sum, 'legacy_shape_gate': 'PENDING_SOL_REVIEW; residual-stress × strain is only a first-order screening diagnostic, not a free-energy bound' if shape_sum is not None else 'UNKNOWN_MISSING_PHASE_DIAGNOSTIC', 'native_md_executed': False, 'native_md_execution_pending': True, 'new_fe_direction_attempts': 0, 'pressure_bar': 20000, 'temperature_K': 600, 'role': role, 'seed_registration_path': str(registration_path), 'seed_registration_sha256': drv_sha(registration_path), 'geometry_manifest_sha256': drv_sha(drv_PAYLOAD / 'native_inputs/geometry-manifest.json'), 'reason': 'This entrypoint is a bounded preparation diagnostic. Local pressure/phase/MSD observations remain review evidence; independent RDF/angle and native source gates are still required. FE is never invoked by this prepare-only entrypoint.'}
        (run_root / 'acceptance').mkdir(parents=True, exist_ok=True)
        pair['planned_prepare_upper_md_steps'] = setup_steps
        pair['planned_prepare_atom_steps'] = setup_atomsteps
        pair['candidate_accounting'] = {'md_steps_this_candidate_planned': setup_steps, 'atom_steps_this_candidate_planned': setup_atomsteps, 'fe_direction_attempts_this_candidate': 0, 'native_run0_pe_parity': 'NOT_EXECUTED_STATIC_ONLY', 'future_duration_pair_warm_reserve_per_phase': {'warm_steps_per_block': 1000, 'blocks_per_cycle': 2, 'cycles': 2, 'total_steps': 4000}, 'future_ancestor_budget_per_phase_steps': 16000 + 4000, 'proposal_sha256': drv_sha(drv_PAYLOAD / 'native_inputs/independent-seed-registration.json')}
        (run_root / 'acceptance' / 'case08-pair-admission.json').write_text(drv_json.dumps(pair, indent=2) + '\n')
        if pair['status'] == 'UNKNOWN_SCIENTIFIC_GATE':
            print('UNKNOWN_SCIENTIFIC_GATE: both setup payloads preserved; neither phase FE was started')
            raise SystemExit(42)
        print(f'READY_FOR_PARENT_REVIEW: {len(phase_rows)} selected setup(s) preserved; no FE started')

    # Direct source merge: native_zero_md.py; namespace prefix zero_
    """Guarded native run-0 numeric regression for Case-06 sources, gauge and size map.

    Runs six unique LAMMPS `run 0` calls through the Case08 instrumentation wrapper
    (raw, gauge, and size for each phase) and records total energy and every per-site
    force. This program never launches positive
    MD, submits a scheduler job, or treats mock/fixture evidence as science.
    """
    import argparse as zero_argparse, hashlib as zero_hashlib, json as zero_json, math as zero_math, os as zero_os, re as zero_re, subprocess as zero_subprocess, time as zero_time
    from pathlib import Path as zero_Path
    zero_HERE = zero_Path(__file__).resolve().parent
    zero_PAYLOAD = ASSET_ROOT
    zero_NATIVE = zero_PAYLOAD / 'native_inputs'
    zero_EXPECTED_MATRIX_SHA = '58599733bcecb0017d0863e1054ba9311858f8e6b986713af064be737e5c5d9e'
    zero_EXPECTED_POTENTIAL_SHA = 'c8f00d8f0cbc131b0298b79260ba8098975624363c9d178223e51e48f025e97a'
    zero_EXPECTED_BINARY_SHA = os.environ.get("CASE159_LAMMPS_SHA256", '434e1de023b260ef427495a257b6ad0ec995f27cfa1a8129d9089c6100dceb68')
    zero_PE_ABS = 1e-06
    zero_PE_REL = 1e-10
    zero_FORCE_ABS = 1e-08
    zero_FORCE_REL = 1e-10
    zero_NATIVE_CALLS_STARTED = 0

    class zero_Unknown(RuntimeError):
        pass

    def zero_sha(path):
        h = zero_hashlib.sha256()
        with zero_Path(path).open('rb') as f:
            for b in iter(lambda : f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    def zero_ref(path, root):
        p = zero_Path(path).resolve()
        r = zero_Path(root).resolve()
        try:
            rel = p.relative_to(r).as_posix()
        except ValueError as exc:
            raise zero_Unknown(f'artifact outside job root: {p}') from exc
        return {'path': rel, 'sha256': zero_sha(p)}

    def zero__load(path):
        return zero_json.loads(zero_Path(path).read_text())

    def zero_read_data(path):
        lines = zero_Path(path).read_text().splitlines()
        bounds = {}
        tilt = (0.0, 0.0, 0.0)
        atoms = []
        in_atoms = False
        in_vel = False
        vel = {}
        for line in lines:
            v = line.split()
            if len(v) >= 4 and v[2:4] == ['xlo', 'xhi']:
                bounds['x'] = (float(v[0]), float(v[1]))
            elif len(v) >= 4 and v[2:4] == ['ylo', 'yhi']:
                bounds['y'] = (float(v[0]), float(v[1]))
            elif len(v) >= 4 and v[2:4] == ['zlo', 'zhi']:
                bounds['z'] = (float(v[0]), float(v[1]))
            elif len(v) >= 6 and v[3:6] == ['xy', 'xz', 'yz']:
                tilt = tuple(map(float, v[:3]))
            elif line.strip().startswith('Atoms'):
                in_atoms = True
                in_vel = False
            elif line.strip().startswith('Velocities'):
                in_vel = True
                in_atoms = False
            elif line.strip() and (not line[0].isspace()) and (not line[0].isdigit()):
                in_atoms = False
                in_vel = False
            elif in_atoms and (not line.strip()):
                if atoms:
                    in_atoms = False
            elif in_atoms and len(v) >= 5 and v[0].isdigit():
                atoms.append((int(v[0]), int(v[1])))
            elif in_vel and len(v) >= 4 and v[0].isdigit():
                vel[int(v[0])] = [float(x) for x in v[1:4]]
        if set(bounds) != {'x', 'y', 'z'} or not atoms:
            raise zero_Unknown(f'cannot parse LAMMPS data {path}')
        atoms.sort()
        ids = [x[0] for x in atoms]
        if len(ids) != len(set(ids)) or ids != list(range(1, len(ids) + 1)):
            raise zero_Unknown(f'atom IDs not contiguous 1..N in {path}')
        lo = [bounds[k][0] for k in ('x', 'y', 'z')]
        hi = [bounds[k][1] for k in ('x', 'y', 'z')]
        H = [[hi[0] - lo[0], 0.0, 0.0], [tilt[0], hi[1] - lo[1], 0.0], [tilt[1], tilt[2], hi[2] - lo[2]]]
        atom_rows = []
        in_atoms = False
        for line in lines:
            s = line.strip()
            if s.startswith('Atoms'):
                in_atoms = True
                continue
            if in_atoms and (not s):
                if atom_rows:
                    in_atoms = False
                continue
            if in_atoms:
                v = s.split()
                if len(v) >= 5 and v[0].isdigit():
                    image = [int(x) for x in v[5:8]] if len(v) >= 8 else [0, 0, 0]
                    atom_rows.append((int(v[0]), [float(x) for x in v[2:5]], image))
        atom_rows.sort()
        return {'atoms': len(atoms), 'ids': ids, 'types': [x[1] for x in atoms], 'H': H, 'origin': lo, 'positions': [x[1] for x in atom_rows], 'image_flags': [x[2] for x in atom_rows], 'velocities': [vel.get(i, [0.0, 0.0, 0.0]) for i in ids], 'volume': (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])}

    def zero__input_text(data, potential, forcefile, obsfile, *, author_cpu=False):
        pair_style = "pace" if author_cpu else "pace/kk"
        return f'clear\nunits metal\natom_style atomic\nboundary p p p\nread_data {zero_Path(data)}\npair_style {pair_style} product\npair_coeff * * {zero_Path(potential)} O Si\nmass 1 15.999\nmass 2 28.085\nthermo 1\nthermo_style custom step atoms pe vol lx ly lz xy xz yz\nthermo_modify flush yes\ndump zero all custom 1 {forcefile} id type x y z ix iy iz vx vy vz fx fy fz\ndump_modify zero sort id first yes flush yes format float %.16g\nrun 0\nprint "CASE06_RUN0_RESULT step=$(step:%.0f) pe_eV=$(pe:%.16g) atoms=$(atoms:%.0f) vol_A3=$(vol:%.16g)" file {obsfile} screen no\nundump zero\n'

    def zero_parse_native(sim, root, phase, label, natoms):
        obs = sim / 'run0-observation.txt'
        force = sim / 'forces.dump'
        if not obs.is_file() or not force.is_file():
            raise zero_Unknown(f'{phase}/{label}: missing run0 energy or force stream')
        line = obs.read_text().strip().splitlines()
        rows = [x for x in line if x.startswith('CASE06_RUN0_RESULT ')]
        if len(rows) != 1:
            raise zero_Unknown(f'{phase}/{label}: expected exactly one run0 result row')
        values = dict((token.split('=', 1) for token in rows[0].split()[1:]))
        if set(values) != {'step', 'pe_eV', 'atoms', 'vol_A3'}:
            raise zero_Unknown('run0 result fields differ')
        numeric = {k: float(values[k]) for k in ('pe_eV', 'vol_A3')}
        step = int(values['step'])
        n = int(values['atoms'])
        if step != 0 or n != natoms or (not all((math.isfinite(x) for x in numeric.values()))) or (numeric['vol_A3'] <= 0):
            raise zero_Unknown(f'{phase}/{label}: invalid native state result')
        lines = force.read_text(errors='replace').splitlines()
        frames = []
        i = 0
        while i < len(lines):
            if lines[i].strip() != 'ITEM: TIMESTEP':
                i += 1
                continue
            try:
                timestep = int(lines[i + 1])
                count = int(lines[i + 3])
                box_header = lines[i + 4].split()
                hdr = lines[i + 8].split()[2:]
                needed = ('id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz')
                if timestep != 0 or count != natoms or (not set(needed).issubset(hdr)):
                    raise ValueError('bad dump header')
                ix = {k: hdr.index(k) for k in needed}
                atoms = []
                for raw in lines[i + 9:i + 9 + count]:
                    v = raw.split()
                    atoms.append({'id': int(v[ix['id']]), 'type': int(v[ix['type']]), 'xyz': [float(v[ix[k]]) for k in ('x', 'y', 'z')], 'image': [int(v[ix[k]]) for k in ('ix', 'iy', 'iz')], 'velocity': [float(v[ix[k]]) for k in ('vx', 'vy', 'vz')], 'force': [float(v[ix[k]]) for k in ('fx', 'fy', 'fz')]})
                atoms.sort(key=lambda atom: atom['id'])
                if [x['id'] for x in atoms] != list(range(1, natoms + 1)):
                    raise ValueError('bad dump IDs')
                if any((not math.isfinite(c) for a in atoms for key in ('xyz', 'velocity', 'force') for c in a[key])):
                    raise ValueError('nonfinite atom state')
                b0 = list(map(float, lines[i + 5].split()))
                b1 = list(map(float, lines[i + 6].split()))
                b2 = list(map(float, lines[i + 7].split()))
                if len(b0) == 3 and len(b1) == 3 and (len(b2) == 3):
                    (xy, xz, yz) = (b0[2], b1[2], b2[2])
                    xlo = b0[0] - min(0.0, xy, xz, xy + xz)
                    xhi = b0[1] - max(0.0, xy, xz, xy + xz)
                    ylo = b1[0] - min(0.0, yz)
                    yhi = b1[1] - max(0.0, yz)
                    origin = [xlo, ylo, b2[0]]
                    H = [[xhi - xlo, 0.0, 0.0], [xy, yhi - ylo, 0.0], [xz, yz, b2[1] - b2[0]]]
                else:
                    origin = [b0[0], b1[0], b2[0]]
                    H = [[b0[1] - b0[0], 0.0, 0.0], [0.0, b1[1] - b1[0], 0.0], [0.0, 0.0, b2[1] - b2[0]]]
                frames.append({'atoms': atoms, 'origin': origin, 'H': H})
                i += 9 + count
            except (ValueError, IndexError, KeyError):
                i += 1
        if len(frames) != 1:
            raise zero_Unknown(f'{phase}/{label}: expected one force frame, found {len(frames)}')
        frame = frames[0]
        atoms = frame['atoms']
        return {'step': step, 'atom_count': n, **numeric, 'atom_types': [x['type'] for x in atoms], 'positions_A': [x['xyz'] for x in atoms], 'image_flags': [x['image'] for x in atoms], 'velocities_A_per_ps': [x['velocity'] for x in atoms], 'forces_eV_per_A': [x['force'] for x in atoms], 'H_A': frame['H'], 'origin_A': frame['origin'], 'observation_path': str(obs), 'force_path': str(force)}

    def zero_invocation_evidence(sim, root, natoms, *, native_binary, role, phase, label):
        manifest = sim / 'case08-instrumentation.jsonl'
        if not manifest.is_file():
            raise zero_Unknown(f'wrapper instrumentation receipt absent in {sim}')
        recs = [json.loads(x) for x in manifest.read_text().splitlines() if x.strip()]
        if len(recs) != 1:
            raise zero_Unknown(f'expected one guarded invocation, got {len(recs)}')
        rec = recs[0]
        inv = rec.get('invocation_id')
        if rec.get('no_md_run') is not False or rec.get('run_commands_instrumented') != 1 or rec.get('run_plan') != [{'run_index': 1, 'planned_steps': 0}]:
            raise zero_Unknown('wrapper did not instrument exactly one literal run 0')
        original = zero_Path(rec['original_path'])
        executed = zero_Path(rec['instrumented_path'])
        receipt = sim / f'case08-execution.{inv}.json'
        for (p, digest) in ((original, rec.get('original_sha256')), (executed, rec.get('instrumented_sha256'))):
            if not p.is_file() or zero_sha(p) != digest:
                raise zero_Unknown(f'wrapper source hash mismatch: {p}')
        if not receipt.is_file():
            raise zero_Unknown('wrapper completion receipt missing')
        event = zero__load(receipt)
        if event.get('native_returncode') != 0 or event.get('wrapper_integrity_rc') != 0 or event.get('integrity_errors'):
            raise zero_Unknown('guarded native zero-step invocation failed or wrapper integrity is unknown')
        archive = event.get('native_log_archive', {})
        log = zero_Path(archive.get('path', ''))
        if not archive.get('exists') or not log.is_file() or zero_sha(log) != archive.get('sha256'):
            raise zero_Unknown('native log archive missing or hash mismatch')
        text = log.read_text(errors='replace')
        begin = zero_re.findall('^CASE08_RUN_BEGIN segment=(\\S+) index=(\\d+) planned_steps=(\\d+) start_step=(-?\\d+)\\s*$', text, zero_re.M)
        end = zero_re.findall('^CASE08_RUN_END segment=(\\S+) index=(\\d+) planned_steps=(\\d+) end_step=(-?\\d+)\\s*$', text, zero_re.M)
        loop = zero_re.findall('^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$', text, zero_re.M)
        if len(begin) != 1 or len(end) != 1 or len(loop) != 1 or (begin[0][1:] != ('1', '0', '0')) or (end[0][1:] != ('1', '0', '0')) or (begin[0][0] != end[0][0]) or (int(loop[0][0]) != 0) or (int(loop[0][1]) != natoms):
            raise zero_Unknown('native logs do not prove ordered BEGIN/Loop0/END for correct atom count')
        if not text.find('CASE08_RUN_BEGIN ') < text.find('Loop time ') < text.find('CASE08_RUN_END '):
            raise zero_Unknown('native run0 event order invalid')
        argv = event.get('command_argv')
        if not isinstance(argv, list) or not argv or zero_Path(argv[0]).resolve() != zero_Path(native_binary).resolve():
            raise zero_Unknown('wrapper receipt lacks the actual native command argv')
        binary_sha = zero_sha(native_binary)
        expected_binary_sha = (zero_os.environ.get('CASE06_AUTHOR_BINARY_SHA')
                               if role == 'A' and zero_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') == '1'
                               else zero_EXPECTED_BINARY_SHA)
        if not expected_binary_sha or binary_sha != expected_binary_sha:
            raise zero_Unknown('native executable SHA differs from its frozen provider identity')
        outputs = zero_Path(zero_os.environ.get('CASE06_OUTPUTS', root)).resolve()
        provenance = outputs / 'provenance' / 'native-binaries'
        provenance.mkdir(parents=True, exist_ok=True)
        binary_doc = provenance / f'{inv}.json'
        zero_write_json(binary_doc, {'schema': 'case06-native-binary-provenance/v1', 'invocation_id': inv, 'role': role, 'phase': phase, 'run0_label': label, 'native_binary': {'path': str(zero_Path(native_binary).resolve()), 'sha256': binary_sha}, 'argv': [str(x) for x in argv]})
        binary_ref = {'path': binary_doc.relative_to(outputs).as_posix(), 'sha256': zero_sha(binary_doc)}
        normalized = sim / f'case06-native-zero-adapter-receipt-{inv}.json'
        normalized_doc = {'schema': 'case06-native-invocation-receipt/v1', 'invocation_id': inv, 'native_returncode': 0, 'wrapper_integrity_rc': 0, 'manifest_run_plan_match': True, 'native_step': 0, 'native_atom_count': natoms, 'original_input_sha256': zero_sha(original), 'executed_input_sha256': zero_sha(executed), 'native_log_sha256': zero_sha(log), 'wrapper_receipt': zero_ref(receipt, root), 'binary_provenance_ref': binary_ref, 'native_zero_only': True}
        zero_write_json(normalized, normalized_doc)
        return {'invocation_id': inv, 'phase': phase, 'run0_label': label, 'native_returncode': event['native_returncode'], 'wrapper_integrity_rc': event['wrapper_integrity_rc'], 'native_step': 0, 'native_atom_count': natoms, 'native_log_path': zero_ref(log, root)['path'], 'native_log_sha256': zero_sha(log), 'original_input_path': zero_ref(original, root)['path'], 'original_input_sha256': zero_sha(original), 'instrumented_input_path': zero_ref(executed, root)['path'], 'instrumented_input_sha256': zero_sha(executed), 'execution_receipt_path': zero_ref(normalized, root)['path'], 'execution_receipt_sha256': zero_sha(normalized), 'binary_provenance_ref': binary_ref, 'wrapper_execution_receipt_path': zero_ref(receipt, root)['path'], 'wrapper_execution_receipt_sha256': zero_sha(receipt), 'native_loop_zero_only': True, 'ordered_BEGIN_Loop_END': True}

    def zero_run_case(data, potential, wrapper, native_binary, work, role, phase, label, root, natoms):
        global zero_NATIVE_CALLS_STARTED
        sim = work / phase / label
        sim.mkdir(parents=True, exist_ok=False)
        parsed = zero_read_data(data)
        if parsed['atoms'] != natoms:
            raise zero_Unknown(f"{phase}/{label}: expected {natoms} atoms, found {parsed['atoms']}")
        inpath = sim / 'run0.lmp'
        author_cpu = role == 'A' and zero_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') == '1'
        inpath.write_text(zero__input_text(zero_Path(zero_os.path.relpath(data, sim)), zero_Path(zero_os.path.relpath(potential, sim)), 'forces.dump', 'run0-observation.txt', author_cpu=author_cpu))
        env = zero_os.environ.copy()
        env['CASE08_REAL_LMP'] = str(zero_Path(native_binary).resolve())
        env['CASE08_WRAPPER'] = str(wrapper.resolve())
        if not zero_Path(env.get('CASE08_SOLVE', '')).is_file() or not zero_Path(env.get('CASE08_PYTHON', '')).is_file():
            raise zero_Unknown('CASE08_SOLVE and CASE08_PYTHON must identify the packaged single-file instrumentation runtime')
        args = [str(wrapper.resolve())]
        if not author_cpu:
            args.extend(['-k', 'on', 'g', '1', '-sf', 'kk', '-pk', 'kokkos', 'newton', 'on', 'neigh', 'half'])
        args.extend(['-in', str(inpath), '-log', str(sim / 'log.lammps')])
        zero_NATIVE_CALLS_STARTED += 1
        start = zero_time.monotonic()
        result = zero_subprocess.run(args, cwd=sim, env=env, text=True, capture_output=True)
        elapsed = zero_time.monotonic() - start
        (sim / 'launcher.stdout.log').write_text(result.stdout)
        (sim / 'launcher.stderr.log').write_text(result.stderr)
        if result.returncode != 0:
            raise zero_Unknown(f'{phase}/{label}: guarded native zero-MD command returned {result.returncode}')
        obs = zero_parse_native(sim, root, phase, label, natoms)
        call = zero_invocation_evidence(sim, root, natoms, native_binary=native_binary, role=role, phase=phase, label=label)
        observation_ref = zero_ref(sim / 'run0-observation.txt', root)
        force_ref = zero_ref(sim / 'forces.dump', root)
        call.update({'observation_path': observation_ref['path'], 'observation_sha256': observation_ref['sha256'], 'force_dump_path': force_ref['path'], 'force_dump_sha256': force_ref['sha256']})
        if label == 'prepared-snapshot':
            state = zero_read_data(data)
            if obs['atom_types'] != state['types'] or obs['image_flags'] != state['image_flags'] or any((abs(a - b) > 1e-10 for (row_a, row_b) in zip(obs['H_A'], state['H']) for (a, b) in zip(row_a, row_b))) or any((abs(a - b) > 1e-10 for (a, b) in zip(obs['origin_A'], state['origin']))) or any((abs(a - b) > 1e-10 for (row_a, row_b) in zip(obs['positions_A'], state['positions']) for (a, b) in zip(row_a, row_b))) or any((abs(a - b) > 1e-10 for (row_a, row_b) in zip(obs['velocities_A_per_ps'], state['velocities']) for (a, b) in zip(row_a, row_b))):
                raise zero_Unknown(f'{phase}: native run0 changed prepared snapshot atom identity/positions/images/velocities')
            obs['native_snapshot_state_match'] = {'status': 'PASS_NUMERICAL_REGRESSION_ONLY', 'atom_ids': list(range(1, natoms + 1)), 'source_data_sha256': zero_sha(data), 'compared': ['H_A', 'origin_A', 'types', 'positions_A', 'image_flags', 'velocities_A_per_ps']}
            state_path = sim / 'parsed-native-snapshot-state.json'
            zero_write_json(state_path, {'schema': 'case06-native-run0-snapshot-state/v1', 'step': 0, 'snapshot_source': zero_ref(data, root), 'native_H_A': obs['H_A'], 'native_origin_A': obs['origin_A'], 'native_atom_types': obs['atom_types'], 'native_positions_A': obs['positions_A'], 'native_image_flags': obs['image_flags'], 'native_velocities_A_per_ps': obs['velocities_A_per_ps'], 'native_total_PE_eV': obs['pe_eV'], 'native_volume_A3': obs['vol_A3'], 'observation': zero_ref(sim / 'run0-observation.txt', root), 'force_dump': zero_ref(sim / 'forces.dump', root), 'comparison': obs['native_snapshot_state_match']})
            obs['native_snapshot_state_path'] = str(state_path)
            native_call = call
            proof_path = sim / 'prepared-snapshot-run0-proof.json'
            zero_write_json(proof_path, {'schema': 'case06-prepared-snapshot-run0-proof/v1', 'native_returncode': native_call['native_returncode'], 'wrapper_integrity_rc': native_call['wrapper_integrity_rc'], 'actual_steps': 0, 'snapshot_sha256': zero_sha(data), 'execution_receipt': {'path': native_call['execution_receipt_path'], 'sha256': native_call['execution_receipt_sha256']}, 'native_log': {'path': native_call['native_log_path'], 'sha256': native_call['native_log_sha256']}, 'native_dump': {'path': native_call['force_dump_path'], 'sha256': native_call['force_dump_sha256']}, 'native_dump_sha256': native_call['force_dump_sha256'], 'native_observation': {'path': native_call['observation_path'], 'sha256': native_call['observation_sha256']}, 'parsed_state': zero_ref(state_path, root)})
            obs['prepared_snapshot_run0_proof_path'] = str(proof_path)
        obs.update({'native_call': call, 'elapsed_seconds': elapsed, 'lattice_path': zero_ref(data, root)['path'], 'lattice_sha256': zero_sha(data), 'potential_sha256': zero_sha(potential), 'native_snapshot_state_match': obs.get('native_snapshot_state_match'), 'native_snapshot_state_path': zero_ref(obs['native_snapshot_state_path'], root)['path'] if obs.get('native_snapshot_state_path') else None, 'native_snapshot_state_sha256': zero_sha(obs['native_snapshot_state_path']) if obs.get('native_snapshot_state_path') else None, 'observation_path': zero_ref(obs['observation_path'], root)['path'], 'observation_sha256': zero_sha(sim / 'run0-observation.txt'), 'force_dump_path': zero_ref(sim / 'forces.dump', root)['path'], 'force_dump_sha256': zero_sha(sim / 'forces.dump')})
        return obs

    def zero_compare_pair(base, target, *, phase, label, site_map, site_map_doc, root, criterion):
        nb = base['atom_count']
        nt = target['atom_count']
        mapping = site_map
        if len(mapping) != nt or any((not 1 <= x <= nb for x in mapping)):
            raise zero_Unknown(f'{phase}/{label} site map has invalid length or source ID')
        expected_mult = 1 if nt == nb else 2
        counts = {i: 0 for i in range(1, nb + 1)}
        for i in mapping:
            counts[i] += 1
        if set(counts.values()) != {expected_mult}:
            raise zero_Unknown(f'{phase}/{label} site map does not cover base sites at required multiplicity')
        pe_delta = target['pe_eV'] - base['pe_eV'] if nt == nb else target['pe_eV'] / nt - base['pe_eV'] / nb
        pe_limit = max(float(criterion['base_total_PE_absolute_tolerance_eV']), float(criterion['base_total_PE_relative_tolerance']) * abs(base['pe_eV']))
        if nt == 2 * nb:
            pe_limit /= nb
        force_rows = []
        maximum_ratio = 0.0
        for (tid, bid) in enumerate(mapping, 1):
            fb = base['forces_eV_per_A'][bid - 1]
            ft = target['forces_eV_per_A'][tid - 1]
            delta = zero_math.sqrt(sum(((x - y) ** 2 for (x, y) in zip(ft, fb))))
            scale = max(zero_math.sqrt(sum((x * x for x in fb))), zero_math.sqrt(sum((x * x for x in ft))))
            limit = max(float(criterion['per_atom_force_vector_absolute_tolerance_eV_per_A']), float(criterion['per_atom_force_vector_relative_tolerance']) * scale)
            maximum_ratio = max(maximum_ratio, delta / limit)
            force_rows.append({'base_atom_id': bid, 'target_atom_id': tid, 'base_force_eV_per_A': fb, 'target_force_eV_per_A': ft, 'delta_norm_eV_per_A': delta, 'limit_eV_per_A': limit})
        pass_ = abs(pe_delta) <= pe_limit and maximum_ratio <= 1.0
        map_path = root / 'provenance' / f'{phase}-{label}-site-map.json'
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_doc = dict(site_map_doc)
        map_doc.update({'schema': 'case06-native-run0-site-map/v1', 'phase': phase, 'comparison': label, 'base_atoms': nb, 'target_atoms': nt, 'target_to_base_atom_ids': mapping, 'mapping_unique_bijective': True})
        zero_write_json(map_path, map_doc)
        return {'status': 'PASS_NUMERICAL_REGRESSION_ONLY' if pass_ else 'NOT_MET_NUMERICAL_REGRESSION', 'native_command_count': 2, 'run_steps': [0, 0], 'base': {k: base[k] for k in ('pe_eV', 'atom_count')}, 'target': {k: target[k] for k in ('pe_eV', 'atom_count')}, 'pe_delta_eV_per_atom': pe_delta, 'pe_limit_eV_per_atom': pe_limit, 'maximum_force_tolerance_ratio': maximum_ratio, 'force_site_map': zero_ref(map_path, root), 'force_comparisons': force_rows, 'base_call': base['native_call'], 'target_call': target['native_call'], 'base_observation': {k: base[k] for k in ('step', 'vol_A3', 'observation_path', 'observation_sha256', 'force_dump_path', 'force_dump_sha256')}, 'target_observation': {k: target[k] for k in ('step', 'vol_A3', 'observation_path', 'observation_sha256', 'force_dump_path', 'force_dump_sha256')}}

    def zero_write_json(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(zero_json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n')

    def zero_main(argv=None):
        global zero_NATIVE_CALLS_STARTED
        ap = zero_argparse.ArgumentParser(description=__doc__)
        ap.add_argument('--work-root', type=zero_Path, required=True)
        ap.add_argument('--wrapper', type=zero_Path, required=True)
        ap.add_argument('--native-binary', type=zero_Path, required=True)
        ap.add_argument('--potential', type=zero_Path, default=zero_NATIVE / 'SiOx_potential.yace')
        ap.add_argument('--output', type=zero_Path)
        ap.add_argument('--role', default='B')
        a = ap.parse_args(argv)
        root = a.work_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        proof_path = a.output.resolve() if a.output else root / 'acceptance' / 'native-zero-md-regression.json'
        try:
            matrix_path = zero_PAYLOAD / 'candidate-scope.json'
            geometry_path = zero_NATIVE / 'geometry-manifest.json'
            matrix_doc = zero__load(matrix_path)
            if matrix_doc.get('schema') != 'case06-candidate-public-scope/v1' or matrix_doc.get('source_matrix_sha256') != zero_EXPECTED_MATRIX_SHA:
                raise zero_Unknown('public candidate scope does not bind the frozen source matrix SHA')
            if zero_sha(a.potential) != zero_EXPECTED_POTENTIAL_SHA:
                raise zero_Unknown('public YACE SHA mismatch')
            expected_binary_sha = (zero_os.environ.get('CASE06_AUTHOR_BINARY_SHA')
                                   if a.role == 'A' and zero_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') == '1'
                                   else zero_EXPECTED_BINARY_SHA)
            if not expected_binary_sha or zero_sha(a.native_binary) != expected_binary_sha:
                raise zero_Unknown('provider-pinned native LAMMPS binary SHA mismatch')
            if not a.wrapper.is_file() or not zero_os.access(a.wrapper, zero_os.X_OK):
                raise zero_Unknown('guarded LAMMPS wrapper missing/not executable')
            matrix = matrix_doc
            criterion = matrix['native_zero_md_numeric_regression']
            geo = zero__load(geometry_path)
            if criterion.get('threshold_adaptation_after_data') is not False:
                raise zero_Unknown('numeric regression thresholds not frozen')
            source_hashes = {'alpha_quartz': zero_sha(zero_NATIVE / 'alpha_quartz-576.data'), 'coesite_original': zero_sha(zero_NATIVE / 'coesite-384.source.data'), 'coesite_aligned': zero_sha(zero_NATIVE / 'coesite-384.data'), 'potential': zero_sha(a.potential), 'native_binary': zero_sha(a.native_binary)}
            phases = {}
            phase_inputs = {'alpha_quartz': {'raw': zero_NATIVE / 'alpha_quartz-576.data', 'gauge': zero_NATIVE / 'alpha_quartz-576.data', 'size': zero_NATIVE / 'alpha_quartz-1152.data'}, 'coesite': {'raw': zero_NATIVE / 'coesite-384.source.data', 'gauge': zero_NATIVE / 'coesite-384.data', 'size': zero_NATIVE / 'coesite-768.data'}}
            for (phase, n) in (('alpha_quartz', 576), ('coesite', 384)):
                calc = phase_inputs[phase]
                calls = {}
                for (label, data) in calc.items():
                    calls[label] = zero_run_case(data, a.potential, a.wrapper.resolve(), a.native_binary.resolve(), root / 'native-run0', a.role, phase, label, root, n if label != 'size' else 2 * n)
                raw_gauge_map = list(range(1, n + 1))
                size_map = [(i - 1) % n + 1 for i in range(1, 2 * n + 1)]
                geom = next((x for x in geo['structures'] if x['phase'] == phase))
                pairs = geom.get('size_supercell', {}).get('site_pairs')
                if not isinstance(pairs, list) or len(pairs) != 2 * n:
                    raise zero_Unknown(f'{phase}: geometry manifest lacks frozen 2x source-derived site_pairs')
                expected_map = [int(x['base_atom_id']) for x in sorted(pairs, key=lambda x: int(x['target_atom_id']))]
                if expected_map != size_map:
                    raise zero_Unknown(f'{phase}: size source-id ordering differs from frozen geometry site map')
                identity_doc = {'site_pairs': [{'base_atom_id': i, 'target_atom_id': i, 'tile_representative': [0, 0, 0]} for i in range(1, n + 1)], 'map_kind': 'identity_raw_to_gauge', 'derivation': 'preserved atom ID correspondence under fixed integer unimodular gauge'}
                size_doc = {'site_pairs': pairs, 'map_kind': 'geometry_source_derived_determinant_two', 'derivation_script_sha256': zero_sha(zero_Path(__file__)), 'source_geometry_manifest_sha256': zero_sha(geometry_path)}
                rg = zero_compare_pair(calls['raw'], calls['gauge'], phase=phase, label='raw_to_gauge', site_map=raw_gauge_map, site_map_doc=identity_doc, root=root, criterion=criterion)
                bs = zero_compare_pair(calls['gauge'], calls['size'], phase=phase, label='base_to_size', site_map=expected_map, site_map_doc=size_doc, root=root, criterion=criterion)
                size_map_ref = bs['force_site_map']
                identity_map_ref = rg['force_site_map']
                rec = {'status': 'PASS_NUMERICAL_REGRESSION_ONLY' if rg['status'] == bs['status'] == 'PASS_NUMERICAL_REGRESSION_ONLY' else 'NOT_MET_NUMERICAL_REGRESSION', 'base_atom_count': n, 'site_map': dict(size_map_ref, base_atom_count=n, target_atom_count=2 * n, mapping_unique_bijective=True), 'comparisons': {'raw_to_gauge': rg, 'base_to_size': bs}}
                phases[phase] = rec
            good = all((x['status'] == 'PASS_NUMERICAL_REGRESSION_ONLY' for x in phases.values()))
            proof = {'schema': 'case06-native-zero-md-regression/v1', 'status': 'PASS_NUMERICAL_REGRESSION_ONLY' if good else 'NOT_MET_NUMERICAL_REGRESSION', 'source_hashes': source_hashes, 'matrix_sha256': zero_EXPECTED_MATRIX_SHA, 'geometry_manifest_sha256': zero_sha(geometry_path), 'numeric_criteria': {k: criterion[k] for k in ('base_total_PE_absolute_tolerance_eV', 'base_total_PE_relative_tolerance', 'per_atom_force_vector_absolute_tolerance_eV_per_A', 'per_atom_force_vector_relative_tolerance')}, 'phases': phases, 'new_positive_md_steps': 0, 'native_md_executed': True, 'native_run0_only': True, 'claim_limit': 'Numerical representation/engine consistency only; no canonical sampling or thermodynamic convergence claim.'}
            zero_write_json(proof_path, proof)
            print(zero_json.dumps({'status': proof['status'], 'native_md_steps': 0, 'native_calls': zero_NATIVE_CALLS_STARTED, 'proof_path': str(proof_path), 'proof_sha256': zero_sha(proof_path)}, indent=2))
            return 0 if good else 2
        except Exception as exc:
            failure = {'schema': 'case06-native-zero-md-regression/v1', 'status': 'UNKNOWN_OR_NOT_MET_STOP_BEFORE_POSITIVE_MD', 'native_md_executed': zero_NATIVE_CALLS_STARTED > 0, 'native_zero_step_calls_started': zero_NATIVE_CALLS_STARTED, 'positive_md_steps': 0, 'reason': f'{type(exc).__name__}: {exc}'}
            zero_write_json(proof_path, failure)
            print(zero_json.dumps(failure, indent=2))
            return 2

    # Direct source merge: instrument_lammps.py; namespace prefix instr_
    """Instrument each Calphy-generated LAMMPS input with a per-step cell guard."""
    import argparse as instr_argparse
    import hashlib as instr_hashlib
    import json as instr_json
    from pathlib import Path as instr_Path
    import re as instr_re
    import time as instr_time, math as instr_math
    instr_THERMO_FIELDS = ['step', 'time', 'temp', 'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz', 'vol', 'lx', 'ly', 'lz', 'xy', 'xz', 'yz', 'v_case08_ha', 'v_case08_hb', 'v_case08_hc', 'v_case08_face_violation', 'pe', 'etotal']
    instr_GUARD = ['variable case08_ha equal vol/sqrt((ly*lz)*(ly*lz)+(xy*lz)*(xy*lz)+(xy*yz-ly*xz)*(xy*yz-ly*xz))', 'variable case08_hb equal vol/(lx*sqrt(lz*lz+yz*yz))', 'variable case08_hc equal lz', 'variable case08_face_violation equal (v_case08_ha<=${threshold})||(v_case08_hb<=${threshold})||(v_case08_hc<=${threshold})', 'fix case08_face_guard all halt 1 v_case08_face_violation > 0.5 error hard message yes']

    def instr_instrument_text(text: str, source_name: str, threshold: float=10.5, thermo_interval: int=100, invocation_id: str='run') -> tuple[str, dict]:
        if not instr_math.isfinite(threshold) or threshold <= 0:
            raise ValueError('face-height threshold must be finite and positive')
        if isinstance(thermo_interval, bool) or thermo_interval < 1:
            raise ValueError('thermo interval must be a positive integer')
        lines = text.splitlines()
        if not lines:
            raise ValueError('empty generated LAMMPS input')
        if any(('case08_face_guard' in ln for ln in lines)):
            raise ValueError('input already has Case08 instrumentation; refusing double instrumentation')
        run_total = sum((bool(instr_re.match('^\\s*run\\s+', ln, instr_re.I)) for ln in lines))
        if run_total == 0:
            meta = {'source_name': source_name, 'native_guard': 'not_applicable_no_MD_run', 'threshold_face_height_A': threshold, 'cell_formula': 'n/a_no_MD_run', 'thermo_fields': [], 'thermo_interval_steps': None, 'run_commands_instrumented': 0, 'no_md_run': True, 'instrumentation_utc': instr_time.strftime('%Y-%m-%dT%H:%M:%SZ', instr_time.gmtime())}
            return (text if text.endswith('\n') else text + '\n', meta)
        fields = instr_THERMO_FIELDS
        out = []
        injected = False
        run_count = 0
        run_plan = []
        for line in lines:
            stripped = line.strip()
            if instr_re.match('^(read_data|read_restart)\\s+', stripped, instr_re.I):
                out.append(line)
                if not injected:
                    out.extend((line.replace('${threshold}', format(threshold, '.12g')) for line in instr_GUARD))
                    injected = True
                continue
            if instr_re.match('^run\\s+', stripped, instr_re.I):
                if not injected:
                    raise ValueError('no read_data/read_restart before first run; cannot safely install guard')
                toks = stripped.split()
                if len(toks) < 2 or not toks[1].isdigit():
                    raise ValueError(f'unrecognized run command; cannot budget safely: {stripped}')
                planned = int(toks[1])
                run_count += 1
                run_plan.append({'run_index': run_count, 'planned_steps': planned})
                segment = instr_Path(source_name).name
                out.append(f'print "CASE08_RUN_BEGIN segment={segment} index={run_count} planned_steps={planned} start_step=$(step:%.0f)"')
                out.extend(['thermo_style custom ' + ' '.join(fields), f'thermo {thermo_interval}', 'thermo_modify flush yes'])
                traj = str(instr_Path(source_name).resolve().parent / f'{instr_Path(source_name).stem}.{invocation_id}.run{run_count}.lammpstrj')
                out.extend([f'dump case08_traj_{run_count} all custom 100 {traj} id type x y z', f'dump_modify case08_traj_{run_count} sort id flush yes'])
                out.append(line)
                out.append(f'undump case08_traj_{run_count}')
                out.append(f'print "CASE08_RUN_END segment={segment} index={run_count} planned_steps={planned} end_step=$(step:%.0f)"')
                continue
            out.append(line)
        if not injected:
            raise ValueError('no read_data/read_restart command; cannot install guard')
        content = '\n'.join(out) + '\n'
        if content.count('fix case08_face_guard all halt 1') != 1:
            raise ValueError('expected exactly one persistent fix halt guard')
        if run_count != run_total:
            raise ValueError('not every run command was instrumented')
        meta = {'source_name': source_name, 'native_guard': 'LAMMPS fix halt checks each MD step (N=1); error hard', 'threshold_face_height_A': threshold, 'cell_formula': 'restricted triclinic reciprocal heights: h_a=V/|b×c|, h_b=V/|c×a|, h_c=lz', 'thermo_fields': fields, 'thermo_interval_steps': thermo_interval, 'run_commands_instrumented': run_count, 'no_md_run': False, 'run_plan': run_plan, 'instrumentation_utc': instr_time.strftime('%Y-%m-%dT%H:%M:%SZ', instr_time.gmtime())}
        return (content, meta)

    def instr_main(argv=None):
        ap = instr_argparse.ArgumentParser()
        ap.add_argument('--input', required=True, type=instr_Path)
        ap.add_argument('--output', required=True, type=instr_Path)
        ap.add_argument('--manifest', required=True, type=instr_Path)
        ap.add_argument('--min-face-A', type=float, default=10.5)
        ap.add_argument('--thermo-interval', type=int, default=100)
        ap.add_argument('--invocation-id', required=True)
        ap.add_argument('--native-log', type=instr_Path, required=True)
        a = ap.parse_args(argv)
        raw = a.input.read_bytes()
        original = raw.decode('utf-8')
        (content, meta) = instr_instrument_text(original, str(a.input.resolve()), a.min_face_A, a.thermo_interval, a.invocation_id)
        data = content.encode('utf-8')
        a.output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = a.output.with_suffix(a.output.suffix + '.tmp')
        tmp_output.write_bytes(data)
        tmp_output.replace(a.output)
        record = {**meta, 'original_path': str(a.input.resolve()), 'original_sha256': instr_hashlib.sha256(raw).hexdigest(), 'instrumented_path': str(a.output.resolve()), 'instrumented_sha256': instr_hashlib.sha256(data).hexdigest(), 'original_bytes': len(raw), 'instrumented_bytes': len(data)}
        snapshot_dir = a.manifest.parent / 'case08-input-snapshots'
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_dir / f'{a.input.name}.{a.invocation_id}.raw'
        if snapshot.exists() and snapshot.read_bytes() != raw:
            raise RuntimeError(f'snapshot hash collision or corrupt snapshot: {snapshot}')
        if not snapshot.exists():
            tmp_snapshot = snapshot.with_suffix(snapshot.suffix + '.tmp')
            tmp_snapshot.write_bytes(raw)
            tmp_snapshot.replace(snapshot)
        record['original_snapshot_path'] = str(snapshot.resolve())
        record['invocation_id'] = a.invocation_id
        m = instr_re.match('^(\\d+)-', a.invocation_id)
        record['call_index'] = int(m.group(1)) if m else None
        record['native_log_path'] = str(a.native_log.resolve())
        record['planned_native_trajectory_glob'] = f'{a.input.stem}.{a.invocation_id}.run*.lammpstrj'
        a.manifest.parent.mkdir(parents=True, exist_ok=True)
        with a.manifest.open('a', encoding='utf-8') as f:
            f.write(instr_json.dumps(record, sort_keys=True) + '\n')
        print(instr_json.dumps(record, sort_keys=True))

    # Direct source merge: configure_runtime.py; namespace prefix cfg_
    """Render the frozen Case08 JSON/YAML input against this exact run directory."""
    import argparse as cfg_argparse, hashlib as cfg_hashlib, json as cfg_json, os as cfg_os, re as cfg_re
    from pathlib import Path as cfg_Path

    def cfg_main(argv=None):
        ap = cfg_argparse.ArgumentParser()
        ap.add_argument('--template', type=cfg_Path, required=True)
        ap.add_argument('--out', type=cfg_Path, required=True)
        ap.add_argument('--run-root', type=cfg_Path, required=True)
        ap.add_argument('--wrapper', type=cfg_Path, required=True)
        ap.add_argument('--potential', type=cfg_Path, required=True)
        a = ap.parse_args(argv)
        root = a.run_root.resolve()
        wrapper = a.wrapper.resolve()
        potential = a.potential.resolve()
        doc = cfg_json.loads(a.template.read_text())
        role = doc.get('role')
        if role not in {'B', 'R', 'S', 'A'}:
            raise SystemExit('runtime template must bind one registered fresh-setup role B/R/S/A')
        registration_path = root / 'native_inputs' / f'seed-registration-{role}.json'
        if not registration_path.is_file():
            raise SystemExit(f'missing role-specific seed registration: {registration_path}')
        registration = cfg_json.loads(registration_path.read_text())
        if registration.get('role') != role:
            raise SystemExit('runtime template and seed registration roles differ')
        template_sha = cfg_hashlib.sha256(a.template.read_bytes()).hexdigest()
        if registration.get('input_sha256') != template_sha:
            raise SystemExit('runtime input template hash differs from independent seed preregistration')
        author_cpu = False
        if role == 'A':
            binary_text = cfg_os.environ.get('CASE08_REAL_LMP', '')
            binary = cfg_Path(binary_text)
            expected_binary = cfg_os.environ.get('CASE06_AUTHOR_BINARY_SHA', '')
            if (cfg_os.environ.get('CASE06_AUTHOR_REFERENCE_WORKER') != '1'
                    or binary_text != '/opt/lammps-29Aug2024-update3/bin/lmp'
                    or not cfg_re.fullmatch('[0-9a-f]{64}', expected_binary)
                    or not binary.is_file()):
                raise SystemExit('private A CPU renderer requires the image-pinned host worker binary identity')
            binary_hash = cfg_hashlib.sha256()
            with binary.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    binary_hash.update(chunk)
            if binary_hash.hexdigest() != expected_binary:
                raise SystemExit('private A CPU renderer requires the image-pinned host worker binary identity')
            author_cpu = True
        declared = {r['phase']: int(r['master_seed']) for r in registration['phases']}
        phases = []
        for calc in doc['calculations']:
            if calc.get('queue', {}).get('cores') != 1:
                raise SystemExit('each Calphy calculation must use one execution rank')
            if author_cpu:
                if (calc.get('md', {}).get('cmdargs') != ''
                        or calc.get('md', {}).get('init_commands') != ['atom_style atomic']
                        or calc.get('pair_style') != 'pace product'
                        or calc.get('execution_mode') != 'executable'):
                    raise SystemExit('private A CPU input must bind atomic style, pace product, and executable mode')
            elif '-k on g 1' not in calc.get('md', {}).get('cmdargs', ''):
                raise SystemExit('native LAMMPS GPU request must remain exactly one Kokkos GPU')
            phase = cfg_Path(calc['lattice']).name
            phase_name = 'alpha_quartz' if phase.startswith('alpha_quartz-') else 'coesite' if phase.startswith('coesite-') else None
            if phase_name is None or phase_name in phases:
                raise SystemExit(f'unregistered or duplicate phase input: {phase}')
            if int(calc['md']['seed']) != declared.get(phase_name):
                raise SystemExit(f'{phase_name} master seed differs from preregistration')
            phases.append(phase_name)
            lattice = (root / 'native_inputs' / phase).resolve()
            if not lattice.is_file():
                raise SystemExit(f'missing lattice {lattice}')
            calc['lattice'] = str(lattice)
            calc['lammps_executable'] = str(wrapper)
            calc['pair_coeff'] = f'* * {potential} O Si'
            expected_pair_style = 'pace product' if author_cpu else 'pace/kk product'
            if calc.get('pair_style') != expected_pair_style:
                raise SystemExit('unexpected pair_style')
            if calc.get('element') != ['O', 'Si']:
                raise SystemExit('unexpected element order')
            if calc.get('temperature') != 600.0 or calc.get('pressure') != 20000.0:
                raise SystemExit('unexpected target conditions')
        if set(phases) != {'alpha_quartz', 'coesite'} or len({int(c['md']['seed']) for c in doc['calculations']}) != 2:
            raise SystemExit('seed3 candidate must include one unique independent seed for each declared phase')
        data = (cfg_json.dumps(doc, indent=2, sort_keys=True) + '\n').encode()
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(data)
        receipt = {'template': str(a.template.resolve()), 'template_sha256': cfg_hashlib.sha256(a.template.read_bytes()).hexdigest(), 'runtime_input': str(a.out.resolve()), 'runtime_input_sha256': cfg_hashlib.sha256(data).hexdigest(), 'run_root': str(root), 'wrapper': str(wrapper), 'potential': str(potential), 'lattices': [c['lattice'] for c in doc['calculations']], 'calphy_calls_guarded_by_wrapper': True}
        (a.out.parent / 'runtime-input-provenance.json').write_text(cfg_json.dumps(receipt, indent=2) + '\n')
        print(cfg_json.dumps(receipt, sort_keys=True))

    # Direct source merge: verify_v2.py; namespace prefix audit_
    """Independent, fail-closed audit for the current Case-06 single-state-v2 campaign.

    The historical ``verify.py`` remains the v1 verifier.  This module consumes the
    versioned campaign evidence described by ``case06-single-state-v2-campaign-evidence/v1``
    and deliberately returns UNKNOWN when source-backed data needed for a scientific
    judgment are absent.  A scheduler success, CSV status, or receipt status alone can
    never admit a direction.
    """
    import argparse as audit_argparse
    import csv as audit_csv
    import hashlib as audit_hashlib
    import itertools as audit_itertools
    import json as audit_json
    import math as audit_math
    import re as audit_re
    import sys as audit_sys
    from datetime import datetime as audit_datetime
    from pathlib import Path as audit_Path
    from decimal import Decimal as audit_Decimal
    from typing import Any as audit_Any
    audit_DEFAULT_PLAN = ASSET_ROOT / 'candidate-scope.json'
    audit_DEFAULT_EXTENSION = ASSET_ROOT / 'candidate-scope.json'

    def audit_source_matrix_sha():
        return audit_json.loads((ASSET_ROOT / 'candidate-scope.json').read_text())['source_matrix_sha256']
    audit_DELTA_HEADER = ['T_K', 'P_bar', 'G_coesite_minus_G_alpha_eV_per_atom', 'repeat_uncertainty_eV_per_atom', 'direction_uncertainty_eV_per_atom', 'switching_uncertainty_eV_per_atom', 'finite_size_uncertainty_eV_per_atom', 'combined_uncertainty_eV_per_atom', 'decision', 'reason']
    audit_GIBBS_HEADER = ['phase', 'T_K', 'P_bar', 'G_eV_per_atom', 'replicate', 'direction', 'cell_atoms', 'equilibration_steps', 'switching_steps', 'window_start', 'window_end', 'uncertainty_eV_per_atom', 'status', 'reason']
    audit_PUBLIC_YACE = 'c8f00d8f0cbc131b0298b79260ba8098975624363c9d178223e51e48f025e97a'
    audit_PHASE_ATOMS = {'alpha_quartz': 576, 'coesite': 384}
    audit_ROLE_MAP = {'B': 'baseline', 'R': 'independent_repeat', 'S': 'adaptive_size', 'D': 'adaptive_duration', 'A': 'independent_reference'}
    audit_ROLE_TO_REPLICATE = {value: key for (key, value) in audit_ROLE_MAP.items() if key in ('B', 'R', 'S', 'D')}

    class audit_UnknownEvidence(ValueError):
        """Evidence needed to judge a criterion is absent or unsupported."""

    class audit_Mismatch(ValueError):
        """Source-backed evidence contradicts a frozen criterion."""

    def audit_sha(path: audit_Path) -> str:
        h = audit_hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda : stream.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def audit_finite(value: audit_Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if audit_math.isfinite(result) else None

    def audit_add(checks: list[dict], name: str, status: str, detail: str='') -> None:
        checks.append({'check': name, 'status': status, 'detail': detail})

    def audit__verify_runtime_source_identity(outputs: audit_Path, evidence: dict, plan: dict, checks: list[dict]) -> bool:
        """Replay installed Calphy, runtime hash list and all six initial binary refs."""
        software = evidence.get('software')
        if not isinstance(software, dict):
            audit_add(checks, 'v2_runtime_source_identity', 'UNKNOWN', 'campaign software provenance is absent')
            return False
        try:
            method = plan.get('native_method', {})
            wheel_expected = method.get('calphy_wheel_sha256')
            binary_expected = os.environ.get("CASE159_LAMMPS_SHA256", method.get('lammps_stable_binary_sha256'))
            manifest_ref = software.get('calphy_source_manifest')
            identity_ref = software.get('calphy_source_identity') or software.get('calphy_identity_ref')
            runtime_ref = software.get('runtime_source_receipt_ref')
            binary_refs = software.get('native_binary_provenance_refs')
            zero_ref = software.get('native_zero_md_regression_ref')
            for (name, ref) in (('Calphy source manifest', manifest_ref), ('installed Calphy identity', identity_ref), ('runtime source SHA list', runtime_ref), ('native zero-MD regression', zero_ref)):
                if not isinstance(ref, dict):
                    raise audit_UnknownEvidence(f'{name} reference is absent')
            manifest_path = audit__file_ref(outputs, manifest_ref)
            manifest = audit__load_json(manifest_path)
            if manifest.get('wheel_sha256') != wheel_expected or software.get('calphy_wheel_sha256') != wheel_expected:
                raise audit_Mismatch('Calphy source manifest/evidence differs from the frozen wheel SHA')
            source_map = manifest.get('calphy_python_sources')
            if not isinstance(source_map, dict) or not source_map or any((not isinstance(k, str) or not audit_re.fullmatch('[0-9a-f]{64}', str(v)) for (k, v) in source_map.items())):
                raise audit_Mismatch('Calphy source manifest has an invalid module hash map')
            identity_path = audit__file_ref(outputs, identity_ref)
            identity = audit__load_json(identity_path)
            if identity.get('schema') != 'case08-calphy-source-identity/v1' or identity.get('version') != '2.1.2' or identity.get('wheel_sha256') != wheel_expected or (identity.get('pass') is not True) or (identity.get('errors') != []) or (identity.get('observed_file_sha256') != source_map):
                raise audit_Mismatch('installed Calphy module hashes do not match the frozen wheel source manifest')
            runtime_path = audit__file_ref(outputs, runtime_ref)
            runtime_hashes = {}
            for line in runtime_path.read_text(encoding='utf-8', errors='strict').splitlines():
                m = audit_re.fullmatch('([0-9a-f]{64})\\s+\\*?(.+)', line.strip())
                if not m:
                    raise audit_Mismatch('runtime source SHA receipt has a malformed sha256sum line')
                p = m.group(2).strip()
                if p in runtime_hashes:
                    raise audit_Mismatch('runtime source SHA receipt repeats a source path')
                runtime_hashes[p] = m.group(1)
            if not runtime_hashes:
                raise audit_UnknownEvidence('runtime source SHA receipt is empty')
            runtime_by_name = {audit_Path(p).name: d for (p, d) in runtime_hashes.items()}
            source_refs = {'native binary': None, 'public potential': evidence.get('hamiltonian'), 'instrumenter': software.get('instrumenter'), 'guard wrapper': software.get('wrapper')}
            for (label, ref) in source_refs.items():
                if label == 'native binary':
                    continue
                if not isinstance(ref, dict):
                    raise audit_UnknownEvidence(f'runtime source lacks {label} artifact reference')
                source_path = audit__file_ref(outputs, ref)
                runtime_digest = runtime_by_name.get(source_path.name)
                if runtime_digest is None or runtime_digest != audit_sha(source_path):
                    raise audit_Mismatch(f'runtime source SHA receipt does not bind the delivered {label}')
            if not isinstance(binary_refs, list) or len(binary_refs) != 6:
                raise audit_UnknownEvidence('initial native binary provenance must cover raw/gauge/size for both phases')
            zero_path = audit__file_ref(outputs, zero_ref)
            zero = audit__load_json(zero_path)
            if zero.get('schema') != 'case06-native-zero-md-regression/v1' or zero.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY' or zero.get('new_positive_md_steps') != 0 or (zero.get('native_run0_only') is not True) or (zero.get('matrix_sha256') != audit_source_matrix_sha()):
                raise audit_Mismatch('native zero-MD regression is not a hash-bound pass for the current matrix')
            phases = zero.get('phases', {})
            if set(phases) != {'alpha_quartz', 'coesite'}:
                raise audit_Mismatch('zero-MD regression lacks both phases')
            raw_calls = {}
            for (phase, phase_doc) in phases.items():
                comparisons = phase_doc.get('comparisons', {})
                if set(comparisons) != {'raw_to_gauge', 'base_to_size'}:
                    raise audit_Mismatch('zero-MD regression lacks raw/gauge and base/size comparisons')
                for comparison in comparisons.values():
                    if comparison.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY':
                        raise audit_Mismatch('zero-MD geometry comparison is not a passing raw record')
                    for name in ('base_call', 'target_call'):
                        call = comparison.get(name)
                        if not isinstance(call, dict) or not isinstance(call.get('invocation_id'), str):
                            raise audit_UnknownEvidence('zero-MD comparison lacks an invocation-bound call record')
                        inv = call['invocation_id']
                        if inv in raw_calls and raw_calls[inv] != call:
                            raise audit_Mismatch('duplicate zero-MD invocation has conflicting evidence')
                        raw_calls[inv] = call
            seen = set()
            binary_paths = set()
            binary_by_inv = {}
            for ref in binary_refs:
                p = audit__file_ref(outputs, ref)
                doc = audit__load_json(p)
                if doc.get('schema') != 'case06-native-binary-provenance/v1':
                    raise audit_UnknownEvidence('unsupported initial native binary provenance schema')
                native = doc.get('native_binary', {})
                digest = native.get('sha256') if isinstance(native, dict) else None
                if digest != binary_expected:
                    raise audit_Mismatch('initial zero-MD call uses an unpinned native binary SHA')
                key = (doc.get('phase'), doc.get('run0_label'))
                if not isinstance(key[0], str) or not key[0] or (not isinstance(key[1], str)) or (not key[1]):
                    raise audit_Mismatch('native binary provenance has missing phase/label')
                if key[1] in ('raw', 'gauge', 'size'):
                    if key in seen:
                        raise audit_Mismatch('initial native binary provenance duplicates a phase/geometry call')
                    if key[0] not in ('alpha_quartz', 'coesite'):
                        raise audit_Mismatch('initial native binary provenance has an unregistered phase')
                    seen.add(key)
                if not isinstance(doc.get('argv'), list) or not doc['argv']:
                    raise audit_UnknownEvidence('initial binary provenance lacks exact invocation argv')
                inv = doc.get('invocation_id')
                if not isinstance(inv, str) or not inv or inv in binary_by_inv:
                    raise audit_Mismatch('native binary provenance has missing or duplicate invocation ID')
                binary_paths.add(audit_Path(str(native.get('path', ''))).name)
                binary_by_inv[inv] = (ref, doc)
            if seen != {(phase, label) for phase in ('alpha_quartz', 'coesite') for label in ('raw', 'gauge', 'size')}:
                raise audit_Mismatch('initial native binary provenance does not cover the exact six phase/geometry evaluations')
            if set(raw_calls) != set(binary_by_inv):
                raise audit_Mismatch('raw zero-MD call inventory differs from native binary provenance invocation IDs')
            for (inv, call) in raw_calls.items():
                (ref, doc) = binary_by_inv[inv]
                if call.get('phase') != doc.get('phase') or call.get('run0_label') != doc.get('run0_label') or call.get('binary_provenance_ref', {}).get('sha256') != ref.get('sha256'):
                    raise audit_Mismatch('raw zero-MD call does not bind its matching binary provenance record')
            audit__replay_initial_zero_md_calls(outputs, zero_path, zero, raw_calls, binary_by_inv)
            binary_matches = [v for (p, v) in runtime_hashes.items() if audit_Path(p).name in binary_paths]
            if not binary_matches or any((v != binary_expected for v in binary_matches)):
                raise audit_Mismatch('runtime source SHA receipt does not bind the invoked native binary path and expected SHA')
            audit_add(checks, 'v2_runtime_source_identity', 'PASS', 'installed Calphy module hashes, runtime source SHA list, and six initial native binary records replayed')
            return True
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_runtime_source_identity', 'UNKNOWN', str(exc))
            return False
        except Exception as exc:
            audit_add(checks, 'v2_runtime_source_identity', 'FAIL', str(exc))
            return False

    def audit__parse_initial_zero_data_atoms(path: audit_Path, expected_atoms: int) -> list[dict]:
        """Parse source atom/image/velocity rows for the six initial native calls."""
        geom = audit__geom_data(path)
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        rows = {}
        velocities = {}
        section = ''
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('Atoms'):
                section = 'Atoms'
                continue
            if stripped == 'Velocities':
                section = 'Velocities'
                continue
            if not stripped:
                if section and (rows if section == 'Atoms' else velocities):
                    section = ''
                continue
            fields = line.split('#', 1)[0].split()
            if section == 'Atoms' and len(fields) >= 5 and fields[0].isdigit():
                aid = int(fields[0])
                typ = int(fields[1])
                tokens = tuple(fields[2:5])
                image = tuple((int(x) for x in fields[5:8])) if len(fields) >= 8 else (0, 0, 0)
                rows[aid] = (typ, tokens, image)
            elif section == 'Velocities' and len(fields) >= 4 and fields[0].isdigit():
                aid = int(fields[0])
                velocities[aid] = tuple(fields[1:4])
        if set(rows) != set(range(1, expected_atoms + 1)) or geom['n'] != expected_atoms:
            raise audit_Mismatch('initial native run0 source data lacks exact contiguous atom rows')
        if velocities and set(velocities) != set(rows):
            raise audit_Mismatch('initial native run0 source data has incomplete velocity rows')
        atoms = []
        for aid in sorted(rows):
            (typ, tokens, image) = rows[aid]
            geomrow = next((x for x in geom['atoms'] if x[0] == aid), None)
            if geomrow is None or geomrow[1] != typ:
                raise audit_Mismatch('source geometry parser disagrees on atom IDs/types')
            xyz = tuple((finite(x) for x in tokens))
            if any((x is None for x in xyz)):
                raise audit_Mismatch('nonfinite initial run0 source position')
            xyzerr = tuple((_coordinate_round_bound(v, t, 17) for (v, t) in zip(xyz, tokens)))
            vtokens = velocities.get(aid, ('0', '0', '0'))
            vel = tuple((finite(x) for x in vtokens))
            if any((x is None for x in vel)):
                raise audit_Mismatch('nonfinite initial run0 source velocity')
            velerr = tuple((_coordinate_round_bound(v, t, 17) for (v, t) in zip(vel, vtokens)))
            atoms.append({'id': aid, 'type': typ, 'image': image, 'xyz': xyz, 'xyz_error': xyzerr, 'vel': vel, 'vel_error': velerr})
        return atoms

    def audit__reference_phase_sources(rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
        """Validate the frozen A design: two phase preparations, each shared by F/B."""
        if len(rows) != 4 or any((r.get('role') != 'independent_reference' for r in rows)):
            raise audit_UnknownEvidence('held-out A requires four phase×direction records')
        grouped = {}
        for row in rows:
            grouped.setdefault(row.get('phase'), []).append(row)
        if set(grouped) != set(audit_PHASE_ATOMS):
            raise audit_UnknownEvidence('held-out A must cover exactly both phases')
        phase_seeds = {}
        phase_snapshots = {}
        for (phase, items) in grouped.items():
            if len(items) != 2 or {r.get('direction') for r in items} != {'forward', 'backward'}:
                raise audit_UnknownEvidence(f'held-out A {phase} must share one preparation across F/B')
            seeds = {str(r.get('seed') if r.get('seed') is not None else r.get('master_seed')) for r in items}
            snapshots = {str(r.get('snapshot_sha256') if r.get('snapshot_sha256') is not None else r.get('equilibrated_snapshot_sha256')) for r in items}
            if len(seeds) != 1 or 'None' in seeds:
                raise audit_UnknownEvidence(f'held-out A {phase} F/B do not share one valid master seed')
            if len(snapshots) != 1 or 'None' in snapshots:
                raise audit_UnknownEvidence(f'held-out A {phase} F/B do not share one prepared snapshot')
            phase_seeds[phase] = next(iter(seeds))
            phase_snapshots[phase] = next(iter(snapshots))
        if len(set(phase_seeds.values())) != 2:
            raise audit_Mismatch('held-out A phase master seeds are not independent')
        if len(set(phase_snapshots.values())) != 2:
            raise audit_Mismatch('held-out A phase snapshots are not distinct')
        return (phase_seeds, phase_snapshots)

    def audit__replay_initial_zero_md_calls(outputs: audit_Path, proof_path: audit_Path, zero: dict, calls: dict[str, dict], binaries: dict[str, tuple]) -> None:
        """Reparse the six guarded run-0 calls and recompute the frozen PE/force checks.

        The producer's PASS fields are treated as indexes only. Native logs, literal
        inputs, observations, force dumps, source data and site maps are all read
        again here. The proof is stored below a role work root, so its call paths
        are resolved from that root while public source bytes come from the frozen
        candidate native_inputs inventory.
        """
        proof_root = proof_path.parent.parent.resolve()
        allowed = outputs.resolve()
        if proof_root != allowed and allowed not in proof_root.parents:
            raise audit_Mismatch('initial run0 proof work root escapes candidate outputs')
        phases = zero.get('phases', {})
        expected_data = {('alpha_quartz', 'raw'): 'alpha_quartz-576.data', ('alpha_quartz', 'gauge'): 'alpha_quartz-576.data', ('alpha_quartz', 'size'): 'alpha_quartz-1152.data', ('coesite', 'raw'): 'coesite-384.source.data', ('coesite', 'gauge'): 'coesite-384.data', ('coesite', 'size'): 'coesite-768.data'}
        parsed = {}
        criteria = audit_load_current_plan().get('native_zero_md_numeric_regression', {})
        pe_abs = float(criteria.get('base_total_PE_absolute_tolerance_eV', audit_math.nan))
        pe_rel = float(criteria.get('base_total_PE_relative_tolerance', audit_math.nan))
        force_abs = float(criteria.get('per_atom_force_vector_absolute_tolerance_eV_per_A', audit_math.nan))
        force_rel = float(criteria.get('per_atom_force_vector_relative_tolerance', audit_math.nan))
        if not all((audit_math.isfinite(x) and x >= 0 for x in (pe_abs, pe_rel, force_abs, force_rel))):
            raise audit_Mismatch('frozen native zero-MD numeric criteria are absent or invalid')

        def local_ref(ref: audit_Any, what: str) -> audit_Path:
            if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
                raise audit_UnknownEvidence(f'initial run0 {what} reference is missing')
            raw = audit_Path(ref['path'])
            if raw.is_absolute() or '..' in raw.parts:
                raise audit_Mismatch(f'unsafe initial run0 {what} path')
            path = (proof_root / raw).resolve()
            if proof_root not in path.parents or not path.is_file():
                raise audit_UnknownEvidence(f'initial run0 {what} is missing')
            if audit_sha(path) != ref.get('sha256'):
                raise audit_Mismatch(f'initial run0 {what} SHA differs from raw bytes')
            return path
        for phase in ('alpha_quartz', 'coesite'):
            for label in ('raw', 'gauge', 'size'):
                inv = next((i for (i, (_, doc)) in binaries.items() if doc.get('phase') == phase and doc.get('run0_label') == label), None)
                if inv is None:
                    raise audit_Mismatch(f'initial run0 has no binary-bound call for {phase}/{label}')
                call = calls[inv]
                native_doc = binaries[inv][1]
                if call.get('phase') != phase or call.get('run0_label') != label:
                    raise audit_Mismatch('initial run0 invocation phase/label differs from its call record')
                n = (576 if phase == 'alpha_quartz' else 384) * (2 if label == 'size' else 1)
                source_path = outputs / 'native_inputs' / expected_data[phase, label]
                if not source_path.is_file():
                    raise audit_UnknownEvidence(f'frozen source data missing for {phase}/{label}')
                data = audit__geom_data(source_path)
                if data['n'] != n:
                    raise audit_Mismatch(f'frozen source atom count differs for {phase}/{label}')
                original = local_ref({'path': call.get('original_input_path'), 'sha256': call.get('original_input_sha256')}, 'original input')
                executed = local_ref({'path': call.get('instrumented_input_path'), 'sha256': call.get('instrumented_input_sha256')}, 'instrumented input')
                log = local_ref({'path': call.get('native_log_path'), 'sha256': call.get('native_log_sha256')}, 'native log')
                wrapper_path = local_ref({'path': call.get('wrapper_execution_receipt_path'), 'sha256': call.get('wrapper_execution_receipt_sha256')}, 'wrapper receipt')
                normalized_path = local_ref({'path': call.get('execution_receipt_path'), 'sha256': call.get('execution_receipt_sha256')}, 'normalized receipt')
                obs_path = local_ref({'path': call.get('observation_path'), 'sha256': call.get('observation_sha256')}, 'native observation')
                dump_path = local_ref({'path': call.get('force_dump_path'), 'sha256': call.get('force_dump_sha256')}, 'native force dump')
                wrapper = audit__load_json(wrapper_path)
                normalized = audit__load_json(normalized_path)
                if wrapper.get('native_returncode') != 0 or wrapper.get('wrapper_integrity_rc') != 0 or wrapper.get('integrity_errors') != [] or (wrapper.get('expected_run_count') != 1):
                    raise audit_Mismatch(f'{phase}/{label} wrapper receipt is not a clean zero-positive-run call')
                if wrapper.get('invocation_id') != inv or normalized.get('invocation_id') != inv or normalized.get('native_returncode') != 0 or (normalized.get('wrapper_integrity_rc') != 0) or (normalized.get('manifest_run_plan_match') is not True) or (normalized.get('native_step') != 0) or (normalized.get('native_atom_count') != n) or (normalized.get('native_zero_only') is not True):
                    raise audit_Mismatch(f'{phase}/{label} normalized run0 receipt disagrees with raw wrapper invocation')
                binary = audit__replay_binary_provenance(outputs, normalized, wrapper, None)
                if binary.get('sha256') != native_doc.get('native_binary', {}).get('sha256'):
                    raise audit_Mismatch(f'{phase}/{label} actual wrapper binary differs from binary provenance')
                events = audit__read_native_log(log)
                if len(events) != 1 or events[0]['steps'] != 0 or events[0]['atoms'] != n or (events[0]['index'] != 1):
                    raise audit_Mismatch(f'{phase}/{label} raw native log is not exactly one ordered zero-step event')
                if wrapper.get('native_log_archive', {}).get('sha256') != audit_sha(log):
                    raise audit_Mismatch(f'{phase}/{label} wrapper archive does not bind raw native log')
                if normalized.get('native_log_sha256') != audit_sha(log):
                    raise audit_Mismatch(f'{phase}/{label} normalized receipt does not bind raw native log')
                expected_name = expected_data[phase, label]
                for script in (original, executed):
                    text = script.read_text(encoding='utf-8', errors='strict')
                    if audit__source_run_steps(script) != [0]:
                        raise audit_Mismatch(f'{phase}/{label} literal input is not exactly run 0')
                    clean = [_strip_lammps_comment(line).strip() for line in text.splitlines()]
                    reads = [x.split() for x in clean if x.lower().startswith('read_data ')]
                    if len(reads) != 1 or audit_Path(reads[0][-1]).name != expected_name:
                        raise audit_Mismatch(f'{phase}/{label} input does not load the registered source data')
                    if sum((x.lower() == 'units metal' for x in clean)) != 1 or sum((x.lower() == 'atom_style atomic' for x in clean)) != 1:
                        raise audit_Mismatch(f'{phase}/{label} units/atom_style are not the pinned setup')
                    if sum((x.lower() == 'pair_style pace/kk product' for x in clean)) != 1:
                        raise audit_Mismatch(f'{phase}/{label} pair style differs from the pinned Hamiltonian')
                    coeff = [x.split() for x in clean if x.lower().startswith('pair_coeff ')]
                    if len(coeff) != 1 or len(coeff[0]) != 6 or coeff[0][1:3] != ['*', '*'] or (coeff[0][4:] != ['O', 'Si']):
                        raise audit_Mismatch(f'{phase}/{label} pair coefficients differ from pinned O/Si Hamiltonian')
                    potential = audit_Path(coeff[0][3])
                    potential = potential if potential.is_absolute() else script.parent / potential
                    public_copy = outputs / 'native_inputs' / 'SiOx_potential.yace'
                    if potential.name != 'SiOx_potential.yace' or not public_copy.is_file() or audit_sha(public_copy) != audit_PUBLIC_YACE:
                        raise audit_Mismatch(f'{phase}/{label} input does not name the pinned YACE artifact')
                    if potential.exists() and audit_sha(potential) != audit_PUBLIC_YACE:
                        raise audit_Mismatch(f'{phase}/{label} input resolves to non-pinned YACE bytes')
                    masses = sorted((x.split() for x in clean if x.lower().startswith('mass ')))
                    if masses != [['mass', '1', '15.999'], ['mass', '2', '28.085']]:
                        raise audit_Mismatch(f'{phase}/{label} masses differ from pinned O/Si values')
                native = audit__parse_run0_force_dump(dump_path, n)
                observation = obs_path.read_text(encoding='utf-8', errors='strict').splitlines()
                rows = [x for x in observation if x.startswith('CASE06_RUN0_RESULT ')]
                if len(rows) != 1:
                    raise audit_Mismatch(f'{phase}/{label} needs one raw native PE observation')
                fields = dict((x.split('=', 1) for x in rows[0].split()[1:]))
                if set(fields) != {'step', 'pe_eV', 'atoms', 'vol_A3'}:
                    raise audit_Mismatch('native zero-MD observation schema mismatch')
                pe = audit_finite(fields['pe_eV'])
                vol = audit_finite(fields['vol_A3'])
                if int(fields['step']) != 0 or int(fields['atoms']) != n or pe is None or (vol is None):
                    raise audit_Mismatch(f'{phase}/{label} raw native PE observation is invalid')
                det = audit__det3(native['H'])
                if abs(det - vol) > 2e-12 * max(abs(det), abs(vol), 1.0):
                    raise audit_Mismatch(f'{phase}/{label} PE volume differs from raw dump determinant')
                source_rows = audit__parse_initial_zero_data_atoms(source_path, n)
                source_geom = data
                native_rows = native['atoms']
                source_H = source_geom['H']
                for i in range(3):
                    native_origin = native['origin'][i]
                    source_origin = source_geom['origin'][i]
                    native_origin_err = native['origin_error'][i]
                    source_origin_err = source_geom['origin_error'][i]
                    if abs(native_origin - source_origin) > native_origin_err + source_origin_err + 16 * audit_sys.float_info.epsilon * (abs(native_origin) + abs(source_origin) + 1):
                        raise audit_Mismatch(f'{phase}/{label} native run0 box origin differs from registered source')
                    for j in range(3):
                        source_h_err = source_geom['H_error'][i][j]
                        native_h_err = native['H_error'][i][j]
                        if abs(native['H'][i][j] - source_H[i][j]) > native_h_err + source_h_err + 16 * audit_sys.float_info.epsilon * (abs(native['H'][i][j]) + abs(source_H[i][j]) + 1):
                            raise audit_Mismatch(f'{phase}/{label} native run0 cell differs from registered source')
                if [(a['id'], a['type']) for a in source_rows] != [(a['id'], a['type']) for a in native['atoms']]:
                    raise audit_Mismatch(f'{phase}/{label} run0 dump IDs/types differ from registered input data')
                for (sr, nr) in zip(source_rows, native['atoms']):
                    if sr['image'] != nr['image']:
                        raise audit_Mismatch(f'{phase}/{label} native run0 image flags differ from source data')
                    for j in range(3):
                        err = sr['xyz_error'][j] + audit__significant_print_half_quantum(nr['tokens']['xyz'][j], 16) + 16 * audit_sys.float_info.epsilon * (abs(sr['xyz'][j]) + abs(nr['xyz'][j]) + 1)
                        if abs(sr['xyz'][j] - nr['xyz'][j]) > err:
                            raise audit_Mismatch(f'{phase}/{label} native run0 position differs from source data')
                        verr = sr['vel_error'][j] + audit__significant_print_half_quantum(nr['tokens']['vel'][j], 16) + 16 * audit_sys.float_info.epsilon * (abs(nr['vel'][j]) + 1)
                        if abs(nr['vel'][j]) > verr:
                            raise audit_Mismatch(f'{phase}/{label} run0 unexpectedly has nonzero source-free velocity')
                parsed[phase, label] = {'pe': pe, 'native': native, 'source': data, 'n': n, 'dump_sha': audit_sha(dump_path), 'log_sha': audit_sha(log)}
        for phase in ('alpha_quartz', 'coesite'):
            n = 576 if phase == 'alpha_quartz' else 384
            for (comparison, base_label, target_label) in (('raw_to_gauge', 'raw', 'gauge'), ('base_to_size', 'gauge', 'size')):
                proof_comparison = phases[phase]['comparisons'][comparison]
                map_path = local_ref(proof_comparison.get('force_site_map'), 'site map')
                map_doc = audit__load_json(map_path)
                site_pairs = map_doc.get('site_pairs')
                if not isinstance(site_pairs, list):
                    raise audit_UnknownEvidence(f'{phase}/{comparison} site map has no raw pair list')
                pairs = sorted(site_pairs, key=lambda x: int(x.get('target_atom_id', 0)))
                mapping = [int(x['base_atom_id']) for x in pairs]
                expected_mapping = list(range(1, n + 1)) if comparison == 'raw_to_gauge' else [(i - 1) % n + 1 for i in range(1, 2 * n + 1)]
                if mapping != expected_mapping:
                    raise audit_Mismatch(f'{phase}/{comparison} site map differs from the frozen source mapping')
                base = parsed[phase, base_label]
                target = parsed[phase, target_label]
                per_atom = target['n'] == 2 * base['n']
                delta = target['pe'] / target['n'] - base['pe'] / base['n'] if per_atom else target['pe'] - base['pe']
                pe_limit = max(pe_abs, pe_rel * abs(base['pe'])) / (base['n'] if per_atom else 1)
                max_ratio = 0.0
                for (tid, bid) in enumerate(mapping):
                    fb = base['native']['atoms'][bid - 1]['force']
                    ft = target['native']['atoms'][tid]['force']
                    err = audit_math.sqrt(sum(((x - y) ** 2 for (x, y) in zip(ft, fb))))
                    scale = max(audit_math.sqrt(sum((x * x for x in fb))), audit_math.sqrt(sum((x * x for x in ft))))
                    limit = max(force_abs, force_rel * scale)
                    max_ratio = max(max_ratio, err / limit if limit else 0.0 if err == 0 else audit_math.inf)
                if abs(delta) > pe_limit or max_ratio > 1.0:
                    raise audit_Mismatch(f'{phase}/{comparison} independently recomputed PE/force comparison exceeds frozen numeric criteria')
                if proof_comparison.get('status') != 'PASS_NUMERICAL_REGRESSION_ONLY':
                    raise audit_Mismatch(f'{phase}/{comparison} producer comparison status is not PASS')
                for (side, label) in (('base_observation', base_label), ('target_observation', target_label)):
                    obs = proof_comparison.get(side)
                    raw = parsed[phase, label]
                    call = calls[next((i for (i, (_, doc)) in binaries.items() if doc.get('phase') == phase and doc.get('run0_label') == label))]
                    if not isinstance(obs, dict) or obs.get('observation_sha256') != call.get('observation_sha256') or obs.get('force_dump_sha256') != raw['dump_sha'] or (obs.get('observation_path') != call.get('observation_path')) or (obs.get('force_dump_path') != call.get('force_dump_path')):
                        raise audit_Mismatch(f'{phase}/{comparison} summary observations do not bind the replayed raw call')
                if not audit_math.isclose(float(proof_comparison.get('base', {}).get('pe_eV', audit_math.nan)), base['pe'], rel_tol=1e-12, abs_tol=1e-15):
                    raise audit_Mismatch(f'{phase}/{comparison} base energy summary differs from raw observation')
                if not audit_math.isclose(float(proof_comparison.get('target', {}).get('pe_eV', audit_math.nan)), target['pe'], rel_tol=1e-12, abs_tol=1e-15):
                    raise audit_Mismatch(f'{phase}/{comparison} target energy summary differs from raw observation')
                if not audit_math.isclose(float(proof_comparison.get('pe_delta_eV_per_atom', audit_math.nan)), delta, rel_tol=1e-12, abs_tol=1e-15):
                    raise audit_Mismatch(f'{phase}/{comparison} producer PE summary differs from raw recomputation')

    def audit__load_json(path: audit_Path) -> dict:
        try:
            doc = audit_json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise audit_Mismatch(f'cannot parse JSON {path}: {exc}') from exc
        if not isinstance(doc, dict):
            raise audit_Mismatch(f'JSON root must be an object: {path}')
        return doc

    def audit__safe_path(root: audit_Path, value: audit_Any, *, external_root: audit_Path | None=None) -> audit_Path:
        if not isinstance(value, str) or not value:
            raise audit_UnknownEvidence('artifact path missing')
        path = audit_Path(value)
        if path.is_absolute() or '..' in path.parts:
            raise audit_Mismatch(f'unsafe artifact path: {value}')
        candidate = (root / path).resolve()
        allowed = [root.resolve()]
        if external_root is not None:
            allowed.append(external_root.resolve())
        if not any((candidate == base or base in candidate.parents for base in allowed)):
            raise audit_Mismatch(f'artifact escapes evidence root: {value}')
        if not candidate.is_file():
            raise audit_UnknownEvidence(f'artifact missing: {value}')
        return candidate

    def audit__file_ref(root: audit_Path, ref: audit_Any, *, external_root: audit_Path | None=None, exact_sha: str | None=None) -> audit_Path:
        if isinstance(ref, str):
            raise audit_UnknownEvidence('file reference requires path and sha256')
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
            raise audit_UnknownEvidence('file reference requires path and sha256')
        expected = exact_sha or ref.get('sha256')
        if not isinstance(expected, str) or not audit_re.fullmatch('[0-9a-f]{64}', expected):
            raise audit_UnknownEvidence('file reference SHA-256 missing or malformed')
        path = audit__safe_path(root, ref['path'], external_root=external_root)
        if audit_sha(path) != expected:
            raise audit_Mismatch(f"SHA-256 mismatch: {ref['path']}")
        if 'bytes' in ref and int(ref['bytes']) != path.stat().st_size:
            raise audit_Mismatch(f"byte length mismatch: {ref['path']}")
        return path

    def audit__ledger_file_ref(outputs: audit_Path, ref: audit_Any, reference_root: audit_Path | None=None) -> audit_Path:
        """Resolve a ledger artifact only in its declared namespace.

        Author-reference artifacts stay outside candidate outputs. Their root is the
        directory containing the explicitly supplied private reference descriptor;
        absolute paths and parent traversal remain forbidden.
        """
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('ledger artifact reference is malformed')
        namespace = ref.get('namespace', ref.get('root', 'candidate'))
        clean = {k: v for (k, v) in ref.items() if k not in ('namespace', 'root')}
        if namespace in ('candidate', 'candidate_outputs'):
            raw = audit_Path(str(clean.get('path', '')))
            if raw.is_absolute():
                base = outputs.resolve()
                resolved = raw.resolve()
                if resolved != base and base not in resolved.parents:
                    raise audit_Mismatch('absolute candidate artifact path escapes candidate outputs')
                clean['path'] = str(resolved.relative_to(base))
            return audit__file_ref(outputs, clean)
        if namespace in ('author_reference', 'private_reference'):
            if reference_root is None:
                raise audit_UnknownEvidence('author-reference artifact supplied without sealed reference descriptor')
            raw = audit_Path(str(clean.get('path', '')))
            if raw.is_absolute():
                base = reference_root.resolve()
                resolved = raw.resolve()
                if resolved != base and base not in resolved.parents:
                    raise audit_Mismatch('absolute author-reference artifact path escapes sealed reference root')
                clean['path'] = str(resolved.relative_to(base))
            return audit__file_ref(reference_root, clean, external_root=reference_root)
        raise audit_Mismatch(f'unsupported ledger artifact namespace: {namespace}')

    def audit_load_current_plan(path: audit_Path=audit_DEFAULT_PLAN) -> dict:
        doc = audit__load_json(path)
        plan = doc.get('current_v2_full_campaign')
        if not isinstance(plan, dict) or plan.get('schema') != 'case06-single-state-v2-full-campaign-plan/v1':
            raise audit_UnknownEvidence('current_v2_full_campaign plan is missing or unsupported')
        if plan.get('status') != 'PLANNED_NOT_ACTIVATED_NO_HPC_SUBMISSION':
            raise audit_UnknownEvidence('current v2 plan status is not the frozen v1 planning state')
        return plan

    def audit_verify_output_manifest(outputs: audit_Path, manifest_path: audit_Path, checks: list[dict]) -> dict[str, audit_Path]:
        """Hash every delivered file; summary and manifest are excluded to avoid recursion."""
        try:
            doc = audit__load_json(manifest_path)
            if doc.get('schema') not in ('case08-outputs-manifest/v1', 'case08-outputs-manifest/v2', 'case06-campaign-output-manifest/v1'):
                raise audit_UnknownEvidence('unsupported output inventory schema')
            rows = doc.get('files', doc.get('entries'))
            if isinstance(rows, dict):
                rows = [{'path': key, **(value if isinstance(value, dict) else {'sha256': value})} for (key, value) in rows.items()]
            if not isinstance(rows, list):
                raise audit_UnknownEvidence('output inventory has no files/entries list')
            observed: dict[str, audit_Path] = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise audit_Mismatch('output inventory row is not an object')
                rel = row.get('path')
                if rel in ('summary.json', 'outputs-manifest.json', manifest_path.name):
                    raise audit_Mismatch(f'self-referencing output inventory entry: {rel}')
                path = audit__safe_path(outputs, rel)
                digest = row.get('sha256')
                if digest != audit_sha(path):
                    raise audit_Mismatch(f'output inventory hash mismatch: {rel}')
                nbytes = row.get('bytes', row.get('size_bytes'))
                if nbytes is not None and int(nbytes) != path.stat().st_size:
                    raise audit_Mismatch(f'output inventory size mismatch: {rel}')
                if rel in observed:
                    raise audit_Mismatch(f'duplicate output inventory path: {rel}')
                observed[rel] = path
            actual = {p.relative_to(outputs).as_posix() for p in outputs.rglob('*') if p.is_file() and p.resolve() != manifest_path.resolve() and (p.name not in ('summary-hash-audit.json', 'campaign-evidence.json'))}
            listed = set(observed)
            if 'summary.json' in actual:
                actual.remove('summary.json')
            if actual != listed:
                (missing, extra) = (sorted(actual - listed), sorted(listed - actual))
                raise audit_Mismatch(f'output inventory membership mismatch; unlisted={missing[:4]}, absent={extra[:4]}')
            audit_add(checks, 'v2_output_file_inventory', 'PASS', f'{len(observed)} files rehashed; summary self-hash excluded')
            return observed
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_output_file_inventory', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_output_file_inventory', 'FAIL', str(exc))
        return {}

    def audit__ti_spring_function2(u: float) -> float:
        return (70 * u ** 4 - 315 * u ** 3 + 540 * u ** 2 - 420 * u + 126) * u ** 5

    def audit__significant_print_half_quantum(token: str, significant: int) -> float:
        """Half-bin for native `%g` serialization; zero is an exact printed zero."""
        try:
            d = audit_Decimal(token)
        except Exception as exc:
            raise audit_Mismatch('malformed native floating token') from exc
        if not d.is_finite():
            raise audit_Mismatch('nonfinite native floating token')
        if d.is_zero():
            return 0.0
        exponent = d.copy_abs().adjusted() - (significant - 1)
        return float(audit_Decimal(5).scaleb(exponent - 1))

    def audit_parse_lambda(path: audit_Path, atoms: int, direction: str, expected_switch_steps: int | None=None) -> float:
        text = path.read_text(encoding='utf-8')
        header = next((line for line in text.splitlines() if line.lstrip().startswith('#')), '')
        if not all((token in header for token in ('dU_sys', 'dU_ref1', 'dU_ref2', 'lambda', '[eV/atom]'))):
            raise audit_Mismatch('lambda curve lacks expected source column/unit header')
        rows = []
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            try:
                row = [float(v) for v in s.split()]
            except ValueError as exc:
                raise audit_Mismatch('lambda curve has malformed numeric row') from exc
            if len(row) != 4 or not all((audit_math.isfinite(v) for v in row)):
                raise audit_Mismatch('lambda curve has short/nonfinite row')
            rows.append((row, s.split()))
        if expected_switch_steps is None:
            raise audit_UnknownEvidence('lambda grid requires a source-replayed native switch length')
        if len(rows) != expected_switch_steps + 1:
            raise audit_Mismatch(f'lambda curve has {len(rows)} rows; pinned fix print 1 requires N+1={expected_switch_steps + 1}')
        lam = [r[0][-1] for r in rows]
        if direction == 'forward':
            if abs(lam[0]) > 1e-10 or abs(lam[-1] - 1.0) > 1e-08 or any((b < a - 1e-12 for (a, b) in zip(lam, lam[1:]))):
                raise audit_Mismatch('forward lambda endpoints/order are not 0 to 1')
        elif direction == 'backward':
            if abs(lam[0] - 1.0) > 1e-08 or abs(lam[-1]) > 1e-10 or any((b > a + 1e-12 for (a, b) in zip(lam, lam[1:]))):
                raise audit_Mismatch('backward lambda endpoints/order are not 1 to 0')
        else:
            raise audit_Mismatch('unknown direction')
        eps = audit_sys.float_info.epsilon
        for (i, (row, tokens)) in enumerate(rows):
            observed = row[-1]
            token = tokens[-1]
            u = i / expected_switch_steps
            s = audit__ti_spring_function2(u)
            term_abs = 70 * abs(u ** 9) + 315 * abs(u ** 8) + 540 * abs(u ** 7) + 420 * abs(u ** 6) + 126 * abs(u ** 5)
            poly_err = 16 * eps / (1 - 16 * eps) * term_abs
            expected = s
            if direction == 'backward':
                expected = 1.0 - s
                poly_err += eps * (1.0 + abs(s))
            bound = audit__significant_print_half_quantum(token, 15) + poly_err + 2 * audit_math.ulp(observed)
            if abs(observed - expected) > bound:
                raise audit_Mismatch(f'lambda sample {i} differs from pinned function-2 schedule')
        numeric_rows = [r[0] for r in rows]
        duds = [row[0] - (row[1] + row[2]) / atoms for row in numeric_rows]
        return sum(((a + b) * 0.5 * (right[-1] - left[-1]) for (left, right, a, b) in zip(numeric_rows, numeric_rows[1:], duds, duds[1:])))

    def audit_parse_lammps_cell(path: audit_Path) -> tuple[int, float, dict[int, float], dict[int, int]]:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        n = None
        bounds = {}
        tilt = (0.0, 0.0, 0.0)
        masses = {}
        counts = {}
        for (i, line) in enumerate(lines):
            s = line.strip()
            m = audit_re.match('^(\\d+) atoms$', s)
            if m:
                n = int(m.group(1))
            for axis in ('x', 'y', 'z'):
                m = audit_re.match(f'^([-+0-9.eE]+)\\s+([-+0-9.eE]+)\\s+{axis}lo\\s+{axis}hi$', s)
                if m:
                    bounds[axis] = tuple(map(float, m.groups()))
            m = audit_re.match('^([-+0-9.eE]+)\\s+([-+0-9.eE]+)\\s+([-+0-9.eE]+)\\s+xy\\s+xz\\s+yz$', s)
            if m:
                tilt = tuple(map(float, m.groups()))
            if s == 'Masses':
                j = i + 1
                while j < len(lines) and (not lines[j].strip()):
                    j += 1
                while j < len(lines) and lines[j].strip():
                    c = lines[j].split('#', 1)[0].split()
                    if len(c) >= 2:
                        try:
                            masses[int(c[0])] = float(c[1])
                        except ValueError:
                            pass
                    j += 1
            if s == 'Atoms' or s.startswith('Atoms #'):
                j = i + 1
                while j < len(lines) and (not lines[j].strip()):
                    j += 1
                seen = 0
                while j < len(lines) and (n is None or seen < n):
                    c = lines[j].split()
                    if len(c) >= 3:
                        try:
                            typ = int(c[1])
                            counts[typ] = counts.get(typ, 0) + 1
                            seen += 1
                        except ValueError:
                            break
                    j += 1
        if n is None or set(bounds) != {'x', 'y', 'z'} or (not masses) or (sum(counts.values()) != n):
            raise audit_UnknownEvidence('Einstein endpoint data lacks parseable counts/masses/bounds')
        lx = bounds['x'][1] - bounds['x'][0]
        ly = bounds['y'][1] - bounds['y'][0]
        lz = bounds['z'][1] - bounds['z'][0]
        volume = lx * ly * lz
        if not audit_math.isfinite(volume) or volume <= 0:
            raise audit_Mismatch('Einstein endpoint has nonpositive or nonfinite volume')
        return (n, volume, masses, counts)

    def audit_einstein_reference(path: audit_Path, temp: float, springs: list[float], element_types: dict[str, int], volume_override: float | None=None) -> tuple[int, float, float]:
        (n, volume, masses, counts) = audit_parse_lammps_cell(path)
        if volume_override is not None:
            volume = float(volume_override)
        if len(springs) != 2 or any((not audit_math.isfinite(float(k)) or float(k) <= 0 for k in springs)):
            raise audit_Mismatch('two positive finite O/Si spring constants required')
        if set(element_types) != {'O', 'Si'} or not audit_math.isfinite(temp) or temp <= 0:
            raise audit_Mismatch('invalid temperature or element map')
        for (el, mass) in (('O', 15.999), ('Si', 28.085)):
            typ = int(element_types[el])
            if typ not in masses or abs(masses[typ] - mass) > 1e-08:
                raise audit_Mismatch(f'native masses do not bind {el} to expected type')
        if [float(x) for x in springs] != [2.0, 4.0]:
            raise audit_Mismatch('current v2 requires the frozen supplied O/Si spring constants [2,4] eV/A^2')
        if counts[int(element_types['O'])] != 2 * counts[int(element_types['Si'])] or n != sum(counts.values()):
            raise audit_Mismatch('native cell is not stoichiometric SiO2')
        kB = 1.380649e-23
        ev = 1.602176634e-19
        av = 6.02214076e+23
        h = 6.62607015e-34
        beta = 1.0 / (kB * temp)
        total_mass = 0.0
        terms = []
        com_sum = 0.0
        for (el, k_ev) in zip(('O', 'Si'), springs):
            typ = int(element_types[el])
            count = counts[typ]
            mass = masses[typ] * 0.001 / av
            k = float(k_ev) * ev / 1e-20
            total_mass += mass * count
            terms.append((count, k, mass))
        for (count, k, mass) in terms:
            com_sum += count * (mass / total_mass) ** 2 / k
        fe = sum((count * 1.5 * audit_math.log(beta * beta * k * h * h / (4 * audit_math.pi * audit_math.pi * mass)) for (count, k, mass) in terms)) * (kB * temp / ev / n)
        fcm = kB * temp / ev / n * audit_math.log(volume * 1e-30 * (beta / (2 * audit_math.pi * com_sum)) ** 1.5)
        return (n, volume, fe - fcm)
    audit_NPT_COLUMNS = ('step', 'lx', 'ly', 'lz', 'xy', 'xz', 'yz', 'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz', 'temp')

    def audit_parse_native_npt_table(path: audit_Path, *, cadence: int, first: int, last: int, count: int) -> list[dict[str, float]]:
        """Parse exact 15-column native fix-ave/time rows; reject silent truncation."""
        def parse_rows(table_path: audit_Path) -> list[dict[str, float]]:
            parsed = []
            for (line_no, line) in enumerate(table_path.read_text(encoding='utf-8', errors='strict').splitlines(), 1):
                text = line.strip()
                if not text or text.startswith('#'):
                    continue
                fields = text.split()
                if len(fields) != 15:
                    raise audit_Mismatch(f'{table_path.name}:{line_no}: expected exactly 15 native NPT columns')
                values = [finite(x) for x in fields]
                if any((x is None for x in values)):
                    raise audit_Mismatch(f'{table_path.name}:{line_no}: nonfinite/malformed native NPT value')
                parsed.append(dict(zip(audit_NPT_COLUMNS, values)))
            return parsed

        rows = parse_rows(path)
        if (path.name == 'case06-npt-fullcell-10step.dat' and cadence == 10
                and first == 1010 and last == 11000 and count == 1000):
            alias_path = path.with_name('case06-npt-fullcell-100step.dat')
            alias = parse_rows(alias_path)
            def normalize(values: list[dict[str, float]], *, step_cadence: int, step_first: int,
                          label: str) -> tuple[list[dict[str, float]], dict[str, float] | None]:
                expected = list(range(step_first, last + step_cadence, step_cadence))
                steps = [r['step'] for r in values]
                if steps == expected and len(values) == len(expected):
                    return (values, None)
                boundary_step = step_first - step_cadence
                if steps == [boundary_step] + expected and len(values) == len(expected) + 1:
                    return (values[1:], values[0])
                raise audit_Mismatch(f'{label}: raw NPT grid differs from the exact cadence, with at most one initial boundary row')
            rows, dense_boundary = normalize(rows, step_cadence=10, step_first=1010,
                                             label=path.name)
            alias, alias_boundary = normalize(alias, step_cadence=100, step_first=1100,
                                               label=alias_path.name)
            if (dense_boundary is None) != (alias_boundary is None):
                raise audit_Mismatch('dense NPT and 100-step alias disagree on the initial boundary row')
            if dense_boundary is not None and any((abs(dense_boundary[k] - alias_boundary[k]) > 1e-08
                                                   for k in audit_NPT_COLUMNS)):
                raise audit_Mismatch('dense NPT and 100-step alias initial boundary rows disagree')
            dense_by_step = {r['step']: r for r in rows}
            for alias_row in alias:
                dense_row = dense_by_step.get(alias_row['step'])
                if dense_row is None or any((abs(alias_row[k] - dense_row[k]) > 1e-08
                                             for k in audit_NPT_COLUMNS)):
                    raise audit_Mismatch('100-step alias disagrees rowwise with dense NPT primary')
        steps = [r['step'] for r in rows]
        if len(rows) != count or steps != [first + i * cadence for i in range(count)] or steps[-1] != last:
            raise audit_Mismatch(f'{path.name}: raw NPT grid differs from {count} rows {first}..{last}/{cadence}')
        if any((min((r[k] for k in ('lx', 'ly', 'lz'))) <= 0 for r in rows)):
            raise audit_Mismatch(f'{path.name}: nonpositive triclinic diagonal')
        return rows

    def audit__validate_npt_source_ref(root: audit_Path, ref: dict, source: dict, *, cadence: int, expected_rows: int, expected_start: int, expected_end: int, invocation_index: dict | None=None) -> tuple[audit_Path, list[dict[str, float]]]:
        path = audit__file_ref(root, ref)
        if not isinstance(source, dict) or not source.get('invocation_id') or source.get('run_index') is None:
            raise audit_UnknownEvidence('native NPT table lacks global invocation/run-index binding')
        if int(source.get('run_index')) < 0:
            raise audit_Mismatch('native NPT source has negative run index')
        if invocation_index is not None:
            inv = invocation_index.get(str(source['invocation_id']))
            if inv is None:
                raise audit_Mismatch('NPT source invocation is absent from global native ledger')
            (binding, _position) = audit__segment_for_native_ref(inv, source)
            if binding.get('segment_kind') not in ('setup_npt', 'setup_npt_primary', 'setup_npt_dense'):
                raise audit_Mismatch('NPT table source is not emitted by a native setup NPT segment')
            outputs = inv.get('native_outputs', inv.get('outputs', {}))
            if isinstance(outputs, list):
                out = next((x for x in outputs if isinstance(x, dict) and x.get('path') == ref.get('path')), None)
            else:
                out = outputs.get(path.name) if isinstance(outputs, dict) else None
            if not isinstance(out, dict) or out.get('path') != ref.get('path') or out.get('sha256') != ref.get('sha256'):
                raise audit_UnknownEvidence('NPT raw table is not listed as an output of its source-bound native invocation')
        rows = audit_parse_native_npt_table(path, cadence=cadence, first=expected_start, last=expected_end, count=expected_rows)
        return (path, rows)

    def audit__validate_lambda_native_binding(outputs: audit_Path, record: dict, ledger: dict, trace_path: audit_Path, expected_steps: int, reference_root: audit_Path | None=None) -> None:
        ref = record.get('switch_source_invocation')
        run_index = record.get('switch_run_index')
        if not isinstance(ref, dict) or not ref.get('invocation_id') or run_index is None:
            raise audit_UnknownEvidence('lambda curve lacks explicit native switch invocation/run-index binding')
        iid = str(ref['invocation_id'])
        call = ledger.get('invocations', {}).get(iid)
        if not isinstance(call, dict):
            raise audit_Mismatch('lambda switch invocation is absent from native ledger')
        try:
            (seg, position) = audit__segment_for_native_ref(call, {**ref, 'run_index': run_index})
        except Exception as exc:
            raise audit_Mismatch('lambda switch run index is absent from native ledger') from exc
        if seg.get('segment_kind', seg.get('kind')) != 'fe_switch' or int(seg.get('actual_steps', seg.get('planned_steps', -1))) != expected_steps:
            raise audit_Mismatch('lambda source run is not the source-replayed FE switch segment')
        listed = call.get('native_outputs', call.get('outputs', []))
        if isinstance(listed, dict):
            listed = list(listed.values())
        if not any((isinstance(x, dict) and x.get('path') == record.get('lambda_curve', {}).get('path') and (x.get('sha256') == sha(trace_path)) for x in listed)):
            raise audit_UnknownEvidence('lambda curve is not enumerated as output of its switch invocation')
        executed_ref = call.get('executed_input')
        if not isinstance(executed_ref, dict):
            raise audit_UnknownEvidence('lambda switch executed input is not retained')
        executed = audit__ledger_file_ref(outputs, executed_ref, reference_root)
        commands = audit__source_run_steps(executed)
        if position >= len(commands) or commands[position] != expected_steps:
            raise audit_Mismatch('lambda switch run index differs from executed input literal run command')
        lines = [_strip_lammps_comment(line).strip() for line in executed.read_text(encoding='utf-8', errors='strict').splitlines()]
        f4 = [line for line in lines if audit_re.match('^fix\\s+f4\\s+all\\s+print\\s+1\\b', line, audit_re.I) and audit_re.search('\\bfile\\s+' + audit_re.escape(trace_path.name) + '(?:\\s|$)', line)]
        if len(f4) != 1:
            raise audit_Mismatch('executed native input does not bind the lambda output to fix-print-1 source')
        fixline = f4[0]
        if not audit_re.search('^fix\\s+f4\\s+all\\s+print\\s+1\\s+"?\\$\\{dU1\\}\\s+\\$\\{dU2\\}\\s+\\$\\{dU3\\}\\s+\\$\\{lambda\\}"?', fixline, audit_re.I):
            raise audit_Mismatch('native fix-print columns are not the pinned system/reference/lambda variables')
        if any((fixline.count(f'${{{name}}}') != 1 for name in ('dU1', 'dU2', 'dU3', 'lambda'))):
            raise audit_Mismatch('native fix-print variable inventory is incomplete or duplicated')
        expected_title = '# dU_sys[eV/atom] dU_ref1[eV/atom] dU_ref2[eV/atom] lambda'
        if expected_title not in fixline:
            raise audit_Mismatch('native fix-print title does not bind the expected energy units/column order')
        variables = {}
        for line in lines:
            vm = audit_re.fullmatch('variable\\s+(dU[123]|lambda)\\s+equal\\s+(.+)', line, audit_re.I)
            if vm:
                (name, expr) = vm.groups()
                name = name.lower()
                if name in variables:
                    raise audit_Mismatch('duplicate native lambda energy variable definition')
                variables[name] = audit_re.sub('\\s+', '', expr).lower()
        if variables != {'du1': 'pe/atoms', 'du2': 'f_ff1', 'du3': 'f_ff2', 'lambda': 'f_ff1[1]'}:
            raise audit_Mismatch('native dU variables differ from pinned Calphy: raw total f_ff1/f_ff2 and system PE per atom')
        springs = {}
        for line in lines:
            m = audit_re.fullmatch('fix\\s+(ff1|ff2)\\s+(g1|g2)\\s+ti/spring\\s+(\\S+)\\s+(\\d+)\\s+(\\d+)\\s+function\\s+(\\d+)', line, audit_re.I)
            if m:
                (fixid, group, k, nswitch, nwarm, func) = m.groups()
                key = fixid.lower()
                if key in springs:
                    raise audit_Mismatch('duplicate ti/spring fix ID in executed switch input')
                springs[key] = (group.lower(), audit_finite(k), int(nswitch), int(nwarm), int(func))
        if springs != {'ff1': ('g1', 2.0, expected_steps, 1000, 2), 'ff2': ('g2', 4.0, expected_steps, 1000, 2)}:
            raise audit_Mismatch('executed native input must bind ff1/g1 k=2 and ff2/g2 k=4, function 2, exact switch and warm steps')
        groups = {}
        for line in lines:
            m = audit_re.fullmatch('group\\s+(g1|g2)\\s+type\\s+(\\d+)', line, audit_re.I)
            if m:
                key = m.group(1).lower()
                if key in groups:
                    raise audit_Mismatch('duplicate Einstein type group definition')
                groups[key] = int(m.group(2))
        if groups != {'g1': 1, 'g2': 2}:
            raise audit_Mismatch('Einstein spring groups must map g1→O/type1 and g2→Si/type2')

    def audit_reconstruct_direction(root: audit_Path, record: dict, source_root: audit_Path | None=None, ledger: dict | None=None) -> dict:
        """Recompute one direction G from hashed raw TI, native cell, H and input data."""
        if record.get('phase') not in audit_PHASE_ATOMS or record.get('direction') not in ('forward', 'backward'):
            raise audit_Mismatch('direction has invalid phase/direction')
        role = record.get('role')
        if role not in audit_ROLE_MAP.values():
            raise audit_Mismatch('direction role is not a frozen v2 role')
        if audit_finite(record.get('T_K')) != 600.0 or audit_finite(record.get('P_bar')) != 20000.0:
            raise audit_Mismatch('direction is outside current 600 K/20 kbar state')
        n_expected = audit_PHASE_ATOMS[record['phase']] * (2 if record.get('role') == 'adaptive_size' else 1)
        if int(record.get('atoms', record.get('cell_atoms', -1))) != n_expected:
            raise audit_Mismatch('direction atom count differs from current phase')
        refroot = source_root or root
        lambda_path = audit__file_ref(refroot, record.get('lambda_curve'))
        cell_path = audit__file_ref(refroot, record.get('einstein_endpoint'))
        mean_ref = record.get('mean_h')
        if not isinstance(mean_ref, dict):
            raise audit_UnknownEvidence('source-derived full-H mean cell is missing')
        mean_path = audit__file_ref(refroot, mean_ref)
        with mean_path.open(newline='', encoding='utf-8') as f:
            rows = list(audit_csv.DictReader(f))
        if not rows:
            raise audit_UnknownEvidence('mean-H source has no data rows')
        hkeys = ('lx_A', 'ly_A', 'lz_A', 'xy_A', 'xz_A', 'yz_A')
        if any((not all((k in row for k in hkeys)) for row in rows)):
            raise audit_UnknownEvidence('mean-H source lacks labeled full triclinic matrix fields')
        start = audit_finite(record.get('npt_start_step'))
        discard = audit_finite(record.get('discard_steps'))
        if start != 1000.0 or discard != 1000.0:
            raise audit_Mismatch('current v2 setup requires the preregistered 1k ramp/10k NPT, discard first 1k')
        if 'step' not in rows[0]:
            raise audit_UnknownEvidence('mean-H source has no native step column')
        retained = []
        for row in rows:
            step = audit_finite(row.get('step'))
            if step is None:
                raise audit_Mismatch('mean-H source has nonnumeric step')
            if step > start + discard:
                retained.append(row)
        if len(retained) != 900:
            raise audit_UnknownEvidence(f'current-v2 mean-H retained window needs 900 dense-primary rows; found {len(retained)}')
        steps = [audit_finite(r.get('step')) for r in retained]
        if steps[0] != 2010.0 or steps[-1] != 11000.0 or any((b - a != 10.0 for (a, b) in zip(steps, steps[1:]))):
            raise audit_Mismatch('mean-H rows are not the exact current-v2 dense 2010..11000/10 retained window')
        dense_ref = record.get('mean_h_native_source')
        if not isinstance(dense_ref, dict):
            raise audit_UnknownEvidence('mean-H CSV lacks an independently hash-bound native dense-primary source')
        dense_path = audit__file_ref(refroot, dense_ref)
        source_invocation = record.get('mean_h_source_invocation')
        if not isinstance(source_invocation, dict) or not source_invocation.get('invocation_id') or source_invocation.get('run_index') is None:
            raise audit_UnknownEvidence('mean-H dense-primary source is not bound to a native invocation/run index')
        audit__validate_npt_source_ref(refroot, dense_ref, source_invocation, cadence=10, expected_rows=1000, expected_start=1010, expected_end=11000)
        mean_native_rows = audit_parse_native_npt_table(dense_path, cadence=10, first=1010, last=11000, count=1000)
        native_retained = [r for r in mean_native_rows if r['step'] > 2000]
        if [audit_finite(r.get('step')) for r in retained] != [r['step'] for r in native_retained]:
            raise audit_Mismatch('mean-H CSV retained rows do not match native dense-primary source')
        values = [[audit_finite(row[k]) for k in hkeys] for row in retained]
        native_values = [[r[k] for k in NPT_COLUMNS[1:7]] for r in native_retained]
        if any((v is None for row in values for v in row)):
            raise audit_Mismatch('mean-H source contains nonfinite values')
        if len(values) != len(native_values) or any((abs(values[i][j] - native_values[i][j]) > 1e-08 for i in range(len(values)) for j in range(6))):
            raise audit_Mismatch('mean-H CSV values are not a rowwise reproduction of native dense-primary H observations')
        hvals = [sum((row[i] for row in values)) / len(values) for i in range(len(hkeys))]
        hm_ref = record.get('mean_cell_matrix_A')
        if not isinstance(hm_ref, list) or len(hm_ref) != 3:
            raise audit_UnknownEvidence('direction does not expose recomputed mean-cell matrix')
        expected_h = [[hvals[0], 0.0, 0.0], [hvals[3], hvals[1], 0.0], [hvals[4], hvals[5], hvals[2]]]
        try:
            if any((abs(float(hm_ref[i][j]) - expected_h[i][j]) > 1e-08 for i in range(3) for j in range(3))):
                raise audit_Mismatch('declared mean-H differs from raw source rows')
        except (TypeError, IndexError, ValueError) as exc:
            if isinstance(exc, audit_Mismatch):
                raise
            raise audit_Mismatch('malformed mean-H matrix') from exc
        total_volume = abs(hvals[0] * hvals[1] * hvals[2])
        if total_volume <= 0 or not audit_math.isfinite(total_volume):
            raise audit_Mismatch('invalid mean-H determinant')
        springs = record.get('spring_constants_eV_per_A2')
        element_types = record.get('element_to_type')
        if not isinstance(element_types, dict):
            raise audit_UnknownEvidence('native element/type mapping missing')
        (n, vol, gref) = audit_einstein_reference(cell_path, 600.0, springs, element_types, volume_override=total_volume)
        if n != n_expected:
            raise audit_Mismatch('Einstein endpoint atom count differs from phase')
        endpoint = audit__geom_data(cell_path)
        if endpoint['n'] != n_expected or set(endpoint['types']) != set(element_types.values()):
            raise audit_Mismatch('Einstein endpoint ID/type inventory differs from current phase mapping')
        for i in range(3):
            for j in range(3):
                if abs(endpoint['H'][i][j] - expected_h[i][j]) > endpoint['H_error'][i][j] + 1e-08:
                    raise audit_Mismatch('Einstein endpoint full triclinic H differs from source-derived mean-H cell')
        if any((abs(v) > 1e-08 for v in endpoint['origin'])):
            raise audit_Mismatch('Einstein endpoint origin differs from the prepared zero-origin cell')
        switch_steps = audit_finite(record.get('switch_steps'))
        if switch_steps is None or int(switch_steps) not in (20000, 40000):
            raise audit_UnknownEvidence('direction lacks source-replayed 20k/40k native switch length')
        if ledger is None:
            raise audit_UnknownEvidence('direction reconstruction lacks replayed global native ledger')
        audit__validate_lambda_native_binding(root, record, ledger, lambda_path, int(switch_steps), refroot)
        work = audit_parse_lambda(lambda_path, n, record['direction'], int(switch_steps))
        pv = 20000.0 * (vol / n) / (1.602176634e-19 * 1e+25)
        sign = 1.0 if record['direction'] == 'forward' else -1.0
        g = gref + pv + sign * work
        if not audit_math.isfinite(g):
            raise audit_Mismatch('reconstructed G is nonfinite')
        return {'run_id': str(record.get('run_id')), 'role': role, 'phase': record['phase'], 'direction': record['direction'], 'replicate': str(record.get('replicate')), 'seed': str(record.get('seed')), 'atoms': n, 'work_eV_per_atom': work, 'einstein_reference_eV_per_atom': gref, 'pv_eV_per_atom': pv, 'G_eV_per_atom': g, 'lambda_sha256': audit_sha(lambda_path), 'einstein_sha256': audit_sha(cell_path), 'mean_h_sha256': audit_sha(mean_path), 'mean_volume_A3': total_volume}

    def audit_midpoint_and_hysteresis(values: list[dict]) -> tuple[float, float]:
        by = {(r['phase'], r['direction']): r['G_eV_per_atom'] for r in values}
        required = {(p, d) for p in audit_PHASE_ATOMS for d in ('forward', 'backward')}
        if set(by) != required:
            raise audit_UnknownEvidence('role requires exactly one direction for each phase/direction')
        dg = (by['coesite', 'forward'] + by['coesite', 'backward'] - by['alpha_quartz', 'forward'] - by['alpha_quartz', 'backward']) / 2.0
        h = (abs(by['coesite', 'forward'] - by['coesite', 'backward']) + abs(by['alpha_quartz', 'forward'] - by['alpha_quartz', 'backward'])) / 2.0
        return (dg, h)

    def audit__read_csv(path: audit_Path, expected: list[str]) -> list[dict]:
        with path.open(newline='', encoding='utf-8') as f:
            reader = audit_csv.DictReader(f)
            if reader.fieldnames != expected:
                raise audit_Mismatch(f'CSV header mismatch in {path.name}')
            return list(reader)

    def audit__check_campaign_identity(outputs: audit_Path, evidence: dict, plan: dict, extension_path: audit_Path, checks: list[dict]) -> bool:
        ok = True
        if evidence.get('schema') != 'case06-single-state-v2-campaign-evidence/v1':
            audit_add(checks, 'v2_campaign_schema', 'UNKNOWN', 'campaign evidence schema missing/unsupported')
            return False
        if evidence.get('protocol') != 'single-state-v2' or not evidence.get('campaign_id'):
            audit_add(checks, 'v2_campaign_identity', 'FAIL', 'missing campaign id or protocol mismatch')
            ok = False
        h = evidence.get('hamiltonian', {})
        if h.get('sha256') != audit_PUBLIC_YACE:
            audit_add(checks, 'v2_hamiltonian', 'FAIL', 'campaign YACE does not match public SHA')
            ok = False
        else:
            try:
                if not isinstance(h, dict) or not isinstance(h.get('path'), str):
                    raise audit_UnknownEvidence('campaign evidence lacks the delivered YACE file reference')
                hp = audit__file_ref(outputs, h)
                if audit_sha(hp) != audit_PUBLIC_YACE:
                    raise audit_Mismatch('delivered campaign YACE bytes differ from the frozen public SHA')
                audit_add(checks, 'v2_hamiltonian', 'PASS', audit_PUBLIC_YACE)
            except audit_UnknownEvidence as exc:
                audit_add(checks, 'v2_hamiltonian', 'UNKNOWN', str(exc))
                ok = False
            except Exception as exc:
                audit_add(checks, 'v2_hamiltonian', 'FAIL', str(exc))
                ok = False
        if 'software' in evidence:
            if not audit__verify_runtime_source_identity(outputs, evidence, plan, checks):
                ok = False
        else:
            audit_add(checks, 'v2_runtime_source_identity', 'UNKNOWN', 'campaign software provenance is absent')
            ok = False
        contract = evidence.get('contract_sha256')
        contract_path = REPO / 'packages/case-06/output-contract.md'
        if contract != audit_sha(contract_path):
            audit_add(checks, 'v2_contract_binding', 'FAIL', 'campaign evidence is not bound to current output contract')
            ok = False
        else:
            audit_add(checks, 'v2_contract_binding', 'PASS', 'output contract SHA matches')
        try:
            ext = audit__load_json(extension_path)
            ext_sha = audit_sha(extension_path)
            matrix_plan = plan.get('current_v2_full_campaign') if isinstance(plan.get('current_v2_full_campaign'), dict) else plan
            proposal = matrix_plan.get('resource_proposal_not_activated', {}) if isinstance(matrix_plan, dict) else {}
            if proposal.get('resource_receipt_sha256') != ext_sha:
                raise audit_Mismatch('immutable public resource supplement SHA differs from frozen current matrix')
            if ext.get('scope', {}).get('case') != 'case-06' or ext.get('scope', {}).get('T_K') != 600 or ext.get('scope', {}).get('P_bar') != 20000:
                raise audit_Mismatch('resource supplement scope mismatch')
            hist = ext.get('historical', {})
            if hist.get('reset') is not False or hist.get('original_admission') != 'EXHAUSTED_NOT_COMPLETE':
                raise audit_Mismatch('historical 12-hour exhaustion was reset or omitted')
            if ext.get('execution_authorized') is not False or ext.get('prospective', {}).get('activated') is not False:
                raise audit_Mismatch('immutable public supplement was mutated to claim activation')
            active = int(ext['prospective']['active_limit_seconds'])
            new_md = int(ext['prospective']['actual_or_reserved_md_step_limit'])
            if active <= 0 or active > 21600 or new_md <= 0 or (new_md > 600000):
                raise audit_Mismatch('prospective supplement exceeds reviewed 6h/600k ceiling')
            if hist.get('conservative_accounted_seconds') != 43208 or hist.get('actual_md_steps') != 353284:
                raise audit_Mismatch('historical accounting anchor changed')
            audit_add(checks, 'v2_historical_budget_preserved', 'PASS', 'immutable public supplement remains unactivated and the historic 12h remains exhausted')
            resource_ref = evidence.get('resource_receipt')
            if not isinstance(resource_ref, dict):
                audit_add(checks, 'v2_resource_activation', 'UNKNOWN', 'campaign lacks actual hash-bound resource receipt/adoption')
                ok = False
            else:
                resource_path = audit__file_ref(outputs, resource_ref)
                resource = audit__load_json(resource_path)
                prospective = resource.get('prospective', {})
                if resource.get('schema') != 'case06-v2-resource-receipt/v1' or prospective.get('activated') is not True:
                    audit_add(checks, 'v2_resource_activation', 'UNKNOWN', 'actual resource receipt is not an activated execution adoption')
                    ok = False
                else:
                    resource_hist = resource.get('historical', {})
                    resource_seconds = resource_hist.get('conservative_accounted_seconds', resource_hist.get('accounted_seconds'))
                    resource_md = resource_hist.get('actual_md_steps', resource_hist.get('md_steps'))
                    ext_observed = hist.get('observed_seconds', hist.get('observed_active_seconds'))
                    ext_reserve = hist.get('unlocated_reserve_seconds', hist.get('conservative_unlocated_reserve_seconds'))
                    ext_atomsteps = hist.get('atomsteps', hist.get('actual_atomsteps'))
                    if resource_hist.get('reset') is not False or resource_hist.get('original_admission') != 'EXHAUSTED_NOT_COMPLETE' or resource_seconds != hist.get('conservative_accounted_seconds') or (resource_md != hist.get('actual_md_steps')) or (resource_hist.get('observed_seconds') not in (None, ext_observed)) or (resource_hist.get('unlocated_reserve_seconds') not in (None, ext_reserve)) or (resource_hist.get('atomsteps') not in (None, ext_atomsteps)):
                        raise audit_Mismatch('activated resource receipt changes or resets immutable historical accounting')
                    if resource.get('schema') != 'case06-v2-resource-receipt/v1' or prospective.get('active_limit_seconds') != active or prospective.get('md_limit') != new_md or (int(prospective.get('active_limit_seconds', 0)) > 21600) or (int(prospective.get('md_limit', 0)) > 600000):
                        raise audit_Mismatch('activated receipt exceeds or differs from immutable prospective ceilings')
                    admission_ref = resource.get('execution_admission_ref') or resource.get('execution_admission') or evidence.get('execution_admission') or evidence.get('software', {}).get('execution_admission_ref')
                    if not isinstance(admission_ref, dict):
                        audit_add(checks, 'v2_resource_activation', 'UNKNOWN', 'activated resource receipt lacks source-bound execution-admission reference')
                        ok = False
                    else:
                        admission_path = audit__file_ref(outputs, admission_ref)
                        admission = audit__load_json(admission_path)
                        software_admission = evidence.get('software', {}).get('execution_admission_ref')
                        if not isinstance(software_admission, dict):
                            raise audit_UnknownEvidence('campaign software section lacks the source-bound execution-admission ref')
                        software_admission_path = audit__file_ref(outputs, software_admission)
                        if software_admission_path != admission_path or software_admission.get('sha256') != admission_ref.get('sha256'):
                            raise audit_Mismatch('resource receipt and campaign software bind different execution-admission files')
                        matrix = matrix_plan
                        matrix_sha = audit_source_matrix_sha() if audit_DEFAULT_PLAN.is_file() else None
                        resource_supplement = admission.get('resource_supplement_ref', {})
                        if admission.get('schema') != 'case06-v2-execution-admission/v1' or admission.get('status') != 'ACTIVE':
                            raise audit_Mismatch('execution-admission source is not ACTIVE')
                        if admission.get('campaign_id') != evidence.get('campaign_id') or admission.get('protocol') != 'single-state-v2':
                            raise audit_Mismatch('execution-admission campaign/protocol identity mismatch')
                        admission_matrix_sha = admission.get('currentmatrix_sha256') or admission.get('current_matrix_sha256')
                        if matrix_sha is None or admission_matrix_sha != matrix_sha:
                            raise audit_Mismatch('execution-admission does not bind the current matrix SHA')
                        if resource_supplement.get('sha256') != ext_sha:
                            raise audit_Mismatch('execution-admission does not bind the immutable public supplement SHA')
                        if admission.get('historical', {}).get('reset') is not False or admission.get('historical', {}).get('accounted_seconds') != 43208:
                            raise audit_Mismatch('execution-admission resets or changes exhausted historical accounting')
                        required_admission_refs = ('payload_manifest_ref', 'source_review_ref', 'verifier_implementation_review_ref', 'reference_calibration_prereg_review_ref', 'resource_supplement_ref')
                        review_keys = {'payload_manifest_ref', 'source_review_ref', 'verifier_implementation_review_ref', 'reference_calibration_prereg_review_ref'}
                        for key in required_admission_refs:
                            item = admission.get(key)
                            if not isinstance(item, dict) or not audit_re.fullmatch('[0-9a-f]{64}', str(item.get('sha256', ''))):
                                raise audit_Mismatch(f'execution-admission source reference is absent/malformed: {key}')
                            if key != 'resource_supplement_ref':
                                rel = audit_Path(str(item.get('path', '')))
                                if rel.is_absolute() or '..' in rel.parts:
                                    raise audit_Mismatch(f'unsafe admission bundle source path: {key}')
                                p = (admission_path.parent / rel).resolve()
                                if admission_path.parent.resolve() not in p.parents or not p.is_file():
                                    raise audit_UnknownEvidence(f'admission bundle source is missing/escapes its bundle: {key}')
                                if audit_sha(p) != item['sha256']:
                                    raise audit_Mismatch(f'execution-admission source hash mismatch: {key}')
                                if key in review_keys - {'payload_manifest_ref'}:
                                    review = audit__load_json(p)
                                    review_status = review.get('status', review.get('verdict'))
                                    if review_status not in ('PASS', 'PASS_STATIC_SOURCE_ORDER_ONLY', 'PASS_STATIC_SOURCE_ORDER_AND_STRICT_ZERO_MD_STUB_ONLY', 'PASS_STATIC_SOURCE_ORDER_ONLY_NO_NATIVE_SCIENCE', 'PASS_SOURCE_INVENTORY'):
                                        raise audit_Mismatch(f'execution-admission referenced review is not an accepted PASS: {key}')
                            elif item.get('sha256') != ext_sha:
                                raise audit_Mismatch('execution-admission resource supplement ref SHA mismatch')
                        if any((admission.get(k) != 'PASS' for k in ('full_verifier_review', 'reference_calibration_review', 'payload_job_plan_review'))):
                            raise audit_Mismatch('execution-admission lacks required independent review PASS fields')
                        audit_add(checks, 'v2_resource_activation', 'PASS', 'activated campaign resource receipt independently binds exact execution admission, current matrix and immutable supplement')
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_resource_activation', 'UNKNOWN', str(exc))
            ok = False
        except Exception as exc:
            audit_add(checks, 'v2_resource_activation', 'FAIL', str(exc))
            ok = False
        return ok

    def audit__geom_data(path: audit_Path) -> dict:
        """Read orthogonal/restricted-triclinic atomic LAMMPS data without driver code."""
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        bounds = {}
        bounds_tokens = {}
        tilt = (0.0, 0.0, 0.0)
        tilt_tokens = ('0', '0', '0')
        atoms = []
        inside = False
        for line in lines:
            tokens = line.split()
            if len(tokens) >= 4 and tokens[2:4] == ['xlo', 'xhi']:
                bounds[0] = (float(tokens[0]), float(tokens[1]))
                bounds_tokens[0] = (tokens[0], tokens[1])
            elif len(tokens) >= 4 and tokens[2:4] == ['ylo', 'yhi']:
                bounds[1] = (float(tokens[0]), float(tokens[1]))
                bounds_tokens[1] = (tokens[0], tokens[1])
            elif len(tokens) >= 4 and tokens[2:4] == ['zlo', 'zhi']:
                bounds[2] = (float(tokens[0]), float(tokens[1]))
                bounds_tokens[2] = (tokens[0], tokens[1])
            elif len(tokens) >= 6 and tokens[3:6] == ['xy', 'xz', 'yz']:
                tilt = tuple((float(x) for x in tokens[:3]))
                tilt_tokens = tuple(tokens[:3])
            elif line.strip().split()[:1] == ['Atoms']:
                inside = True
            elif inside and (not line.strip()):
                if atoms:
                    inside = False
            elif inside:
                clean = line.split('#', 1)[0].split()
                if len(clean) >= 5 and clean[0].isdigit():
                    atom_id = int(clean[0])
                    typ = int(clean[1])
                    xyz = tuple((float(x) for x in clean[2:5]))
                    if not all((math.isfinite(x) for x in xyz)):
                        raise audit_Mismatch(f'nonfinite atom coordinate in {path}')
                    atoms.append((atom_id, typ, xyz, tuple(clean[2:5]), tuple((audit__coordinate_round_bound(x, t, 17) for (x, t) in zip(xyz, clean[2:5])))))
        if set(bounds) != {0, 1, 2} or not atoms:
            raise audit_UnknownEvidence(f'cannot parse full cell/atoms from {path}')
        if len({a[0] for a in atoms}) != len(atoms):
            raise audit_Mismatch(f'duplicate atom IDs in {path}')
        lo = tuple((bounds[i][0] for i in range(3)))
        hi = tuple((bounds[i][1] for i in range(3)))
        H = ((hi[0] - lo[0], 0.0, 0.0), (tilt[0], hi[1] - lo[1], 0.0), (tilt[1], tilt[2], hi[2] - lo[2]))
        if any((not math.isfinite(x) for row in H for x in row)) or audit__det3(H) <= 0:
            raise audit_Mismatch(f'invalid full cell in {path}')
        origin_err = tuple((audit__coordinate_round_bound(lo[i], bounds_tokens[i][0], 17) for i in range(3)))
        herr = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        for i in range(3):
            herr[i][i] = audit__coordinate_round_bound(bounds[i][0], bounds_tokens[i][0], 17) + audit__coordinate_round_bound(bounds[i][1], bounds_tokens[i][1], 17)
        herr[1][0] = audit__coordinate_round_bound(tilt[0], tilt_tokens[0], 17)
        herr[2][0] = audit__coordinate_round_bound(tilt[1], tilt_tokens[1], 17)
        herr[2][1] = audit__coordinate_round_bound(tilt[2], tilt_tokens[2], 17)
        return {'origin': lo, 'origin_error': origin_err, 'H': H, 'H_error': herr, 'atoms': atoms, 'n': len(atoms), 'types': {t: sum((a[1] == t for a in atoms)) for t in {a[1] for a in atoms}}}

    def audit__det3(m):
        return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])

    def audit__frac_row(x, h):
        """Solve row-vector x=f@H for restricted triclinic lower-triangular H."""
        z = x[2] / h[2][2]
        y = (x[1] - z * h[2][1]) / h[1][1]
        xx = (x[0] - y * h[1][0] - z * h[2][0]) / h[0][0]
        return (xx, y, z)

    def audit__inverse_tri(h):
        (a, b, c) = (h[0][0], h[1][1], h[2][2])
        xy = h[1][0]
        xz = h[2][0]
        yz = h[2][1]
        return ((1 / a, 0.0, 0.0), (-xy / (a * b), 1 / b, 0.0), ((xy * yz - b * xz) / (a * b * c), -yz / (b * c), 1 / c))

    def audit__matmul3(a, b):
        return [[sum((a[i][k] * b[k][j] for k in range(3))) for j in range(3)] for i in range(3)]

    def audit__rowmul3(v, m):
        return tuple((sum((v[k] * m[k][j] for k in range(3))) for j in range(3)))

    def audit__fractional_error(x, h, xerr):
        matrix = h['H'] if isinstance(h, dict) else h
        inv = audit__inverse_tri(matrix)
        norm = max((sum((abs(v) for v in row)) for row in inv))
        hnorm = max((sum((abs(v) for v in row)) for row in h['H_error'])) if isinstance(h, dict) else 0
        herr = h['H_error'] if isinstance(h, dict) else [[0.0, 0.0, 0.0] for _ in range(3)]
        denom = 1 - norm * hnorm
        if denom <= 0:
            raise audit_UnknownEvidence('cell token intervals do not bound inverse')
        inv_err = [[sum((abs(inv[i][k]) * herr[k][l] * abs(inv[l][j]) for k in range(3) for l in range(3))) / denom for j in range(3)] for i in range(3)]
        gamma = 16 * audit_sys.float_info.epsilon / (1 - 16 * audit_sys.float_info.epsilon)
        f = audit__frac_row(x, h['H'] if isinstance(h, dict) else h)
        err = []
        for j in range(3):
            err.append(sum((xerr[i] * abs(inv[i][j]) for i in range(3))) + sum((abs(x[i]) * inv_err[i][j] for i in range(3))) + gamma * (sum((abs(x[i] * inv[i][j]) for i in range(3))) + 1))
        return (f, tuple(err))

    def audit__coordinate_round_bound(v: float, token: str, significant: int) -> float:
        if not audit_math.isfinite(v):
            raise audit_Mismatch('nonfinite geometry token')
        if v == 0.0:
            return 0.0
        return float(abs(audit_Decimal.from_float(v) - audit_Decimal(token)))

    def audit__parse_run0_force_dump(path: audit_Path, expected_atoms: int) -> dict:
        """Parse exactly one native 0-step state/force frame, without trusting a receipt."""
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        if len(lines) < 9 or lines[0].strip() != 'ITEM: TIMESTEP' or int(lines[1]) != 0:
            raise audit_Mismatch('run0 force dump must start with exactly one step-0 frame')
        if lines[2].strip() != 'ITEM: NUMBER OF ATOMS' or int(lines[3]) != expected_atoms:
            raise audit_Mismatch('run0 force dump atom count differs from the prepared cell')
        bh = lines[4].split()
        if bh[:3] != ['ITEM:', 'BOX', 'BOUNDS']:
            raise audit_Mismatch('run0 dump lacks BOX BOUNDS')
        rows = [lines[i].split() for i in (5, 6, 7)]
        if any((len(x) != 3 for x in rows)):
            raise audit_Mismatch('run0 triclinic box bounds must have exact three-column rows')
        bt = [[finite(x) for x in row] for row in rows]
        if any((v is None for row in bt for v in row)):
            raise audit_Mismatch('run0 dump has nonfinite box bounds')
        (xy, xz, yz) = (bt[0][2], bt[1][2], bt[2][2])
        xlo = bt[0][0] - min(0.0, xy, xz, xy + xz)
        xhi = bt[0][1] - max(0.0, xy, xz, xy + xz)
        ylo = bt[1][0] - min(0.0, yz)
        yhi = bt[1][1] - max(0.0, yz)
        origin = (xlo, ylo, bt[2][0])
        H = ((xhi - xlo, 0.0, 0.0), (xy, yhi - ylo, 0.0), (xz, yz, bt[2][1] - bt[2][0]))
        bq = [[_significant_print_half_quantum(tok, 17) for tok in row] for row in rows]
        origin_error = (bq[0][0] + bq[0][2] + bq[1][2] + 16 * audit_sys.float_info.epsilon * (abs(xlo) + 1), bq[1][0] + bq[2][2] + 8 * audit_sys.float_info.epsilon * (abs(ylo) + 1), bq[2][0])
        H_error = ((bq[0][0] + bq[0][1] + 2 * bq[0][2] + 2 * bq[1][2] + 32 * audit_sys.float_info.epsilon * (abs(H[0][0]) + 1), 0.0, 0.0), (bq[0][2], bq[1][0] + bq[1][1] + 2 * bq[2][2] + 16 * audit_sys.float_info.epsilon * (abs(H[1][1]) + 1), 0.0), (bq[1][2], bq[2][2], bq[2][0] + bq[2][1] + 16 * audit_sys.float_info.epsilon * (abs(H[2][2]) + 1)))
        hdr = lines[8].split()
        if hdr[:2] != ['ITEM:', 'ATOMS']:
            raise audit_Mismatch('run0 dump lacks ATOMS header')
        cols = hdr[2:]
        required = ('id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz')
        if len(cols) != len(required) or set(cols) != set(required):
            raise audit_Mismatch('run0 dump must contain exact 14-field state/force schema')
        ix = {k: cols.index(k) for k in required}
        atoms = []
        if len(lines) != 9 + expected_atoms:
            raise audit_Mismatch('run0 dump must contain exactly one complete frame and no trailing data')
        for line in lines[9:]:
            f = line.split()
            if len(f) != 14:
                raise audit_Mismatch('run0 dump atom row has missing or extra fields')
            try:
                aid = int(f[ix['id']])
                typ = int(f[ix['type']])
                image = tuple((int(f[ix[k]]) for k in ('ix', 'iy', 'iz')))
            except ValueError as exc:
                raise audit_Mismatch('run0 dump ID/type/image must be integer tokens') from exc
            xyz = tuple((finite(f[ix[k]]) for k in ('x', 'y', 'z')))
            vel = tuple((finite(f[ix[k]]) for k in ('vx', 'vy', 'vz')))
            force = tuple((finite(f[ix[k]]) for k in ('fx', 'fy', 'fz')))
            if aid <= 0 or typ not in (1, 2) or any((v is None for v in xyz + vel + force)):
                raise audit_Mismatch('run0 dump has invalid identity or nonfinite state/force')
            atoms.append({'id': aid, 'type': typ, 'image': image, 'xyz': xyz, 'vel': vel, 'force': force, 'tokens': {'xyz': tuple((f[ix[k]] for k in ('x', 'y', 'z'))), 'vel': tuple((f[ix[k]] for k in ('vx', 'vy', 'vz')))}})
        atoms.sort(key=lambda a: a['id'])
        if [a['id'] for a in atoms] != list(range(1, expected_atoms + 1)):
            raise audit_Mismatch('run0 dump IDs are not unique contiguous 1..N')
        if audit__det3(H) <= 0 or not all((math.isfinite(x) for row in H for x in row)):
            raise audit_Mismatch('run0 dump cell is invalid')
        return {'step': 0, 'atoms': atoms, 'H': H, 'H_error': H_error, 'origin': origin, 'origin_error': origin_error, 'box_tokens': rows}

    def audit__parse_run0_snapshot_state(path: audit_Path, expected_atoms: int) -> dict:
        """Parse atom IDs/types/coordinates/images/velocities directly from a data file."""
        geom = audit__geom_data(path)
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        atom_rows = {}
        vel_rows = {}
        section = ''
        for line in lines:
            stripped = line.strip()
            if stripped in ('Atoms', 'Atoms # atomic', 'Velocities'):
                section = 'Atoms' if stripped.startswith('Atoms') else 'Velocities'
                continue
            if not stripped:
                if section and (atom_rows if section == 'Atoms' else vel_rows):
                    section = ''
                continue
            f = line.split('#', 1)[0].split()
            if section == 'Atoms' and len(f) >= 5 and f[0].isdigit():
                aid = int(f[0])
                typ = int(f[1])
                xyz = tuple(f[2:5])
                image = tuple(map(int, f[5:8])) if len(f) >= 8 else (0, 0, 0)
                atom_rows[aid] = (typ, tuple((finite(x) for x in xyz)), xyz, image)
            elif section == 'Velocities' and len(f) >= 4 and f[0].isdigit():
                aid = int(f[0])
                vals = tuple(f[1:4])
                vel_rows[aid] = (tuple((finite(x) for x in vals)), vals)
        ids = set(atom_rows)
        if len(ids) != expected_atoms or ids != set(range(1, expected_atoms + 1)) or set(vel_rows) != ids:
            raise audit_Mismatch('prepared snapshot must contain all unique atom rows and velocities')
        atoms = []
        for aid in sorted(ids):
            (typ, xyz, xtok, image) = atom_rows[aid]
            (vel, vtok) = vel_rows[aid]
            if typ not in (1, 2) or any((v is None for v in xyz + vel)):
                raise audit_Mismatch('prepared snapshot has invalid/nonfinite atom state')
            atoms.append({'id': aid, 'type': typ, 'xyz': xyz, 'xyz_tokens': xtok, 'xyz_error': tuple((_coordinate_round_bound(v, t, 17) for (v, t) in zip(xyz, xtok))), 'image': image, 'vel': vel, 'vel_tokens': vtok, 'vel_error': tuple((_coordinate_round_bound(v, t, 17) for (v, t) in zip(vel, vtok)))})
        return {'geom': geom, 'atoms': atoms}

    def audit__resolve_absolute_inside(root: audit_Path, value: audit_Any) -> audit_Path:
        if not isinstance(value, str) or not value:
            raise audit_UnknownEvidence('native invocation path is missing')
        candidate = audit_Path(value).resolve()
        base = root.resolve()
        if candidate != base and base not in candidate.parents:
            raise audit_Mismatch('native invocation path escapes candidate outputs')
        if not candidate.is_file():
            raise audit_UnknownEvidence(f'native invocation file missing: {candidate}')
        return candidate

    def audit__prepared_run_root(proof_path: audit_Path) -> audit_Path:
        """Derive the relocated role root from the prepared-run0 proof layout.

        `native_zero_md.py` writes nested wrapper references relative to its role
        root, while campaign evidence later relocates the proof and its top-level
        artifacts into candidate/private evidence roots.  The fixed directory
        suffix is therefore the only safe bridge between those namespaces.
        """
        proof_path = proof_path.resolve()
        parent = proof_path.parent
        parts = parent.parts
        matches = [i for (i, p) in enumerate(parts) if p == 'native-run0-snapshot']
        if len(matches) != 1:
            raise audit_UnknownEvidence('prepared run0 proof is outside the registered native-run0-snapshot layout')
        i = matches[0]
        if len(parts) != i + 3 or parts[i + 2] != 'prepared-snapshot':
            raise audit_UnknownEvidence('prepared run0 proof has an unexpected role-root layout')
        root = parent.parents[2]
        if i == 0 or root.parts[-1] != parts[i - 1]:
            raise audit_Mismatch('prepared run0 role root path is inconsistent')
        return root

    def audit__prepared_role_ref(outputs: audit_Path, role_root: audit_Path, ref: audit_Any, reference_root: audit_Path | None) -> audit_Path:
        """Resolve nested refs in either declared namespace or legacy role-root form."""
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
            raise audit_UnknownEvidence('prepared run0 nested receipt reference is malformed')
        if ref.get('namespace') in ('candidate', 'candidate_outputs', 'author_reference', 'private_reference'):
            path = audit__ledger_file_ref(outputs, ref, reference_root)
            try:
                rel = path.parent.relative_to(role_root.resolve()).as_posix()
            except ValueError as exc:
                raise audit_Mismatch('namespaced wrapper receipt is outside the prepared role root') from exc
            if not rel.startswith('native-run0-snapshot/') or not rel.endswith('/prepared-snapshot'):
                raise audit_Mismatch('namespaced wrapper receipt is outside its prepared native-call directory')
            return path
        raw = audit_Path(ref['path'])
        if raw.is_absolute() or '..' in raw.parts:
            raise audit_Mismatch('nested prepared-run0 ref is not a safe role-root relative path')
        candidate = (role_root / raw).resolve()
        base = role_root.resolve()
        if candidate != base and base not in candidate.parents:
            raise audit_Mismatch('nested prepared-run0 ref escapes its role root')
        if not candidate.is_file():
            raise audit_UnknownEvidence(f"role-root artifact missing: {ref['path']}")
        if audit_sha(candidate) != ref.get('sha256'):
            raise audit_Mismatch(f"role-root artifact SHA mismatch: {ref['path']}")
        return candidate

    def audit__prepared_manifest_member(wrapper_dir: audit_Path, role_root: audit_Path, remote_path: audit_Any, expected_sha: audit_Any, expected_relative_parent: str) -> audit_Path:
        """Map a recorded remote absolute input to its collected sibling by basename.

        The remote path is provenance text and normally no longer exists after
        collection.  Its required role-root suffix, sibling location and frozen
        digest identify the local collected copy without attempting to open the
        stale remote absolute path.
        """
        if not isinstance(remote_path, str) or not remote_path:
            raise audit_UnknownEvidence('instrumentation source path is missing')
        remote = audit_Path(remote_path)
        if not remote.is_absolute() or remote.name in ('', '.', '..'):
            raise audit_Mismatch('instrumentation source path must be an absolute recorded remote path')
        suffix = audit_Path(expected_relative_parent)
        if tuple(remote.parent.parts[-len(suffix.parts):]) != suffix.parts:
            raise audit_Mismatch('instrumentation source path is outside the prepared native-call directory')
        local = (wrapper_dir / remote.name).resolve()
        base = role_root.resolve()
        if local.parent != wrapper_dir.resolve() or (local != base and base not in local.parents):
            raise audit_Mismatch('instrumentation source member escapes the prepared native-call directory')
        if not local.is_file():
            raise audit_UnknownEvidence(f'collected instrumentation member missing: {remote.name}')
        if not isinstance(expected_sha, str) or audit_sha(local) != expected_sha:
            raise audit_Mismatch('collected instrumentation member hash differs from its remote source record')
        return local

    def audit__resolve_prepared_potential(outputs: audit_Path, role_root: audit_Path, operand: str, expected_sha: str) -> audit_Path:
        remote = audit_Path(operand)
        if remote.name != 'SiOx_potential.yace' or 'native_inputs' not in remote.parts:
            raise audit_Mismatch('native pair_coeff does not name the registered native_inputs/SiOx_potential.yace')
        candidates = [outputs / 'native_inputs' / remote.name, outputs.parent / 'payload' / 'native_inputs' / remote.name, outputs.parent / 'native_inputs' / remote.name, role_root / 'native_inputs' / remote.name]
        if remote.is_absolute() and remote.is_file():
            resolved = remote.resolve()
            allowed = [outputs.resolve(), outputs.parent.resolve(), role_root.resolve()]
            if any((resolved == base or base in resolved.parents for base in allowed)):
                candidates.insert(0, resolved)
        valid = []
        for path in candidates:
            path = path.resolve()
            if path.is_file() and path not in valid and (audit_sha(path) == expected_sha):
                valid.append(path)
        if not valid:
            raise audit_Mismatch('registered native_inputs potential is unavailable or has the wrong SHA')
        return valid[0]

    def audit__replay_binary_provenance(outputs: audit_Path, normalized_receipt: dict, wrapper_receipt: dict, reference_root: audit_Path | None) -> dict:
        """Bind the invoked executable argv to the job's recorded native binary SHA."""
        ref = normalized_receipt.get('binary_provenance_ref')
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('native invocation lacks a hash-bound binary provenance receipt')
        path = audit__ledger_file_ref(outputs, ref, reference_root)
        doc = audit__load_json(path)
        if doc.get('schema') != 'case06-native-binary-provenance/v1':
            raise audit_UnknownEvidence('unsupported native binary provenance schema')
        matrix = audit_load_current_plan()
        if reference_root is not None and doc.get('role') == 'A':
            provider_path = reference_root / 'provenance' / 'author-provider-identity.json'
            provider_doc = audit__load_json(provider_path)
            expected = provider_doc.get('binary_sha256') if provider_doc.get('schema') == 'case06-author-cpu-provider/v1' else None
        else:
            expected = os.environ.get("CASE159_LAMMPS_SHA256", matrix.get('native_method', {}).get('lammps_stable_binary_sha256'))
        binary = doc.get('native_binary', {})
        digest = binary.get('sha256') if isinstance(binary, dict) else None
        if not isinstance(expected, str) or digest != expected:
            raise audit_Mismatch('run0 native binary SHA differs from the frozen compiled build')
        argv = doc.get('argv')
        wrapper_argv = wrapper_receipt.get('command_argv')
        if not isinstance(argv, list) or not argv or (not isinstance(wrapper_argv, list)):
            raise audit_UnknownEvidence('binary provenance or wrapper receipt lacks the actual command argv')
        if argv != wrapper_argv:
            raise audit_Mismatch('native binary provenance argv differs from the guarded wrapper execution')
        invoked = audit_Path(str(argv[0]))
        recorded_path = binary.get('path')
        if not isinstance(recorded_path, str) or not recorded_path or invoked.name != audit_Path(recorded_path).name:
            raise audit_Mismatch('native binary provenance path does not match the executed argv')
        for key in ('phase', 'role', 'run0_label'):
            if not isinstance(doc.get(key), str) or not doc[key]:
                raise audit_UnknownEvidence(f'native binary provenance lacks {key}')
        return {'sha256': digest, 'provenance_sha256': audit_sha(path), 'phase': doc['phase'], 'role': doc['role'], 'run0_label': doc['run0_label']}

    def audit__raw_prepared_snapshot_run0(outputs: audit_Path, proof_ref: dict, snapshot_ref: dict, expected_atoms: int, reference_root: audit_Path | None) -> dict:
        proof_path = audit__ledger_file_ref(outputs, proof_ref, reference_root)
        proof = audit__load_json(proof_path)
        if proof.get('schema') != 'case06-prepared-snapshot-run0-proof/v1':
            raise audit_UnknownEvidence('unsupported prepared run0 proof schema')
        role_root = audit__prepared_run_root(proof_path)
        snapshot_path = audit__ledger_file_ref(outputs, snapshot_ref, reference_root)
        if proof.get('snapshot_sha256') != audit_sha(snapshot_path):
            raise audit_Mismatch('run0 proof does not bind the prepared snapshot bytes')
        receipt_path = audit__ledger_file_ref(outputs, proof.get('execution_receipt'), reference_root)
        receipt = audit__load_json(receipt_path)
        if receipt.get('schema') != 'case06-native-invocation-receipt/v1':
            raise audit_UnknownEvidence('normalized native invocation receipt schema is missing')
        if receipt.get('native_returncode') != 0 or receipt.get('wrapper_integrity_rc') != 0 or receipt.get('manifest_run_plan_match') is not True or (receipt.get('native_zero_only') is not True):
            raise audit_Mismatch('native run0 execution receipt failed or does not prove zero-only invocation')
        if receipt.get('native_step') != 0 or receipt.get('native_atom_count') != expected_atoms:
            raise audit_Mismatch('native execution receipt step/atom count mismatch')
        wrapper_path = audit__prepared_role_ref(outputs, role_root, receipt.get('wrapper_receipt'), reference_root)
        wrapper = audit__load_json(wrapper_path)
        if wrapper.get('native_returncode') != 0 or wrapper.get('wrapper_integrity_rc') != 0 or wrapper.get('integrity_errors') != [] or (wrapper.get('expected_run_count') != 1):
            raise audit_Mismatch('raw wrapper receipt is not a clean zero-positive-run invocation')
        binary_provenance = audit__replay_binary_provenance(outputs, receipt, wrapper, reference_root)
        log_path = audit__ledger_file_ref(outputs, proof.get('native_log'), reference_root)
        dump_path = audit__ledger_file_ref(outputs, proof.get('native_dump'), reference_root)
        observation_path = audit__ledger_file_ref(outputs, proof.get('native_observation'), reference_root)
        state_path = audit__ledger_file_ref(outputs, proof.get('parsed_state'), reference_root)
        if proof.get('native_dump_sha256') != audit_sha(dump_path):
            raise audit_Mismatch('proof native dump SHA field disagrees with raw dump')
        for (field, path) in (('native_log_sha256', log_path), ('original_input_sha256', None), ('executed_input_sha256', None)):
            if field in receipt and path is not None and (receipt[field] != audit_sha(path)):
                raise audit_Mismatch(f'normalized receipt {field} differs from raw file')
        if receipt.get('native_log_sha256') != audit_sha(log_path):
            raise audit_Mismatch('normalized receipt native log SHA does not match raw log')
        if wrapper.get('native_log_archive', {}).get('sha256') != audit_sha(log_path):
            raise audit_Mismatch('wrapper archive SHA does not bind the supplied raw native log')
        events = audit__read_native_log(log_path)
        if len(events) != 1 or events[0]['steps'] != 0 or events[0]['atoms'] != expected_atoms or (events[0]['index'] != 1):
            raise audit_Mismatch('raw native log must contain exactly one ordered BEGIN/Loop0/END with the prepared atom count')
        native_dump = audit__parse_run0_force_dump(dump_path, expected_atoms)
        source = audit__parse_run0_snapshot_state(snapshot_path, expected_atoms)
        geom = source['geom']
        manifest_path = wrapper_path.parent / 'case08-instrumentation.jsonl'
        if not manifest_path.is_file():
            raise audit_UnknownEvidence('wrapper instrumentation manifest is missing')
        recs = [json.loads(x) for x in manifest_path.read_text(encoding='utf-8', errors='strict').splitlines() if x.strip()]
        invocation = receipt.get('invocation_id')
        rows = [r for r in recs if r.get('invocation_id') == invocation]
        if len(rows) != 1:
            raise audit_Mismatch('instrumentation manifest must have exactly one matching invocation row')
        row = rows[0]
        expected_call_dir = wrapper_path.parent.relative_to(role_root).as_posix()
        original = audit__prepared_manifest_member(wrapper_path.parent, role_root, row.get('original_path'), row.get('original_sha256'), expected_call_dir)
        executed = audit__prepared_manifest_member(wrapper_path.parent, role_root, row.get('instrumented_path'), row.get('instrumented_sha256'), expected_call_dir)
        if audit_sha(original) != row.get('original_sha256') or audit_sha(executed) != row.get('instrumented_sha256'):
            raise audit_Mismatch('original/executed input bytes disagree with instrumentation manifest')
        if receipt.get('original_input_sha256') != audit_sha(original) or receipt.get('executed_input_sha256') != audit_sha(executed):
            raise audit_Mismatch('normalized receipt does not bind actual original/executed inputs')
        for path in (original, executed):
            text = path.read_text(encoding='utf-8', errors='strict')
            if audit__source_run_steps(path) != [0]:
                raise audit_Mismatch('prepared run0 input must contain exactly one literal run 0 and no positive run')
            clean = [_strip_lammps_comment(line).strip() for line in text.splitlines()]
            reads = [re.fullmatch('read_data\\s+(\\S+)', x, re.I) for x in clean if x.lower().startswith('read_data')]
            if len(reads) != 1:
                raise audit_Mismatch('run0 input must load exactly one prepared data file')
            read_path = audit_Path(reads[0].group(1))
            if read_path.name != snapshot_path.name or audit_sha(snapshot_path) != proof.get('snapshot_sha256'):
                raise audit_Mismatch('native input read_data does not name the hash-bound prepared snapshot')
            if sum((x.lower() == 'atom_style atomic' for x in clean)) != 1 or sum((x.lower() == 'units metal' for x in clean)) != 1:
                raise audit_Mismatch('native run0 input units/atom style are not source-bound')
            pair_style = [x for x in clean if x.lower().startswith('pair_style ')]
            coeff = [x.split() for x in clean if x.lower().startswith('pair_coeff ')]
            masses = [x.split() for x in clean if x.lower().startswith('mass ')]
            expected_pair_style = 'pair_style pace product' if reference_root is not None and binary_provenance.get('role') == 'A' else 'pair_style pace/kk product'
            if len(pair_style) != 1 or pair_style[0].lower() != expected_pair_style:
                raise audit_Mismatch('run0 input pair_style differs from pinned provider Hamiltonian')
            if len(coeff) != 1 or len(coeff[0]) != 6 or coeff[0][1:3] != ['*', '*'] or (coeff[0][4:] != ['O', 'Si']):
                raise audit_Mismatch('run0 input pair_coeff element ordering differs from pinned Hamiltonian')
            audit__resolve_prepared_potential(outputs, role_root, coeff[0][3], audit_PUBLIC_YACE)
            if sorted(masses) != [['mass', '1', '15.999'], ['mass', '2', '28.085']]:
                raise audit_Mismatch('run0 input masses differ from frozen O/Si values')
        observation = observation_path.read_text(encoding='utf-8', errors='strict').splitlines()
        obsrows = [x for x in observation if x.startswith('CASE06_RUN0_RESULT ')]
        if len(obsrows) != 1:
            raise audit_Mismatch('native observation must contain exactly one energy/state line')
        fields = dict((x.split('=', 1) for x in obsrows[0].split()[1:]))
        if set(fields) != {'step', 'pe_eV', 'atoms', 'vol_A3'}:
            raise audit_Mismatch('native observation field schema mismatch')
        pe = audit_finite(fields['pe_eV'])
        vol = audit_finite(fields['vol_A3'])
        if int(fields['step']) != 0 or int(fields['atoms']) != expected_atoms or pe is None or (vol is None) or (vol <= 0):
            raise audit_Mismatch('native observation has invalid step/count/PE/volume')
        H = native_dump['H']
        origin = native_dump['origin']
        det = audit__det3(H)
        if abs(det - vol) > 2e-12 * max(abs(det), abs(vol), 1.0):
            raise audit_Mismatch('native observation volume differs from dumped cell determinant')
        if geom['n'] != expected_atoms or native_dump['step'] != 0:
            raise audit_Mismatch('snapshot/native dump atom count or step mismatch')
        src_atoms = source['atoms']
        dst = native_dump['atoms']
        if [(a['id'], a['type']) for a in src_atoms] != [(a['id'], a['type']) for a in dst]:
            raise audit_Mismatch('native run0 ID/type inventory differs from prepared snapshot')
        for i in range(3):
            if abs(geom['origin'][i] - origin[i]) > geom['origin_error'][i] + native_dump['origin_error'][i]:
                raise audit_Mismatch('native run0 cell origin differs from prepared snapshot')
            for j in range(3):
                if abs(geom['H'][i][j] - H[i][j]) > geom['H_error'][i][j] + native_dump['H_error'][i][j]:
                    raise audit_Mismatch('native run0 full cell matrix differs from prepared snapshot')
        for (s, d) in zip(src_atoms, dst):
            if s['image'] != d['image']:
                raise audit_Mismatch('native run0 periodic image flags differ from prepared snapshot')
            for (key, srcvals, dstvals, tokens, sig) in (('position', s['xyz'], d['xyz'], d['tokens']['xyz'], 16), ('velocity', s['vel'], d['vel'], d['tokens']['vel'], 16)):
                for (j, (sv, dv, token)) in enumerate(zip(srcvals, dstvals, tokens)):
                    srcerr = float(abs(audit_Decimal.from_float(sv) - audit_Decimal(s['xyz_tokens'][j] if key == 'position' else s['vel_tokens'][j])))
                    dst_err = audit__significant_print_half_quantum(token, sig)
                    if abs(sv - dv) > srcerr + dst_err + 8 * audit_sys.float_info.epsilon * (abs(sv) + abs(dv) + 1):
                        raise audit_Mismatch(f'native run0 {key} differs from prepared snapshot')
        for (s, d) in zip(src_atoms, dst):
            for j in range(3):
                sq = s['xyz'][j] + sum((s['image'][k] * geom['H'][k][j] for k in range(3)))
                dq = d['xyz'][j] + sum((d['image'][k] * H[k][j] for k in range(3)))
                err = float(abs(audit_Decimal.from_float(s['xyz'][j]) - audit_Decimal(s['xyz_tokens'][j])))
                err += sum((abs(s['image'][k]) * geom['H_error'][k][j] for k in range(3)))
                err += sum((abs(d['image'][k]) * native_dump['H_error'][k][j] for k in range(3)))
                err += audit__significant_print_half_quantum(d['tokens']['xyz'][j], 16) + 16 * audit_sys.float_info.epsilon * (abs(sq) + abs(dq) + 1)
                if abs(sq - dq) > err:
                    raise audit_Mismatch('native run0 unwrapped q differs from prepared snapshot')
        audit__load_json(state_path)
        return {'proof_sha256': audit_sha(proof_path), 'native_log_sha256': audit_sha(log_path), 'native_dump_sha256': audit_sha(dump_path), 'native_observation_sha256': audit_sha(observation_path), 'prepared_snapshot_sha256': audit_sha(snapshot_path), 'atoms': expected_atoms, 'step': 0, 'total_PE_eV': pe, 'volume_A3': vol, 'native_force_rows': len(dst), 'raw_BEGIN_Loop_END': 'PASS', 'full_state_replay': 'PASS', 'native_binary_provenance': binary_provenance}

    def audit__frac_error_bound(x, h, xerr, herr):
        invnorm = max(1.0 / max(abs(h[0][0]), 1e-300), 1.0 / max(abs(h[1][1]), 1e-300), 1.0 / max(abs(h[2][2]), 1e-300))
        hnorm = max((sum((abs(y) for y in row)) for row in herr))
        denom = 1.0 - invnorm * hnorm
        if denom <= 0:
            raise audit_UnknownEvidence('geometry H interval cannot certify its inverse')
        gamma = 12 * audit_sys.float_info.epsilon / (1 - 12 * audit_sys.float_info.epsilon)
        hpert = invnorm * invnorm * hnorm / denom
        xnorm = sum((abs(v) for v in x))
        invdiag = (1 / abs(h[0][0]), 1 / abs(h[1][1]), 1 / abs(h[2][2]))
        return tuple((sum(xerr) / min(abs(h[i][i]), abs(h[0][0]), abs(h[1][1]), abs(h[2][2])) + xnorm * hpert + gamma * (xnorm * invnorm + 1.0) for i in range(3)))

    def audit_verify_public_geometry(outputs: audit_Path, evidence: dict, plan: dict, checks: list[dict]) -> bool:
        """Independently verify public-large-cell quotient/source projection from raw atoms."""
        ref = evidence.get('geometry_manifest')
        if not isinstance(ref, dict):
            audit_add(checks, 'v2_public_geometry', 'UNKNOWN', 'hash-bound quotient geometry manifest missing')
            return False
        try:
            mpath = audit__file_ref(outputs, ref)
            manifest = audit__load_json(mpath)
            if manifest.get('schema') != 'case06-public-periodic-quotient/v1':
                raise audit_UnknownEvidence('unsupported geometry manifest protocol')
            reg = plan.get('geometry_registry', {})
            rows = manifest.get('structures')
            if not isinstance(rows, list):
                raise audit_UnknownEvidence('geometry manifest lacks structures')
            byphase = {r.get('phase'): r for r in rows if isinstance(r, dict)}
            if set(byphase) != {'alpha_quartz', 'coesite'}:
                raise audit_Mismatch('geometry manifest must contain exactly both phases')
            for (phase, plankey) in (('alpha_quartz', 'public_large_alpha'), ('coesite', 'public_large_coesite')):
                rec = reg.get(plankey)
                row = byphase[phase]
                if not isinstance(rec, dict):
                    raise audit_UnknownEvidence('current matrix has no source geometry registry')
                if row.get('source_sha256') != rec.get('sha256') or row.get('source_atoms') != rec.get('atoms'):
                    raise audit_Mismatch(f'{phase}: public large source identity differs from current matrix')
                factors = tuple((int(x) for x in rec.get('quotient_diagonal', [])))
                if tuple(row.get('quotient_factors', [])) != factors or audit_math.prod(factors) != int(row.get('periodic_tile_count', -1)):
                    raise audit_Mismatch(f'{phase}: quotient factors/tile multiplicity differ from matrix')
                source_ref = row.get('source_file', row.get('source_artifact'))
                if isinstance(source_ref, dict):
                    source = audit__file_ref(outputs, source_ref)
                else:
                    expected_path = rec.get('path')
                    if row.get('source_path') != expected_path:
                        raise audit_Mismatch(f'{phase}: source path differs from current public registry')
                    source = (REPO / expected_path).resolve()
                    if not source.is_file():
                        raise audit_UnknownEvidence(f'{phase}: public source file is not available locally')
                data_ref = row.get('derived_data', row.get('data_artifact'))
                if isinstance(data_ref, dict):
                    derived = audit__file_ref(outputs, data_ref)
                else:
                    data_rel = row.get('data_path')
                    if not isinstance(data_rel, str):
                        raise audit_UnknownEvidence(f'{phase}: derived data artifact path missing')
                    derived = audit__safe_path(outputs, data_rel)
                    if row.get('data_sha256') != audit_sha(derived):
                        raise audit_Mismatch(f'{phase}: derived data file hash mismatch')
                if audit_sha(source) != rec.get('sha256'):
                    raise audit_Mismatch(f'{phase}: source bytes do not match public registry')
                s = audit__geom_data(source)
                d = audit__geom_data(derived)
                ntarget = audit_PHASE_ATOMS[phase]
                if s['n'] != int(rec['atoms']) or d['n'] != ntarget:
                    raise audit_Mismatch(f'{phase}: source/quotient atom counts are incorrect')
                if d['types'] != {1: 2 * ntarget // 3, 2: ntarget // 3} or any((s['types'].get(t, 0) != d['types'].get(t, 0) * audit_math.prod(factors) for t in {1, 2})):
                    raise audit_Mismatch(f'{phase}: quotient composition is not preserved')
                gauge = None
                rawd = d
                if phase == 'coesite':
                    gauge = reg.get('prospective_triclinic_representation', {}).get('coesite_unimodular_row_basis_c_prime_eq_c_minus_a')
                    gauge_doc = row.get('basis_gauge')
                    if not isinstance(gauge_doc, dict) or gauge_doc.get('row_matrix') != gauge:
                        raise audit_UnknownEvidence("coesite derived-cell gauge is absent or differs from the frozen c'=c-a matrix")
                    raw_path = gauge_doc.get('source_data_path')
                    raw_sha = gauge_doc.get('source_data_sha256')
                    if not isinstance(raw_path, str) or not isinstance(raw_sha, str):
                        raise audit_UnknownEvidence('coesite basis_gauge lacks source-data path/hash')
                    rawd_path = audit__safe_path(outputs, raw_path)
                    if audit_sha(rawd_path) != raw_sha:
                        raise audit_Mismatch('coesite ungauged source-data SHA mismatch')
                    rawd = audit__geom_data(rawd_path)
                    if rawd['n'] != ntarget:
                        raise audit_Mismatch('coesite ungauged source-data atom count mismatch')
                    if gauge_doc.get('gauged_data_path') != row.get('data_path') or gauge_doc.get('gauged_data_sha256') != row.get('data_sha256'):
                        raise audit_Mismatch('coesite basis_gauge gauged artifact does not bind derived runtime data')
                    u = [[int(v) for v in rr] for rr in gauge]
                    det = u[0][0] * (u[1][1] * u[2][2] - u[1][2] * u[2][1]) - u[0][1] * (u[1][0] * u[2][2] - u[1][2] * u[2][0]) + u[0][2] * (u[1][0] * u[2][1] - u[1][1] * u[2][0])
                    if det != 1 or gauge_doc.get('determinant') != 1:
                        raise audit_Mismatch('coesite basis gauge is not the frozen unimodular determinant-one map')
                    expected_gauged = audit__matmul3(u, rawd['H'])
                    for i in range(3):
                        for j in range(3):
                            bound = sum((abs(u[i][k]) * rawd['H_error'][k][j] for k in range(3))) + 8 * audit_sys.float_info.epsilon * sum((abs(u[i][k] * rawd['H'][k][j]) for k in range(3)))
                            if abs(d['H'][i][j] - expected_gauged[i][j]) > bound:
                                raise audit_Mismatch('coesite gauged H is not the frozen row-basis transform of source data')
                    if [a[0] for a in rawd['atoms']] != [a[0] for a in d['atoms']] or [a[1] for a in rawd['atoms']] != [a[1] for a in d['atoms']] or rawd['origin'] != d['origin']:
                        raise audit_Mismatch('coesite gauge changed atom IDs/types or box origin')
                    for (a, b) in zip(rawd['atoms'], d['atoms']):
                        for j in range(3):
                            bound = a[4][j] + b[4][j] + 4 * audit_sys.float_info.epsilon * (abs(a[2][j]) + abs(b[2][j]))
                            if abs(a[2][j] - b[2][j]) > bound:
                                raise audit_Mismatch('coesite gauge changed Cartesian atom coordinates')
                else:
                    if row.get('basis_gauge') not in (None, {}):
                        raise audit_Mismatch('alpha quotient has an unregistered basis gauge')
                    rawd = d
                for i in range(3):
                    for j in range(3):
                        expected = s['H'][i][j] / factors[i]
                        expected_err = s['H_error'][i][j] / factors[i] + audit_math.ulp(expected) * 0.5
                        bound = expected_err + rawd['H_error'][i][j] + 4 * audit_sys.float_info.epsilon * abs(rawd['H'][i][j])
                        if abs(rawd['H'][i][j] - expected) > bound:
                            raise audit_Mismatch(f'{phase}: derived full H is not H_large row-scaled by quotient')
                target_by_type = {t: [] for t in rawd['types']}
                source_by_type = {t: [] for t in s['types']}
                for atom in rawd['atoms']:
                    rel = tuple((atom[2][i] - rawd['origin'][i] for i in range(3)))
                    xerr = tuple((atom[4][i] + rawd['origin_error'][i] + audit_sys.float_info.epsilon * (abs(atom[2][i]) + abs(rawd['origin'][i])) for i in range(3)))
                    (f, ferr) = audit__fractional_error(rel, rawd, xerr)
                    target_by_type[atom[1]].append((tuple((x % 1.0 for x in f)), ferr))
                for atom in s['atoms']:
                    rel = tuple((atom[2][i] - s['origin'][i] for i in range(3)))
                    xerr = tuple((atom[4][i] + s['origin_error'][i] + audit_sys.float_info.epsilon * (abs(atom[2][i]) + abs(s['origin'][i])) for i in range(3)))
                    (f, ferr) = audit__fractional_error(rel, s, xerr)
                    q = tuple((f[i] * factors[i] % 1.0 for i in range(3)))
                    qerr = tuple((ferr[i] * factors[i] + audit_math.ulp(f[i] * factors[i]) * 0.5 for i in range(3)))
                    source_by_type[atom[1]].append((q, qerr))
                for (typ, srcs) in source_by_type.items():
                    tgts = target_by_type[typ]
                    scale = 10 ** 10
                    bins = {}
                    for (idx, (t, _)) in enumerate(tgts):
                        key = tuple((int(round(x % 1.0 * scale)) % scale for x in t))
                        bins.setdefault(key, []).append(idx)
                    counts = [0] * len(tgts)
                    for (q, qerr) in srcs:
                        key = tuple((int(round(x % 1.0 * scale)) % scale for x in q))
                        candidates = set()
                        for offs in audit_itertools.product((-1, 0, 1), repeat=3):
                            k = tuple(((key[i] + offs[i]) % scale for i in range(3)))
                            candidates.update(bins.get(k, []))
                        matches = []
                        for idx in candidates:
                            (t, terr) = tgts[idx]
                            dist = [min(abs(q[i] - t[i]), 1 - abs(q[i] - t[i])) for i in range(3)]
                            if all((dist[i] <= qerr[i] + terr[i] for i in range(3))):
                                matches.append(idx)
                        if len(matches) != 1:
                            raise audit_UnknownEvidence(f'{phase}: quotient site match is ambiguous or outside propagated numerical envelope')
                        counts[matches[0]] += 1
                    if any((c != audit_math.prod(factors) for c in counts)):
                        raise audit_Mismatch(f'{phase}: source-to-quotient site multiplicity is not exactly tile count')
                size = row.get('size_supercell')
                if not isinstance(size, dict):
                    raise audit_UnknownEvidence(f'{phase}: size supercell source record missing')
                size_atoms = int(size.get('atoms', -1))
                size_path = size.get('path')
                size_sha = size.get('sha256')
                if size_atoms != 2 * ntarget or not isinstance(size_path, str) or (not isinstance(size_sha, str)):
                    raise audit_Mismatch(f'{phase}: size supercell count/path/hash invalid')
                size_file = audit__safe_path(outputs, size_path)
                if audit_sha(size_file) != size_sha:
                    raise audit_Mismatch(f'{phase}: size supercell bytes do not match manifest')
                sd = audit__geom_data(size_file)
                size_registry = plan.get('geometry_registry', {})
                pmat = size_registry.get('size_supercell_integer_matrices_ASE_rows_Hnew_eq_P_Hold', size_registry.get('size_supercell_integer_matrices_rows_Hnew_eq_P_Hold', {})).get(phase)
                if pmat is None or size.get('matrix_row_convention') != pmat:
                    raise audit_UnknownEvidence(f'{phase}: size matrix does not bind the current plan')
                expected_size_h = audit__matmul3(pmat, d['H'])
                for i in range(3):
                    for j in range(3):
                        bound = sum((abs(pmat[i][k]) * d['H_error'][k][j] for k in range(3))) + 8 * audit_sys.float_info.epsilon * sum((abs(pmat[i][k] * d['H'][k][j]) for k in range(3)))
                        if abs(sd['H'][i][j] - expected_size_h[i][j]) > bound:
                            raise audit_Mismatch(f'{phase}: size supercell H is not P times runtime base H')
                if sd['n'] != 2 * ntarget or [a[1] for a in sd['atoms']].count(1) != 2 * d['types'].get(1, 0):
                    raise audit_Mismatch(f'{phase}: size supercell atom count/composition mismatch')
                pairs = size.get('site_pairs')
                base_ids = [a[0] for a in d['atoms']]
                reps = ((0, 0, 0), (0, 1, 0))
                expected_pairs = [{'base_atom_id': int(base_id), 'target_atom_id': tile * ntarget + idx + 1, 'tile_representative': list(reps[tile])} for tile in range(2) for (idx, base_id) in enumerate(base_ids)]
                if pairs != expected_pairs:
                    raise audit_Mismatch(f'{phase}: size site map differs from independent base-ID/tile reconstruction')
                if [a[0] for a in sd['atoms']] != list(range(1, 2 * ntarget + 1)):
                    raise audit_Mismatch(f'{phase}: size data target IDs are not exact generated IDs')
                pinv = audit__inverse_tri(pmat)
                base_by_id = {a[0]: a for a in d['atoms']}
                size_by_id = {a[0]: a for a in sd['atoms']}
                for pair in expected_pairs:
                    ba = base_by_id[pair['base_atom_id']]
                    ta = size_by_id[pair['target_atom_id']]
                    if ba[1] != ta[1]:
                        raise audit_Mismatch(f'{phase}: size mapping changes atom type')
                    brel = tuple((ba[2][i] - d['origin'][i] for i in range(3)))
                    trel = tuple((ta[2][i] - sd['origin'][i] for i in range(3)))
                    (bf, bfe) = audit__fractional_error(brel, d, tuple((ba[4][i] + d['origin_error'][i] for i in range(3))))
                    (tf, tfe) = audit__fractional_error(trel, sd, tuple((ta[4][i] + sd['origin_error'][i] for i in range(3))))
                    translated = tuple((sum(((bf[k] + pair['tile_representative'][k]) * pinv[k][j] for k in range(3))) % 1.0 for j in range(3)))
                    terr = tuple((sum(((bfe[k] + 8 * audit_sys.float_info.epsilon * (abs(bf[k]) + 1)) * abs(pinv[k][j]) for k in range(3))) + tfe[j] + 8 * audit_sys.float_info.epsilon * (abs(translated[j]) + 1) for j in range(3)))
                    delta = tuple((min(abs(translated[j] - tf[j]), 1 - abs(translated[j] - tf[j])) for j in range(3)))
                    if any((delta[j] > terr[j] for j in range(3))):
                        raise audit_Mismatch(f'{phase}: size mapped atom is not the advertised periodic tile of its base site')
            audit_add(checks, 'v2_public_geometry', 'PASS', 'independently reprojected both public source structures to quotient cells, composition and tile multiplicity')
            return True
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_public_geometry', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_public_geometry', 'FAIL', f'{type(exc).__name__}: {exc}')
        return False

    def audit__load_direction_records(evidence: dict, checks: list[dict]) -> list[dict]:
        rows = evidence.get('directions')
        if not isinstance(rows, list):
            audit_add(checks, 'v2_direction_records', 'UNKNOWN', 'direction records missing')
            return []
        ids = set()
        out = []
        for row in rows:
            if not isinstance(row, dict):
                audit_add(checks, 'v2_direction_records', 'FAIL', 'malformed direction row')
                continue
            rid = str(row.get('run_id') or '')
            if not rid or rid in ids:
                audit_add(checks, 'v2_direction_records', 'FAIL', f'missing/duplicate run id {rid}')
                continue
            ids.add(rid)
            if row.get('status') not in ('COMPLETE', 'FAILED', 'ABORTED', 'UNKNOWN', 'RUNNING', 'PLANNED'):
                audit_add(checks, 'v2_direction_status', 'FAIL', f'{rid}: unsupported status')
            out.append(row)
        return out

    def audit__read_native_log(path: audit_Path) -> list[dict]:
        text = path.read_text(encoding='utf-8', errors='replace')
        bpat = '(?m)^CASE08_RUN_BEGIN[^\\n]*?segment=(\\S+)\\s+index=(\\d+)\\s+planned_steps=(\\d+)\\s+start_step=(-?[0-9.eE+\\-]+)\\s*$'
        epat = '(?m)^CASE08_RUN_END[^\\n]*?segment=(\\S+)\\s+index=(\\d+)\\s+planned_steps=(\\d+)\\s+end_step=(-?[0-9.eE+\\-]+)\\s*$'
        lpat = '(?m)^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$'
        events = []
        for (kind, pat) in (('BEGIN', bpat), ('LOOP', lpat), ('END', epat)):
            for m in audit_re.finditer(pat, text):
                events.append((m.start(), kind, m.groups()))
        events.sort(key=lambda x: x[0])
        if len(events) % 3:
            raise audit_Mismatch('native log has incomplete BEGIN/Loop/END event triple')
        parsed = []
        for i in range(0, len(events), 3):
            triple = events[i:i + 3]
            if [x[1] for x in triple] != ['BEGIN', 'LOOP', 'END']:
                raise audit_Mismatch('native event order is not BEGIN < Loop < END')
            (_, _, (seg_b, idx_b, plan_b, start)) = triple[0]
            (_, _, (steps, atoms)) = triple[1]
            (_, _, (seg_e, idx_e, plan_e, end)) = triple[2]
            if (seg_b, idx_b, plan_b) != (seg_e, idx_e, plan_e) or int(plan_b) != int(steps):
                raise audit_Mismatch('native BEGIN/Loop/END invocation plans disagree')
            if int(round(float(end) - float(start))) != int(steps):
                raise audit_Mismatch('native step delta disagrees with Loop count')
            parsed.append({'segment': seg_b, 'index': int(idx_b), 'steps': int(steps), 'atoms': int(atoms), 'start_step': float(start), 'end_step': float(end)})
        return parsed

    def audit__read_native_log_complete_prefix(path: audit_Path) -> tuple[list[dict], dict | None]:
        """Recover only fully ordered BEGIN/Loop/END triples before a terminal halt."""
        text = path.read_text(encoding='utf-8', errors='replace')
        patterns = {'BEGIN': 'CASE08_RUN_BEGIN[^\\n]*?segment=(\\S+)\\s+index=(\\d+)\\s+planned_steps=(\\d+)\\s+start_step=(-?[0-9.eE+\\-]+)', 'END': 'CASE08_RUN_END[^\\n]*?segment=(\\S+)\\s+index=(\\d+)\\s+planned_steps=(\\d+)\\s+end_step=(-?[0-9.eE+\\-]+)', 'LOOP': 'Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms'}
        events = []
        for (kind, pattern) in patterns.items():
            for match in audit_re.finditer(pattern, text):
                events.append((match.start(), kind, match.groups()))
        events.sort(key=lambda x: x[0])
        done = []
        state = 'BEGIN'
        current = {}
        for (_, kind, groups) in events:
            if state == 'BEGIN':
                if kind != 'BEGIN':
                    raise audit_Mismatch('native complete-prefix begins with non-BEGIN event')
                (seg, idx, steps, start) = groups
                current = {'segment': seg, 'index': int(idx), 'planned': int(steps), 'start': float(start)}
                state = 'LOOP'
            elif state == 'LOOP':
                if kind != 'LOOP':
                    raise audit_Mismatch('native complete-prefix missing Loop after BEGIN')
                (steps, atoms) = groups
                if int(steps) != current['planned']:
                    raise audit_Mismatch('native Loop differs from BEGIN planned steps')
                current.update(steps=int(steps), atoms=int(atoms))
                state = 'END'
            else:
                if kind != 'END':
                    raise audit_Mismatch('native complete-prefix has out-of-order event before END')
                (seg, idx, steps, end) = groups
                if (seg, int(idx), int(steps)) != (current['segment'], current['index'], current['planned']):
                    raise audit_Mismatch('native END differs from BEGIN/Loop event')
                end = float(end)
                if int(round(end - current['start'])) != current['steps']:
                    raise audit_Mismatch('native complete-prefix step delta differs from Loop')
                done.append({'segment': current['segment'], 'index': current['index'], 'steps': current['steps'], 'atoms': current['atoms'], 'start_step': current['start'], 'end_step': end})
                current = {}
                state = 'BEGIN'
        if state == 'BEGIN':
            return (done, None)
        pending = {'state': state, 'segment': current.get('segment'), 'index': current.get('index'), 'planned_steps': current.get('planned'), 'observed_loop_steps': current.get('steps')}
        return (done, pending)

    def audit__source_run_steps(path: audit_Path) -> list[int]:
        """Read literal LAMMPS run commands; comments/variables are not accepted as proof."""
        result = []
        for line in path.read_text(encoding='utf-8', errors='strict').splitlines():
            clean = audit__strip_lammps_comment(line).strip()
            if not clean:
                continue
            fields = clean.split()
            if fields[0].lower() == 'run':
                if len(fields) < 2 or not audit_re.fullmatch('\\d+', fields[1]):
                    raise audit_UnknownEvidence(f'nonliteral LAMMPS run command in {path.name}')
                result.append(int(fields[1]))
        return result

    def audit__strip_lammps_comment(line: str) -> str:
        """Drop only unquoted comments; fix-print titles may contain a literal #."""
        quote = None
        escaped = False
        for (i, ch) in enumerate(line):
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ('"', "'"):
                quote = ch
            elif ch == '#':
                return line[:i]
        return line

    def audit_verify_native_ledger(outputs: audit_Path, evidence: dict, checks: list[dict], reference_root: audit_Path | None=None) -> dict:
        ref = evidence.get('native_event_ledger')
        known_steps = 0
        known_atoms = 0
        reservation_upper = None
        ledger = None
        try:
            ledger_path = audit__file_ref(outputs, ref)
            ledger = audit__load_json(ledger_path)
            if ledger.get('schema') not in ('case06-native-event-ledger/v1', 'case06-native-event-ledger/v2', 'case06-global-native-event-ledger/v1'):
                raise audit_UnknownEvidence('native ledger schema unsupported')
            invocations = ledger.get('native_invocations')
            cycles = ledger.get('direction_attempts')
            integration_cycles = ledger.get('integration_cycles')
            setups = ledger.get('phase_setups', ledger.get('setups', []))
            if not isinstance(invocations, list) or not isinstance(cycles, list) or (not isinstance(integration_cycles, list)) or (not isinstance(setups, list)):
                raise audit_UnknownEvidence('global native_invocations/direction_attempts/integration_cycles/phase_setups are required')
            invocation_by_id = {}
            segment_by_key = {}
            total_steps = 0
            total_atoms = 0
            for call in invocations:
                if not isinstance(call, dict):
                    raise audit_Mismatch('native invocation row malformed')
                cid = str(call.get('invocation_id') or '')
                if not cid or cid in invocation_by_id:
                    raise audit_Mismatch('duplicate/missing global invocation id')
                original = audit__ledger_file_ref(outputs, call.get('original_input'), reference_root)
                executed = audit__ledger_file_ref(outputs, call.get('executed_input'), reference_root)
                log = audit__ledger_file_ref(outputs, call.get('native_log'), reference_root)
                receipt = audit__ledger_file_ref(outputs, call.get('execution_receipt'), reference_root)
                receipt_doc = audit__load_json(receipt)
                receipt_pass = receipt_doc.get('native_returncode') == 0 and receipt_doc.get('wrapper_integrity_rc') == 0 and (receipt_doc.get('manifest_run_plan_match') is True)
                if receipt_doc.get('original_input_sha256') != audit_sha(original) or receipt_doc.get('executed_input_sha256') != audit_sha(executed):
                    raise audit_Mismatch(f'{cid}: execution receipt input hashes mismatch')
                if receipt_doc.get('native_log_sha256') != audit_sha(log):
                    raise audit_Mismatch(f'{cid}: native log hash mismatch')
                incomplete = None
                try:
                    parsed = audit__read_native_log(log)
                except audit_Mismatch:
                    (parsed, incomplete) = audit__read_native_log_complete_prefix(log)
                declared = call.get('run_segments', call.get('run_plan'))
                if not isinstance(declared, list) or len(parsed) > len(declared) or (len(parsed) != len(declared) and incomplete is None):
                    raise audit_Mismatch(f'{cid}: native segment count differs from source-bound plan')
                original_runs = audit__source_run_steps(original)
                executed_runs = audit__source_run_steps(executed)
                native_runs = [x['steps'] for x in parsed]
                if incomplete is None:
                    if original_runs != native_runs:
                        raise audit_Mismatch(f'{cid}: literal original-input run commands differ from native Loop segments')
                    if executed_runs != native_runs:
                        raise audit_Mismatch(f'{cid}: executed/guarded-input run commands differ from native Loop segments')
                else:
                    ncomplete = len(native_runs)
                    if original_runs[:ncomplete] != native_runs or executed_runs[:ncomplete] != native_runs:
                        raise audit_Mismatch(f'{cid}: completed native prefix differs from literal source run commands')
                    pending_marker = int(incomplete.get('index', ncomplete + 1))
                    if pending_marker != ncomplete + 1:
                        raise audit_Mismatch(f'{cid}: incomplete native marker is not the next source run')
                    pending_idx = pending_marker - 1
                    pending_steps = incomplete.get('planned_steps')
                    if pending_idx >= len(original_runs) or pending_idx >= len(executed_runs):
                        raise audit_Mismatch(f'{cid}: incomplete event index lacks source run command')
                    if pending_steps is not None and (original_runs[pending_idx] != pending_steps or executed_runs[pending_idx] != pending_steps):
                        raise audit_Mismatch(f'{cid}: incomplete native event plan differs from literal run commands')
                if not any(('CASE08' in line and ('RUN_BEGIN' in line or 'instrument' in line.lower()) for line in executed.read_text(encoding='utf-8', errors='replace').splitlines())):
                    raise audit_UnknownEvidence(f'{cid}: executed input lacks source-visible Case08 guard instrumentation')
                for (idx, (got, want)) in enumerate(zip(parsed, declared)):
                    if not isinstance(want, dict):
                        raise audit_Mismatch(f'{cid}: malformed run segment plan')
                    if int(want.get('planned_steps', want.get('steps', -1))) != got['steps'] or int(want.get('atoms', got['atoms'])) != got['atoms']:
                        raise audit_Mismatch(f'{cid}: segment {idx} differs from parsed BEGIN/Loop/END')
                    native_name = want.get('native_segment_name', want.get('segment_name', want.get('segment')))
                    if not isinstance(native_name, str) or native_name != got['segment']:
                        raise audit_UnknownEvidence(f'{cid}: run segment role is not bound to its literal native marker label')
                    key = (cid, got['index'])
                    if key in segment_by_key:
                        raise audit_Mismatch(f'{cid}: duplicate native run index')
                    segment_by_key[key] = {**got, 'invocation_id': cid, 'atoms': got['atoms'], 'segment_kind': want.get('segment_kind', want.get('kind')), 'phase': call.get('phase'), 'input_sha256': audit_sha(original), 'log_sha256': audit_sha(log)}
                    total_steps += got['steps']
                    total_atoms += got['steps'] * got['atoms']
                    known_steps += got['steps']
                    known_atoms += got['steps'] * got['atoms']
                invocation_by_id[cid] = call
                if incomplete is not None:
                    try:
                        planned_all = 0
                        for future_call in ledger.get('native_invocations', []):
                            source = audit__ledger_file_ref(outputs, future_call.get('original_input'), reference_root)
                            planned_all += sum(audit__source_run_steps(source))
                        reservation_upper = max(0, planned_all - known_steps)
                    except Exception:
                        reservation_upper = None
                    raise audit_UnknownEvidence(f'{cid}: native log ended with incomplete event {incomplete}; known completed Loop prefix retained; wrapper/returncode pass={receipt_pass}')
                if not receipt_pass:
                    raise audit_UnknownEvidence(f'{cid}: wrapper/native receipt is not successful; {known_steps} source-reconciled steps retained as lower bound')
            seen_cycle_ids = set()
            cycle_switch_map = {}
            for whole in integration_cycles:
                if not isinstance(whole, dict):
                    raise audit_Mismatch('integration-cycle row malformed')
                cycle_id = str(whole.get('cycle_id') or '')
                if not cycle_id or cycle_id in seen_cycle_ids:
                    raise audit_Mismatch('missing/duplicate integration cycle id')
                seen_cycle_ids.add(cycle_id)
                refs = whole.get('invocation_segments', whole.get('segments'))
                if not isinstance(refs, list):
                    raise audit_UnknownEvidence(f'{cycle_id}: cycle native segment refs missing')
                linked = []
                for link in refs:
                    key = (str(link.get('invocation_id') or ''), int(link.get('run_index', -1)))
                    seg = segment_by_key.get(key)
                    if seg is None:
                        raise audit_Mismatch(f'{cycle_id}: references absent native segment')
                    kind = link.get('segment_kind', seg.get('segment_kind'))
                    linked.append({**seg, 'segment_kind': kind, 'leg': link.get('leg')})
                switches = [s for s in linked if s['segment_kind'] == 'fe_switch' and s['steps'] > 0]
                warms = [s for s in linked if str(s['segment_kind']).startswith('fe_warm_') and s['steps'] > 0]
                if len(switches) != 2 or len(warms) != 2:
                    if whole.get('status', 'COMPLETE') == 'COMPLETE':
                        raise audit_Mismatch(f'{cycle_id}: completed native integration cycle must source two switches and two warm segments')
                    audit_add(checks, 'v2_incomplete_integration_cycle', 'UNKNOWN', f'{cycle_id}: incomplete native cycle; actual segments retained')
                else:
                    ordered_kinds = [s['segment_kind'] for s in linked if s['steps'] > 0]
                    if ordered_kinds != ['fe_warm_physical', 'fe_switch', 'fe_warm_einstein', 'fe_switch']:
                        raise audit_Mismatch(f'{cycle_id}: actual cycle segment role/order differs from physical warm/F/E warm/B contract')
                cycle_switch_map[cycle_id] = {}
                for seg in switches:
                    leg = str(seg.get('leg') or '').lower()
                    if leg not in ('forward', 'backward') or leg in cycle_switch_map[cycle_id]:
                        raise audit_Mismatch(f'{cycle_id}: switch leg refs must identify one forward and one backward segment')
                    cycle_switch_map[cycle_id][leg] = (seg['invocation_id'], seg['index'])
                switch_steps = {int(s['steps']) for s in switches}
                if len(switch_steps) != 1 or next(iter(switch_steps)) not in (20000, 40000):
                    raise audit_Mismatch(f'{cycle_id}: forward/backward switch lengths disagree with frozen baseline/duration protocol')
                if any((s['steps'] != 1000 for s in warms)):
                    raise audit_Mismatch(f'{cycle_id}: Calphy warm segment differs from pinned 1000-step method')
                for kind in ('fe_switch', 'fe_warm_physical', 'fe_warm_einstein'):
                    for seg in linked:
                        if seg['segment_kind'] == kind and seg['atoms'] not in (audit_PHASE_ATOMS.get(whole.get('phase')), 2 * audit_PHASE_ATOMS.get(whole.get('phase'))):
                            raise audit_Mismatch(f'{cycle_id}: cycle phase/atom count mismatch')
            direction_attempts = []
            reference_keys = []
            for cycle in cycles:
                if not isinstance(cycle, dict):
                    raise audit_Mismatch('integration cycle row malformed')
                role = cycle.get('role')
                phase = cycle.get('phase')
                if role not in audit_ROLE_MAP.values() or phase not in audit_PHASE_ATOMS:
                    raise audit_Mismatch('cycle role/phase invalid')
                refs = cycle.get('invocation_segments', cycle.get('segments'))
                if not isinstance(refs, list) or not refs:
                    raise audit_UnknownEvidence('cycle lacks segment references')
                linked = []
                positive_switch = False
                for link in refs:
                    cid = str(link.get('invocation_id') or '')
                    idx = int(link.get('run_index', -1))
                    seg = segment_by_key.get((cid, idx))
                    if seg is None:
                        raise audit_Mismatch('cycle references absent native segment')
                    size_factor = 2 if role in ('adaptive_size', 'S') else 1
                    if seg['atoms'] != audit_PHASE_ATOMS[phase] * size_factor:
                        raise audit_Mismatch('cycle phase/role atom count mismatch')
                    if seg.get('phase') not in (None, phase):
                        raise audit_Mismatch('native invocation phase mismatch')
                    kind = link.get('segment_kind', seg.get('segment_kind'))
                    if kind == 'fe_switch' and seg['steps'] > 0:
                        positive_switch = True
                    linked.append({**seg, 'segment_kind': kind, 'leg': link.get('leg')})
                    reference_keys.append((cid, idx))
                direction_attempts.append({**cycle, 'attempt_kind': 'direction', 'attempt_id': str(cycle.get('run_id') or cycle.get('attempt_id') or cycle.get('cycle_id') or ''), 'linked_segments': linked, 'started_positive_switch': positive_switch})
                cycle_id = str(cycle.get('cycle_id') or '')
                leg = str(cycle.get('leg') or '').lower()
                if cycle_id not in seen_cycle_ids or leg not in ('forward', 'backward'):
                    raise audit_Mismatch(f"{cycle.get('run_id')}: direction row lacks valid parent cycle/leg")
                switch_refs = [s for s in linked if s.get('segment_kind') == 'fe_switch']
                if len(switch_refs) != 1:
                    raise audit_Mismatch(f"{cycle.get('run_id')}: direction must reference exactly one switch segment")
                key = (switch_refs[0]['invocation_id'], switch_refs[0]['index'])
                if cycle_switch_map.get(cycle_id, {}).get(leg) != key:
                    raise audit_Mismatch(f"{cycle.get('run_id')}: direction switch differs from its parent cycle leg")
            setup_rows = []
            setup_total_by_phase = {}
            setup_prep_by_id = {}
            setup_warm_by_id = {}
            setup_ids = set()
            for setup in setups:
                if not isinstance(setup, dict):
                    raise audit_Mismatch('phase setup row malformed')
                sid = str(setup.get('setup_id') or '')
                phase = setup.get('phase')
                if not sid or phase not in audit_PHASE_ATOMS:
                    raise audit_Mismatch('setup id/phase invalid')
                if sid in setup_ids:
                    raise audit_Mismatch(f'duplicate setup ancestry row {sid}; shared descendants must reference one row')
                setup_ids.add(sid)
                refs = setup.get('invocation_segments', setup.get('segments', []))
                linked = []
                for link in refs:
                    cid = str(link.get('invocation_id') or '')
                    idx = int(link.get('run_index', -1))
                    seg = segment_by_key.get((cid, idx))
                    if seg is None:
                        raise audit_Mismatch('setup references absent native segment')
                    size_factor = 2 if setup.get('role') in ('adaptive_size', 'S') else 1
                    if seg['atoms'] != audit_PHASE_ATOMS[phase] * size_factor:
                        raise audit_Mismatch('setup phase/role atom count mismatch')
                    linked.append({**seg, 'segment_kind': link.get('segment_kind', seg.get('segment_kind'))})
                    reference_keys.append((cid, idx))
                sourced_steps = sum((x['steps'] for x in linked))
                if setup.get('actual_steps') is None or int(setup['actual_steps']) != sourced_steps:
                    raise audit_Mismatch(f'{sid}: setup total does not match linked native segment steps')
                setup_total_by_phase[phase] = max(setup_total_by_phase.get(phase, 0), sourced_steps)
                prep = sum((x['steps'] for x in linked if 'warm' not in str(x.get('segment_kind') or '').lower() and 'switch' not in str(x.get('segment_kind') or '').lower()))
                warm = sum((x['steps'] for x in linked if 'warm' in str(x.get('segment_kind') or '').lower()))
                setup_prep_by_id[sid] = prep
                setup_warm_by_id[sid] = warm
                cap = int(audit_load_current_plan().get('new_contract_caps', {}).get('setup_ancestry_md_steps_per_phase', 20000))
                if sourced_steps > cap:
                    raise audit_Mismatch(f'{sid}: grouped preparation+warm ancestry {sourced_steps} exceeds {cap}')
                setup_rows.append({**setup, 'linked_segments': linked, 'source_actual_steps': sourced_steps})
            costs = {}
            for cycle in direction_attempts:
                for seg in cycle['linked_segments']:
                    key = (seg['invocation_id'], seg['index'])
                    if seg['steps'] > 0:
                        costs[key] = costs.get(key, 0) + 1
            for setup in setup_rows:
                for seg in setup['linked_segments']:
                    key = (seg['invocation_id'], seg['index'])
                    if seg['steps'] > 0:
                        costs[key] = costs.get(key, 0) + 1
            if any((n != 1 for n in costs.values())):
                raise audit_Mismatch('positive native segment is multiply attributed across setup/direction cost partitions')
            covered = {k for (k, n) in costs.items() if n == 1}
            positive = {k for (k, v) in segment_by_key.items() if v['steps'] > 0}
            if covered != positive:
                raise audit_UnknownEvidence(f'native segment cost partition incomplete; uncovered={len(positive - covered)}')
            for (phase, steps) in setup_total_by_phase.items():
                cap = int(audit_load_current_plan().get('new_contract_caps', {}).get('setup_ancestry_md_steps_per_phase', 20000))
                if steps > cap:
                    raise audit_Mismatch(f'{phase}: grouped setup/warm ancestry {steps} exceeds {cap}')
            audit_add(checks, 'v2_native_event_replay', 'PASS', f'{len(invocations)} globally unique invocations, {len(segment_by_key)} native segments replayed once; {total_steps} MD steps')
            return {'attempt_count': sum((1 for x in direction_attempts if x['started_positive_switch'])), 'actual_md_steps': total_steps, 'actual_atomsteps': total_atoms, 'known_actual_lower_bound_md_steps': total_steps, 'known_actual_lower_bound_atomsteps': total_atoms, 'unknown_segment_reserved_upper_md_steps': 0, 'accounting_status': 'COMPLETE_REPLAY', 'attempts': direction_attempts, 'direction_attempts': direction_attempts, 'invocations': invocation_by_id, 'segments': segment_by_key, 'setups': setup_rows, 'setup_steps_by_phase': setup_total_by_phase, 'setup_prep_steps_by_id': setup_prep_by_id, 'setup_warm_steps_by_id': setup_warm_by_id, 'raw_ledger': ledger}
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_native_event_replay', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_native_event_replay', 'FAIL', str(exc))
        if reservation_upper is None and ledger is not None:
            try:
                total = 0
                for call in ledger.get('native_invocations', []):
                    original = audit__ledger_file_ref(outputs, call.get('original_input'), reference_root)
                    total += sum(audit__source_run_steps(original))
                reservation_upper = max(0, total - known_steps)
            except Exception:
                reservation_upper = None
        return {'attempt_count': None, 'actual_md_steps': None, 'actual_atomsteps': None, 'attempts': [], 'known_actual_lower_bound_md_steps': known_steps, 'known_actual_lower_bound_atomsteps': known_atoms, 'unknown_segment_reserved_upper_md_steps': reservation_upper, 'accounting_status': 'PARTIAL_UNKNOWN' if known_steps or reservation_upper else 'UNKNOWN'}

    def audit_verify_budget_and_roles(evidence: dict, ledger: dict, checks: list[dict], plan: dict) -> dict:
        if ledger['attempt_count'] is None:
            audit_add(checks, 'v2_budget_reconciliation', 'UNKNOWN', 'native ledger could not be replayed')
            return {}
        roles = {r: [] for r in audit_ROLE_MAP.values()}
        seeds = {r: set() for r in audit_ROLE_MAP.values()}
        snapshots = {r: set() for r in audit_ROLE_MAP.values()}
        run_records = {}
        dir_rows = evidence.get('directions')
        if not isinstance(dir_rows, list):
            audit_add(checks, 'v2_budget_reconciliation', 'UNKNOWN', 'campaign direction registry missing')
            return {}
        ledger_by_id = {str(a.get('attempt_id')): a for a in ledger.get('direction_attempts', [])}
        seen_direction_ids = set()
        for direction in dir_rows:
            attempt_id = str(direction.get('run_id') or direction.get('attempt_id') or '')
            attempt = ledger_by_id.get(attempt_id)
            if not attempt or attempt.get('attempt_kind', 'direction') != 'direction':
                audit_add(checks, 'v2_attempt_source_binding', 'UNKNOWN', f'{attempt_id}: direction not linked to native ledger attempt')
                continue
            if attempt_id in seen_direction_ids:
                audit_add(checks, 'v2_attempt_source_binding', 'FAIL', f'duplicate direction id {attempt_id}')
                continue
            seen_direction_ids.add(attempt_id)
            role = direction.get('role')
            if role not in audit_ROLE_MAP.values():
                audit_add(checks, 'v2_direction_role', 'FAIL', f'{attempt_id}: invalid role')
                continue
            role_row = {**attempt, **direction}
            for field in ('seed', 'snapshot_sha256', 'equilibrated_snapshot_sha256'):
                if role_row.get(field) is None and attempt.get(field) is not None:
                    role_row[field] = attempt[field]
            roles[role].append(role_row)
            seed_value = direction.get('seed') if direction.get('seed') is not None else attempt.get('seed')
            snap = direction.get('snapshot_sha256') if direction.get('snapshot_sha256') is not None else direction.get('equilibrated_snapshot_sha256', attempt.get('snapshot_sha256'))
            seed = str(seed_value)
            if not seed or seed == 'None':
                audit_add(checks, 'v2_seed_binding', 'UNKNOWN', f"{attempt['attempt_id']} missing seed")
            if not snap:
                audit_add(checks, 'v2_snapshot_binding', 'UNKNOWN', f"{attempt['attempt_id']} missing equilibrated snapshot SHA")
            seeds.setdefault(role, set()).add(seed)
            if snap:
                snapshots.setdefault(role, set()).add(snap)
            run_records[str(attempt.get('attempt_id'))] = attempt
            if audit_finite(direction.get('T_K', attempt.get('T_K'))) != 600 or audit_finite(direction.get('P_bar', attempt.get('P_bar'))) != 20000:
                audit_add(checks, 'v2_state_scope', 'FAIL', f"{attempt['attempt_id']} has wrong T/P")
            if direction.get('hamiltonian_sha256', attempt.get('hamiltonian_sha256')) != audit_PUBLIC_YACE:
                audit_add(checks, 'v2_attempt_hamiltonian', 'FAIL', f"{attempt['attempt_id']} wrong YACE")
            switch_segments = [s for s in attempt.get('linked_segments', []) if s.get('segment_kind') == 'fe_switch']
            if len(switch_segments) != 1:
                audit_add(checks, 'v2_switch_segment_binding', 'UNKNOWN', f"{attempt['attempt_id']} has no explicit switching segment refs")
            else:
                switch_steps = sum((int(s['steps']) for s in switch_segments))
                declared = direction.get('switch_steps')
                if declared is None or int(declared) != switch_steps:
                    audit_add(checks, 'v2_switch_segment_binding', 'FAIL', f"{attempt['attempt_id']} switch steps do not match native segments")
                cap = int(plan.get('native_method', {}).get('duration_switch_steps_per_direction', 40000))
                if switch_steps > cap:
                    audit_add(checks, 'v2_switching_cap', 'FAIL', f"{attempt['attempt_id']} switch exceeds frozen cap")
                if direction.get('status') == 'COMPLETE' and (not attempt.get('started_positive_switch')):
                    audit_add(checks, 'v2_direction_attempt_status', 'FAIL', f"{attempt['attempt_id']} marked complete without positive switching")
                expected_leg = 'forward' if direction.get('direction') == 'forward' else 'backward'
                if switch_segments[0].get('leg') not in (expected_leg, expected_leg[0].upper(), expected_leg[0]):
                    audit_add(checks, 'v2_switch_leg_binding', 'FAIL', f"{attempt['attempt_id']} does not reference its declared {expected_leg} leg")
            setup_id = str(direction.get('setup_id') or '')
            if not setup_id or not any((str(s.get('setup_id')) == setup_id for s in ledger.get('setups', []))):
                audit_add(checks, 'v2_setup_ancestry_binding', 'UNKNOWN', f"{attempt['attempt_id']} has no shared setup ancestry row")
            if str(direction.get('role')) != str(attempt.get('role')) or str(direction.get('phase')) != str(attempt.get('phase')) or str(direction.get('direction')) != str(attempt.get('direction')):
                audit_add(checks, 'v2_direction_ledger_binding', 'FAIL', f"{attempt['attempt_id']} role/phase/direction differs from global ledger")
        if seen_direction_ids != set(ledger_by_id):
            missing = sorted(set(ledger_by_id) - seen_direction_ids)
            audit_add(checks, 'v2_direction_ledger_coverage', 'UNKNOWN' if missing else 'FAIL', f'campaign rows and global direction-cycle inventory differ; unlisted={missing[:8]}')
        expected = {'baseline': 4, 'independent_repeat': 4, 'independent_reference': 4}
        for (role, count) in expected.items():
            if len(roles[role]) != count:
                audit_add(checks, 'v2_role_coverage', 'UNKNOWN', f'{role}: expected {count} attempts, saw {len(roles[role])}')
            seen = {(r.get('phase'), r.get('direction')) for r in roles[role]}
            want = {(p, d) for p in audit_PHASE_ATOMS for d in ('forward', 'backward')}
            if len(roles[role]) == 4 and seen != want:
                audit_add(checks, 'v2_role_direction_coverage', 'FAIL', f'{role}: direction rows are not exactly both phases × forward/backward')
        if len(roles['adaptive_size']) + len(roles['adaptive_duration']) != 4:
            audit_add(checks, 'v2_adaptive_role_coverage', 'UNKNOWN', 'exactly four S or four D attempts are required')
        if roles['adaptive_size'] and roles['adaptive_duration']:
            audit_add(checks, 'v2_adaptive_exclusivity', 'FAIL', 'S and D both used')
        cand_roles = ('baseline', 'independent_repeat', 'adaptive_size', 'adaptive_duration')
        cand_seeds = set().union(*(seeds[r] for r in cand_roles))
        cand_snaps = set().union(*(snapshots[r] for r in cand_roles))
        arows = roles['independent_reference']
        if any((seeds['independent_reference'] & seeds[r] for r in cand_roles)):
            audit_add(checks, 'v2_reference_seed_independence', 'FAIL', 'held-out reference reuses a candidate seed')
        else:
            try:
                (phase_seeds, phase_snapshots) = audit__reference_phase_sources(arows)
                audit_add(checks, 'v2_reference_seed_independence', 'PASS', 'two phase-specific A seeds shared by F/B, disjoint from candidate roles')
            except audit_UnknownEvidence as exc:
                audit_add(checks, 'v2_reference_seed_independence', 'UNKNOWN', str(exc))
            except audit_Mismatch as exc:
                audit_add(checks, 'v2_reference_seed_independence', 'FAIL', str(exc))
        if any((snapshots['independent_reference'] & snapshots[r] for r in cand_roles)):
            audit_add(checks, 'v2_reference_snapshot_independence', 'FAIL', 'held-out reference reuses a candidate snapshot')
        else:
            try:
                (_, phase_snapshots) = audit__reference_phase_sources(arows)
                audit_add(checks, 'v2_reference_snapshot_independence', 'PASS', 'two phase-specific A snapshots shared by F/B and disjoint from candidates')
            except audit_UnknownEvidence as exc:
                audit_add(checks, 'v2_reference_snapshot_independence', 'UNKNOWN', str(exc))
            except audit_Mismatch as exc:
                audit_add(checks, 'v2_reference_snapshot_independence', 'FAIL', str(exc))
        new_steps = ledger['actual_md_steps']
        attempt_count = ledger['attempt_count']
        if attempt_count > 16 or new_steps > 600000 or new_steps > 1000000:
            audit_add(checks, 'v2_campaign_caps', 'FAIL', f'attempts={attempt_count}, new MD={new_steps}')
        else:
            audit_add(checks, 'v2_campaign_caps', 'PASS', f'attempts={attempt_count}/16, new MD={new_steps}/600000 supplemental and /1000000 protocol')
        for (phase, steps) in ledger.get('setup_steps_by_phase', {}).items():
            if steps > int(plan.get('new_contract_caps', {}).get('setup_ancestry_md_steps_per_phase', 20000)):
                audit_add(checks, 'v2_grouped_setup_cap', 'FAIL', f'{phase}: shared setup/warm ancestry {steps} exceeds cap')
            else:
                audit_add(checks, 'v2_grouped_setup_cap', 'PASS', f'{phase}: source-replayed shared setup/warm steps={steps}')
        return {'roles': roles, 'candidate_seeds': cand_seeds, 'candidate_snapshots': cand_snaps, 'run_records': run_records, 'setup_steps_by_phase': ledger.get('setup_steps_by_phase', {}), 'native_invocations': ledger.get('invocations', {})}

    def audit_reconstruct_all_directions(outputs: audit_Path, evidence: dict, checks: list[dict]) -> list[dict]:
        result = []
        rows = audit_expand_direction_sources(outputs, evidence, checks)
        ledger_ref = evidence.get('native_event_ledger')
        try:
            ledger_doc = audit__load_json(audit__file_ref(outputs, ledger_ref))
            inv_rows = ledger_doc.get('native_invocations', [])
            replay_ledger = {'invocations': {str(x.get('invocation_id')): x for x in inv_rows if isinstance(x, dict)}}
        except Exception as exc:
            replay_ledger = None
            audit_add(checks, 'v2_lambda_native_source_binding', 'UNKNOWN', f'global invocation source inventory unavailable: {exc}')
        for record in rows:
            if record.get('status') != 'COMPLETE' or record.get('role') == 'independent_reference':
                continue
            try:
                result.append(audit_reconstruct_direction(outputs, record, ledger=replay_ledger))
            except audit_UnknownEvidence as exc:
                audit_add(checks, 'v2_L2_direction_G', 'UNKNOWN', f"{record.get('run_id')}: {exc}")
            except Exception as exc:
                audit_add(checks, 'v2_L2_direction_G', 'FAIL', f"{record.get('run_id')}: {exc}")
        if result:
            audit_add(checks, 'v2_L2_direction_G', 'PASS', f'independently reconstructed {len(result)} current-v2 direction G values')
        else:
            audit_add(checks, 'v2_L2_direction_G', 'UNKNOWN', 'no complete current-v2 candidate directions with raw curves/cells/H')
        return result

    def audit_expand_direction_sources(outputs: audit_Path, evidence: dict, checks: list[dict]) -> list[dict]:
        """Expand compact campaign rows through their hash-bound integration manifests.

        The campaign schema intentionally stores links in ``native_receipts``. One link
        must resolve to the matching per-direction ``integration-run.json``; raw lambda,
        cell and mean-H files are taken from that manifest and rehashed independently.
        """
        rows = evidence.get('directions', [])
        expanded = []
        if not isinstance(rows, list):
            audit_add(checks, 'v2_direction_source_manifest', 'UNKNOWN', 'campaign directions are not a list')
            return []
        for row in rows:
            merged = dict(row)
            integration = None
            for ref in row.get('native_receipts', []) if isinstance(row.get('native_receipts'), list) else []:
                try:
                    path = audit__file_ref(outputs, ref)
                    if path.name.endswith('integration-run.json'):
                        doc = audit__load_json(path)
                        if str(doc.get('run_id')) == str(row.get('run_id')):
                            integration = doc
                            merged['_integration_manifest_sha256'] = audit_sha(path)
                            break
                except audit_UnknownEvidence:
                    continue
            if integration is not None:
                for key in ('phase', 'T_K', 'P_bar', 'direction', 'replicate', 'cell_atoms', 'switching_steps', 'equilibration_steps', 'seed', 'calphy_master_seed', 'trace_path', 'trace_sha256', 'einstein_reference_data', 'einstein_reference_data_sha256', 'mean_h_thermo_path', 'mean_h_thermo_sha256', 'mean_cell_matrix_A', 'mean_cell_volume_A3', 'spring_constants_eV_per_A2', 'element_to_type', 'hamiltonian_sha256', 'switch_source_invocation', 'switch_run_index', 'npt_start_step', 'discard_steps', 'mean_h_native_source', 'mean_h_source_invocation'):
                    if key in integration and (key not in merged or merged[key] in (None, '')):
                        merged[key] = integration[key]
                merged['lambda_curve'] = {'path': integration.get('trace_path'), 'sha256': integration.get('trace_sha256')}
                merged['einstein_endpoint'] = {'path': integration.get('einstein_reference_data'), 'sha256': integration.get('einstein_reference_data_sha256')}
                mean_path = integration.get('mean_h_thermo_path')
                mean_sha = integration.get('mean_h_thermo_sha256')
                if mean_path and mean_sha:
                    merged['mean_h'] = {'path': mean_path, 'sha256': mean_sha}
                else:
                    merged['mean_h'] = None
                if merged.get('atoms') is None:
                    merged['atoms'] = integration.get('cell_atoms')
            elif not all((isinstance(row.get(k), dict) for k in ('lambda_curve', 'einstein_endpoint', 'mean_h'))):
                audit_add(checks, 'v2_direction_source_manifest', 'UNKNOWN', f"{row.get('run_id')}: no hash-bound matching integration-run.json/native raw source bundle")
            expanded.append(merged)
        if expanded and all((x.get('_integration_manifest_sha256') for x in expanded if x.get('status') == 'COMPLETE')):
            audit_add(checks, 'v2_direction_source_manifest', 'PASS', 'direction rows bound to matching hash-checked integration manifests')
        return expanded

    def audit_role_science(directions: list[dict], role: str) -> tuple[float, float]:
        selected = [x for x in directions if x['role'] == role]
        return audit_midpoint_and_hysteresis(selected)

    def audit__verify_candidate_calibration_freeze(outputs: audit_Path | None, directions: list[dict], evidence: dict, metrics: dict, checks: list[dict]) -> dict | None:
        try:
            if outputs is None:
                raise audit_UnknownEvidence('calibration freeze lacks a candidate outputs root')
            cal = evidence.get('calibration')
            ref = cal.get('freeze_receipt') if isinstance(cal, dict) else None
            if not isinstance(ref, dict):
                raise audit_UnknownEvidence('candidate E_cal has no immutable freeze receipt')
            path = audit__file_ref(outputs, ref)
            frozen = audit__load_json(path)
            if frozen.get('schema') != 'case06-candidate-calibration-freeze/v1':
                raise audit_Mismatch('candidate freeze schema mismatch')
            if frozen.get('campaign_id') != evidence.get('campaign_id') or frozen.get('protocol') != 'single-state-v2':
                raise audit_Mismatch('candidate freeze campaign/protocol mismatch')
            if frozen.get('hamiltonian_sha256') != audit_PUBLIC_YACE or frozen.get('matrix_sha256') != audit_source_matrix_sha():
                raise audit_Mismatch('candidate freeze Hamiltonian/current matrix binding mismatch')
            if frozen.get('T_K') != 600 or frozen.get('P_bar') != 20000:
                raise audit_Mismatch('candidate freeze is outside current state')
            stamp = frozen.get('frozen_utc')
            try:
                parsed = audit_datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError()
            except Exception as exc:
                raise audit_Mismatch('candidate freeze timestamp is not timezone-aware') from exc
            selected = frozen.get('selected_component')
            selected_role = {'size': 'adaptive_size', 'duration': 'adaptive_duration'}.get(selected)
            if selected_role is None or metrics.get('selected_component') != selected:
                raise audit_Mismatch('candidate freeze selected component differs from raw adaptive decision')
            for (key, value) in (('delta_g_baseline', metrics.get('delta_g_baseline')), ('delta_g_repeat', metrics.get('delta_g_repeat')), ('delta_g_selected', metrics.get('delta_g_selected')), ('H', metrics.get('H')), ('R', metrics.get('R')), ('E_selected', metrics.get('E_selected')), ('candidate_tolerance_eV_per_atom', metrics.get('E_cal'))):
                actual = audit_finite(frozen.get(key))
                if value is None or actual is None or abs(actual - float(value)) > 1e-12:
                    raise audit_Mismatch(f'candidate freeze {key} differs from independent raw reconstruction')
            declared = audit_finite(cal.get('candidate_tolerance_eV_per_atom'))
            if declared is None or abs(declared - float(metrics['E_cal'])) > 1e-12:
                raise audit_Mismatch('campaign calibration summary differs from raw E_cal')
            records = evidence.get('directions')
            if not isinstance(records, list):
                raise audit_UnknownEvidence('raw campaign direction rows absent for freeze audit')
            source_roles = {'baseline', 'independent_repeat', selected_role}
            rows = [r for r in records if isinstance(r, dict) and r.get('role') in source_roles]
            ids = [str(r.get('run_id') or '') for r in rows]
            if any((not x for x in ids)) or len(ids) != len(set(ids)):
                raise audit_Mismatch('freeze source run IDs are missing/duplicated')
            frozen_ids = frozen.get('source_run_ids')
            hashes = frozen.get('source_row_sha256')
            if not isinstance(frozen_ids, list) or set(map(str, frozen_ids)) != set(ids) or len(frozen_ids) != len(ids):
                raise audit_Mismatch('candidate freeze source IDs differ from B/R/selected source rows')
            if not isinstance(hashes, dict) or set(hashes) != set(ids):
                raise audit_Mismatch('candidate freeze source row hash inventory is incomplete')
            for row in rows:
                rid = str(row['run_id'])
                digest = audit_hashlib.sha256(audit_json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()
                if hashes.get(rid) != digest:
                    raise audit_Mismatch(f'candidate freeze raw row hash mismatch: {rid}')
            result = {'path': str(path.resolve()), 'sha256': audit_sha(path), 'frozen_utc': stamp, 'document': frozen}
            audit_add(checks, 'v2_candidate_calibration_freeze', 'PASS', 'E_cal and all source row hashes replay from B/R/selected raw rows')
            return result
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_candidate_calibration_freeze', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_candidate_calibration_freeze', 'FAIL', str(exc))
        return None

    def audit__validate_freeze_precedes_first_a(freeze: dict, private_invocations: dict, reference_root: audit_Path) -> None:
        try:
            frozen = audit_datetime.fromisoformat(str(freeze.get('frozen_utc')).replace('Z', '+00:00'))
            if frozen.tzinfo is None:
                raise ValueError()
        except Exception as exc:
            raise audit_Mismatch('candidate freeze timestamp is not timezone-aware') from exc
        starts = []
        for call in private_invocations.values() if isinstance(private_invocations, dict) else []:
            if not isinstance(call, dict) or call.get('role') not in ('A', 'independent_reference'):
                continue
            receipt_ref = call.get('execution_receipt')
            if not isinstance(receipt_ref, dict):
                raise audit_UnknownEvidence('A invocation lacks a hash-bound wrapper receipt')
            receipt = audit__load_json(audit__ledger_file_ref(reference_root, receipt_ref, reference_root))
            try:
                started = audit_datetime.fromisoformat(str(receipt.get('started_utc')).replace('Z', '+00:00'))
                if started.tzinfo is None:
                    raise ValueError()
                starts.append(started)
            except Exception as exc:
                raise audit_Mismatch('A wrapper receipt has invalid raw started_utc') from exc
        if not starts:
            raise audit_UnknownEvidence('private reference ledger has no raw A wrapper start time')
        if not frozen < min(starts):
            raise audit_Mismatch('candidate E_cal freeze occurred at or after first raw A wrapper start')

    def audit_verify_adaptive_and_error(directions: list[dict], evidence: dict, ledger: dict, checks: list[dict], outputs: audit_Path | None=None) -> dict:
        if not directions:
            audit_add(checks, 'v2_adaptive_rule', 'UNKNOWN', 'raw direction G values unavailable')
            return {}
        try:
            (dg_b, h_b) = audit_role_science(directions, 'baseline')
            (dg_r, h_r) = audit_role_science(directions, 'independent_repeat')
            h = max(h_b, h_r)
            repeat = abs(dg_b - dg_r)
            setup_by_id = {str(s.get('setup_id')): int(s.get('source_actual_steps', -1)) for s in ledger.get('setups', [])}
            prep_by_id = ledger.get('setup_prep_steps_by_id', {})
            b_rows = [r for r in evidence.get('directions', []) if r.get('role') == 'baseline']
            b_setup_ids = {str(r.get('setup_id')) for r in b_rows if r.get('setup_id')}
            setup = max((prep_by_id.get(sid, setup_by_id.get(sid, 0)) for sid in b_setup_ids), default=-1)
            adaptive = evidence.get('adaptive_decision', {})
            chosen = adaptive.get('selected_component')
            expected = 'duration' if h > repeat else 'size'
            baseline_setups = {str(r.get('setup_id')) for r in b_rows if r.get('setup_id')}
            baseline_setup_rows = [s for s in ledger.get('setups', []) if str(s.get('setup_id')) in baseline_setups]
            baseline_16k = len(baseline_setup_rows) == 2 and {s.get('phase') for s in baseline_setup_rows} == set(audit_PHASE_ATOMS) and all((setup_by_id.get(str(s.get('setup_id'))) == 16000 for s in baseline_setup_rows))
            if h > repeat and (not baseline_16k):
                audit_add(checks, 'v2_adaptive_rule', 'UNKNOWN', 'H>R indicates duration but both source-replayed B phase setups are not exactly 16k; stop unresolved')
                chosen_expected = 'stop_unresolved'
            else:
                chosen_expected = expected
            if adaptive.get('status') not in ('FROZEN', 'EXECUTED') or adaptive.get('rule', {}).get('sha256') is None:
                audit_add(checks, 'v2_adaptive_rule', 'UNKNOWN', 'predeclared adaptive rule/reference freeze evidence missing')
            elif chosen != chosen_expected:
                audit_add(checks, 'v2_adaptive_rule', 'FAIL', f'selected {chosen}; recomputed policy requires {chosen_expected}')
            else:
                audit_add(checks, 'v2_adaptive_rule', 'PASS', f'H={h:.12g}; R={repeat:.12g}; selected={chosen}')
            selected_role = 'adaptive_duration' if chosen == 'duration' else 'adaptive_size' if chosen == 'size' else None
            if not selected_role:
                audit_add(checks, 'v2_selected_error', 'UNKNOWN', 'adaptive component was not legally selected')
                return {'delta_g_baseline': dg_b, 'delta_g_repeat': dg_r, 'H': h, 'R': repeat}
            (dg_s, _) = audit_role_science(directions, selected_role)
            e_selected = abs(dg_s - dg_b)
            e_cal = h + repeat + e_selected
            if not all((math.isfinite(x) for x in (h, repeat, e_selected, e_cal))):
                raise audit_Mismatch('adaptive error envelope is nonfinite')
            output_rows = audit__read_csv(audit_Path(evidence['_outputs_root']), audit_DELTA_HEADER) if False else None
            terms = {'E_dir': h, 'E_repeat': repeat, 'E_selected': e_selected, 'E_cal': e_cal}
            calibration = evidence.get('calibration', {})
            selected_component = 'duration' if chosen == 'duration' else 'size' if chosen == 'size' else None
            freeze = audit__verify_candidate_calibration_freeze(outputs, directions, evidence, {'delta_g_baseline': dg_b, 'delta_g_repeat': dg_r, 'delta_g_selected': ds, 'H': h, 'R': repeat, 'E_selected': e_selected, 'E_cal': e_cal, 'selected_component': selected_component}, checks)
            declared = calibration.get('candidate_tolerance_eV_per_atom')
            if freeze is None:
                audit_add(checks, 'v2_calibrated_envelope', 'UNKNOWN', 'source-bound candidate freeze did not validate')
            elif declared is None or audit_finite(declared) is None:
                audit_add(checks, 'v2_calibrated_envelope', 'UNKNOWN', 'candidate E_cal not frozen/source-bound')
            elif abs(float(declared) - e_cal) > 1e-07:
                audit_add(checks, 'v2_calibrated_envelope', 'FAIL', 'declared E_cal differs from independently reconstructed H+R+selected effect')
            else:
                audit_add(checks, 'v2_calibrated_envelope', 'PASS', 'E_cal is the preregistered conservative sum; not a 95% CI')
            return {'delta_g_baseline': dg_b, 'delta_g_repeat': dg_r, 'delta_g_selected': dg_s, 'H': h, 'R': repeat, 'E_selected': e_selected, 'E_cal': e_cal, 'selected_component': selected_component, 'freeze_receipt': freeze}
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_adaptive_rule', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_adaptive_rule', 'FAIL', str(exc))
        return {}

    def audit__resolve_reference_path(ref_doc_path: audit_Path, ref: dict, outputs: audit_Path) -> audit_Path:
        ref_root = ref_doc_path.parent.resolve()
        path = audit__file_ref(ref_root, ref, external_root=ref_root)
        try:
            path.relative_to(outputs.resolve())
        except ValueError:
            return path
        raise audit_Mismatch('held-out reference artifact must stay outside candidate outputs')

    def audit_verify_reference(outputs: audit_Path, evidence: dict, metrics: dict, checks: list[dict], reference_path: audit_Path | None) -> dict:
        if reference_path is None:
            audit_add(checks, 'v2_L3_reference', 'UNKNOWN', 'held-out private same-H reference was not supplied')
            return {}
        try:
            reference_path = reference_path.resolve()
            try:
                reference_path.relative_to(outputs.resolve())
            except ValueError:
                pass
            else:
                raise audit_Mismatch('held-out reference descriptor must be outside candidate outputs')
            ref = audit__load_json(reference_path)
            if ref.get('schema') != 'case06-single-state-v2-independent-reference/v1':
                raise audit_UnknownEvidence('unsupported held-out reference schema')
            if ref.get('hamiltonian_sha256') != audit_PUBLIC_YACE or audit_finite(ref.get('T_K')) != 600 or audit_finite(ref.get('P_bar')) != 20000:
                raise audit_Mismatch('held-out reference T/P/Hamiltonian mismatch')
            if not metrics or any((k not in metrics for k in ('delta_g_baseline', 'E_cal'))):
                raise audit_UnknownEvidence('candidate calibration E_cal unavailable before reference comparison')
            runs = ref.get('directions')
            if not isinstance(runs, list):
                raise audit_UnknownEvidence('private reference requires raw direction records')
            (phase_seeds, phase_snapshots) = audit__reference_phase_sources(runs)
            reconstructed = []
            ref_root = reference_path.parent
            candidate_seeds = {str(x.get('seed')) for x in evidence.get('directions', []) if x.get('role') != 'independent_reference' and x.get('seed') is not None}
            candidate_snapshots = {str(x.get('snapshot_sha256') if x.get('snapshot_sha256') is not None else x.get('equilibrated_snapshot_sha256')) for x in evidence.get('directions', []) if x.get('role') != 'independent_reference' and x.get('snapshot_sha256', x.get('equilibrated_snapshot_sha256'))}
            if set(phase_seeds.values()) & candidate_seeds:
                raise audit_Mismatch('phase-level held-out reference master seed overlaps candidate source')
            if set(phase_snapshots.values()) & candidate_snapshots:
                raise audit_Mismatch('phase-level held-out reference snapshot overlaps candidate source')
            private_ledger_ref = ref.get('native_event_ledger')
            if not isinstance(private_ledger_ref, dict):
                raise audit_UnknownEvidence('private reference lacks its own native event ledger; metadata cannot certify raw source independence')
            private_checks = []
            private_ledger = audit_verify_native_ledger(ref_root, {'native_event_ledger': private_ledger_ref}, private_checks, ref_root)
            if private_ledger.get('actual_md_steps') is None:
                states = '; '.join((f"{x['status']}:{x['detail']}" for x in private_checks[:5]))
                raise audit_UnknownEvidence(f'private reference native ledger did not replay: {states}')
            freeze = metrics.get('freeze_receipt')
            if not isinstance(freeze, dict):
                raise audit_UnknownEvidence('raw-validated candidate calibration freeze is unavailable')
            descriptor_freeze = ref.get('candidate_calibration_freeze_ref')
            if not isinstance(descriptor_freeze, dict) or descriptor_freeze.get('sha256') != freeze.get('sha256'):
                raise audit_Mismatch('private descriptor freeze SHA differs from independently validated candidate freeze')
            descriptor_path = audit__ledger_file_ref(outputs, {**descriptor_freeze, 'namespace': 'candidate'})
            if descriptor_path.resolve() != audit_Path(freeze['path']).resolve():
                raise audit_Mismatch('private descriptor points to a different candidate freeze file')
            if ref.get('candidate_calibration_frozen_utc') != freeze.get('frozen_utc'):
                raise audit_Mismatch('private descriptor freeze timestamp differs from frozen candidate receipt')
            if audit_finite(ref.get('candidate_tolerance_eV_per_atom')) is None or abs(float(ref['candidate_tolerance_eV_per_atom']) - float(metrics['E_cal'])) > 1e-12:
                raise audit_Mismatch('private descriptor tolerance differs from the frozen independently recomputed E_cal')
            private_invocations = private_ledger.get('invocations', {})
            audit__validate_freeze_precedes_first_a(freeze, private_invocations, ref_root)
            private_replay = {'invocations': private_ledger.get('invocations', {})}
            ledger_attempts = {str(x.get('attempt_id')): x for x in private_ledger.get('direction_attempts', [])}
            for rec in runs:
                if rec.get('role') != 'independent_reference':
                    raise audit_Mismatch('reference raw row has wrong role')
                rec_seed = rec.get('seed') if rec.get('seed') is not None else rec.get('master_seed')
                if str(rec_seed) in candidate_seeds:
                    raise audit_Mismatch('reference seed overlaps candidate')
                snap = str(rec.get('snapshot_sha256') or '')
                if not snap or snap in candidate_snapshots:
                    raise audit_Mismatch('reference snapshot is missing or overlaps candidate')
                attempt = ledger_attempts.get(str(rec.get('run_id')))
                if not attempt:
                    raise audit_Mismatch('private reference direction is absent from its independently replayed ledger')
                for field in ('role', 'phase', 'direction'):
                    if str(attempt.get(field)) != str(rec.get(field)):
                        raise audit_Mismatch(f'private reference {field} differs between raw record and native ledger')
                reconstructed.append(audit_reconstruct_direction(ref_root, rec, source_root=ref_root, ledger=private_replay))
            (dg_a, _) = audit_midpoint_and_hysteresis(reconstructed)
            diff = abs(dg_a - metrics['delta_g_baseline'])
            if ref.get('unsealed_after_candidate_calibration') is not True:
                raise audit_UnknownEvidence('reference is not certified blinded until E_cal was frozen')
            if diff > metrics['E_cal'] + 1e-12:
                audit_add(checks, 'v2_L3_heldout_match', 'FAIL', f"|ΔG_A−ΔG_B|={diff:.12g} exceeds frozen E_cal={metrics['E_cal']:.12g}")
            else:
                audit_add(checks, 'v2_L3_heldout_match', 'PASS', f"held-out difference {diff:.12g} ≤ frozen E_cal {metrics['E_cal']:.12g}; envelope is not a 95% CI")
            audit_add(checks, 'v2_L3_reference', 'PASS', 'four A curves independently reconstructed from a private source-bound native ledger; two phase preparations shared by F/B')
            return {'delta_g_reference': dg_a, 'heldout_difference': diff, 'E_cal': metrics['E_cal']}
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_L3_reference', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_L3_reference', 'FAIL', str(exc))
        return {}

    def audit__check_csv_projection(outputs: audit_Path, evidence: dict, directions: list[dict], metrics: dict, checks: list[dict]) -> None:
        for (filename, header) in (('gibbs_free_energy.csv', audit_GIBBS_HEADER), ('delta_g.csv', audit_DELTA_HEADER)):
            path = outputs / filename
            if not path.is_file():
                audit_add(checks, f'v2_{filename}', 'UNKNOWN', 'required output CSV absent')
                continue
            try:
                rows = audit__read_csv(path, header)
                if filename == 'gibbs_free_energy.csv':

                    def key(row):
                        phase = str(row.get('phase') or '')
                        direction = str(row.get('direction') or '')
                        (t, p, atoms) = (finite(row.get(k)) for k in ('T_K', 'P_bar', 'cell_atoms'))
                        rep = row.get('replicate')
                        if str(rep) not in ('B', 'R', 'S', 'D'):
                            rep = audit_ROLE_TO_REPLICATE.get(str(row.get('role')), rep)
                        rep = str(rep) if rep is not None else ''
                        if not phase or direction not in ('forward', 'backward') or None in (t, p, atoms) or (rep not in ('B', 'R', 'S', 'D')):
                            raise audit_UnknownEvidence('Gibbs row lacks the public composite identity fields')
                        return (phase, t, p, rep, direction, int(atoms))
                    candidate = [r for r in directions if r.get('role') != 'independent_reference']
                    registered = [r for r in evidence.get('directions', []) if isinstance(r, dict) and r.get('role') != 'independent_reference']
                    if not candidate:
                        audit_add(checks, 'v2_gibbs_projection', 'UNKNOWN', 'no independently reconstructed direction values')
                    elif len(registered) != len(candidate) or any((r.get('status') != 'COMPLETE' for r in registered)):
                        audit_add(checks, 'v2_gibbs_projection', 'UNKNOWN', 'candidate registry is incomplete or not every candidate direction has an independently reconstructed raw G')
                    else:
                        registered_keys = {key(r) for r in registered}
                        if len(registered_keys) != len(registered) or {key(r) for r in candidate} != registered_keys:
                            raise audit_UnknownEvidence('raw-reconstructed directions do not cover the registered candidate composite keys')
                        by_key = {}
                        for raw in candidate:
                            k = key(raw)
                            if k in by_key:
                                raise audit_UnknownEvidence(f'direction registry composite key is ambiguous: {k}')
                            by_key[k] = raw
                        csv_by_key = {}
                        for row in rows:
                            k = key(row)
                            if k in csv_by_key:
                                raise audit_Mismatch(f'Gibbs CSV duplicates public composite key {k}')
                            csv_by_key[k] = row
                        if set(csv_by_key) != set(by_key):
                            raise audit_UnknownEvidence('Gibbs CSV rows do not one-to-one match candidate directions by phase/T/P/replicate/direction/atoms')
                        if any((r.get('status') not in ('COMPLETE', 'ADMITTED') for r in rows)):
                            raise audit_UnknownEvidence('Gibbs CSV contains a non-complete scientific row')
                        matched = True
                        for (k, raw) in by_key.items():
                            value = audit_finite(csv_by_key[k].get('G_eV_per_atom'))
                            if value is None or abs(value - raw['G_eV_per_atom']) > 1e-07:
                                audit_add(checks, 'v2_gibbs_projection', 'FAIL', f'{k}: CSV G differs from raw reconstruction')
                                matched = False
                        if matched:
                            audit_add(checks, 'v2_gibbs_projection', 'PASS', 'direction rows cross-checked by public composite key; no run_id column assumed')
                elif not metrics:
                    audit_add(checks, 'v2_delta_g_projection', 'UNKNOWN', 'candidate ΔG not independently derived')
                else:
                    rows20 = [r for r in rows if audit_finite(r.get('T_K')) == 600 and audit_finite(r.get('P_bar')) == 20000]
                    if len(rows20) != 1:
                        audit_add(checks, 'v2_delta_g_projection', 'UNKNOWN', 'expected one current state row')
                    else:
                        r = rows20[0]
                        v = audit_finite(r.get('G_coesite_minus_G_alpha_eV_per_atom'))
                        u = audit_finite(r.get('combined_uncertainty_eV_per_atom'))
                        if v is None or abs(v - metrics['delta_g_baseline']) > 1e-07:
                            audit_add(checks, 'v2_delta_g_projection', 'FAIL', 'delta_g.csv does not match independently reconstructed baseline ΔG')
                        elif metrics.get('E_cal') is None:
                            audit_add(checks, 'v2_delta_g_projection', 'UNKNOWN', 'E_cal envelope is unavailable')
                        elif u is None or abs(u - metrics['E_cal']) > 1e-07:
                            audit_add(checks, 'v2_delta_g_projection', 'FAIL', 'combined uncertainty does not match E_cal envelope')
                        else:
                            terms = {'repeat_uncertainty_eV_per_atom': metrics.get('R'), 'direction_uncertainty_eV_per_atom': metrics.get('H')}
                            selected = metrics.get('selected_component')
                            terms['switching_uncertainty_eV_per_atom'] = metrics.get('E_selected') if selected == 'duration' else None
                            terms['finite_size_uncertainty_eV_per_atom'] = metrics.get('E_selected') if selected == 'size' else None
                            bad = False
                            unknown_term = False
                            for (column, want) in terms.items():
                                actual = audit_finite(r.get(column))
                                if want is None:
                                    if actual is not None:
                                        audit_add(checks, 'v2_delta_g_projection', 'FAIL', f'unselected {column} was reported as a number')
                                        bad = True
                                elif actual is None:
                                    audit_add(checks, 'v2_delta_g_projection', 'UNKNOWN', f'required measured component {column} is absent')
                                    unknown_term = True
                                elif abs(actual - want) > 1e-07:
                                    audit_add(checks, 'v2_delta_g_projection', 'FAIL', f'{column} differs from raw-reconstructed component')
                                    bad = True
                            if not bad and (not unknown_term):
                                audit_add(checks, 'v2_delta_g_projection', 'PASS', 'ΔG and all measured error components match raw reconstruction; unselected term remains unknown')
            except audit_UnknownEvidence as exc:
                audit_add(checks, f'v2_{filename}', 'UNKNOWN', str(exc))
            except Exception as exc:
                audit_add(checks, f'v2_{filename}', 'FAIL', str(exc))

    def audit__check_required_product_artifacts(outputs: audit_Path, ledger: dict, metrics: dict, checks: list[dict]) -> None:
        """Check publication products exist and cannot overstate independently replayed evidence."""
        summary_path = outputs / 'summary.json'
        allocation_path = outputs / 'allocation_log.json'
        error_path = outputs / 'error_budget.csv'
        missing = [p.name for p in (summary_path, allocation_path, error_path) if not p.is_file()]
        figure_dir = outputs / 'figures'
        if not figure_dir.is_dir() or not any((p.is_file() for p in figure_dir.rglob('*'))):
            missing.append('figures/')
        if missing:
            audit_add(checks, 'v2_required_product_artifacts', 'UNKNOWN', f'missing required contract outputs: {missing}')
            return
        try:
            summary = audit__load_json(summary_path)
            allocation = audit__load_json(allocation_path)
            actual = ledger.get('actual_md_steps')
            atomsteps = ledger.get('actual_atomsteps')
            if actual is not None and (summary.get('total_md_steps') != actual or summary.get('total_atom_steps') != atomsteps):
                raise audit_Mismatch('summary native step totals differ from independently replayed global ledger')
            if summary.get('status') in ('COMPLETE', 'PASS', 'ADMITTED') and (ledger.get('actual_md_steps') is None or summary.get('author_coverage_status') not in ('COMPLETE',)):
                raise audit_Mismatch('summary overstates completion without verifier-backed author coverage')
            with error_path.open(newline='', encoding='utf-8') as stream:
                reader = audit_csv.DictReader(stream)
                rows = list(reader)
                required = {'quantity', 'estimate_eV_per_atom', 'status', 'reason'}
                if not required.issubset(set(reader.fieldnames or [])):
                    raise audit_UnknownEvidence('error_budget.csv lacks contract columns')
            category_tokens = {'repeat': ('repeat',), 'direction': ('direction', 'hysteresis'), 'switching': ('switch',), 'finite_size': ('finite_size', 'finite size')}
            categories = {k: [] for k in category_tokens}
            for row in rows:
                label = str(row.get('quantity', '')).strip().lower()
                for (category, tokens) in category_tokens.items():
                    if any((token in label for token in tokens)):
                        categories[category].append(row)
                if str(row.get('status', '')).upper() in ('UNKNOWN', 'UNMEASURED', 'NOT_MEASURED'):
                    val = audit_finite(row.get('estimate_eV_per_atom'))
                    if val is not None:
                        raise audit_Mismatch(f"unknown error component {row.get('quantity')} is reported numerically")
            expected = {'repeat': metrics.get('R'), 'direction': metrics.get('H'), 'switching': metrics.get('E_selected') if metrics.get('selected_component') == 'duration' else None, 'finite_size': metrics.get('E_selected') if metrics.get('selected_component') == 'size' else None}
            unresolved = []
            for (category, matched) in categories.items():
                if len(matched) != 1:
                    unresolved.append(f'{category}: expected one distinct error-budget row, found {len(matched)}')
                    continue
                row = matched[0]
                actual = audit_finite(row.get('estimate_eV_per_atom'))
                want = expected[category]
                if want is None:
                    if actual is not None or str(row.get('status', '')).upper() not in ('UNKNOWN', 'UNMEASURED', 'NOT_MEASURED'):
                        raise audit_Mismatch(f'unselected {category} error source must remain explicitly UNKNOWN, not numeric/zero')
                elif actual is None:
                    unresolved.append(f'{category}: raw-recomputed measured error estimate missing')
                elif abs(actual - want) > 1e-07:
                    raise audit_Mismatch(f'error_budget {category} estimate differs from verifier-recomputed value')
            if unresolved:
                audit_add(checks, 'v2_error_budget_projection', 'UNKNOWN', '; '.join(unresolved))
            else:
                audit_add(checks, 'v2_error_budget_projection', 'PASS', 'four distinct error components reconcile; unselected systematic remains UNKNOWN')
            if not isinstance(allocation, dict):
                raise audit_UnknownEvidence('allocation_log.json is not an object')
            audit_add(checks, 'v2_required_product_artifacts', 'PASS', f'summary/allocation/error budget/figures present; totals cross-check actual={actual}, atomsteps={atomsteps}')
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_required_product_artifacts', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_required_product_artifacts', 'FAIL', str(exc))

    def audit_verify(outputs: audit_Path, campaign_evidence_path: audit_Path | None=None, reference_path: audit_Path | None=None, plan_path: audit_Path=audit_DEFAULT_PLAN, extension_path: audit_Path=audit_DEFAULT_EXTENSION) -> dict:
        outputs = outputs.resolve()
        checks = []
        try:
            plan = audit_load_current_plan(plan_path)
            audit_add(checks, 'v2_plan', 'PASS', f"loaded {plan['schema']}")
        except Exception as exc:
            plan = {}
            audit_add(checks, 'v2_plan', 'UNKNOWN', str(exc))
        evidence_path = campaign_evidence_path or outputs / 'campaign-evidence.json'
        try:
            evidence = audit__load_json(evidence_path)
        except Exception as exc:
            evidence = {}
            audit_add(checks, 'v2_campaign_evidence', 'UNKNOWN', str(exc))
        if evidence:
            audit__check_campaign_identity(outputs, evidence, plan, extension_path, checks)
            audit_verify_public_geometry(outputs, evidence, plan, checks)
            manifest_ref = evidence.get('candidate_manifest')
            try:
                mp = audit__file_ref(outputs, manifest_ref)
                audit_verify_output_manifest(outputs, mp, checks)
            except audit_UnknownEvidence as exc:
                audit_add(checks, 'v2_output_file_inventory', 'UNKNOWN', str(exc))
            except Exception as exc:
                audit_add(checks, 'v2_output_file_inventory', 'FAIL', str(exc))
            ref_root = reference_path.resolve().parent if reference_path is not None else None
            ledger = audit_verify_native_ledger(outputs, evidence, checks, ref_root)
            role_data = audit_verify_budget_and_roles(evidence, ledger, checks, plan) if plan else {}
            directions = audit_reconstruct_all_directions(outputs, evidence, checks)
            campaign_id = evidence.get('campaign_id')
            raw_ledger = ledger.get('raw_ledger', {})
            invocations = ledger.get('invocations', {})
            if raw_ledger and (raw_ledger.get('campaign_id') not in (None, campaign_id) or raw_ledger.get('protocol') not in (None, 'single-state-v2')):
                audit_add(checks, 'v2_historical_row_exclusion', 'FAIL', 'attempt ledger contains unbound/historical protocol rows')
            else:
                audit_add(checks, 'v2_historical_row_exclusion', 'PASS', 'only immutable current campaign id/protocol rows are counted')
            metrics = audit_verify_adaptive_and_error(directions, evidence, ledger, checks, outputs)
            ref_result = audit_verify_reference(outputs, evidence, metrics, checks, reference_path)
            audit__check_csv_projection(outputs, evidence, directions, metrics, checks)
            audit__check_required_product_artifacts(outputs, ledger, metrics, checks)
            audit_verify_science_gates(outputs, evidence, role_data, checks, ledger, ref_root)
            audit_verify_active_time(outputs, evidence, extension_path, checks)
        else:
            audit_add(checks, 'v2_historical_artifacts', 'UNKNOWN', 'no campaign evidence; historical Case-08 artifacts cannot be admitted into current v2')
            ledger = {'attempt_count': None, 'actual_md_steps': None, 'actual_atomsteps': None, 'attempts': []}
            metrics = {}
            ref_result = {}
        blocking_checks = [x for x in checks if x.get('blocking', True)]
        statuses = [x['status'] for x in blocking_checks]
        if 'FAIL' in statuses:
            status = 'FAIL'
            code = 1
        elif not statuses or any((x in statuses for x in ('UNKNOWN', 'PARTIAL'))):
            status = 'UNKNOWN'
            code = 2
        else:
            status = 'ELIGIBLE'
            code = 0
        unresolved_precision = any((x.get('blocking') is False and x.get('status') == 'UNKNOWN' for x in checks))
        return {'schema': 'case06-single-state-v2-verification/v1', 'verifier': 'packages/case-06/tests/verify_v2.py', 'status': status, 'exit_code': code, 'candidate_status': 'NOT_COMPLETE' if status != 'ELIGIBLE' else 'EVIDENCE_ELIGIBLE_CLAIM_UNRESOLVED' if unresolved_precision else 'CANDIDATE_EVIDENCE_ELIGIBLE', 'scientific_resolution_status': 'UNRESOLVED' if unresolved_precision else 'MEASURED' if status == 'ELIGIBLE' else 'UNKNOWN', 'author_coverage_status': 'PARTIAL', 'historical_budget_status': 'EXHAUSTED_NOT_COMPLETE', 'historical_lifetime_union': 'UNKNOWN', 'campaign_evidence': str(evidence_path), 'native_accounting': ledger, 'reconstructed_adaptive_metrics': metrics, 'reference_metrics': ref_result, 'checks': checks}

    def audit__source_output_bound(outputs: audit_Path, ref: dict, invocation_ref: dict, invocations: dict, *, allowed_kinds: tuple[str, ...], reference_root: audit_Path | None=None) -> tuple[audit_Path, dict]:
        if not isinstance(invocation_ref, dict):
            raise audit_UnknownEvidence('raw source lacks invocation reference')
        iid = str(invocation_ref.get('invocation_id') or '')
        idx = invocation_ref.get('run_index')
        if not iid or idx is None:
            raise audit_UnknownEvidence('raw source invocation/run index is missing')
        call = invocations.get(iid)
        if not isinstance(call, dict):
            raise audit_Mismatch('raw source invocation is absent from replayed global ledger')
        try:
            (segment, position) = audit__segment_for_native_ref(call, invocation_ref)
        except Exception as exc:
            raise audit_Mismatch('raw source run index is absent from invocation') from exc
        kind = segment.get('segment_kind', segment.get('kind'))
        if kind not in allowed_kinds:
            raise audit_Mismatch(f'raw source is linked to incompatible native stage {kind!r}')
        path = audit__ledger_file_ref(outputs, ref, reference_root)
        listed = call.get('native_outputs', call.get('outputs', {}))
        if isinstance(listed, dict):
            listed = list(listed.values())
        out = None
        for item in listed if isinstance(listed, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                item_path = audit__ledger_file_ref(outputs, item, reference_root)
            except (audit_Mismatch, audit_UnknownEvidence):
                continue
            if item_path.resolve() == path.resolve() and item.get('sha256') == ref.get('sha256'):
                out = item
                break
        if not isinstance(out, dict):
            raise audit_UnknownEvidence('raw scientific source is not enumerated as an output of the linked invocation')
        return (path, {**call, '_resolved_run_segment': segment, '_resolved_run_position': position})

    def audit__segment_for_native_ref(call: dict, ref: dict) -> tuple[dict, int]:
        """Resolve the driver's one-based native marker index, never a list offset.

        Native RUN markers are numbered from 1.  Some early verifier fixtures used
        zero-based arrays without an explicit marker index; retain that format only
        as a compatibility fallback when the segment rows carry no index at all.
        """
        raw = ref.get('run_index')
        if raw is None:
            raise audit_Mismatch('native segment reference has no run_index')
        wanted = int(raw)
        segs = call.get('run_segments', call.get('run_plan', []))
        if not isinstance(segs, list):
            raise audit_Mismatch('native invocation run_segments is not a list')
        indexed = []
        has_explicit_index = False
        for (pos, seg) in enumerate(segs):
            if not isinstance(seg, dict):
                continue
            marker = seg.get('run_index', seg.get('native_run_index', seg.get('index')))
            if marker is not None:
                has_explicit_index = True
                if int(marker) == wanted:
                    indexed.append((seg, pos))
        if len(indexed) == 1:
            return indexed[0]
        if len(indexed) > 1:
            raise audit_Mismatch('native marker run_index is duplicated within invocation')
        if has_explicit_index:
            raise audit_Mismatch('native marker run_index is not present in invocation')
        name = ref.get('native_segment_name', ref.get('segment_name'))
        if name is not None:
            named = [(seg, pos) for (pos, seg) in enumerate(segs) if isinstance(seg, dict) and seg.get('native_segment_name', seg.get('segment_name')) == name]
            if len(named) == 1:
                return named[0]
            if len(named) > 1:
                raise audit_Mismatch('native segment name is duplicated within invocation')
        if 1 <= wanted <= len(segs):
            seg = segs[wanted - 1]
            if isinstance(seg, dict):
                return (seg, wanted - 1)
        if wanted == 0 and len(segs) == 1 and isinstance(segs[0], dict):
            return (segs[0], 0)
        raise audit_Mismatch('native marker run_index is not present in invocation')

    def audit__require_native_ave_time_source(outputs: audit_Path, call: dict, filename: str, cadence: int, reference_root: audit_Path | None=None) -> None:
        """Check the executed LAMMPS input actually creates the named raw table."""
        ref = call.get('executed_input')
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('native executed input not retained in global invocation')
        path = audit__ledger_file_ref(outputs, ref, reference_root)
        found = []
        for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
            line = audit__strip_lammps_comment(raw).strip()
            parts = line.split()
            if len(parts) >= 8 and parts[0] == 'fix' and ('ave/time' in parts):
                j = parts.index('ave/time')
                if len(parts) > j + 4 and parts[j + 1:j + 4] == [str(cadence), '1', str(cadence)] and any((parts[k:k + 2] == ['file', filename] for k in range(j + 4, len(parts) - 1))):
                    found.append((line, parts, j))
        if len(found) != 1:
            raise audit_Mismatch(f'executed native input must bind exactly one fix ave/time {cadence} 1 {cadence} to {filename}')
        (line, parts, j) = found[0]
        if not audit_re.search('\\bformat\\s+["\\\']\\s*%\\.16g["\\\']', line):
            raise audit_UnknownEvidence(f'native ave/time source {filename} does not declare the frozen leading-space %.16g format')
        if filename == 'case06-npt-fullcell-10step.dat':
            expected = [f'v_c_{x}' for x in ('lx', 'ly', 'lz', 'xy', 'xz', 'yz', 'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz', 'temp')]
            try:
                file_index = next((k for k in range(j + 4, len(parts) - 1) if parts[k:k + 2] == ['file', filename]))
            except StopIteration:
                raise audit_Mismatch('dense NPT fix loses its native file argument')
            observed = parts[j + 4:file_index]
            if observed != expected:
                raise audit_Mismatch('dense NPT ave/time variables/order differ from the frozen full-cell schema')

    def audit__script_binds_ave_time(path: audit_Path, filename: str, cadence: int) -> bool:
        text = path.read_text(encoding='utf-8', errors='replace')
        if not audit_re.search('(?m)^\\s*variable\\s+c_temp\\s+equal\\s+temp\\s*(?:#.*)?$', text):
            return False
        for raw in text.splitlines():
            parts = audit__strip_lammps_comment(raw).split()
            if 'ave/time' not in parts:
                continue
            j = parts.index('ave/time')
            if parts[0:1] == ['fix'] and len(parts) > j + 4 and (parts[j + 1:j + 4] == [str(cadence), '1', str(cadence)]) and (f'v_c_temp' in parts[j + 4:]) and any((parts[k:k + 2] == ['file', filename] for k in range(j + 4, len(parts) - 1))):
                return True
        return False

    def audit__require_native_dump_source(outputs: audit_Path, call: dict, filename: str, cadence: int, reference_root: audit_Path | None=None) -> None:
        ref = call.get('executed_input')
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('native executed input missing for trajectory source')
        path = audit__ledger_file_ref(outputs, ref, reference_root)
        found = []
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        expected = ['id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz', 'vx', 'vy', 'vz']
        for raw in lines:
            line = audit__strip_lammps_comment(raw).strip()
            parts = line.split()
            if len(parts) >= 7 and parts[0] == 'dump' and (parts[3] == 'custom') and (parts[4] == str(cadence)) and (parts[5] == filename):
                if parts[6:] != expected:
                    raise audit_Mismatch(f'native dump {filename} columns differ from exact ID/type/xyz/image/velocity contract')
                found.append(parts[1])
        if len(found) != 1:
            raise audit_Mismatch(f'executed native input must bind exactly one custom dump cadence {cadence} to {filename}')
        dump_id = found[0]
        mods = []
        for raw in lines:
            line = audit__strip_lammps_comment(raw).strip()
            parts = line.split()
            if len(parts) > 2 and parts[0] == 'dump_modify' and (parts[1] == dump_id):
                mods.append(parts[2:])
        if len(mods) != 1:
            raise audit_UnknownEvidence(f'native dump {filename} lacks one source-bound dump_modify precision/order declaration')
        options = mods[0]
        if not all((pair in [options[i:i + 2] for i in range(max(0, len(options) - 1))] for pair in (['sort', 'id'], ['format', 'float']))):
            raise audit_Mismatch(f'native dump {filename} is not sorted by atom ID or lacks float formatting')
        try:
            fmt_index = options.index('format')
        except ValueError:
            raise audit_Mismatch(f'native dump {filename} lacks numeric output format')
        if options[fmt_index:fmt_index + 3] != ['format', 'float', '%.16g'] or 'first' not in options or options[options.index('first') + 1:options.index('first') + 2] != ['yes']:
            raise audit_UnknownEvidence(f'native dump {filename} must retain first frame with explicit %.16g float format')

    def audit__read_mean_h_components(path: audit_Path) -> list[list[float]]:
        with path.open(newline='', encoding='utf-8') as stream:
            reader = audit_csv.DictReader(stream)
            rows = list(reader)
            fields = set(reader.fieldnames or [])
        alias = ('lx_A', 'ly_A', 'lz_A', 'xy_A', 'xz_A', 'yz_A')
        alternatives = tuple((next((name for name in options if name in fields), '') for options in (('lx_A', 'lx'), ('ly_A', 'ly'), ('lz_A', 'lz'), ('xy_A', 'xy'), ('xz_A', 'xz'), ('yz_A', 'yz'))))
        if not rows or any((not x for x in alternatives)):
            raise audit_UnknownEvidence('retained mean-H source lacks six labeled cell components')
        values = [[finite(r[k]) for k in alternatives] for r in rows]
        if any((any((x is None for x in row)) for row in values)):
            raise audit_Mismatch('mean-H source contains nonfinite cell component')
        mean = [sum((row[j] for row in values)) / len(values) for j in range(6)]
        return [[mean[0], 0.0, 0.0], [mean[3], mean[1], 0.0], [mean[4], mean[5], mean[2]]]

    def audit__native_type_masses(call: dict, outputs: audit_Path, reference_root: audit_Path | None=None) -> dict[int, float]:
        ref = call.get('executed_input')
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('executed native input missing for mass binding')
        path = audit__ledger_file_ref(outputs, ref, reference_root)
        found = {}
        for raw in path.read_text(encoding='utf-8', errors='strict').splitlines():
            line = audit__strip_lammps_comment(raw).strip()
            m = audit_re.fullmatch('mass\\s+([12])\\s+([-+0-9.eE]+)', line, audit_re.I)
            if m:
                typ = int(m.group(1))
                val = audit_finite(m.group(2))
                if typ in found:
                    raise audit_Mismatch('native script redefines an element mass')
                found[typ] = val
        if set(found) != {1, 2} or abs(found[1] - 15.999) > 1e-09 or abs(found[2] - 28.085) > 1e-09:
            raise audit_UnknownEvidence('native executed input does not source-bind frozen O/Si masses 15.999/28.085')
        return found

    def audit__minimum_triclinic_face(rows: list[dict[str, float]]) -> float:
        min_h = float('inf')
        for r in rows:
            a = (r['lx'], 0.0, 0.0)
            b = (r['xy'], r['ly'], 0.0)
            c = (r['xz'], r['yz'], r['lz'])
            cross = lambda u, v: (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            norm = lambda v: math.sqrt(sum((x * x for x in v)))
            volume = r['lx'] * r['ly'] * r['lz']
            if volume <= 0:
                raise audit_Mismatch('NPT cell determinant is nonpositive')
            min_h = min(min_h, volume / norm(cross(b, c)), volume / norm(cross(c, a)), volume / norm(cross(a, b)))
        return min_h

    def audit__acf_interval(values: list[float]) -> dict[str, float]:
        n = len(values)
        ess = audit__geyer_ess(values)
        if not audit_math.isfinite(ess):
            raise audit_UnknownEvidence('frozen Geyer ESS requires at least four finite observations')
        ess = max(1.0, min(float(n), ess))
        try:
            from scipy.stats import t as student_t
            import statistics
        except Exception as exc:
            raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
        half = float(student_t.ppf(0.975, max(1, int(audit_math.floor(ess)) - 1))) * statistics.stdev(values) / audit_math.sqrt(ess) if n > 1 and ess > 1 else 0.0
        return {'ess': ess, 'ci95_halfwidth': half}

    def audit__student_t_mean_ci(values: list[float]) -> tuple[float, float]:
        if len(values) < 2:
            raise audit_UnknownEvidence('at least two blocks are required for a t interval')
        try:
            from scipy.stats import t as student_t
            import statistics
        except Exception as exc:
            raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
        mean = sum(values) / len(values)
        return (mean, float(student_t.ppf(0.975, len(values) - 1)) * statistics.stdev(values) / audit_math.sqrt(len(values)))

    def audit__geyer_ess(values: list[float]) -> float:
        """Frozen initial-positive adjacent-pair ESS used by the v2 scientific gates."""
        x = list(map(float, values))
        n = len(x)
        if n < 4 or not all((math.isfinite(v) for v in x)):
            return float('nan')
        mean = sum(x) / n
        z = [v - mean for v in x]
        c0 = sum((v * v for v in z)) / n
        if c0 <= 0:
            return float(n)
        rho = [1.0]
        for k in range(1, n // 2 + 1):
            rho.append(sum((z[i] * z[i + k] for i in range(n - k))) / ((n - k) * c0))
        tau = 1.0
        for k in range(1, len(rho), 2):
            pair = rho[k] + (rho[k + 1] if k + 1 < len(rho) else 0.0)
            if pair <= 0:
                break
            tau += 2.0 * pair
        return max(1.0, min(float(n), n / tau))

    def audit__mean_ci_ess(values: list[float]) -> dict[str, float]:
        ess = audit__geyer_ess(values)
        if not audit_math.isfinite(ess) or ess <= 2:
            raise audit_UnknownEvidence('frozen ESS is insufficient to form a t interval')
        try:
            from scipy.stats import t as student_t
            import statistics
        except Exception as exc:
            raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
        mean = sum(values) / len(values)
        half = float(student_t.ppf(0.975, max(1, int(audit_math.floor(ess)) - 1))) * statistics.stdev(values) / audit_math.sqrt(ess)
        return {'mean': mean, 'ess': ess, 'ci95_low': mean - half, 'ci95_high': mean + half}

    def audit_recompute_v2_fixed_h_temperature(path: audit_Path) -> dict:
        rows = []
        for (line_no, line) in enumerate(path.read_text(encoding='utf-8', errors='strict').splitlines(), 1):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            fields = s.split()
            if len(fields) != 2:
                raise audit_Mismatch(f'{path.name}:{line_no}: fixed-H temperature must have exactly step,T columns')
            (step, temp) = (audit_finite(fields[0]), audit_finite(fields[1]))
            if step is None or temp is None or not step.is_integer():
                raise audit_Mismatch(f'{path.name}:{line_no}: nonfinite or non-integer fixed-H temperature row')
            rows.append((int(step), temp))
        expected = list(range(11020, 16001, 20))
        steps = [x[0] for x in rows]
        if len(rows) == 251 and steps == [11000] + expected:
            rows = rows[1:]
            steps = steps[1:]
        if steps != expected or len(rows) != 250:
            raise audit_Mismatch('fixed-H temperature must be 250 native samples at steps 11020..16000/20, optionally preceded by one initial boundary row')
        values = [x[1] for x in rows]
        first = values[:125]
        second = values[125:]
        full_ci = audit__mean_ci_ess(values)
        first_ci = audit__mean_ci_ess(first)
        second_ci = audit__mean_ci_ess(second)
        import statistics
        try:
            from scipy.stats import t as student_t
        except Exception as exc:
            raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
        drift = second_ci['mean'] - first_ci['mean']
        se = audit_math.sqrt(statistics.variance(first) / first_ci['ess'] + statistics.variance(second) / second_ci['ess'])
        df = max(1, int(audit_math.floor(min(first_ci['ess'], second_ci['ess']))) - 1)
        drift_half = float(student_t.ppf(0.975, df)) * se
        enough = full_ci['ess'] >= 20 and first_ci['ess'] >= 10 and (second_ci['ess'] >= 10)
        coverage = all((x['ci95_low'] <= 600 <= x['ci95_high'] for x in (full_ci, first_ci, second_ci)))
        drift_ok = drift - drift_half <= 0 <= drift + drift_half
        return {'rows': len(rows), 'first_step': rows[0][0], 'last_step': rows[-1][0], 'full': full_ci, 'first_half': first_ci, 'second_half': second_ci, 'half_drift_K': drift, 'half_drift_ci95': [drift - drift_half, drift + drift_half], 'ess_pass': enough, 'temperature_ci_pass': coverage, 'drift_pass': drift_ok, 'gate_pass': enough and coverage and drift_ok, 'sha256': audit_sha(path)}

    def audit_parse_v2_fixed_h_dump(path: audit_Path, expected_atoms: int, start_step: int=11000, end_step: int=16000, cadence: int=20) -> list[dict]:
        """Strictly parse full-cell custom dumps with ID/type/q/image/velocity."""
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        frames = []
        i = 0
        required = {'id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz', 'vx', 'vy', 'vz'}
        while i < len(lines):
            if lines[i].strip() != 'ITEM: TIMESTEP':
                raise audit_Mismatch(f'{path.name}: unexpected data outside a dump frame at line {i + 1}')
            try:
                step = int(lines[i + 1])
                if lines[i + 2].strip() != 'ITEM: NUMBER OF ATOMS':
                    raise ValueError('atom count header')
                n = int(lines[i + 3])
                bounds_header = lines[i + 4].split()
                if bounds_header[:3] != ['ITEM:', 'BOX', 'BOUNDS']:
                    raise ValueError('bounds header')
                tilt = all((x in bounds_header for x in ('xy', 'xz', 'yz')))
                if not tilt:
                    raise audit_UnknownEvidence('fixed-H dump does not declare triclinic tilt columns')
                bounds = [lines[i + j].split() for j in (5, 6, 7)]
                if any((len(row) != 3 for row in bounds)):
                    raise ValueError('triclinic bound rows')
                b = [[float(v) for v in row] for row in bounds]
                (xy, xz, yz) = (b[0][2], b[1][2], b[2][2])
                xlo = b[0][0] - min(0.0, xy, xz, xy + xz)
                xhi = b[0][1] - max(0.0, xy, xz, xy + xz)
                ylo = b[1][0] - min(0.0, yz)
                yhi = b[1][1] - max(0.0, yz)
                (zlo, zhi) = b[2][:2]
                H = ((xhi - xlo, 0.0, 0.0), (xy, yhi - ylo, 0.0), (xz, yz, zhi - zlo))
                origin = (xlo, ylo, zlo)
                hdr = lines[i + 8].split()
                if hdr[:2] != ['ITEM:', 'ATOMS']:
                    raise ValueError('atom header')
                cols = hdr[2:]
                if len(cols) != 11 or set(cols) != required:
                    raise audit_Mismatch('fixed-H dump atom columns must be exact 11-field ID/type/xyz/image/velocity schema')
                idx = {k: cols.index(k) for k in required}
                atoms = []
                atom_tokens = {}
                for line in lines[i + 9:i + 9 + n]:
                    values = line.split()
                    if len(values) != 11:
                        raise audit_Mismatch('fixed-H dump atom row has extra or missing fields')
                    aid = int(values[idx['id']])
                    typ = int(values[idx['type']])
                    image = tuple((int(values[idx[k]]) for k in ('ix', 'iy', 'iz')))
                    xyz = tuple((float(values[idx[k]]) for k in ('x', 'y', 'z')))
                    vel = tuple((float(values[idx[k]]) for k in ('vx', 'vy', 'vz')))
                    if aid <= 0 or typ not in (1, 2) or (not all((math.isfinite(x) for x in xyz + vel))):
                        raise audit_Mismatch('fixed-H dump has invalid atom identity/state')
                    unwrapped = tuple((xyz[j] + sum((image[k] * H[k][j] for k in range(3))) for j in range(3)))
                    atoms.append((aid, typ, xyz, image, vel, unwrapped))
                    atom_tokens[aid] = {'xyz': tuple((values[idx[k]] for k in ('x', 'y', 'z'))), 'vel': tuple((values[idx[k]] for k in ('vx', 'vy', 'vz')))}
                if n != expected_atoms or len({a[0] for a in atoms}) != n:
                    raise audit_Mismatch('fixed-H dump atom count or ID uniqueness mismatch')
                atoms.sort(key=lambda a: a[0])
                bq = [[_significant_print_half_quantum(tok, 17) for tok in row] for row in bounds]
                herr = ((bq[0][0] + bq[0][1] + 2 * bq[0][2] + 2 * bq[1][2], 0.0, 0.0), (bq[0][2], bq[1][0] + bq[1][1] + 2 * bq[2][2], 0.0), (bq[1][2], bq[2][2], bq[2][0] + bq[2][1]))
                oerr = (bq[0][0] + bq[0][2] + bq[1][2], bq[1][0] + bq[2][2], bq[2][0])
                frames.append({'step': step, 'H': H, 'H_error': herr, 'origin': origin, 'origin_error': oerr, 'atoms': atoms, 'atom_tokens': atom_tokens})
                i += 9 + n
            except (ValueError, IndexError, OverflowError) as exc:
                raise audit_Mismatch(f'{path.name}: malformed native dump frame: {exc}') from exc
        expected = list(range(start_step, end_step + 1, cadence))
        if not expected or [x['step'] for x in frames] != expected:
            raise audit_Mismatch(f'native dump must contain exactly {len(expected)} frames at {start_step}..{end_step}/{cadence}')
        first = frames[0]
        for frame in frames[1:]:
            if frame['H'] != first['H'] or frame['origin'] != first['origin']:
                raise audit_Mismatch('fixed-H native trajectory changed H or cell origin')
            if [(a[0], a[1]) for a in frame['atoms']] != [(a[0], a[1]) for a in first['atoms']]:
                raise audit_Mismatch('fixed-H native trajectory changed atom IDs/types')
        return frames

    def audit__bounded_cell_match(observed: dict, reference: dict) -> bool:
        """Compare H and origin using only the source token intervals."""
        oh = observed.get('H')
        rh = reference.get('H')
        oe = observed.get('H_error', [[0.0] * 3 for _ in range(3)])
        re_ = reference.get('H_error', [[0.0] * 3 for _ in range(3)])
        oo = observed.get('origin')
        ro = reference.get('origin')
        ooe = observed.get('origin_error', (0.0, 0.0, 0.0))
        roe = reference.get('origin_error', (0.0, 0.0, 0.0))
        if not (oh and rh and oo and ro):
            return False
        for i in range(3):
            if abs(oo[i] - ro[i]) > ooe[i] + roe[i]:
                return False
            for j in range(3):
                if abs(oh[i][j] - rh[i][j]) > oe[i][j] + re_[i][j]:
                    return False
        return True

    def audit__frame_q_error(frame: dict, image: tuple[int, int, int], xyz_tokens: tuple[str, str, str], xyz: tuple[float, float, float] | None=None) -> tuple[float, float, float]:
        """Enclose ASCII-to-binary64 parsing and image-aware x + image*H arithmetic."""
        herr = frame.get('H_error', [[0.0] * 3 for _ in range(3)])
        if xyz is None:
            xyz = tuple((float(x) for x in xyz_tokens))
        m = 16
        gamma = m * audit_sys.float_info.epsilon / (1 - m * audit_sys.float_info.epsilon)
        errors = []
        for j in range(3):
            value = float(xyz[j])
            quant = audit__significant_print_half_quantum(xyz_tokens[j], 16) + 0.5 * audit_math.ulp(value)
            box = sum((abs(image[k]) * herr[k][j] for k in range(3)))
            arithmetic = gamma * (abs(value) + sum((abs(image[k] * frame['H'][k][j]) for k in range(3))) + 1.0)
            errors.append(quant + box + arithmetic)
        return tuple(errors)

    def audit__spring_energy_with_source_bound(frame: dict, anchors: dict[int, tuple], atom_type: int, spring_k: float) -> tuple[float, float, int]:
        """Recompute a total group spring energy and enclose source-state roundoff.

        Anchors are the prepared read_data coordinates captured when the pinned
        ti/spring fixes are installed, not the later lambda=1 state.
        """
        predicted = 0.0
        model_error = 0.0
        count = 0
        eps = audit_sys.float_info.epsilon
        subtract_gamma = eps / (1.0 - eps)
        for (aid, typ, xyz, image, _velocity, q) in frame['atoms']:
            if typ != atom_type:
                continue
            if aid not in anchors or anchors[aid][0] != typ:
                raise audit_Mismatch('spring trace atom is absent from its prepared anchor inventory')
            anchor_q = anchors[aid][1]
            anchor_error = anchors[aid][2]
            token = frame.get('atom_tokens', {}).get(aid, {})
            current_error = audit__frame_q_error(frame, image, token.get('xyz', ('0', '0', '0')), xyz)
            for j in range(3):
                delta = q[j] - anchor_q[j]
                b = current_error[j] + anchor_error[j] + subtract_gamma * (abs(q[j]) + abs(anchor_q[j]) + 1.0)
                predicted += 0.5 * spring_k * delta * delta
                model_error += 0.5 * spring_k * (2.0 * abs(delta) * b + b * b)
            count += 1
        if count == 0:
            raise audit_Mismatch('spring energy group has no atoms')
        operations = 16 * count + 6
        gamma = operations * eps / (1.0 - operations * eps)
        return (predicted, model_error + gamma * abs(predicted), count)

    def audit__frames_same_physical_state(left: dict, right: dict) -> bool:
        if not audit__bounded_cell_match(left, right):
            return False
        aa = {a[0]: a for a in left['atoms']}
        bb = {a[0]: a for a in right['atoms']}
        if set(aa) != set(bb):
            return False
        for (aid, a) in aa.items():
            b = bb[aid]
            if a[1] != b[1]:
                return False
            ta = left.get('atom_tokens', {}).get(aid, {})
            tb = right.get('atom_tokens', {}).get(aid, {})
            ae = audit__frame_q_error(left, a[3], ta.get('xyz', ('0', '0', '0')), a[2])
            be = audit__frame_q_error(right, b[3], tb.get('xyz', ('0', '0', '0')), b[2])
            if any((abs(a[5][j] - b[5][j]) > ae[j] + be[j] for j in range(3))):
                return False
            for j in range(3):
                av = a[4][j]
                bv = b[4][j]
                averr = audit__significant_print_half_quantum(ta.get('vel', ('0', '0', '0'))[j], 16)
                bverr = audit__significant_print_half_quantum(tb.get('vel', ('0', '0', '0'))[j], 16)
                if abs(av - bv) > averr + bverr + 2 * audit_math.ulp(av):
                    return False
        return True

    def audit__snapshot_matches_dump(snapshot: dict, frame: dict) -> bool:
        if not audit__bounded_cell_match(frame, snapshot['geom']):
            return False
        refs = {a['id']: a for a in snapshot['atoms']}
        seen = {a[0]: a for a in frame['atoms']}
        if set(refs) != set(seen):
            return False
        for (aid, r) in refs.items():
            atom = seen[aid]
            if atom[1] != r['type']:
                return False
            image = r['image']
            qref = tuple((r['xyz'][j] + sum((image[k] * snapshot['geom']['H'][k][j] for k in range(3))) for j in range(3)))
            xyz_tok = frame.get('atom_tokens', {}).get(aid, {}).get('xyz', ('0', '0', '0'))
            qerr = audit__frame_q_error(frame, atom[3], xyz_tok, atom[2])
            referr = []
            for j in range(3):
                referr.append(r['xyz_error'][j] + sum((abs(image[k]) * snapshot['geom']['H_error'][k][j] for k in range(3))) + 8 * audit_sys.float_info.epsilon * (1 + sum((abs(image[k] * snapshot['geom']['H'][k][j]) for k in range(3)))))
            if any((abs(atom[5][j] - qref[j]) > qerr[j] + referr[j] for j in range(3))):
                return False
            vel_tok = frame.get('atom_tokens', {}).get(aid, {}).get('vel', ('0', '0', '0'))
            for j in range(3):
                if abs(atom[4][j] - r['vel'][j]) > audit__significant_print_half_quantum(vel_tok[j], 16) + r['vel_error'][j]:
                    return False
        return True

    def audit_recompute_v2_fixed_h_msd(path: audit_Path, expected_atoms: int, type_masses: dict[int, float]) -> dict:
        """Same-origin, mass-COM-corrected 2k/3k MSD and paired-growth estimates."""
        frames = audit_parse_v2_fixed_h_dump(path, expected_atoms)
        if set(type_masses) != {1, 2} or type_masses != {1: 15.999, 2: 28.085}:
            raise audit_Mismatch('fixed-H MSD requires frozen native masses O=15.999, Si=28.085')
        import numpy as np
        ids = [a[0] for a in frames[0]['atoms']]
        types = np.array([a[1] for a in frames[0]['atoms']])
        masses = np.array([type_masses[int(t)] for t in types], dtype=float)
        positions = np.array([[a[5] for a in f['atoms']] for f in frames], dtype=float)
        if not np.isfinite(positions).all():
            raise audit_Mismatch('nonfinite unwrapped fixed-H coordinates')
        all_metrics = {}
        for (element, typ) in (('O', 1), ('Si', 2)):
            mask = types == typ
            series = {2000: [], 3000: []}
            for (lag, offset) in ((2000, 100), (3000, 150)):
                for origin in range(251 - offset):
                    delta = positions[origin + offset] - positions[origin]
                    com = np.average(delta, axis=0, weights=masses)
                    corrected = delta - com
                    series[lag].append(float(np.mean(np.sum(corrected[mask] ** 2, axis=1))))
            growth = [series[3000][i] - series[2000][i] for i in range(101)]
            metrics = {}
            for (lag, values) in series.items():
                ci = audit__mean_ci_ess(values)
                metrics[str(lag)] = {**ci, 'one_sided_upper95': ci['mean'] + audit__one_sided_t_half(values, ci['ess'])}
            gci = audit__mean_ci_ess(growth)
            metrics['same_origin_growth'] = {**gci, 'one_sided_upper95': gci['mean'] + audit__one_sided_t_half(growth, gci['ess'])}
            all_metrics[element] = metrics
        gap = audit__fixed_h_si_o_gap(frames)
        for metric in all_metrics.values():
            for lag in ('2000', '3000', 'same_origin_growth'):
                metric[lag]['gap_upper_limit_A2'] = (gap / 2.0) ** 2
                metric[lag]['gap_gate_pass'] = metric[lag]['one_sided_upper95'] < (gap / 2.0) ** 2
        gate_pass = all((all((all_metrics[e][k]['ess'] >= 10 and all_metrics[e][k]['gap_gate_pass'] for k in ('2000', '3000', 'same_origin_growth'))) for e in all_metrics))
        min_face = min((_cell_face_heights(f['H']) for f in frames))
        return {'frame_count': len(frames), 'first_step': frames[0]['step'], 'last_step': frames[-1]['step'], 'atoms': expected_atoms, 'cell_matrix_A': frames[0]['H'], 'minimum_neighbor_gap_A': gap, 'gate_pass': gate_pass, 'minimum_face_height_A': min_face, 'face_gate_pass': min_face > 10.5, 'metrics': all_metrics, 'trajectory_sha256': audit_sha(path)}

    def audit__cell_face_heights(H) -> float:
        import numpy as np
        h = np.asarray(H, dtype=float)
        v = abs(float(np.linalg.det(h)))
        values = [v / float(np.linalg.norm(np.cross(h[(i + 1) % 3], h[(i + 2) % 3]))) for i in range(3)]
        if not values or not all((math.isfinite(x) and x > 0 for x in values)):
            raise audit_Mismatch('invalid cell face height')
        return min(values)

    def audit__fixed_h_si_o_gap(frames: list[dict]) -> float:
        """Minimum same-frame fourth/fifth O-neighbor gap; also reject bond-ID exchange."""
        import numpy as np
        shifts = np.asarray(list(audit_itertools.product((-1, 0, 1), repeat=3)), dtype=float)
        baseline = None
        min_gap = float('inf')
        for frame in frames:
            H = np.asarray(frame['H'], dtype=float)
            origin = np.asarray(frame['origin'], dtype=float)
            atoms = frame['atoms']
            ids = np.asarray([a[0] for a in atoms])
            types = np.asarray([a[1] for a in atoms])
            xyz = np.asarray([a[2] for a in atoms], dtype=float)
            oxygen = np.flatnonzero(types == 1)
            silicon = np.flatnonzero(types == 2)
            if len(silicon) == 0 or len(oxygen) < 5:
                raise audit_Mismatch('phase graph cannot be built from fixed-H dump atom types')
            frac = (xyz - origin) @ np.linalg.inv(H)
            edges = set()
            for si in silicon:
                delta = frac[oxygen] - frac[si]
                center = np.rint(delta)
                disp = (delta[:, None, :] - center[:, None, :] - shifts[None, :, :]) @ H
                dist = np.sqrt(np.min(np.sum(disp * disp, axis=2), axis=1))
                order = np.argsort(dist)
                min_gap = min(min_gap, float(dist[order[4]] - dist[order[3]]))
                edges.update(((int(ids[si]), int(ids[oxygen[j]])) for j in order[:4]))
            if baseline is None:
                baseline = edges
            elif edges != baseline:
                raise audit_Mismatch('fixed-H Si-to-four-O ID graph changed during the 5k window')
        if not audit_math.isfinite(min_gap) or min_gap <= 0:
            raise audit_Mismatch('fixed-H fourth/fifth neighbor gap is nonpositive/nonfinite')
        return min_gap

    def audit__parse_descriptor_dump(path: audit_Path, expected_atoms: int) -> list[dict]:
        """Parse old 8-column or current 11-column full-cell dumps for fingerprints."""
        lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
        frames = []
        i = 0
        while i < len(lines):
            if lines[i].strip() != 'ITEM: TIMESTEP':
                raise audit_Mismatch(f'{path.name}: non-frame bytes in dump')
            try:
                step = int(lines[i + 1])
                n = int(lines[i + 3])
                if lines[i + 2].strip() != 'ITEM: NUMBER OF ATOMS' or n != expected_atoms:
                    raise audit_Mismatch('phase control atom count mismatch')
                bh = lines[i + 4].split()
                if bh[:3] != ['ITEM:', 'BOX', 'BOUNDS'] or not all((x in bh for x in ('xy', 'xz', 'yz'))):
                    raise audit_UnknownEvidence('phase descriptor dump must declare restricted triclinic bounds')
                b = [[finite(v) for v in lines[i + j].split()] for j in (5, 6, 7)]
                if any((len(x) != 3 or any((v is None for v in x)) for x in b)):
                    raise audit_Mismatch('phase descriptor box bounds malformed')
                (xy, xz, yz) = (b[0][2], b[1][2], b[2][2])
                xlo = b[0][0] - min(0.0, xy, xz, xy + xz)
                xhi = b[0][1] - max(0.0, xy, xz, xy + xz)
                ylo = b[1][0] - min(0.0, yz)
                yhi = b[1][1] - max(0.0, yz)
                (zlo, zhi) = b[2][:2]
                h = ((xhi - xlo, 0.0, 0.0), (xy, yhi - ylo, 0.0), (xz, yz, zhi - zlo))
                origin = (xlo, ylo, zlo)
                head = lines[i + 8].split()
                if head[:2] != ['ITEM:', 'ATOMS']:
                    raise audit_Mismatch('phase descriptor atom header missing')
                cols = head[2:]
                if len(cols) not in (8, 11) or len(set(cols)) != len(cols) or (not {'id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz'}.issubset(cols)):
                    raise audit_Mismatch('phase descriptor requires exact 8 or 11 atom columns')
                idx = {k: cols.index(k) for k in ('id', 'type', 'x', 'y', 'z', 'ix', 'iy', 'iz')}
                atoms = {}
                for row in lines[i + 9:i + 9 + n]:
                    f = row.split()
                    if len(f) != len(cols):
                        raise audit_Mismatch('phase descriptor atom row has extra/missing columns')
                    aid = int(f[idx['id']])
                    typ = int(f[idx['type']])
                    xyz = tuple((finite(f[idx[k]]) for k in ('x', 'y', 'z')))
                    image = tuple((int(f[idx[k]]) for k in ('ix', 'iy', 'iz')))
                    if aid <= 0 or typ not in (1, 2) or aid in atoms or any((x is None for x in xyz)):
                        raise audit_Mismatch('invalid phase descriptor atom identity/state')
                    atoms[aid] = {'type': typ, 'xyz': xyz, 'image': image}
                if len(atoms) != n:
                    raise audit_Mismatch('phase descriptor atom inventory incomplete')
                frames.append({'step': step, 'atoms': atoms, 'box': [h[0][0], h[1][1], h[2][2], xy, xz, yz], 'origin': origin})
                i += 9 + n
            except (ValueError, IndexError, TypeError) as exc:
                raise audit_Mismatch(f'{path.name}: malformed phase descriptor dump: {exc}') from exc
        if len(frames) < 2 or any((b['step'] < a['step'] for (a, b) in zip(frames, frames[1:]))):
            raise audit_Mismatch('phase descriptor reference must contain at least two nondecreasing native frames')
        return frames

    def audit__phase_fingerprint(frame: dict) -> dict:
        import numpy as np
        ids = sorted(frame['atoms'])
        atoms = frame['atoms']
        h = np.asarray([[frame['box'][0], 0, 0], [frame['box'][3], frame['box'][1], 0], [frame['box'][4], frame['box'][5], frame['box'][2]]], dtype=float)
        origin = np.asarray(frame['origin'], dtype=float)
        q = np.asarray([(np.asarray(atoms[i]['xyz']) - origin) @ np.linalg.inv(h) + np.asarray(atoms[i]['image']) for i in ids])
        types = np.asarray([atoms[i]['type'] for i in ids])
        si = np.where(types == 2)[0]
        oxy = np.where(types == 1)[0]
        if len(si) == 0 or len(oxy) < 5:
            raise audit_Mismatch('phase descriptor lacks required O/Si composition')
        dq = q[si, None, :] - q[None, oxy, :]
        dq -= np.rint(dq)
        d2 = np.full(dq.shape[:2], np.inf)
        vec = np.zeros(dq.shape)
        for shift in audit_itertools.product((-1, 0, 1), repeat=3):
            v = (dq - np.asarray(shift)) @ h
            d = np.einsum('ijk,ijk->ij', v, v)
            take = d < d2
            d2[take] = d[take]
            vec[take] = v[take]
        dist = np.sqrt(d2)
        order = np.argsort(dist, axis=1)
        edges = {(int(ids[si[a]]), int(ids[oxy[b]])) for a in range(len(si)) for b in order[a, :4]}
        bins = np.arange(0.0, 6.0001, 0.1)
        hist = np.histogram(dist.ravel(), bins=bins)[0].astype(float)
        shell = 4 * audit_math.pi / 3 * (bins[1:] ** 3 - bins[:-1] ** 3)
        rdf = hist / (len(si) * shell * (len(oxy) / abs(float(np.linalg.det(h)))))
        rdf /= max(float(rdf.sum()), 1e-300)
        id_si = {int(ids[j]): a for (a, j) in enumerate(si)}
        id_o = {int(ids[j]): b for (b, j) in enumerate(oxy)}
        bridge = {}
        for (sid, oid) in edges:
            bridge.setdefault(oid, []).append(sid)
        angles = []
        for (oid, neighbors) in bridge.items():
            if len(neighbors) != 2:
                continue
            b = id_o[oid]
            u = vec[id_si[neighbors[0]], b]
            v = vec[id_si[neighbors[1]], b]
            c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))
            angles.append(audit_math.degrees(audit_math.acos(max(-1.0, min(1.0, c)))))
        ah = np.histogram(angles, bins=np.arange(0.0, 180.0001, 5.0))[0].astype(float)
        ah /= max(float(ah.sum()), 1e-300)
        return {'edges': edges, 'rdf': rdf, 'angles': ah, 'rdf_peak_A': float((bins[np.argmax(hist)] + bins[np.argmax(hist) + 1]) / 2), 'angle_mean_deg': float(np.mean(angles)) if angles else None}

    def audit__descriptor_distance(a: dict, b: dict) -> float:
        import numpy as np

        def js(x, y):
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            m = (x + y) / 2

            def kl(p, q):
                mask = p > 0
                return float(np.sum(p[mask] * np.log(p[mask] / q[mask])))
            return audit_math.sqrt(max(0.0, (kl(x, m) + kl(y, m)) / 2))
        return (js(a['rdf'], b['rdf']) + js(a['angles'], b['angles'])) / 2

    def audit__source_payload_path(outputs: audit_Path, ref: dict) -> audit_Path:
        """Resolve candidate payload references without permitting arbitrary filesystem reads."""
        if not isinstance(ref, dict):
            raise audit_UnknownEvidence('phase-control reference is malformed')
        namespace = ref.get('namespace', 'candidate')
        if namespace in ('candidate', 'candidate_outputs'):
            clean = {k: v for (k, v) in ref.items() if k != 'namespace'}
            return audit__file_ref(outputs, clean)
        if namespace != 'candidate_source':
            raise audit_UnknownEvidence('phase controls must use candidate or candidate_source namespace')
        rel = ref.get('path')
        if not isinstance(rel, str) or audit_Path(rel).is_absolute() or '..' in audit_Path(rel).parts:
            raise audit_Mismatch('unsafe candidate-source reference')
        candidate_root = outputs.parent
        payload = candidate_root / 'payload'
        if not payload.is_dir():
            raise audit_UnknownEvidence('candidate payload root is not adjacent to outputs')
        path = (payload / rel).resolve()
        if payload.resolve() not in path.parents:
            raise audit_Mismatch('candidate-source reference escapes payload')
        if not path.is_file():
            raise audit_UnknownEvidence(f'candidate source artifact missing: {rel}')
        if audit_sha(path) != ref.get('sha256'):
            raise audit_Mismatch(f'candidate source artifact SHA mismatch: {rel}')
        return path

    def audit__tile_control_descriptor_frame(frame: dict, p_rows: list[list[int]]) -> dict:
        """Independently apply the preregistered determinant-two row-cell map."""
        import numpy as np
        p = np.asarray(p_rows, dtype=int)
        if p.shape != (3, 3) or round(float(np.linalg.det(p))) != 2:
            raise audit_Mismatch('S control transform must be a determinant-two integer row matrix')
        (lx, ly, lz, xy, xz, yz) = map(float, frame['box'])
        h = np.asarray([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]], dtype=float)
        origin = np.asarray(frame['origin'], dtype=float)
        new_h = p @ h
        p_inv = np.linalg.inv(p.astype(float))
        tiles = ((0, 0, 0), (0, 1, 0))
        atoms = {}
        new_id = 0
        for tile in tiles:
            for old_id in sorted(frame['atoms']):
                old = frame['atoms'][old_id]
                frac = (np.asarray(old['xyz'], dtype=float) - origin) @ np.linalg.inv(h) + np.asarray(old['image'], dtype=float)
                mapped = (frac + np.asarray(tile, dtype=float)) @ p_inv % 1.0
                new_id += 1
                atoms[new_id] = {'type': int(old['type']), 'xyz': tuple(mapped @ new_h), 'image': (0, 0, 0)}
        box = [float(new_h[0, 0]), float(new_h[1, 1]), float(new_h[2, 2]), float(new_h[1, 0]), float(new_h[2, 0]), float(new_h[2, 1])]
        return {'step': frame.get('step'), 'atoms': atoms, 'box': box, 'origin': (0.0, 0.0, 0.0)}

    def audit__review_phase_descriptor(outputs: audit_Path, setup: dict, gates: dict, fixed_dump: audit_Path, fixed_frames: list[dict], expected_atoms: int, reference_root: audit_Path | None=None) -> dict:
        phase = str(setup.get('phase') or '')
        role = str(setup.get('role') or '')
        gate = gates.get('phase_structure')
        if not isinstance(gate, dict):
            raise audit_UnknownEvidence('phase structure source record is absent')
        control_index_ref = gate.get('control_index')
        control_ns = control_index_ref.get('namespace', 'candidate') if isinstance(control_index_ref, dict) else 'candidate'
        index_path = audit__source_payload_path(outputs, control_index_ref)
        index = audit__load_json(index_path)
        if index.get('schema') != 'case06-v2-structure-control-source-index/v1':
            raise audit_UnknownEvidence('unsupported phase-control index schema')
        plan = audit_load_current_plan()
        frozen = plan.get('phase_descriptor_controls', {})
        if index.get('method', {}).get('sha256') != frozen.get('source_script_sha256'):
            raise audit_Mismatch('phase-control source index is not bound to frozen fingerprint method')
        controls = {x.get('phase'): x for x in index.get('controls', []) if isinstance(x, dict)}
        if set(controls) != {'alpha_quartz', 'coesite'}:
            raise audit_Mismatch('phase-control index must contain both phases')
        raw_control_frames = {}
        for (ph, row) in controls.items():
            expected_sha = frozen.get('alpha_job8973_dump_sha256' if ph == 'alpha_quartz' else 'coesite_job8974_dump_sha256')
            if row.get('raw_dump', {}).get('sha256') != expected_sha:
                raise audit_Mismatch(f'{ph} phase control dump differs from frozen control SHA')
            declared_files = row.get('files')
            if not isinstance(declared_files, list) or not declared_files:
                raise audit_UnknownEvidence(f'{ph} phase control lacks complete raw provenance inventory')
            seen_paths = set()
            for item in declared_files:
                if not isinstance(item, dict) or item.get('path') in seen_paths:
                    raise audit_Mismatch(f'{ph} control inventory has malformed/duplicate paths')
                seen_paths.add(item.get('path'))
                audit__source_payload_path(outputs, {'namespace': control_ns, **item})
            input_sha = frozen.get('source_inputs_sha256', {}).get('alpha_job8973' if ph == 'alpha_quartz' else 'coesite_job8974')
            if row.get('input', {}).get('sha256') != input_sha:
                raise audit_Mismatch(f'{ph} control native input differs from frozen source input SHA')
            ref = audit__source_payload_path(outputs, {'namespace': control_ns, **row['raw_dump']})
            frames = audit__parse_descriptor_dump(ref, audit_PHASE_ATOMS[ph])
            raw_control_frames[ph] = [frames[0], frames[-1]]
        calibration_ref = gate.get('descriptor_calibration')
        if not isinstance(calibration_ref, dict):
            raise audit_UnknownEvidence('pre-data base/size descriptor calibration source is missing')
        calibration_path = audit__source_payload_path(outputs, calibration_ref)
        calibration = audit__load_json(calibration_path)
        if calibration.get('schema') != 'case06-reference-only-structure-calibration/v1' or calibration.get('candidate_data_used') is not False or calibration.get('native_md_executed') is not False or (calibration.get('source_index_sha256') != audit_sha(index_path)) or (calibration.get('method_sha256') != frozen.get('source_script_sha256')):
            raise audit_Mismatch('phase descriptor calibration is not a pre-candidate raw-source calibration')
        if index.get('method', {}).get('sha256') != '0c722b70bd34d78901785dad4f7261cb334ffcb68d4c60f94284a44e4dbc7637':
            raise audit_Mismatch('phase-control fingerprint method historical identity changed')
        if calibration.get('calibrator_sha256') != 'd585943a9e52b68c4835a3c093003a0b961ccdc198e1cbdd34d3af9847b9766e':
            raise audit_Mismatch('phase-control calibration historical identity changed')
        if calibration.get('matrix_sha256') != index.get('matrix_sha256'):
            raise audit_Mismatch('descriptor calibration and raw control index are bound to different matrix revisions')
        role_key = 'S' if role in ('adaptive_size', 'S') else 'base'
        role_cal = calibration.get('roles', {}).get(role_key, {}).get(phase)
        if not isinstance(role_cal, dict):
            raise audit_UnknownEvidence(f'no preregistered descriptor calibration for role {role_key}/{phase}')
        ref_fps = {}
        for (ph, endpoints_in) in raw_control_frames.items():
            if role_key == 'S':
                pmat = audit_load_current_plan().get('geometry_registry', {}).get('size_supercell_integer_matrices_ASE_rows_Hnew_eq_P_Hold', {}).get(ph)
                if not isinstance(pmat, list):
                    raise audit_UnknownEvidence(f'role S lacks frozen size matrix for {ph}')
                ref_fps[ph] = [audit__phase_fingerprint(_tile_control_descriptor_frame(frame, pmat)) for frame in endpoints_in]
            else:
                ref_fps[ph] = [audit__phase_fingerprint(frame) for frame in endpoints_in]
        own = ref_fps[phase]
        other = ref_fps['coesite' if phase == 'alpha_quartz' else 'alpha_quartz']
        endpoints = role_cal.get('endpoints')
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise audit_Mismatch('descriptor calibration must have two raw endpoint fingerprints')
        for (stored, rawfp) in zip(endpoints, own):
            for key in ('rdf', 'angles'):
                a = stored.get(key)
                b = rawfp[key]
                if not isinstance(a, list) or len(a) != len(b) or any((abs(float(x) - float(y)) > 2e-12 for (x, y) in zip(a, b))):
                    raise audit_Mismatch('descriptor calibration fingerprint differs from independently recomputed raw control endpoint')
        plan_matrix = audit_load_current_plan().get('geometry_registry', {}).get('size_supercell_integer_matrices_ASE_rows_Hnew_eq_P_Hold', {}).get(phase)
        expected_P = plan_matrix if role_key == 'S' else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        if role_cal.get('size_matrix_P') != expected_P:
            raise audit_Mismatch('descriptor calibration uses a different source-bound size matrix')
        own_span = audit__descriptor_distance(own[0], own[1])
        cross = min((audit__descriptor_distance(a, b) for a in own for b in other))
        if cross <= 2 * own_span:
            raise audit_UnknownEvidence('frozen external descriptor controls do not adequately separate phases')
        ceiling = min(2 * own_span, cross / 2)
        declared = audit_finite(role_cal.get('maximum_own_distance'))
        if declared is None or abs(declared - ceiling) > 2e-12:
            raise audit_Mismatch('calibrated own-vs-other descriptor ceiling differs from independent raw recomputation')
        candidates = [audit__phase_fingerprint(fixed_frames[i]) for i in (0, len(fixed_frames) // 2, len(fixed_frames) - 1)]
        snapshot_ref = gate.get('prepared_snapshot') or setup.get('snapshot')
        snapshot_path = audit__ledger_file_ref(outputs, snapshot_ref, reference_root)
        snapshot = audit__geom_data(snapshot_path)
        prepared_frame = {'step': None, 'atoms': {a[0]: {'type': a[1], 'xyz': a[2], 'image': (0, 0, 0)} for a in snapshot['atoms']}, 'box': [snapshot['H'][0][0], snapshot['H'][1][1], snapshot['H'][2][2], snapshot['H'][1][0], snapshot['H'][2][0], snapshot['H'][2][1]], 'origin': snapshot['origin']}
        prepared_fp = audit__phase_fingerprint(prepared_frame)
        checks = []
        for c in candidates:
            d_own = min((audit__descriptor_distance(c, r) for r in own))
            d_other = min((audit__descriptor_distance(c, r) for r in other))
            if c['edges'] != prepared_fp['edges']:
                raise audit_Mismatch('native fixed-H phase graph differs from same-run prepared snapshot ID graph')
            if not (d_own <= ceiling and d_own < d_other):
                raise audit_Mismatch('phase fingerprint fails frozen own-vs-other RDF/angle calibration')
            checks.append({'own_distance': d_own, 'other_distance': d_other, 'peak_A': c['rdf_peak_A'], 'angle_mean_deg': c['angle_mean_deg']})
        return {'phase': phase, 'role': role, 'control_index_sha256': audit_sha(index_path), 'calibration_sha256': audit_sha(calibration_path), 'ceiling': ceiling, 'own_reference_span': own_span, 'cross_phase_minimum': cross, 'trajectory_sha256': audit_sha(fixed_dump), 'frames': checks}

    def audit__one_sided_t_half(values: list[float], ess: float) -> float:
        try:
            from scipy.stats import t as student_t
            import statistics
        except Exception as exc:
            raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
        return float(student_t.ppf(0.975, max(1, int(audit_math.floor(ess)) - 1))) * statistics.stdev(values) / audit_math.sqrt(ess)

    def audit_recompute_v2_npt(primary_path: audit_Path, mean_h_path: audit_Path | None=None) -> dict:
        """Recompute current 20-kbar dense-primary and its retained H900 window."""
        mean_h_path = mean_h_path or primary_path
        dense = audit_parse_native_npt_table(primary_path, cadence=10, first=1010, last=11000, count=1000)
        if mean_h_path.resolve() != primary_path.resolve():
            raise audit_UnknownEvidence('current v2 frozen H900 source must be the dense 10-step primary; alias cannot replace it')
        hraw = dense
        retained = [r for r in hraw if r['step'] > 2000]
        if [r['step'] for r in retained] != list(range(2010, 11001, 10)):
            raise audit_Mismatch('mean-H stream is not the frozen 900-row 2010..11000/10 window')
        blocks = [dense[i:i + 200] for i in range(0, 1000, 200)]
        if len(blocks) != 5 or any((len(b) != 200 for b in blocks)):
            raise audit_Mismatch('dense-primary does not partition into five 200-row blocks')
        stats = {}
        for key in audit_NPT_COLUMNS[1:]:
            block_means = [sum((r[key] for r in block)) / 200 for block in blocks]
            (full_mean, full_half) = audit__student_t_mean_ci(block_means)
            (tail_mean, tail_half) = audit__student_t_mean_ci(block_means[-3:])
            first = sum(block_means[:2]) / 2
            last = sum(block_means[-2:]) / 2
            import statistics
            v1 = statistics.variance(block_means[:2]) / 2
            v2 = statistics.variance(block_means[-2:]) / 2
            se = audit_math.sqrt(v1 + v2)
            df = (v1 + v2) ** 2 / (v1 * v1 + v2 * v2) if v1 + v2 else 2
            try:
                from scipy.stats import t as student_t
            except Exception as exc:
                raise audit_UnknownEvidence(f'Student-t implementation unavailable: {exc}') from exc
            drift = last - first
            drift_half = float(student_t.ppf(0.975, df)) * se
            stats[key] = {'full_mean': full_mean, 'full_ci95_halfwidth': full_half, 'tail3_mean': tail_mean, 'tail3_ci95_halfwidth': tail_half, 'first2_mean': first, 'last2_mean': last, 'drift': drift, 'drift_ci95_halfwidth': drift_half}
        p_ess = audit__geyer_ess([r['press'] for r in dense])
        t_ess = audit__geyer_ess([r['temp'] for r in dense])
        hmean = {k: sum((r[k] for r in retained)) / len(retained) for k in audit_NPT_COLUMNS[1:7]}
        mean_volume = sum((r['lx'] * r['ly'] * r['lz'] for r in retained)) / len(retained)
        determinant_of_mean = hmean['lx'] * hmean['ly'] * hmean['lz']
        return {'dense_rows': len(dense), 'dense_first_step': dense[0]['step'], 'dense_last_step': dense[-1]['step'], 'blocks': 5, 'rows_per_block': 200, 'block_statistics': stats, 'pressure_ess': p_ess, 'temperature_ess': t_ess, 'mean_h_rows': len(retained), 'mean_h_first_step': retained[0]['step'], 'mean_h_last_step': retained[-1]['step'], 'mean_h': hmean, 'mean_native_volume_A3': mean_volume, 'determinant_of_mean_h_A3': determinant_of_mean, 'dense_sha256': audit_sha(primary_path), 'mean_h_native_sha256': audit_sha(mean_h_path)}

    def audit__review_setup_sources_batch(outputs: audit_Path, evidence: dict, role_data: dict, checks: list[dict], reference_root: audit_Path | None=None) -> None:
        """Require raw-recomputed phase/stability gates; status-only receipts stay UNKNOWN."""
        attempts = role_data.get('run_records', {})
        if not attempts:
            audit_add(checks, 'v2_native_science_gates', 'UNKNOWN', 'no source-replayed attempt records')
            return
            required = ('npt_primary', 'mean_h', 'temperature', 'phase_structure', 'fixed_h_msd', 'face_height', 'spring_endpoint', 'run0_snapshot')
        unknown = []
        seen_setups = set()
        invocations = role_data.get('native_invocations', {})
        setup_evidence = {str(s.get('setup_id')): s for s in evidence.get('phase_setups', []) if isinstance(s, dict) and s.get('setup_id')}
        for (aid, attempt) in attempts.items():
            setup_id = str(attempt.get('setup_id') or aid)
            setup_record = setup_evidence.get(setup_id, {})
            gates = attempt.get('scientific_gates', setup_record.get('scientific_gates'))
            if not isinstance(gates, dict) and isinstance(setup_record.get('gates'), dict):
                gates = setup_record['gates']
            if not isinstance(gates, dict):
                unknown.append(f'{aid}: no raw gate sources')
                continue
            if setup_id in seen_setups:
                continue
            seen_setups.add(setup_id)
            npt = gates.get('npt_primary')
            mean_gate = gates.get('mean_h') or {}
            dump_path = None
            try:
                if not isinstance(npt, dict) or not isinstance(mean_gate, dict):
                    raise audit_UnknownEvidence('NPT primary/mean-H source records missing')
                primary_ref = npt.get('raw_source')
                primary_inv = npt.get('source_invocation')
                mean_native_ref = mean_gate.get('native_source', mean_gate.get('raw_source', npt.get('mean_h_native_source')))
                mean_inv = mean_gate.get('source_invocation', mean_gate.get('mean_h_source_invocation', npt.get('mean_h_source_invocation', npt.get('source_invocation'))))
                mean_csv_ref = mean_gate.get('derived_source', mean_gate.get('raw_source', setup_record.get('mean_h')))
                (primary_path, _) = audit__source_output_bound(outputs, primary_ref, primary_inv, invocations, allowed_kinds=('setup_npt', 'setup_npt_primary', 'setup_npt_dense'), reference_root=reference_root)
                (mean_path, _) = audit__source_output_bound(outputs, mean_native_ref, mean_inv, invocations, allowed_kinds=('setup_npt', 'setup_npt_primary', 'setup_npt_dense'), reference_root=reference_root)
                csv_path = audit__ledger_file_ref(outputs, mean_csv_ref, reference_root)
                metrics = audit_recompute_v2_npt(primary_path, mean_path)
                native_dense = audit_parse_native_npt_table(primary_path, cadence=10, first=1010, last=11000, count=1000)
                audit__require_native_ave_time_source(outputs, invocations[str(primary_inv['invocation_id'])], 'case06-npt-fullcell-10step.dat', 10, reference_root)
                audit__require_native_ave_time_source(outputs, invocations[str(mean_inv['invocation_id'])], 'case06-npt-fullcell-10step.dat', 10, reference_root)
                with csv_path.open(newline='', encoding='utf-8') as stream:
                    reader = audit_csv.DictReader(stream)
                    csv_rows = list(reader)
                    fields = set(reader.fieldnames or [])
                aliases = {'step': ('step',), 'lx': ('lx_A', 'lx'), 'ly': ('ly_A', 'ly'), 'lz': ('lz_A', 'lz'), 'xy': ('xy_A', 'xy'), 'xz': ('xz_A', 'xz'), 'yz': ('yz_A', 'yz')}
                if any((not any((k in fields for k in opts)) for opts in aliases.values())):
                    raise audit_UnknownEvidence('mean-H CSV lacks step and six labeled H components')
                cols = {k: next((c for c in opts if c in fields)) for (k, opts) in aliases.items()}
                if len(csv_rows) != 900:
                    raise audit_Mismatch('mean-H CSV must contain exactly 900 retained rows')
                mrows = [r for r in native_dense if r['step'] > 2000]
                for (row, raw) in zip(csv_rows, mrows):
                    for key in aliases:
                        val = audit_finite(row.get(cols[key]))
                        want = raw['step'] if key == 'step' else raw[key]
                        if val is None or abs(val - want) > 1e-08:
                            raise audit_Mismatch('mean-H CSV differs rowwise from native dense-primary source')
                audit_add(checks, 'v2_mean_h_source_replay', 'PASS', f'{setup_id}: retained mean-H CSV is rowwise bound to native dense stream steps 2010..11000')
                p = metrics['block_statistics']['press']
                t = metrics['block_statistics']['temp']
                pfull = audit__acf_interval([r['press'] for r in native_dense])
                ptail = audit__acf_interval([r['press'] for r in native_dense[-600:]])
                temp_values = [r['temp'] for r in native_dense]
                tfull = audit__acf_interval(temp_values)
                ttail = audit__acf_interval(temp_values[-600:])
                diagonal_full = all((abs(metrics['block_statistics'][k]['full_mean'] - 20000) + metrics['block_statistics'][k]['full_ci95_halfwidth'] <= 500 for k in ('pxx', 'pyy', 'pzz')))
                diagonal_tail = all((abs(metrics['block_statistics'][k]['tail3_mean'] - 20000) + metrics['block_statistics'][k]['tail3_ci95_halfwidth'] <= 500 for k in ('pxx', 'pyy', 'pzz')))
                shear_tail = all((abs(metrics['block_statistics'][k]['tail3_mean']) <= metrics['block_statistics'][k]['tail3_ci95_halfwidth'] for k in ('pxy', 'pxz', 'pyz')))
                pressure_pass = abs(p['full_mean'] - 20000) + p['full_ci95_halfwidth'] <= 500 and abs(p['tail3_mean'] - 20000) + p['tail3_ci95_halfwidth'] <= 500 and (abs(p['drift']) + p['drift_ci95_halfwidth'] <= 500) and diagonal_full and diagonal_tail and (abs(p['full_mean'] - 20000) + pfull['ci95_halfwidth'] <= 500) and (abs(p['tail3_mean'] - 20000) + ptail['ci95_halfwidth'] <= 500) and (pfull['ess'] >= 10)
                temp_drift = abs(t['drift']) <= t['drift_ci95_halfwidth']
                temp_pass = abs(t['full_mean'] - 600) <= t['full_ci95_halfwidth'] and abs(t['tail3_mean'] - 600) <= t['tail3_ci95_halfwidth'] and temp_drift and (abs(t['full_mean'] - 600) <= tfull['ci95_halfwidth']) and (abs(t['tail3_mean'] - 600) <= ttail['ci95_halfwidth']) and (tfull['ess'] >= 10)
                min_face = audit__minimum_triclinic_face(audit_parse_native_npt_table(primary_path, cadence=10, first=1010, last=11000, count=1000))
                face_pass = min_face > 10.5
                matrices = [[[r['lx'], 0.0, 0.0], [r['xy'], r['ly'], 0.0], [r['xz'], r['yz'], r['lz']]] for r in native_dense]
                tilt_jumps = [max(abs(matrices[i + 1][1][0] - matrices[i][1][0]) / max(abs(matrices[i][0][0]), 1e-12), abs(matrices[i + 1][2][0] - matrices[i][2][0]) / max(abs(matrices[i][0][0]), 1e-12), abs(matrices[i + 1][2][1] - matrices[i][2][1]) / max(abs(matrices[i][1][1]), 1e-12)) for i in range(len(matrices) - 1)]
                no_flip = not any((j >= 0.5 for j in tilt_jumps))
                audit_add(checks, 'v2_npt_dense_source_replay', 'PASS', f"{setup_id}: 1000 raw 10-step rows, five 200-row blocks; pressure ESS={metrics['pressure_ess']:.4g}, T ESS={metrics['temperature_ess']:.4g}; native/CSV H rows={metrics['mean_h_rows']}")
                audit_add(checks, 'v2_npt_pressure_raw_gate', 'PASS' if pressure_pass else 'FAIL', f'{setup_id}: raw 5-block 95% pressure envelope and ESS>=10; target 20000 +/-500 bar')
                audit_add(checks, 'v2_npt_temperature_raw_gate', 'PASS' if temp_pass else 'FAIL', f'{setup_id}: raw full/tail temperature intervals include 600 K and ESS>=10')
                audit_add(checks, 'v2_npt_shear_zero_gate', 'PASS' if shear_tail else 'FAIL', f"{setup_id}: each pxy/pxz/pyz tail-three-block 95% interval {('contains' if shear_tail else 'does not contain')} zero")
                audit_add(checks, 'v2_npt_face_height', 'PASS' if face_pass else 'FAIL', f'{setup_id}: minimum sampled triclinic face height {min_face:.6g} A; required >10.5 A')
                audit_add(checks, 'v2_npt_basis_flip', 'PASS' if no_flip else 'FAIL', f"{setup_id}: raw consecutive-cell normalized tilt jump {('below' if no_flip else 'reaches')} 0.5")
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:npt:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_npt_raw_replay', 'FAIL', f'{aid}: {exc}')
                else:
                    unknown.append(f'{aid}:npt:{exc}')
            try:
                fixed_gate = gates.get('fixed_h_nvt') if isinstance(gates.get('fixed_h_nvt'), dict) else {}
                temp_gate = gates.get('temperature') or {'raw_source': fixed_gate.get('raw_source'), 'source_invocation': fixed_gate.get('temperature_source_invocation', fixed_gate.get('source_invocation'))}
                (temp_path, temp_call) = audit__source_output_bound(outputs, temp_gate.get('raw_source') if isinstance(temp_gate, dict) else None, temp_gate.get('source_invocation') if isinstance(temp_gate, dict) else None, invocations, allowed_kinds=('setup_fixed_h_nvt', 'setup_fixed_h', 'fixed_h_nvt'), reference_root=reference_root)
                temp_metrics = audit_recompute_v2_fixed_h_temperature(temp_path)
                temp_exec = temp_call.get('executed_input')
                if not isinstance(temp_exec, dict):
                    raise audit_UnknownEvidence('fixed-H temperature lacks executed input source')
                temp_script = audit__ledger_file_ref(outputs, temp_exec, reference_root)
                if not audit__script_binds_ave_time(temp_script, temp_path.name, 20):
                    raise audit_Mismatch('executed input does not source the exact 20-step fixed-H temperature stream')
                if temp_metrics['gate_pass']:
                    audit_add(checks, 'v2_fixed_h_temperature_raw_gate', 'PASS', f'{setup_id}: 250 native 20-step samples; full/half ESS and frozen 600 K/drift intervals pass')
                else:
                    audit_add(checks, 'v2_fixed_h_temperature_raw_gate', 'FAIL', f'{setup_id}: frozen temperature ESS/CI/drift gate not met')
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:temperature:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_fixed_h_temperature_raw_gate', 'FAIL', f'{setup_id}: {exc}')
                else:
                    unknown.append(f'{aid}:temperature:{exc}')
            try:
                dump_gate = gates.get('fixed_h_msd') or {'raw_source': fixed_gate.get('trajectory'), 'source_invocation': fixed_gate.get('source_invocation')}
                (dump_path, dump_call) = audit__source_output_bound(outputs, dump_gate.get('raw_source') if isinstance(dump_gate, dict) else None, dump_gate.get('source_invocation') if isinstance(dump_gate, dict) else None, invocations, allowed_kinds=('setup_fixed_h_nvt', 'setup_fixed_h', 'fixed_h_nvt'), reference_root=reference_root)
                phase = str(setup_record.get('phase') or attempt.get('phase') or '')
                atoms = audit_PHASE_ATOMS.get(phase)
                if atoms is None:
                    raise audit_UnknownEvidence('fixed-H phase has no frozen atom count')
                role = str(setup_record.get('role') or attempt.get('role') or '')
                if role not in audit_ROLE_MAP.values():
                    raise audit_UnknownEvidence('fixed-H setup role is not source-bound')
                if role in ('adaptive_size', 'S'):
                    atoms *= 2
                masses = audit__native_type_masses(dump_call, outputs, reference_root)
                msd_metrics = audit_recompute_v2_fixed_h_msd(dump_path, atoms, masses)
                if isinstance(mean_gate, dict):
                    href = mean_gate.get('derived_source')
                    hpath = audit__ledger_file_ref(outputs, href, reference_root)
                    hvalues = audit__read_mean_h_components(hpath)
                    first_h = msd_metrics.get('cell_matrix_A')
                    if first_h is None:
                        raise audit_UnknownEvidence('fixed-H parser did not expose cell matrix')
                    if any((abs(a - b) > 1e-08 for (rowa, rowb) in zip(first_h, hvalues) for (a, b) in zip(rowa, rowb))):
                        raise audit_Mismatch('fixed-H trajectory H differs from source-derived retained mean H')
                audit__require_native_dump_source(outputs, dump_call, dump_path.name, 20, reference_root)
                if msd_metrics['gate_pass']:
                    audit_add(checks, 'v2_fixed_h_msd_raw_gate', 'PASS', f'{setup_id}: 251 native frames; 2k/3k and paired-growth ESS/bounds pass')
                else:
                    audit_add(checks, 'v2_fixed_h_msd_raw_gate', 'FAIL', f'{setup_id}: same-origin MSD/growth ESS or frozen upper-bound gate not met')
                if msd_metrics['face_gate_pass']:
                    audit_add(checks, 'v2_fixed_h_face_height', 'PASS', f"{setup_id}: fixed-H trajectory minimum face height {msd_metrics['minimum_face_height_A']:.6g} A > 10.5 A")
                else:
                    audit_add(checks, 'v2_fixed_h_face_height', 'FAIL', f"{setup_id}: fixed-H trajectory minimum face height {msd_metrics['minimum_face_height_A']:.6g} A does not exceed 10.5 A")
                try:
                    phase_metrics = audit__review_phase_descriptor(outputs, setup_record, gates, dump_path, audit_parse_v2_fixed_h_dump(dump_path, atoms), atoms, reference_root)
                    audit_add(checks, 'v2_phase_structure_raw_gate', 'PASS', f'{setup_id}: same-run ID graph and preregistered own-vs-other RDF/angle descriptor pass')
                except audit_UnknownEvidence as exc:
                    unknown.append(f'{aid}:phase_structure:{exc}')
                except Exception as exc:
                    if isinstance(exc, audit_Mismatch):
                        audit_add(checks, 'v2_phase_structure_raw_gate', 'FAIL', f'{setup_id}: {exc}')
                    else:
                        unknown.append(f'{aid}:phase_structure:{exc}')
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:fixed_h_msd:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_fixed_h_msd_raw_gate', 'FAIL', f'{setup_id}: {exc}')
                else:
                    unknown.append(f'{aid}:fixed_h_msd:{exc}')
            try:
                snapshot_ref = setup_record.get('snapshot') or gates.get('prepared_snapshot') or gates.get('snapshot', {}).get('raw_source')
                snap = audit__ledger_file_ref(outputs, snapshot_ref, reference_root)
                sd = audit__geom_data(snap)
                expected = audit_PHASE_ATOMS.get(str(setup_record.get('phase') or attempt.get('phase') or ''))
                role = str(setup_record.get('role') or attempt.get('role') or '')
                if role in ('adaptive_size', 'S'):
                    expected = expected * 2 if expected else None
                if expected is None or sd['n'] != expected:
                    raise audit_Mismatch('prepared snapshot atom count differs from frozen phase/role')
                if set(sd['types']) != {1, 2}:
                    raise audit_Mismatch('prepared snapshot must contain exactly O/Si atom types')
                if isinstance(mean_gate, dict) and mean_gate.get('derived_source'):
                    hm = audit__read_mean_h_components(audit__ledger_file_ref(outputs, mean_gate['derived_source'], reference_root))
                    for i in range(3):
                        for j in range(3):
                            if abs(sd['H'][i][j] - hm[i][j]) > 1e-08:
                                raise audit_Mismatch('prepared snapshot full H differs from raw NPT H900')
                if dump_path is not None and dump_path.is_file():
                    frames = audit_parse_v2_fixed_h_dump(dump_path, expected)
                    if frames[0]['H'] != sd['H']:
                        raise audit_Mismatch('fixed-H trajectory H differs exactly from prepared snapshot H')
                    frame_ids = [(a[0], a[1]) for a in frames[0]['atoms']]
                    snap_ids = [(a[0], a[1]) for a in sorted(sd['atoms'], key=lambda x: x[0])]
                    if frame_ids != snap_ids:
                        raise audit_Mismatch('fixed-H trajectory IDs/types differ from prepared snapshot')
                audit_add(checks, 'v2_prepared_snapshot_phase_binding', 'PASS', f"{setup_id}: final snapshot has {sd['n']} atoms, O/Si composition, and source-bound H900")
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:snapshot:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_prepared_snapshot_phase_binding', 'FAIL', f'{setup_id}: {exc}')
                else:
                    unknown.append(f'{aid}:snapshot:{exc}')
            try:
                spring_gate = gates.get('spring_endpoint')
                spring_gate = spring_gate if isinstance(spring_gate, dict) else {}
                runtime_ref = spring_gate.get('runtime_input') or setup_record.get('runtime_input') or attempt.get('runtime_input')
                if not isinstance(runtime_ref, dict):
                    runtime_path_value = setup_record.get('runtime_input_path') or attempt.get('runtime_input_path')
                    runtime_sha = setup_record.get('runtime_input_sha256') or attempt.get('runtime_input_sha256')
                    if isinstance(runtime_path_value, str) and isinstance(runtime_sha, str):
                        runtime_ref = {'path': runtime_path_value, 'sha256': runtime_sha, 'namespace': 'candidate'}
                runtime_path = audit__ledger_file_ref(outputs, runtime_ref, reference_root)
                raw_text = runtime_path.read_text(encoding='utf-8', errors='strict')
                try:
                    runtime_doc = audit_json.loads(raw_text)
                except audit_json.JSONDecodeError:
                    try:
                        import yaml
                        runtime_doc = yaml.safe_load(raw_text)
                    except Exception as exc:
                        raise audit_UnknownEvidence(f'runtime input cannot be safely parsed: {exc}') from exc
                calc_rows = runtime_doc.get('calculations') if isinstance(runtime_doc, dict) else None
                phase_name = str(setup_record.get('phase') or attempt.get('phase') or '')
                selected = []
                for row in calc_rows if isinstance(calc_rows, list) else []:
                    lattice = audit_Path(str(row.get('lattice', ''))).name
                    if lattice.startswith(phase_name + '-'):
                        selected.append(row)
                if len(selected) != 1:
                    raise audit_Mismatch('runtime input must contain exactly one calculation for the setup phase')
                calc = selected[0]
                if calc.get('spring_constants') != [2, 4] and calc.get('spring_constants') != [2.0, 4.0]:
                    raise audit_Mismatch('runtime Calculation does not source-bind provided O/Si spring constants [2,4]')
                if calc.get('element') != ['O', 'Si'] or calc.get('mass') != [15.999, 28.085] or audit_finite(calc.get('temperature')) != 600.0:
                    raise audit_Mismatch('runtime Calculation element order, masses, or temperature differs from frozen Hamiltonian')
                if not isinstance(dump_call, dict):
                    raise audit_UnknownEvidence('fixed-H native invocation is unavailable for source binding')
                source_exec = dump_call.get('executed_input')
                if not isinstance(source_exec, dict):
                    raise audit_UnknownEvidence('fixed-H executed native input is missing')
                source_path = audit__ledger_file_ref(outputs, source_exec, reference_root)
                txt = source_path.read_text(encoding='utf-8', errors='strict')
                fixes = []
                for line in txt.splitlines():
                    clean = audit__strip_lammps_comment(line).strip()
                    m = audit_re.fullmatch('fix\\s+3\\s+all\\s+nvt(?:/kk)?\\s+temp\\s+(\\S+)\\s+(\\S+)\\s+(\\S+)', clean, audit_re.I)
                    if m:
                        fixes.append(tuple((audit_finite(x) for x in m.groups())))
                if len(fixes) != 1 or fixes[0][0:2] != (600.0, 600.0) or fixes[0][2] is None or (abs(fixes[0][2] - 0.1) > 5e-07):
                    raise audit_Mismatch('fixed-H source must contain the frozen fix-3 NVT 600/600/0.1 ps command')
                run_steps = audit__source_run_steps(source_path)
                run_position = int(dump_call.get('_resolved_run_position', -1))
                if run_position < 0 or run_position >= len(run_steps) or run_steps[run_position] != 5000:
                    raise audit_Mismatch('provided-k fixed-H invocation is not one continuous native 5000-step segment')
                audit_add(checks, 'v2_provided_spring_source', 'PASS', f'{setup_id}: hash-bound runtime Calculation k=[2,4]/O-Si masses and literal 600 K NVT 5000-step native input')
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:spring:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_provided_spring_source', 'FAIL', f'{setup_id}: {exc}')
                else:
                    unknown.append(f'{aid}:spring:{exc}')
            try:
                gate = gates.get('run0_snapshot')
                if not isinstance(gate, dict):
                    raise audit_UnknownEvidence('prepared snapshot run-0 parity source is absent')
                run0_snapshot_ref = setup_record.get('snapshot') or gates.get('prepared_snapshot') or gates.get('snapshot', {}).get('raw_source')
                if not isinstance(run0_snapshot_ref, dict):
                    raise audit_UnknownEvidence('prepared snapshot source reference is absent for native run0 replay')
                run0_phase = str(setup_record.get('phase') or attempt.get('phase') or '')
                run0_role = str(setup_record.get('role') or attempt.get('role') or '')
                run0_atoms = audit_PHASE_ATOMS.get(run0_phase)
                if run0_role in ('adaptive_size', 'S') and run0_atoms is not None:
                    run0_atoms *= 2
                if run0_atoms is None:
                    raise audit_UnknownEvidence('prepared snapshot run0 has no registered phase atom count')
                replay = audit__raw_prepared_snapshot_run0(outputs, gate.get('raw_source'), run0_snapshot_ref, run0_atoms, reference_root)
                audit_add(checks, 'v2_prepared_snapshot_run0', 'PASS', f'{setup_id}: raw native BEGIN/Loop0/END, zero-only script, PE/volume, full H/origin, ID/type/image/q/velocity and finite force rows independently replayed')
            except audit_UnknownEvidence as exc:
                unknown.append(f'{aid}:run0:{exc}')
            except Exception as exc:
                if isinstance(exc, audit_Mismatch):
                    audit_add(checks, 'v2_prepared_snapshot_run0', 'FAIL', f'{setup_id}: {exc}')
                else:
                    unknown.append(f'{aid}:run0:{exc}')
        if unknown:
            audit_add(checks, 'v2_native_science_gates', 'UNKNOWN', '; '.join(unknown[:12]))
        else:
            audit_add(checks, 'v2_native_science_gates', 'PASS', 'all setup-level source parsers completed; per-cycle warm reviews are separate')

    def audit__api_result(name: str, key: str, checks: list[dict], metrics: dict | None=None) -> dict:
        statuses = [c['status'] for c in checks if c.get('blocking', True)]
        status = 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if any((s in ('UNKNOWN', 'PARTIAL') for s in statuses)) else 'PASS'
        return {'schema': 'case06-v2-source-review-result/v1', key: name, 'status': status, 'checks': checks, 'metrics': metrics or {}}

    def audit_review_setup_sources(outputs: audit_Path, setup_row: dict, native_ledger: dict, reference_root: audit_Path | None=None) -> dict:
        """Raw-recompute all preparation gates for exactly one phase_setup.

        `setup_row` is a `phase_setups[]` row. The native ledger must already have
        passed `verify_native_ledger`; this function uses its raw invocation inventory
        only to bind files to native stage segments.
        """
        checks = []
        sid = str(setup_row.get('setup_id') or '')
        if not sid:
            audit_add(checks, 'v2_setup_source_identity', 'UNKNOWN', 'setup_id missing')
            return audit__api_result(sid, 'setup_id', checks)
        ledger = native_ledger.get('raw_ledger', native_ledger)
        raw_inv = ledger.get('native_invocations', [])
        inv = {str(x.get('invocation_id')): x for x in raw_inv if isinstance(x, dict) and x.get('invocation_id')}
        role_data = {'run_records': {sid: setup_row}, 'native_invocations': inv}
        evidence = {'phase_setups': [setup_row]}
        before = len(checks)
        audit__review_setup_sources_batch(outputs, evidence, role_data, checks, reference_root)
        return audit__api_result(sid, 'setup_id', checks)

    def audit__parse_warm_temperature(path: audit_Path, expected_start: int, expected_end: int, lam: int) -> dict:
        rows = []
        for (no, line) in enumerate(path.read_text(encoding='utf-8', errors='strict').splitlines(), 1):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            f = s.split()
            if len(f) != 6:
                raise audit_Mismatch(f'{path.name}:{no}: warm ave/time row must have step,Tcm,lambda,dU1,dU2,dU3')
            vals = [finite(x) for x in f]
            if any((v is None for v in vals)) or not vals[0].is_integer():
                raise audit_Mismatch(f'{path.name}:{no}: nonfinite or non-integer warm observation')
            rows.append(vals)
        expected = list(range(expected_start + 20, expected_end + 1, 20))
        steps = [int(r[0]) for r in rows]
        if len(rows) == 51 and steps == [expected_start] + expected:
            metric_rows = rows[1:]
        elif len(rows) == 50 and steps == expected:
            metric_rows = rows
        else:
            raise audit_Mismatch(f'{path.name}: expected 50 cadence-20 samples over {expected_start + 20}..{expected_end}, optionally preceded by one start-boundary row')
        if any((abs(r[2] - lam) > 5e-15 for r in rows)):
            raise audit_Mismatch('warm source lambda is not held at its registered endpoint, including any start-boundary row')
        temps = [r[1] for r in metric_rows]
        a = temps[:25]
        b = temps[25:]

        def diagnostic(values):
            ess = audit__geyer_ess(values)
            result = {'mean': sum(values) / len(values), 'ess': ess, 'ci95_low': None, 'ci95_high': None}
            if audit_math.isfinite(ess) and ess > 2:
                try:
                    import statistics
                    from scipy.stats import t as student_t
                    half = float(student_t.ppf(0.975, max(1, int(audit_math.floor(ess)) - 1))) * statistics.stdev(values) / audit_math.sqrt(ess)
                    result['ci95_low'] = result['mean'] - half
                    result['ci95_high'] = result['mean'] + half
                except Exception:
                    pass
            return result
        full = diagnostic(temps)
        ca = diagnostic(a)
        cb = diagnostic(b)
        drift = {'mean_difference_K': None, 'ci95': None}
        if ca['ci95_low'] is not None and cb['ci95_low'] is not None:
            import statistics
            from scipy.stats import t as student_t
            diff = cb['mean'] - ca['mean']
            se = audit_math.sqrt(statistics.variance(a) / ca['ess'] + statistics.variance(b) / cb['ess'])
            df = max(1, int(audit_math.floor(min(ca['ess'], cb['ess']))) - 1)
            half = float(student_t.ppf(0.975, df)) * se
            drift = {'mean_difference_K': diff, 'ci95': [diff - half, diff + half]}
        precision_detail = 'ESS/CI/drift are diagnostic only; they do not establish finite-warm-bias equivalence' if all((x['ci95_low'] is not None for x in (full, ca, cb))) else 'ESS too low for a diagnostic t interval; finite-warm-bias remains UNKNOWN'
        return {'sha256': audit_sha(path), 'rows': len(metric_rows), 'first_step': expected[0], 'last_step': expected[-1], 'full': full, 'first_half': ca, 'second_half': cb, 'half_drift': drift, 'temperature_precision_status': 'UNKNOWN_DIAGNOSTIC_ONLY', 'finite_warm_bias_status': 'UNKNOWN', 'diagnostic_note': precision_detail}

    def audit_review_cycle_sources(outputs: audit_Path, cycle_row: dict, phase_setup: dict, native_ledger: dict, reference_root: audit_Path | None=None) -> dict:
        """Review both per-cycle warm windows from their raw native outputs.

        This deliberately runs once per integration cycle even when several cycles
        share one preparation snapshot (for example B and D).
        """
        checks = []
        metrics = {}
        cycle_id = str(cycle_row.get('cycle_id') or '')
        try:
            if not cycle_id:
                raise audit_UnknownEvidence('cycle_id missing')
            ledger = native_ledger.get('raw_ledger', native_ledger)
            invs = {str(x.get('invocation_id')): x for x in ledger.get('native_invocations', []) if isinstance(x, dict) and x.get('invocation_id')}
            refs = cycle_row.get('invocation_segments', cycle_row.get('segments', []))
            cycle_segments = []
            for ref in refs:
                iid = str(ref.get('invocation_id') or '')
                idx = int(ref.get('run_index', -1))
                call = invs.get(iid)
                if not call:
                    raise audit_Mismatch(f'{cycle_id}: warm source invocation absent from global ledger')
                try:
                    (segment, _position) = audit__segment_for_native_ref(call, ref)
                except Exception as exc:
                    raise audit_Mismatch(f'{cycle_id}: warm marker run index absent from invocation') from exc
                cycle_segments.append((ref, call, segment))
            warm_refs = [(r, c, s) for (r, c, s) in cycle_segments if s.get('segment_kind', s.get('kind')) in ('fe_warm_physical', 'fe_warm_einstein')]
            if len(warm_refs) != 2:
                raise audit_UnknownEvidence(f'{cycle_id}: requires physical and Einstein warm native segments')
            warm_by_kind = {str(s.get('segment_kind', s.get('kind'))): (r, c, s) for (r, c, s) in warm_refs}
            if set(warm_by_kind) != {'fe_warm_physical', 'fe_warm_einstein'}:
                raise audit_Mismatch('warm source kinds are duplicate or incomplete')
            gates = cycle_row.get('warm_sources')
            if not isinstance(gates, dict):
                raise audit_UnknownEvidence('cycle raw warm_sources object missing')
            for (label, kind, lam) in (('physical_lambda0', 'fe_warm_physical', 0), ('einstein_lambda1', 'fe_warm_einstein', 1)):
                source = gates.get(label)
                if not isinstance(source, dict):
                    raise audit_UnknownEvidence(f'{label} raw source record missing')
                (ref, call, seg) = warm_by_kind[kind]
                if int(seg.get('actual_steps', seg.get('planned_steps', -1))) != 1000 or int(seg.get('atoms', 0)) not in (audit_PHASE_ATOMS.get(cycle_row.get('phase')), 2 * audit_PHASE_ATOMS.get(cycle_row.get('phase'))):
                    raise audit_Mismatch(f'{cycle_id}: {kind} is not the exact 1000-step phase-native warm segment')
                temp = source.get('temperature')
                if not isinstance(temp, dict):
                    raise audit_UnknownEvidence(f'{label} temperature file link missing')
                temp_ref = temp.get('raw_source')
                temp_inv = temp.get('source_invocation')
                if not isinstance(temp_inv, dict) or str(temp_inv.get('invocation_id')) != str(ref.get('invocation_id')) or int(temp_inv.get('run_index', -1)) != int(ref.get('run_index', -2)):
                    raise audit_Mismatch(f'{cycle_id}: {label} temperature is not linked to its actual cycle warm segment')
                (temp_path, _) = audit__source_output_bound(outputs, temp_ref, temp_inv, invs, allowed_kinds=(kind,), reference_root=reference_root)
                metrics[label] = audit__parse_warm_temperature(temp_path, int(seg.get('start_step')), int(seg.get('end_step')), lam)
                executed = audit__ledger_file_ref(outputs, call.get('executed_input'), reference_root)
                text = executed.read_text(encoding='utf-8', errors='strict')
                for (source_key, call_key) in (('source_input', 'original_input'), ('source_script', 'executed_input')):
                    declared = source.get(source_key)
                    if not isinstance(declared, dict) or not isinstance(declared.get('raw_source'), dict):
                        raise audit_UnknownEvidence(f'{cycle_id}: {label} missing {source_key} source binding')
                    declared_inv = declared.get('source_invocation', {})
                    if declared_inv.get('invocation_id') != ref.get('invocation_id') or int(declared_inv.get('run_index', -1)) != int(ref.get('run_index', -2)):
                        raise audit_Mismatch(f'{cycle_id}: {label} {source_key} does not bind the warm invocation/run')
                    actual_ref = call.get(call_key)
                    if not isinstance(actual_ref, dict):
                        raise audit_UnknownEvidence(f'{cycle_id}: native call lacks {call_key}')
                    declared_path = audit__ledger_file_ref(outputs, declared['raw_source'], reference_root)
                    actual_path = audit__ledger_file_ref(outputs, actual_ref, reference_root)
                    if declared_path.resolve() != actual_path.resolve() or audit_sha(declared_path) != audit_sha(actual_path):
                        raise audit_Mismatch(f'{cycle_id}: {label} {source_key} differs from invocation source bytes')
                filename = temp_path.name
                if not audit__script_binds_ave_time(executed, filename, 20):
                    fix_lines = [x for x in text.splitlines() if filename in x and 'ave/time' in x]
                    if len(fix_lines) != 1 or audit_re.search('\\bave/time\\s+20\\s+1\\s+20\\b', fix_lines[0]) is None:
                        raise audit_Mismatch(f'{cycle_id}: executed input does not bind warm output to cadence-20 ave/time')
                checks.append({'check': f'v2_{label}_temperature_precision_diagnostic', 'status': 'UNKNOWN', 'blocking': False, 'detail': f'{cycle_id}: exact finite 50-row Tcm/lambda source recomputed; ESS/CI are diagnostic only and finite warm bias remains UNKNOWN'})
                if label == 'physical_lambda0':
                    traj = source.get('trajectory')
                    if not isinstance(traj, dict):
                        raise audit_UnknownEvidence('physical warm trajectory source missing')
                    trref = traj.get('raw_source')
                    trinv = traj.get('source_invocation')
                    if not isinstance(trinv, dict) or trinv.get('invocation_id') != ref.get('invocation_id') or int(trinv.get('run_index', -1)) != int(ref.get('run_index', -2)):
                        raise audit_Mismatch('physical warm trajectory does not bind to the lambda0 warm native segment')
                    (trpath, _) = audit__source_output_bound(outputs, trref, trinv, invs, allowed_kinds=(kind,), reference_root=reference_root)
                    frames = audit_parse_v2_fixed_h_dump(trpath, int(seg.get('atoms')), int(seg['start_step']), int(seg['end_step']), 20)
                    gap = audit__fixed_h_si_o_gap(frames)
                    face = min((_cell_face_heights(f['H']) for f in frames))
                    metrics['physical_lambda0_structure'] = {'frames': len(frames), 'gap_A': gap, 'minimum_face_A': face, 'sha256': audit_sha(trpath)}
                    if face <= 10.5:
                        raise audit_Mismatch('physical warm minimum triclinic face height is not >10.5 A')
                    setup_snapshot = phase_setup.get('snapshot')
                    if isinstance(setup_snapshot, dict):
                        spath = audit__ledger_file_ref(outputs, setup_snapshot, reference_root)
                        sd = audit__parse_run0_snapshot_state(spath, int(seg.get('atoms')))
                        if not audit__snapshot_matches_dump(sd, frames[0]):
                            raise audit_Mismatch('physical warm lambda0 first frame differs from prepared snapshot ID/type/q/velocity/H/origin')
                    else:
                        raise audit_UnknownEvidence('physical warm source lacks its prepared snapshot identity')
                    audit_add(checks, 'v2_physical_warm_structure', 'PASS', f'{cycle_id}: raw lambda0 graph is stable, gap positive, face >10.5 A')
                else:
                    lines = [_strip_lammps_comment(x).strip() for x in text.splitlines()]
                    masses = {}
                    for line in lines:
                        mm = audit_re.fullmatch('mass\\s+([12])\\s+([-+0-9.eE]+)', line, audit_re.I)
                        if mm:
                            typ = int(mm.group(1))
                            if typ in masses:
                                raise audit_Mismatch('Einstein warm input redefines a type mass')
                            masses[typ] = audit_finite(mm.group(2))
                    if set(masses) != {1, 2} or abs(masses[1] - 15.999) > 1e-09 or abs(masses[2] - 28.085) > 1e-09:
                        raise audit_Mismatch('Einstein warm source masses differ from frozen O/Si Hamiltonian')
                    fix_positions = []
                    for (i, line) in enumerate(lines):
                        if audit_re.fullmatch('fix\\s+ff[12]\\s+g[12]\\s+ti/spring\\s+.*', line, audit_re.I):
                            fix_positions.append(i)
                    parsed_fixes = {}
                    for line in lines:
                        fm = audit_re.fullmatch('fix\\s+(ff[12])\\s+(g[12])\\s+ti/spring\\s+([-+0-9.eE]+)\\s+(\\d+)\\s+(\\d+)\\s+function\\s+(\\d+)', line, audit_re.I)
                        if fm:
                            (fid, group, k, nswitch, nwarm, fn) = fm.groups()
                            parsed_fixes.setdefault(fid.lower(), []).append((group.lower(), audit_finite(k), int(nswitch), int(nwarm), int(fn)))
                    switches = [s for (_r, _c, s) in cycle_segments if s.get('segment_kind', s.get('kind')) == 'fe_switch']
                    if len(switches) != 2:
                        raise audit_UnknownEvidence('Einstein spring source requires both native switch segments')
                    expected_switch = int(switches[0].get('actual_steps', switches[0].get('planned_steps', -1)))
                    if set(parsed_fixes) != {'ff1', 'ff2'} or any((len(parsed_fixes[x]) != 1 for x in parsed_fixes)) or parsed_fixes['ff1'][0] != ('g1', 2.0, expected_switch, 1000, 2) or (parsed_fixes['ff2'][0] != ('g2', 4.0, expected_switch, 1000, 2)):
                        raise audit_Mismatch('Einstein warm source does not bind stock ff1/g1 k=2 and ff2/g2 k=4 function-2 fixes')
                    off = [i for (i, x) in enumerate(lines) if audit_re.fullmatch('pair_modify\\s+compute\\s+no', x, audit_re.I)]
                    on = [i for (i, x) in enumerate(lines) if audit_re.fullmatch('pair_modify\\s+compute\\s+yes', x, audit_re.I)]
                    if len(off) != 1 or len(on) != 1 or off[0] >= on[0]:
                        raise audit_Mismatch('Einstein warm must disable then restore pair compute around the lambda-1 warm segment')
                    ff_lines = [i for (i, x) in enumerate(lines) if audit_re.fullmatch('fix\\s+ff[12]\\s+g[12]\\s+ti/spring\\s+.*', x, audit_re.I)]
                    run_positions = [i for (i, x) in enumerate(lines) if audit_re.match('^run\\s+\\d+\\b', x, audit_re.I)]
                    positive_run_positions = [i for i in run_positions if audit_re.fullmatch('run\\s+[1-9]\\d*', lines[i], audit_re.I)]
                    if len(ff_lines) != 2 or not positive_run_positions or max(ff_lines) > positive_run_positions[0]:
                        raise audit_Mismatch('Calphy ti/spring fixes must capture prepared read_data anchors before the first physical warm run')
                    run_line_positions = [i for (i, x) in enumerate(lines) if audit_re.match('^run\\s+\\d+\\b', x, audit_re.I)]
                    warm_run_idx = int(ref.get('run_index', 0))
                    switch_refs = [r for (r, _c, s) in cycle_segments if s.get('segment_kind', s.get('kind')) == 'fe_switch']
                    if len(switch_refs) != 2 or warm_run_idx < 1 or warm_run_idx > len(run_line_positions):
                        raise audit_UnknownEvidence('native input does not expose the exact run ordering for pair-compute transition')
                    switch_first_idx = int(switch_refs[0].get('run_index', 0))
                    if switch_first_idx < 1 or switch_first_idx > len(run_line_positions):
                        raise audit_UnknownEvidence('first switch run index cannot be resolved in executed source')
                    if not run_line_positions[switch_first_idx - 1] < off[0] < run_line_positions[warm_run_idx - 1] < on[0]:
                        raise audit_Mismatch('pair compute must be disabled after forward switch and restored after Einstein warm')
                    spring = source.get('spring')
                    if not isinstance(spring, dict):
                        raise audit_UnknownEvidence('Einstein warm species spring energy output missing')
                    (spath, _) = audit__source_output_bound(outputs, spring.get('raw_source'), spring.get('source_invocation'), invs, allowed_kinds=(kind,), reference_root=reference_root)
                    if audit_sha(spath) != audit_sha(temp_path):
                        raise audit_Mismatch('Einstein spring alias and Tcm source must be the same native six-column trace')
                    trajectory = source.get('trajectory')
                    if not isinstance(trajectory, dict):
                        raise audit_UnknownEvidence('Einstein warm trajectory source missing')
                    traj_ref = trajectory.get('raw_source')
                    (traj_path, _) = audit__source_output_bound(outputs, traj_ref, trajectory.get('source_invocation'), invs, allowed_kinds=(kind,), reference_root=reference_root)
                    anchor_ref = phase_setup.get('snapshot')
                    if not isinstance(anchor_ref, dict):
                        raise audit_UnknownEvidence('Einstein warm lacks prepared snapshot anchor')
                    anchor_path = audit__ledger_file_ref(outputs, anchor_ref, reference_root)
                    physical = warm_by_kind.get('fe_warm_physical')
                    if physical is None:
                        raise audit_UnknownEvidence('Einstein spring anchor lacks physical warm segment')
                    (_phys_ref, _phys_call, phys_seg) = physical
                    phys_source = gates.get('physical_lambda0', {}).get('trajectory', {})
                    phys_ref = phys_source.get('raw_source') if isinstance(phys_source, dict) else None
                    if not isinstance(phys_ref, dict):
                        raise audit_UnknownEvidence('physical warm endpoint anchor source is missing')
                    (phys_path, _) = audit__source_output_bound(outputs, phys_ref, phys_source.get('source_invocation'), invs, allowed_kinds=('fe_warm_physical',), reference_root=reference_root)
                    phys_frames = audit_parse_v2_fixed_h_dump(phys_path, int(phys_seg.get('atoms')), int(phys_seg['start_step']), int(phys_seg['end_step']), 20)
                    if len(phys_frames) != 51:
                        raise audit_Mismatch('physical warm source requires exactly 51 frames')
                    anchor = audit__parse_run0_snapshot_state(anchor_path, int(seg.get('atoms')))
                    if not audit__snapshot_matches_dump(anchor, phys_frames[0]):
                        raise audit_Mismatch('physical warm first frame differs from prepared ti/spring anchor snapshot')
                    frames = audit_parse_v2_fixed_h_dump(traj_path, int(seg.get('atoms')), int(seg['start_step']), int(seg['end_step']), 20)
                    if len(frames) != 51:
                        raise audit_Mismatch('Einstein trajectory must include the source-bound first anchor frame plus 50 observations')
                    if frames[0]['H'] != anchor['geom']['H']:
                        raise audit_Mismatch('Einstein warm trajectory cell differs from prepared ti/spring anchor cell')
                    anchor_ids = [(a['id'], a['type']) for a in sorted(anchor['atoms'], key=lambda x: x['id'])]
                    frame_ids = [(a[0], a[1]) for a in frames[0]['atoms']]
                    if frame_ids != anchor_ids:
                        raise audit_Mismatch('Einstein warm trajectory ID/type inventory differs from prepared spring anchor')
                    q0 = {}
                    for a in anchor['atoms']:
                        (aid, typ, xyz, image) = (a['id'], a['type'], a['xyz'], a['image'])
                        q = tuple((xyz[j] + sum((image[k] * anchor['geom']['H'][k][j] for k in range(3))) for j in range(3)))
                        m = 16
                        gamma = m * audit_sys.float_info.epsilon / (1 - m * audit_sys.float_info.epsilon)
                        qerr = tuple((a['xyz_error'][j] + sum((abs(image[k]) * anchor['geom']['H_error'][k][j] for k in range(3))) + gamma * (abs(xyz[j]) + sum((abs(image[k] * anchor['geom']['H'][k][j]) for k in range(3))) + 1.0) for j in range(3)))
                        q0[aid] = (typ, q, qerr)
                    checks_energy = []
                    for atom in frames[0]['atoms']:
                        (aid, typ, _xyz, _image, _vel, q) = atom
                        if aid not in q0 or q0[aid][0] != typ:
                            raise audit_Mismatch('Einstein anchor ID/type inventory differs from trajectory')
                    energy_tokens = [line.split() for line in spath.read_text(encoding='utf-8', errors='strict').splitlines() if line.strip() and (not line.lstrip().startswith('#'))]
                    energy_raw = [[audit_finite(x) for x in row] for row in energy_tokens]
                    if any((len(row) != 6 or any((x is None for x in row)) or not row[0].is_integer() for row in energy_raw)):
                        raise audit_Mismatch('Einstein warm source must contain finite six-column observations with integer native steps')
                    expected_energy_steps = list(range(int(seg['start_step']) + 20, int(seg['end_step']) + 1, 20))
                    observed_energy_steps = [int(row[0]) for row in energy_raw]
                    if len(energy_raw) == 51 and observed_energy_steps == [int(seg['start_step'])] + expected_energy_steps:
                        energy_raw = energy_raw[1:]
                        energy_tokens = energy_tokens[1:]
                    elif len(energy_raw) != 50 or observed_energy_steps != expected_energy_steps:
                        raise audit_Mismatch('Einstein warm energy/T trace does not bind to the exact native step grid, optionally preceded by one start-boundary row')
                    for (k, row) in enumerate(energy_raw, 1):
                        frame = frames[k]
                        by_type = {}
                        model_error = {}
                        counts = {}
                        for (typ, kspring) in ((1, 2.0), (2, 4.0)):
                            (by_type[typ], model_error[typ], counts[typ]) = audit__spring_energy_with_source_bound(frame, q0, typ, kspring)
                        predicted = by_type
                        for (col, typ) in ((4, 1), (5, 2)):
                            print_error = audit__significant_print_half_quantum(energy_tokens[k - 1][col], 16) + 0.5 * audit_math.ulp(row[col])
                            tol = print_error + model_error[typ]
                            if abs(row[col] - predicted[typ]) > tol:
                                raise audit_Mismatch('Einstein warm per-species spring energy differs from raw unwrapped trajectory/anchor recomputation')
                    metrics['einstein_spring'] = {'rows': len(energy_raw), 'trajectory_frames': len(frames), 'dU2_units': 'total_group_eV', 'dU3_units': 'total_group_eV', 'source_expressions': {'dU2': 'f_ff1', 'dU3': 'f_ff2'}, 'sha256': audit_sha(spath), 'trajectory_sha256': audit_sha(traj_path), 'anchor_sha256': audit_sha(anchor_path)}
                    audit_add(checks, 'v2_einstein_spring_source', 'PASS', f'{cycle_id}: source-bound masses/fixes/pair-compute order and 50-row per-species spring energy recomputed from raw coordinates')
            checks.append({'check': 'v2_finite_warm_bias', 'status': 'UNKNOWN', 'blocking': False, 'detail': 'raw source/hard λ/H/anchor/physical-phase checks do not bound finite warm-start bias'})
            result = audit__api_result(cycle_id, 'cycle_id', checks, metrics)
            hard = [c for c in checks if c.get('blocking', True)]
            result['status'] = 'FAIL' if any((c['status'] == 'FAIL' for c in hard)) else 'UNKNOWN' if any((c['status'] in ('UNKNOWN', 'PARTIAL') for c in hard)) else 'PASS'
            result['claim_status'] = 'UNRESOLVED_FINITE_WARM_BIAS'
            return result
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_cycle_warm_local_admission', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_cycle_warm_local_admission', 'FAIL', str(exc))
        return audit__api_result(cycle_id, 'cycle_id', checks, metrics)

    def audit_verify_science_gates(outputs: audit_Path, evidence: dict, role_data: dict, checks: list[dict], native_ledger: dict | None=None, reference_root: audit_Path | None=None) -> None:
        """Public orchestration facade; preparation is deduplicated, warm is per cycle."""
        setups = evidence.get('phase_setups', [])
        if not setups:
            audit_add(checks, 'v2_native_science_gates', 'UNKNOWN', 'no phase setup source records')
            return
        ledger = native_ledger or role_data or {}
        seen = set()
        unknown = []
        for setup in setups:
            sid = str(setup.get('setup_id') or '')
            if not sid:
                unknown.append('setup_id missing')
                continue
            if sid in seen:
                continue
            seen.add(sid)
            result = audit_review_setup_sources(outputs, setup, ledger, reference_root)
            for c in result['checks']:
                checks.append(c)
            if result['status'] != 'PASS':
                unknown.append(f"{sid}:{result['status']}")
        raw = ledger.get('raw_ledger', ledger)
        cycles = raw.get('integration_cycles', []) if isinstance(raw, dict) else []
        setup_map = {str(s.get('setup_id')): s for s in setups if s.get('setup_id')}
        for cycle in cycles:
            sid = str(cycle.get('setup_id') or '')
            setup = setup_map.get(sid)
            if setup is None:
                unknown.append(f"{cycle.get('cycle_id')}: missing linked phase setup")
                continue
            result = audit_review_cycle_sources(outputs, cycle, setup, ledger, reference_root)
            checks.extend(result['checks'])
            if result['status'] != 'PASS':
                unknown.append(f"{cycle.get('cycle_id')}:{result['status']}")
        if unknown:
            audit_add(checks, 'v2_native_science_gates', 'UNKNOWN', '; '.join(unknown[:20]))
        else:
            audit_add(checks, 'v2_native_science_gates', 'PASS', 'all unique setup gates and each integration-cycle warm gate replayed from raw source')

    def audit_verify_active_time(outputs: audit_Path, evidence: dict, extension_path: audit_Path, checks: list[dict]) -> None:
        """Do not silently add a fresh clock to the exhausted historical 12-hour cap."""
        try:
            ext = audit__load_json(extension_path)
            receipt = evidence.get('resource_receipt')
            if not isinstance(receipt, dict):
                audit_add(checks, 'v2_active_time_accounting', 'UNKNOWN', 'campaign lacks separately activated resource receipt')
                return
            path = audit__file_ref(outputs, receipt)
            doc = audit__load_json(path)
            if doc.get('historical', {}).get('reset') is not False or doc.get('historical', {}).get('original_admission') != 'EXHAUSTED_NOT_COMPLETE':
                raise audit_Mismatch('campaign resource receipt resets historical active allowance')
            if doc.get('prospective', {}).get('activated') is not True:
                audit_add(checks, 'v2_active_time_accounting', 'UNKNOWN', 'prospective active budget not activated')
                return
            limit = int(doc['prospective']['active_limit_seconds'])
            execution = doc.get('execution')
            if not isinstance(execution, dict):
                audit_add(checks, 'v2_active_time_accounting', 'UNKNOWN', 'resource receipt lacks raw execution-clock source links')
                return
            clock_path = audit__file_ref(outputs, execution.get('controller_clock'))
            interval_path = audit__file_ref(outputs, execution.get('execution_intervals'))
            clock = audit__load_json(clock_path)
            interval_doc = audit__load_json(interval_path)
            if clock.get('schema') != 'case06-campaign-clock/v1' or interval_doc.get('schema') != 'case06-execution-intervals/v1':
                raise audit_Mismatch('active-time raw source schema mismatch')

            def utc_seconds(value, where):
                if not isinstance(value, str):
                    raise audit_Mismatch(f'{where}: UTC timestamp missing')
                try:
                    parsed = audit_datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if parsed.tzinfo is None:
                        raise ValueError('timezone absent')
                    return parsed.timestamp()
                except Exception as exc:
                    raise audit_Mismatch(f'{where}: invalid timezone-aware UTC timestamp') from exc
            clock_start = utc_seconds(clock.get('start_utc'), 'campaign clock start')
            clock_end = utc_seconds(clock.get('end_utc'), 'campaign clock end')
            mono_start = clock.get('start_monotonic_ns')
            mono_end = clock.get('end_monotonic_ns')
            if not isinstance(mono_start, int) or not isinstance(mono_end, int) or mono_end < mono_start:
                raise audit_Mismatch('campaign clock lacks ordered monotonic start/end nanoseconds')
            controller_seconds = (mono_end - mono_start) / 1000000000.0
            controller_utc_seconds = clock_end - clock_start
            if abs(controller_seconds - controller_utc_seconds) > 1.0:
                raise audit_Mismatch('campaign controller monotonic and UTC elapsed intervals disagree by >1 s')
            declared_controller = audit_finite(clock.get('controller_elapsed_seconds'))
            if declared_controller is None or abs(declared_controller - controller_seconds) > 1.0:
                raise audit_Mismatch('campaign clock elapsed metadata differs from raw monotonic endpoints')
            intervals = interval_doc.get('intervals')
            if not isinstance(intervals, list):
                raise audit_Mismatch('execution interval list is absent')
            seen = set()
            spans = []
            unfinished = []
            for row in intervals:
                if not isinstance(row, dict):
                    raise audit_Mismatch('execution interval row is not an object')
                iid = row.get('interval_id')
                if not isinstance(iid, str) or not iid or iid in seen:
                    raise audit_Mismatch('execution interval IDs are missing or duplicated')
                seen.add(iid)
                s = row.get('start_monotonic_ns')
                e = row.get('end_monotonic_ns')
                su = utc_seconds(row.get('start_utc'), f'interval {iid} start')
                if not isinstance(s, int) or s < mono_start or s > mono_end:
                    raise audit_Mismatch(f'interval {iid} monotonic start lies outside campaign clock')
                if e is None:
                    if row.get('state') != 'ACTIVE':
                        raise audit_Mismatch(f'interval {iid} has no end but is not ACTIVE')
                    upper = audit_finite(row.get('reserved_upper_seconds'))
                    if upper is None or upper < 0:
                        unfinished.append(iid)
                    else:
                        unfinished.append((iid, upper))
                    continue
                if not isinstance(e, int) or e < s or e > mono_end:
                    raise audit_Mismatch(f'interval {iid} monotonic endpoints are invalid')
                eu = utc_seconds(row.get('end_utc'), f'interval {iid} end')
                elapsed = (e - s) / 1000000000.0
                utc_elapsed = eu - su
                reported = audit_finite(row.get('elapsed_seconds'))
                if abs(elapsed - utc_elapsed) > 1.0 or reported is None or abs(reported - elapsed) > 1.0:
                    raise audit_Mismatch(f'interval {iid} UTC, monotonic, and reported durations disagree')
                spans.append((s, e))
            spans.sort()
            union_ns = 0
            union_end = None
            for (s, e) in spans:
                if union_end is None or s > union_end:
                    union_ns += e - s
                    union_end = e
                elif e > union_end:
                    union_ns += e - union_end
                    union_end = e
            interval_union = union_ns / 1000000000.0
            if interval_union > controller_seconds + 1.0:
                raise audit_Mismatch('native operation interval union exceeds campaign controller interval')
            start_ref = execution.get('outer_job_start')
            outer_elapsed = None
            outer_to_controller = None
            finish_doc = None
            finish_status = None
            if isinstance(start_ref, dict):
                start_path = audit__file_ref(outputs, start_ref)
                fields = dict((line.strip().split('=', 1) for line in start_path.read_text(encoding='utf-8', errors='strict').splitlines() if '=' in line))
                outer_start = utc_seconds(fields.get('started_utc'), 'outer scheduler start')
                if outer_start > clock_start + 1.0:
                    raise audit_Mismatch('outer scheduler start is later than controller start')
                outer_to_controller = max(0.0, clock_end - outer_start)
                finish_status = clock.get('outer_job_finish_status', execution.get('outer_job_finish_status'))
                finish_ref = clock.get('outer_job_finish_ref', execution.get('outer_job_finish_ref'))
                if finish_status in ('COLLECTED_AND_HASH_BOUND', 'VERIFIED') and isinstance(finish_ref, dict):
                    finish_path = audit__file_ref(outputs, finish_ref)
                    finish_doc = audit__load_json(finish_path) if finish_path.suffix.lower() == '.json' else None
                    if not isinstance(finish_doc, dict):
                        raise audit_Mismatch('outer scheduler finish receipt is not parseable JSON')
                    if finish_doc.get('state') not in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT'):
                        raise audit_Mismatch('outer scheduler receipt is not terminal')
                    if finish_doc.get('job_id') != clock.get('scheduler_job_id', finish_doc.get('job_id')):
                        raise audit_Mismatch('outer scheduler terminal receipt job ID differs from campaign clock')
                    finish_started = utc_seconds(finish_doc.get('started_utc', finish_doc.get('start_utc')), 'outer scheduler receipt start')
                    finish_ended = utc_seconds(finish_doc.get('ended_utc', finish_doc.get('end_utc')), 'outer scheduler receipt end')
                    if abs(finish_started - outer_start) > 1.0 or finish_ended < clock_end - 1.0:
                        raise audit_Mismatch('outer scheduler receipt endpoints disagree with source start/controller end')
                    outer_elapsed = finish_ended - outer_start
                else:
                    outer_elapsed = outer_to_controller
            utc_spans = []
            if isinstance(start_ref, dict) and finish_doc is not None:
                utc_spans.append((outer_start, finish_ended))
            extra_refs = execution.get('extra_active_interval_sources', [])
            if extra_refs is None:
                extra_refs = []
            if not isinstance(extra_refs, list):
                raise audit_Mismatch('extra active interval source list has invalid schema')
            for extra_ref in extra_refs:
                p = audit__file_ref(outputs, extra_ref)
                extra = audit__load_json(p)
                if extra.get('schema') != 'case06-author-active-interval/v1':
                    raise audit_Mismatch('author active interval has unsupported raw schema')
                if not isinstance(extra.get('kind'), str) or not extra['kind'] or (not isinstance(extra.get('host'), str)) or (not extra['host']):
                    raise audit_Mismatch('author active interval lacks kind/host provenance')
                es = utc_seconds(extra.get('start_utc'), 'author interval start')
                ee = utc_seconds(extra.get('end_utc'), 'author interval end')
                sm = extra.get('start_monotonic_ns')
                em = extra.get('end_monotonic_ns')
                reported = audit_finite(extra.get('elapsed_seconds'))
                if not isinstance(sm, int) or not isinstance(em, int) or em < sm or (ee < es) or (reported is None):
                    raise audit_Mismatch('author active interval endpoints/duration are invalid')
                local_duration = (em - sm) / 1000000000.0
                utc_duration = ee - es
                if abs(local_duration - utc_duration) > 1.0 or abs(reported - local_duration) > 1.0:
                    raise audit_Mismatch('author interval UTC/monotonic/reported durations disagree')
                utc_spans.append((es, ee))
            utc_spans.sort()
            utc_union = 0.0
            utc_end = None
            for (s, e) in utc_spans:
                if utc_end is None or s > utc_end:
                    utc_union += e - s
                    utc_end = e
                elif e > utc_end:
                    utc_union += e - utc_end
                    utc_end = e
            observed = utc_union if utc_spans else max(controller_seconds, outer_elapsed or 0.0)
            budget = evidence.get('budget', {})
            if not isinstance(budget, dict):
                raise audit_UnknownEvidence('campaign budget source missing')
            raw_observed = audit_finite(execution.get('active_elapsed_seconds'))
            reserve = audit_finite(execution.get('active_unlocated_reserve_seconds'))
            if raw_observed is None or reserve is None or reserve < 0:
                audit_add(checks, 'v2_active_time_accounting', 'UNKNOWN', 'raw observed active time or explicit reserve missing')
                return
            if abs(raw_observed - observed) > 1.0:
                raise audit_Mismatch('resource active elapsed differs from raw controller/outer scheduler interval')
            for (key, expected) in (('active_elapsed_seconds', raw_observed), ('active_unlocated_reserve_seconds', reserve)):
                declared = audit_finite(budget.get(key))
                if declared is None or abs(declared - expected) > 1e-06:
                    raise audit_Mismatch(f'campaign budget {key} differs from resource receipt source')
            budget_remaining = audit_finite(budget.get('active_limit_remaining_seconds'))
            if budget_remaining is None or abs(budget_remaining - max(0.0, limit - observed - reserve)) > 1.0:
                raise audit_Mismatch('campaign budget remaining allowance is not limit minus observed and reserve')
            remaining = audit_finite(execution.get('active_limit_remaining_seconds'))
            expected_remaining = max(0.0, limit - observed - reserve)
            if remaining is None or abs(remaining - expected_remaining) > 1.0:
                raise audit_Mismatch('reported remaining active allowance does not equal limit minus observed and reserve')
            if observed + reserve > limit:
                raise audit_Mismatch('new campaign observed plus reserved active time exceeds its incremental limit')
            audit_add(checks, 'v2_active_interval_union', 'PASS', f'raw controller interval {controller_seconds:g}s; native-operation union {interval_union:g}s; outer/author UTC union {observed:g}s')
            if finish_doc is None:
                audit_add(checks, 'v2_active_outer_job_closure', 'UNKNOWN', 'collector-owned outer scheduler finish is not yet source-bound; controller end is not treated as allocation end')
                return
            audit_add(checks, 'v2_active_outer_job_closure', 'PASS', 'terminal scheduler receipt is hash-bound and agrees with outer start/controller end')
            audit_add(checks, 'v2_active_time_accounting', 'PASS', f'incremental active accounted {observed + reserve:g}/{limit}s; historical exhausted allowance remains unchanged')
        except audit_UnknownEvidence as exc:
            audit_add(checks, 'v2_active_time_accounting', 'UNKNOWN', str(exc))
        except Exception as exc:
            audit_add(checks, 'v2_active_time_accounting', 'FAIL', str(exc))

    def audit_main(argv: list[str] | None=None) -> int:
        parser = audit_argparse.ArgumentParser(description=__doc__)
        parser.add_argument('outputs', type=audit_Path)
        parser.add_argument('--campaign-evidence', type=audit_Path)
        parser.add_argument('--reference', type=audit_Path, help='sealed private author-reference descriptor outside candidate outputs')
        parser.add_argument('--plan', type=audit_Path, default=audit_DEFAULT_PLAN)
        parser.add_argument('--resource-extension', type=audit_Path, default=audit_DEFAULT_EXTENSION)
        parser.add_argument('--receipt', type=audit_Path)
        ns = parser.parse_args(argv)
        result = audit_verify(ns.outputs, ns.campaign_evidence, ns.reference, ns.plan, ns.resource_extension)
        encoded = audit_json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
        if ns.receipt:
            ns.receipt.write_text(encoded, encoding='utf-8')
        audit_sys.stdout.write(encoded)
        return int(result['exit_code'])

    # END MERGED NATIVE KERNEL SOURCE


    # Direct campaign helpers from full_campaign.py; historical A/admission entrypoints excluded.
    """Fail-closed global orchestrator for the Case-06 single-state-v2 campaign.

    The native adapter is the separately source-reviewed fullcell driver. This module
    owns campaign ordering, role isolation, immutable accounting, adaptive selection,
    private-reference isolation, output projection and resource stops. It never treats
    fixture/mock evidence as native science.
    """
    import argparse as fc_argparse, csv as fc_csv, hashlib as fc_hashlib, importlib.util as fc_importlib, json as fc_json, math as fc_math, os as fc_os, re as fc_re, shutil as fc_shutil, sys as fc_sys, time as fc_time, traceback as fc_traceback
    from datetime import datetime as fc_datetime, timezone as fc_timezone
    from pathlib import Path as fc_Path
    from typing import Any as fc_Any
    fc_HERE = fc_Path(__file__).resolve().parent
    fc_PAYLOAD = fc_HERE.parent
    fc_CANDIDATE = fc_PAYLOAD.parent
    fc_PLAN = fc_PAYLOAD / 'planning' / 'case08-run-matrix.json'
    fc_PUBLIC = fc_PAYLOAD / 'packages' / 'case-06'
    fc_OUTPUTS = fc_PAYLOAD / 'outputs'
    fc_REFERENCE = fc_PAYLOAD / 'author-reference-private'
    fc_MATRIX_SHA = '58599733bcecb0017d0863e1054ba9311858f8e6b986713af064be737e5c5d9e'
    fc_POTENTIAL_SHA = 'c8f00d8f0cbc131b0298b79260ba8098975624363c9d178223e51e48f025e97a'
    fc_PHASES = ('alpha_quartz', 'coesite')
    fc_DIRECTIONS = ('forward', 'backward')
    fc_ATOM_COUNTS = {'alpha_quartz': 576, 'coesite': 384}
    fc_ROLE_MAP = {'B': 'baseline', 'R': 'independent_repeat', 'S': 'adaptive_size', 'D': 'adaptive_duration', 'A': 'independent_reference'}
    fc_CSV_GIBBS = ['phase', 'T_K', 'P_bar', 'G_eV_per_atom', 'replicate', 'direction', 'cell_atoms', 'equilibration_steps', 'switching_steps', 'window_start', 'window_end', 'uncertainty_eV_per_atom', 'status', 'reason']
    fc_CSV_DELTA = ['T_K', 'P_bar', 'G_coesite_minus_G_alpha_eV_per_atom', 'repeat_uncertainty_eV_per_atom', 'direction_uncertainty_eV_per_atom', 'switching_uncertainty_eV_per_atom', 'finite_size_uncertainty_eV_per_atom', 'combined_uncertainty_eV_per_atom', 'decision', 'reason']
    fc_CSV_ERROR = ['quantity', 'phase_a', 'phase_b', 'T_K', 'P_bar', 'estimate_eV_per_atom', 'method', 'replicates_or_windows', 'source_run_ids', 'status', 'reason']

    class fc_Stop(RuntimeError):
        pass

    def fc__clock_utc():
        return fc_time.strftime('%Y-%m-%dT%H:%M:%SZ', fc_time.gmtime())

    def fc__outer_job_start(path):
        if not fc_Path(path).is_file():
            return None
        try:
            fields = dict((line.strip().split('=', 1) for line in fc_Path(path).read_text().splitlines() if '=' in line))
            value = fc_datetime.fromisoformat(fields['started_utc'].replace('Z', '+00:00'))
            if value.tzinfo is None:
                value = value.replace(tzinfo=fc_timezone.utc)
            return value.timestamp()
        except Exception:
            return None

    def fc__write_interval(outputs, record_id, kind, role, phase, state, started_utc, started_mono_ns, ended=False):
        path = fc_Path(outputs) / 'execution-intervals.json'
        doc = fc_json.loads(path.read_text()) if path.is_file() else {'schema': 'case06-execution-intervals/v1', 'intervals': []}
        now = fc_time.monotonic_ns()
        row = next((x for x in doc['intervals'] if x.get('interval_id') == record_id), None)
        if row is None:
            row = {'interval_id': record_id, 'kind': 'active', 'operation_kind': kind, 'role': role, 'phase': phase, 'state': state, 'start_utc': started_utc, 'start_monotonic_ns': started_mono_ns}
            doc['intervals'].append(row)
        else:
            row['kind'] = 'active'
            row['operation_kind'] = kind
        if ended:
            row.update({'state': state, 'end_utc': fc__clock_utc(), 'end_monotonic_ns': now, 'elapsed_seconds': max(0.0, (now - started_mono_ns) / 1000000000.0)})
        fc_write_json(path, doc)

    def fc__accounting_totals(ledger):
        steps = atoms = attempts = 0
        for call in ledger.get('native_invocations', []):
            for seg in call.get('run_segments', []):
                n = seg.get('actual_steps')
                a = seg.get('atoms', seg.get('atom_count', call.get('atoms', 0)))
                if isinstance(n, int) and n >= 0:
                    steps += n
                    atoms += n * int(a or 0)
        attempts = len(ledger.get('direction_attempts', []))
        return (steps, atoms, attempts)

    def fc__linked_setup_steps(setup, ledger):
        """Recompute setup ancestry from registered Loop events, including FE warm."""
        index = {str(x.get('invocation_id')): x for x in ledger.get('native_invocations', [])}
        total = 0
        for ref in setup.get('invocation_segments', []):
            call = index.get(str(ref.get('invocation_id')))
            if call is None:
                raise fc_Stop('setup ancestry references an unregistered native invocation')
            matches = [s for s in call.get('run_segments', []) if int(s.get('run_index', -1)) == int(ref.get('run_index', -2))]
            if len(matches) != 1:
                raise fc_Stop('setup ancestry segment does not resolve uniquely')
            n = matches[0].get('actual_steps')
            if not isinstance(n, int) or n < 0:
                raise fc_Stop('setup ancestry has unknown native step count')
            total += n
        return total

    def fc_sha(path: fc_Path) -> str:
        h = fc_hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda : f.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    def fc_write_json(path: fc_Path, obj: fc_Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(fc_json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n')
        fc_os.replace(tmp, path)

    def fc_file_ref(path: fc_Path, root: fc_Path) -> dict:
        path = path.resolve()
        return {'path': str(path.relative_to(root.resolve())) if path.is_relative_to(root.resolve()) else str(path), 'sha256': fc_sha(path)}

    def fc__copy_admission_bundle(admission_path: fc_Path, outputs: fc_Path) -> dict:
        """Retain the exact admission and every hash-bound sibling source document."""
        bundle = outputs / 'provenance' / 'admission-bundle'
        bundle.mkdir(parents=True, exist_ok=True)
        admission_path = fc_Path(admission_path).resolve()
        raw_target = bundle / admission_path.name
        fc_shutil.copy2(admission_path, raw_target)
        if fc_sha(raw_target) != fc_sha(admission_path):
            raise fc_Stop('copied execution admission SHA changed')
        doc = fc_json.loads(admission_path.read_text())
        refs = {}
        for key in ('payload_manifest_ref', 'source_review_ref', 'verifier_implementation_review_ref', 'reference_calibration_prereg_review_ref', 'resource_supplement_ref'):
            item = doc.get(key)
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise fc_Stop(f'admission bundle source missing {key}')
            src = fc_Path(item['path'])
            src = src if src.is_absolute() else admission_path.parent / src
            src = src.resolve()
            if not src.is_file() or fc_sha(src) != item.get('sha256'):
                raise fc_Stop(f'admission bundle source hash mismatch: {key}')
            target = bundle / src.name
            if target.exists() and fc_sha(target) != fc_sha(src):
                raise fc_Stop(f'admission bundle basename collision: {src.name}')
            if not target.exists():
                fc_shutil.copy2(src, target)
            if fc_sha(target) != item['sha256']:
                raise fc_Stop(f'admission bundle copy SHA mismatch: {key}')
            refs[key] = fc_file_ref(target, outputs)
        return {'original_ref': fc_file_ref(raw_target, outputs), 'source_refs': refs}

    def fc__global_zero_binary_refs(proof: fc_Path) -> list[dict]:
        if not proof.is_file():
            return []
        doc = fc_json.loads(proof.read_text())
        refs = []
        for phase in ('alpha_quartz', 'coesite'):
            for comparison in ('raw_to_gauge', 'base_to_size'):
                item = doc.get('phases', {}).get(phase, {}).get('comparisons', {}).get(comparison, {})
                for side in ('base_call', 'target_call'):
                    ref = item.get(side, {}).get('binary_provenance_ref')
                    if isinstance(ref, dict) and ref not in refs:
                        refs.append(ref)
        return refs

    def fc__ref_path(value, root=None):
        p = fc_Path(value.get('path', '') if isinstance(value, dict) else str(value or ''))
        return p if p.is_absolute() or root is None else fc_Path(root) / p

    def fc__replay_invocation(inv, upper_steps, root, artifact_root, role):
        """Recount segments from immutable native Loop/BEGIN/END evidence, never plan sums."""
        required = ('invocation_id', 'original_input', 'executed_input', 'native_log', 'execution_receipt')
        if any((k not in inv for k in required)):
            raise fc_Stop('native invocation omitted immutable file references')
        paths = {k: _ref_path(inv[k], root) for k in ('original_input', 'executed_input', 'native_log', 'execution_receipt')}
        if any((not p.is_file() for p in paths.values())):
            raise fc_Stop('native invocation source/log/receipt is absent')
        for (k, p) in paths.items():
            refval = inv[k]
            if isinstance(refval, dict) and refval.get('sha256') and (refval['sha256'] != fc_sha(p)):
                raise fc_Stop(f'{k} artifact SHA differs from native invocation reference')
            try:
                stored_path = str(p.resolve().relative_to(fc_Path(artifact_root).resolve()))
            except ValueError:
                raise fc_Stop(f'{k} native artifact escapes its declared output namespace')
            namespace = 'author_reference' if role == 'A' else 'candidate'
            inv[k] = {'path': stored_path, 'sha256': fc_sha(p), 'namespace': namespace}
        original = paths['original_input'].read_text(errors='replace')
        executed = paths['executed_input'].read_text(errors='replace')
        log = paths['native_log'].read_text(errors='replace')
        receipt = fc_json.loads(paths['execution_receipt'].read_text())
        if receipt.get('native_returncode') != 0 or receipt.get('wrapper_integrity_rc') != 0 or receipt.get('manifest_run_plan_match') is not True:
            raise fc_Stop('native invocation return/integrity/run-plan receipt is not PASS')
        starts = fc_re.findall('^CASE08_RUN_BEGIN segment=(\\S+) index=(\\d+) planned_steps=(\\d+) start_step=(-?\\d+)\\s*$', log, fc_re.M)
        ends = fc_re.findall('^CASE08_RUN_END segment=(\\S+) index=(\\d+) planned_steps=(\\d+) end_step=(-?\\d+)\\s*$', log, fc_re.M)
        loops = fc_re.findall('^Loop time\\s+[^\\n]*?for\\s+(\\d+)\\s+steps\\s+with\\s+(\\d+)\\s+atoms\\s*$', log, fc_re.M)
        if not starts or len(starts) != len(ends) or len(starts) != len(loops):
            raise fc_Stop('native log BEGIN/Loop/END counts differ')
        original_steps = [int(x) for x in fc_re.findall('^\\s*run\\s+(\\d+)\\s*$', original, fc_re.M | fc_re.I)]
        executed_steps = [int(x) for x in fc_re.findall('^\\s*run\\s+(\\d+)\\s*$', executed, fc_re.M | fc_re.I)]
        segs = []
        for (i, (b, e, l)) in enumerate(zip(starts, ends, loops), 1):
            (name, index, planned, start) = b
            (ename, eindex, eplanned, end) = e
            (actual, atoms) = l
            planned = int(planned)
            actual = int(actual)
            atoms = int(atoms)
            start = int(start)
            end = int(end)
            if name != ename or int(index) != i or int(eindex) != i or (planned != int(eplanned)) or (actual != planned) or (end - start != actual):
                raise fc_Stop('native run segment marker plan differs from actual Loop steps')
            segs.append({'native_segment_name': name, 'run_index': i, 'planned_steps': planned, 'actual_steps': actual, 'atoms': atoms})
        native_steps = [x['actual_steps'] for x in segs]
        if original_steps != native_steps or executed_steps != native_steps:
            raise fc_Stop('literal original/executed run commands differ from actual native Loop events')
        if sum(native_steps) > upper_steps:
            raise fc_Stop('actual native invocation exceeds pre-reserved upper bound')
        inv['run_segments'] = segs
        return (inv, sum(native_steps))

    def fc__invoke(adapter, kind, *, upper_steps, atoms, **kwargs):
        """Execute adapter operation and independently replay every native invocation once."""
        kwargs.setdefault('atoms', atoms)
        started = fc_time.monotonic()
        started_ns = fc_time.monotonic_ns()
        started_utc = fc__clock_utc()
        interval_id = f"{kind}-{kwargs.get('role', 'NA')}-{kwargs.get('phase', 'NA')}-{started_ns}"
        interval_path = fc_Path(fc_os.environ.get('CASE06_OUTPUTS', ''))
        if str(interval_path) != '.':
            fc__write_interval(interval_path, interval_id, kind, kwargs.get('role'), kwargs.get('phase'), 'ACTIVE', started_utc, started_ns)
        try:
            call = getattr(adapter, kind)(**kwargs)
        except Exception as exc:
            if str(interval_path) != '.':
                fc__write_interval(interval_path, interval_id, kind, kwargs.get('role'), kwargs.get('phase'), 'FAILED', started_utc, started_ns, ended=True)
            elapsed = fc_time.monotonic() - started
            ledger = kwargs.get('global_native_ledger')
            partial = getattr(exc, 'partial_native_invocations', [])
            if not partial and callable(getattr(adapter, 'collect_partial_native_invocations', None)):
                try:
                    partial = adapter.collect_partial_native_invocations(role=kwargs.get('role'), run_root=kwargs.get('run_root'), phase=kwargs.get('phase'))
                except Exception as scan_exc:
                    exc.partial_native_scan_error = f'{type(scan_exc).__name__}: {scan_exc}'
            if isinstance(ledger, dict):
                for inv in partial:
                    rec = dict(inv)
                    rec.update({'phase': kwargs.get('phase'), 'role': kwargs.get('role'), 'accounting_status': 'PARTIAL_NATIVE_EVIDENCE_UNKNOWN', 'run_segments': inv.get('run_segments', [])})
                    try:
                        role = kwargs.get('role')
                        rroot = fc_Path(kwargs.get('run_root'))
                        artifact_root = fc_Path(fc_os.environ['CASE06_REFERENCE_ROOT']).resolve() if role == 'A' else fc_Path(fc_os.environ['CASE06_OUTPUTS']).resolve()
                        (rec, _) = fc__replay_invocation(rec, upper_steps, rroot, artifact_root, role)
                    except Exception as replay_exc:
                        rec['accounting_status'] = 'PARTIAL_NATIVE_EVIDENCE_UNKNOWN'
                        rec['replay_error'] = f'{type(replay_exc).__name__}: {replay_exc}'
                    if not any((x.get('invocation_id') == rec.get('invocation_id') for x in ledger['native_invocations'])):
                        ledger['native_invocations'].append(rec)
                if kind == 'run_one_fe_cycle' and (partial or getattr(exc, 'native_started', False)):
                    for direction in fc_DIRECTIONS:
                        ledger['direction_attempts'].append({'run_id': f"{kwargs.get('role')}-{kwargs.get('phase')}-{direction}-aborted", 'cycle_id': kwargs.get('cycle_id'), 'role': fc_ROLE_MAP.get(kwargs.get('role'), kwargs.get('role')), 'phase': kwargs.get('phase'), 'direction': direction, 'status': 'ABORTED_NATIVE_PARTIAL_UNKNOWN', 'reason': f'{type(exc).__name__}: {exc}'})
                fc_write_json(fc_Path(fc_os.environ['CASE06_OUTPUTS']) / 'native-event-ledger.json', ledger)
            raise
        elapsed = fc_time.monotonic() - started
        if str(interval_path) != '.':
            fc__write_interval(interval_path, interval_id, kind, kwargs.get('role'), kwargs.get('phase'), 'RETURNED', started_utc, started_ns, ended=True)
        if not isinstance(call, dict):
            raise fc_Stop(f'{kind} did not return a receipt object')
        if call.get('fixture') is True or call.get('native') is False:
            raise fc_Stop('fixture/non-native receipt cannot be admitted into production campaign')
        invocations = call.get('native_invocations')
        if invocations is None and isinstance(call.get('invocation'), dict):
            invocations = [call['invocation']]
        if not isinstance(invocations, list):
            raise fc_Stop(f'{kind} omitted native_invocations array')
        if not invocations and call.get('cached_native_evidence') is not True:
            raise fc_Stop(f'{kind} omitted native_invocations array')
        replayed = []
        actual = 0
        try:
            for inv in invocations:
                role = kwargs.get('role')
                rroot = fc_Path(kwargs.get('run_root'))
                artifact_root = fc_Path(fc_os.environ['CASE06_REFERENCE_ROOT']).resolve() if role == 'A' else fc_Path(fc_os.environ['CASE06_OUTPUTS']).resolve()
                (rec, n) = fc__replay_invocation(inv, upper_steps, rroot, artifact_root, role)
                replayed.append(rec)
                actual += n
        except Exception as exc:
            ledger = kwargs.get('global_native_ledger')
            if isinstance(ledger, dict):
                for inv in invocations:
                    rec = dict(inv)
                    rec.update({'phase': kwargs.get('phase'), 'role': kwargs.get('role'), 'accounting_status': 'NATIVE_RETURNED_REPLAY_UNKNOWN'})
                    if not any((x.get('invocation_id') == rec.get('invocation_id') for x in ledger['native_invocations'])):
                        ledger['native_invocations'].append(rec)
                if kind == 'run_one_fe_cycle':
                    for direction in fc_DIRECTIONS:
                        ledger['direction_attempts'].append({'run_id': f"{kwargs.get('role')}-{kwargs.get('phase')}-{direction}-replay-unknown", 'cycle_id': kwargs.get('cycle_id'), 'role': fc_ROLE_MAP.get(kwargs.get('role'), kwargs.get('role')), 'phase': kwargs.get('phase'), 'direction': direction, 'status': 'ABORTED_NATIVE_REPLAY_UNKNOWN', 'reason': f'{type(exc).__name__}: {exc}'})
                fc_write_json(fc_Path(fc_os.environ['CASE06_OUTPUTS']) / 'native-event-ledger.json', ledger)
            raise
        call['native_invocations'] = replayed
        if actual > upper_steps:
            raise fc_Stop(f'{kind} actual native steps exceed the pre-reserved bound')
        return (call, elapsed, actual)

    def fc__gate_pass(doc: dict, what: str):
        status = doc.get('status', doc.get('gate_status'))
        if status != 'PASS':
            raise fc_Stop(f"{what} gate is {status or 'UNKNOWN'}; stop before the next stage")
        if doc.get('fixture') is True or doc.get('evidence_kind') == 'mock':
            raise fc_Stop(f'{what} has mock evidence and cannot admit science')

    def fc__source_run0(adapter, role, phase, role_root, runtime_input, ledger, timers, atoms):
        (z, dt, steps) = fc__invoke(adapter, 'run_zero_md_pair', upper_steps=0, atoms=atoms, role=role, phase=phase, run_root=role_root, runtime_input=runtime_input, stage='source_gauge_run0')
        timers['active'] += dt
        for inv in z['native_invocations']:
            fc__append_invocation(ledger, inv, phase, role)
        fc__gate_pass(z.get('gate', {}), f'{role}/{phase} source-gauge run0')
        return z

    def fc__phase_setup(adapter, role, phase, role_root, runtime_input, source_receipt, ledger, setups, timers, atoms):
        (prep, dt, steps) = fc__invoke(adapter, 'prepare_one_phase', upper_steps=16000, atoms=atoms, role=role, phase=phase, run_root=role_root, runtime_input=runtime_input, source_receipt=source_receipt, global_native_ledger=ledger)
        timers['active'] += dt
        for inv in prep['native_invocations']:
            fc__append_invocation(ledger, inv, phase, role)
        state = prep.get('admitted_phase_state')
        if not isinstance(state, dict):
            raise fc_Stop(f'{role}/{phase} prep lacks admitted state')
        fc__annotate_segment_kinds(ledger, state.get('setup_record', {}).get('invocation_segments', []))
        review = adapter.review_setup(outputs=fc_Path(fc_os.environ['CASE06_OUTPUTS']), setup_row=state.get('setup_record', {}), native_ledger=ledger, role=role, phase=phase, reference_root=fc_Path(fc_os.environ['CASE06_REFERENCE_ROOT']) if role == 'A' else None)
        state['source_review'] = review
        state['status'] = review.get('status')
        state['gate_sha256'] = fc_hashlib.sha256(fc_json.dumps(review, sort_keys=True).encode()).hexdigest()
        setup = state.get('setup_record')
        if not isinstance(setup, dict):
            raise fc_Stop(f'{role}/{phase} admitted state lacks setup ledger record')
        setup['role'] = fc_ROLE_MAP[role]
        setup['actual_steps'] = sum((int(seg.get('actual_steps', 0)) for ref in setup.get('invocation_segments', []) for call in ledger['native_invocations'] if call.get('invocation_id') == ref.get('invocation_id') for seg in call.get('run_segments', []) if int(seg.get('run_index', -1)) == int(ref.get('run_index', -2))))
        setups.append(setup)
        fc__gate_pass(review, f'{role}/{phase} raw preparation review')
        fc__gate_pass(state.get('snapshot_run0_gate', {}), f'{role}/{phase} prepared snapshot run0')
        return state

    def fc__append_invocation(ledger, inv, phase, role):
        rec = dict(inv)
        rec.setdefault('phase', phase)
        rec['role'] = role
        if any((x['invocation_id'] == rec['invocation_id'] for x in ledger['native_invocations'])):
            raise fc_Stop('duplicate immutable invocation ID')
        ledger['native_invocations'].append(rec)

    def fc__annotate_segment_kinds(ledger, refs):
        index = {str(x['invocation_id']): x for x in ledger['native_invocations']}
        for ref in refs or []:
            iid = str(ref.get('invocation_id') or '')
            run_index = int(ref.get('run_index', -1))
            call = index.get(iid)
            if call is None:
                raise fc_Stop(f'source segment references unregistered invocation {iid}')
            matches = [s for s in call.get('run_segments', []) if int(s.get('run_index', -1)) == run_index]
            if len(matches) != 1:
                raise fc_Stop(f'source segment {iid}/{run_index} does not map to one native Loop event')
            kind = ref.get('segment_kind') or ref.get('kind')
            if not isinstance(kind, str) or not kind:
                raise fc_Stop(f'source segment {iid}/{run_index} lacks a frozen segment kind')
            prior = matches[0].get('segment_kind')
            if prior not in (None, kind):
                raise fc_Stop(f'native segment {iid}/{run_index} has conflicting source classifications')
            matches[0]['segment_kind'] = kind

    def fc__cycle(adapter, role, phase, state, switch, iteration, ledger, setups, dirs, timers, role_root):
        cycle_id = f'{role}-{phase}-cycle-{iteration}'
        upper = 2 * switch + 2000
        (call, dt, steps) = fc__invoke(adapter, 'run_one_fe_cycle', upper_steps=upper, atoms=int(state['atoms']), role=role, phase=phase, run_root=role_root, admitted_phase_state=state, cycle_id=cycle_id, switching_steps=switch, pre_fe_numpy_rng_state=state.get('pre_fe_numpy_rng_state'), global_native_ledger=ledger)
        timers['active'] += dt
        for inv in call['native_invocations']:
            fc__append_invocation(ledger, inv, phase, role)
        cycle = call.get('integration_cycle')
        if not isinstance(cycle, dict):
            raise fc_Stop(f'{cycle_id} lacks global integration-cycle source references')
        cycle['cycle_id'] = cycle_id
        cycle['role'] = fc_ROLE_MAP[role]
        cycle['phase'] = phase
        cycle['setup_id'] = state['setup_id']
        fc__annotate_segment_kinds(ledger, cycle.get('invocation_segments', []))
        ledger['integration_cycles'].append(cycle)
        setup = state['setup_record']
        setup_refs = setup.setdefault('invocation_segments', [])
        warm_refs = [dict(x) for x in cycle.get('invocation_segments', cycle.get('segments', [])) if str(x.get('segment_kind', '')).startswith('fe_warm_')]
        known = {(str(x.get('invocation_id')), int(x.get('run_index', -1))) for x in setup_refs}
        for ref in warm_refs:
            key = (str(ref.get('invocation_id')), int(ref.get('run_index', -1)))
            if key not in known:
                setup_refs.append(ref)
                known.add(key)
        setup['prep_actual_steps'] = setup.get('prep_actual_steps', setup.get('actual_steps'))
        setup['actual_steps'] = fc__linked_setup_steps(setup, ledger)
        attempt_rows = {}
        direction_rows = {}
        for direction in fc_DIRECTIONS:
            sw = next((x for x in cycle.get('invocation_segments', []) if x.get('segment_kind') == 'fe_switch' and x.get('leg') == direction), None)
            row_id = f'{role}-{phase}-{direction}'
            base = {'run_id': row_id, 'cycle_id': cycle_id, 'role': fc_ROLE_MAP[role], 'phase': phase, 'direction': direction, 'leg': direction, 'T_K': 600, 'P_bar': 20000, 'status': 'UNKNOWN', 'invocation_segments': [sw] if sw else [], 'hamiltonian_sha256': fc_POTENTIAL_SHA}
            ledger['direction_attempts'].append(dict(base))
            attempt_rows[direction] = ledger['direction_attempts'][-1]
            d = {'run_id': row_id, 'role': fc_ROLE_MAP[role], 'phase': phase, 'direction': direction, 'replicate': role, 'setup_id': state['setup_id'], 'seed': state['master_seed'], 'switch_steps': switch, 'T_K': 600, 'P_bar': 20000, 'hamiltonian_sha256': fc_POTENTIAL_SHA, 'snapshot_sha256': state['snapshot_sha256'], 'status': 'UNKNOWN'}
            if role == 'A':
                d['raw_source_namespace'] = 'author_reference'
            else:
                d['raw_source_namespace'] = 'candidate'
            dirs.append(d)
            direction_rows[direction] = d
        review = adapter.review_fe(call=call, role=role, phase=phase, cycle_id=cycle_id)
        fc__gate_pass(review, f'{cycle_id} warm/TI/FE native review')
        cycle['status'] = 'COMPLETE'
        for direction in fc_DIRECTIONS:
            extracted = adapter.extract_cycle(call, direction=direction, role=role, phase=phase, cycle_id=cycle_id)
            if not isinstance(extracted, dict):
                raise fc_Stop('direction extractor returned malformed row')
            row_id = f'{role}-{phase}-{direction}'
            reconstruction_status = 'COMPLETE' if extracted.get('status') == 'PASS' else 'UNKNOWN'
            attempt = attempt_rows[direction]
            attempt.update(extracted.get('direction_attempt', {}))
            attempt.update({'run_id': row_id, 'cycle_id': cycle_id, 'role': fc_ROLE_MAP[role], 'cycle_id': cycle_id, 'leg': direction, 'phase': phase, 'direction': direction, 'T_K': 600, 'P_bar': 20000, 'status': reconstruction_status, 'invocation_segments': [next((x for x in cycle['invocation_segments'] if x.get('segment_kind') == 'fe_switch' and x.get('leg') == direction))], 'hamiltonian_sha256': fc_POTENTIAL_SHA})
            d = direction_rows[direction]
            d.update(extracted.get('campaign_direction', {}))
            d.update({'run_id': row_id, 'role': fc_ROLE_MAP[role], 'phase': phase, 'direction': direction, 'replicate': role, 'setup_id': state['setup_id'], 'seed': state['master_seed'], 'switch_steps': switch, 'T_K': 600, 'P_bar': 20000, 'hamiltonian_sha256': fc_POTENTIAL_SHA, 'snapshot_sha256': state['snapshot_sha256'], 'status': reconstruction_status})
            if role == 'A':
                d['raw_source_namespace'] = 'author_reference'
        setup = state['setup_record']
        setup.setdefault('descendant_cycle_ids', []).append(cycle_id)
        return (call, review)

    def fc__phase_role(adapter, role, phase, state, cycles, ledger, setups, dirs, timers, role_root):
        for n in range(1, cycles + 1):
            fc__cycle(adapter, role, phase, state, 20000 if role != 'D' else 40000, n, ledger, setups, dirs, timers, role_root)

    def fc__delta(role_rows):
        by = {(x['phase'], x['direction']): x for x in role_rows}
        if set(by) != {(p, d) for p in fc_PHASES for d in DIRECTIONS}:
            raise fc_Stop('adaptive rule requires all four role curves with finite G')
        g = {k: float(v['g_eV_per_atom']) for (k, v) in by.items()}
        if not all((math.isfinite(x) for x in g.values())):
            raise fc_Stop('adaptive estimator has nonfinite Gibbs values')
        mid = (g['coesite', 'forward'] + g['coesite', 'backward'] - (g['alpha_quartz', 'forward'] + g['alpha_quartz', 'backward'])) / 2
        h = (abs(g['coesite', 'forward'] - g['coesite', 'backward']) + abs(g['alpha_quartz', 'forward'] - g['alpha_quartz', 'backward'])) / 2
        return (mid, h)

    def fc_choose_adaptive(matrix, dirs, setup_states):
        b = [x for x in dirs if x['replicate'] == 'B']
        r = [x for x in dirs if x['replicate'] == 'R']
        (db, hb) = fc__delta(b)
        (dr, hr) = fc__delta(r)
        H = max(hb, hr)
        R = abs(db - dr)
        b_pass = all((setup_states.get(('B', p), {}).get('status') == 'PASS' for p in fc_PHASES))
        if H > R:
            if not b_pass:
                return {'status': 'STOP', 'selected_component': None, 'H_eV_per_atom': H, 'R_eV_per_atom': R, 'reason': 'duration indicated but both B 16k sources did not PASS'}
            selected = 'D'
            rejected = 'S: not selected because preregistered hysteresis proxy H exceeds repeat proxy R'
        else:
            selected = 'S'
            rejected = 'D: not selected because H<=R; size is the frozen feasible information-gain default'
        return {'status': 'FROZEN', 'selected_component': 'duration' if selected == 'D' else 'size', 'selected_role': selected, 'deltaG_mid_B_eV_per_atom': db, 'deltaG_mid_R_eV_per_atom': dr, 'H_B_eV_per_atom': hb, 'H_R_eV_per_atom': hr, 'H_eV_per_atom': H, 'R_eV_per_atom': R, 'source_role_rows': [x['run_id'] for x in b + r], 'rejected_alternative': rejected, 'not_a_95_percent_CI': True, 'unselected_systematic_status': 'UNKNOWN', 'b_source_pass': b_pass}

    def fc__write_tables(outputs, dirs, decision, calibration=None):
        outputs.mkdir(parents=True, exist_ok=True)
        with (outputs / 'gibbs_free_energy.csv').open('w', newline='') as f:
            w = fc_csv.DictWriter(f, fieldnames=fc_CSV_GIBBS)
            w.writeheader()
            for d in dirs:
                if d.get('role') == 'independent_reference':
                    continue
                row = {k: d.get(k) for k in fc_CSV_GIBBS}
                row['G_eV_per_atom'] = d.get('G_eV_per_atom', d.get('g_eV_per_atom'))
                w.writerow(row)
        with (outputs / 'delta_g.csv').open('w', newline='') as f:
            w = fc_csv.DictWriter(f, fieldnames=fc_CSV_DELTA)
            w.writeheader()
            if calibration and all((calibration.get(k) is not None for k in ('delta_g_B', 'R', 'H', 'E_selected', 'E_cal'))):
                w.writerow({'T_K': 600, 'P_bar': 20000, 'G_coesite_minus_G_alpha_eV_per_atom': calibration['delta_g_B'], 'repeat_uncertainty_eV_per_atom': calibration['R'], 'direction_uncertainty_eV_per_atom': calibration['H'], 'switching_uncertainty_eV_per_atom': calibration['E_selected'] if decision.get('selected_role') == 'D' else 'UNKNOWN', 'finite_size_uncertainty_eV_per_atom': calibration['E_selected'] if decision.get('selected_role') == 'S' else 'UNKNOWN', 'combined_uncertainty_eV_per_atom': calibration['E_cal'], 'decision': 'unresolved', 'reason': 'unselected duration/size systematic remains UNKNOWN; independent verification and claim-interval audit required'})
            else:
                w.writerow({'T_K': 600, 'P_bar': 20000, 'decision': 'unresolved', 'reason': 'required candidate source rows are incomplete; missing terms remain UNKNOWN'})
        with (outputs / 'error_budget.csv').open('w', newline='') as f:
            w = fc_csv.DictWriter(f, fieldnames=fc_CSV_ERROR)
            w.writeheader()
            terms = []
            if calibration:
                terms = [('repeat_uncertainty', calibration.get('R'), '|ΔG_R−ΔG_B|; empirical proxy', calibration.get('R_sources')), ('direction_uncertainty', calibration.get('H'), 'max(H_B,H_R); empirical proxy', calibration.get('H_sources')), ('switching_uncertainty', calibration.get('E_selected') if calibration.get('selected_role') == 'D' else None, 'duration effect', calibration.get('selected_sources') if calibration.get('selected_role') == 'D' else []), ('finite_size_uncertainty', calibration.get('E_selected') if calibration.get('selected_role') == 'S' else None, 'size effect', calibration.get('selected_sources') if calibration.get('selected_role') == 'S' else [])]
            else:
                terms = [('repeat_uncertainty', None, 'repeat proxy unavailable', []), ('direction_uncertainty', None, 'direction proxy unavailable', []), ('switching_uncertainty', None, 'duration effect unavailable/unselected', []), ('finite_size_uncertainty', None, 'size effect unavailable/unselected', [])]
            terms.append(('warm_finite_time_bias', None, 'residual warm-start bias remains unmeasured', []))
            for (q, estimate, method, sources) in terms:
                w.writerow({'quantity': q, 'phase_a': 'alpha_quartz', 'phase_b': 'coesite', 'T_K': 600, 'P_bar': 20000, 'estimate_eV_per_atom': 'UNKNOWN' if estimate is None else estimate, 'method': method, 'replicates_or_windows': 'B/R or selected role', 'source_run_ids': ';'.join(sources or []), 'status': 'UNKNOWN' if estimate is None else 'MEASURED_PROXY', 'reason': 'Empirical sensitivity proxy, not a 95% CI or bound on unmeasured systematic error.' if estimate is not None else 'Unmeasured effects remain UNKNOWN; never substituted by zero.'})
        fig = outputs / 'figures' / 'delta-g-unresolved.svg'
        fig.parent.mkdir(parents=True, exist_ok=True)
        if calibration and all((isinstance(calibration.get(k), (float, int)) and math.isfinite(calibration[k]) for k in ('delta_g_B', 'E_cal'))):
            center = float(calibration['delta_g_B'])
            err = abs(float(calibration['E_cal']))
            span = max(2 * err, 0.0001)
            lo = center - span
            hi = center + span
            scale = lambda x: 70 + (x - lo) / (hi - lo) * 580
            (x0, x1, xm) = (scale(center - err), scale(center + err), scale(center))
            detail = f'candidate center {center:.8g} eV/atom; empirical E_cal ±{err:.4g} eV/atom (not a confidence interval)'
            geometry = f'<line x1="{scale(0):.2f}" y1="132" x2="{scale(0):.2f}" y2="194" stroke="#777" stroke-dasharray="4 4"/><line x1="{x0:.2f}" y1="163" x2="{x1:.2f}" y2="163" stroke="#3677b5" stroke-width="12"/><circle cx="{xm:.2f}" cy="163" r="8" fill="#b23a48"/>'
        else:
            center = err = None
            detail = 'candidate center and empirical tolerance unavailable; source rows incomplete'
            geometry = '<text x="45" y="167" font-family="sans-serif" font-size="17">ΔG remains UNKNOWN</text>'
        fig.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300" viewBox="0 0 720 300">\n<rect width="100%" height="100%" fill="white"/><text x="28" y="42" font-family="sans-serif" font-size="20">Case-06 finite-cell ΔG</text>\n<text x="28" y="80" font-family="sans-serif" font-size="15">600 K · 20,000 bar · coesite − alpha-quartz</text>\n<line x1="70" y1="163" x2="650" y2="163" stroke="#333" stroke-width="2"/>{geometry}\n<text x="28" y="220" font-family="sans-serif" font-size="13">{detail}</text>\n<text x="28" y="251" font-family="sans-serif" font-size="13">Unselected systematic and finite warm-bias terms remain UNKNOWN; claim unresolved.</text></svg>')

    def fc__allocation_log(path, events, decision, budget, stop_reason):
        fc_write_json(path, {'schema': 'case06-fullcampaign-allocation/v1', 'status': 'STOPPED' if stop_reason else 'RUNNING', 'initial_pressure_rationale': '600 K and 20000 bar are fixed by the public task; no pressure scan is permitted.', 'adaptive_decision': decision, 'events': events, 'budget': budget, 'stop_reason': stop_reason})

    def fc__manifest(root):
        entries = []
        for p in sorted((x for x in root.rglob('*') if x.is_file() and x.name not in ('outputs-manifest.json', 'summary.json', 'campaign-evidence.json'))):
            entries.append({'path': str(p.relative_to(root)), 'sha256': fc_sha(p), 'size_bytes': p.stat().st_size})
        return {'schema': 'case06-campaign-output-manifest/v1', 'files': entries}

    def fc__candidate_ecal(dirs, decision):
        b = [x for x in dirs if x['replicate'] == 'B']
        r = [x for x in dirs if x['replicate'] == 'R']
        sr = [x for x in dirs if x['replicate'] == decision['selected_role']]
        (db, hb) = fc__delta(b)
        (dr, hr) = fc__delta(r)
        (ds, _) = fc__delta(sr)
        return max(hb, hr) + abs(db - dr) + abs(ds - db)

    def fc__public_direction_registry(dirs):
        """Expose held-out A coverage metadata without copying its private raw refs/G."""
        public = []
        allowed = {'run_id', 'role', 'phase', 'direction', 'replicate', 'setup_id', 'seed', 'master_seed', 'T_K', 'P_bar', 'atoms', 'cell_atoms', 'switch_steps', 'snapshot_sha256', 'status', 'raw_source_namespace', 'hamiltonian_sha256'}
        for row in dirs:
            if row.get('role') == 'independent_reference':
                public.append({k: v for (k, v) in row.items() if k in allowed})
            else:
                public.append(dict(row))
        return public
    def fc_run_candidate_campaign(outputs: Path) -> dict:
        """Run the preregistered candidate B/R then selected D/S route; never runs A."""
        outputs = outputs.resolve()
        if outputs.exists() and any(outputs.iterdir()):
            raise fc_Stop('candidate output directory is nonempty; refusing to overwrite a trial')
        outputs.mkdir(parents=True, exist_ok=True)
        run_root = outputs / 'integration_runs'
        run_root.mkdir()
        fc_shutil.copytree(ASSET_ROOT / 'phase-controls', outputs / 'phase-controls')
        reference_root = outputs / '_grader_reference_forbidden'
        if reference_root.exists():
            raise fc_Stop('candidate output tree contains a forbidden grader reference path')
        fc_os.environ['CASE06_OUTPUTS'] = str(outputs)
        fc_os.environ['CASE06_REFERENCE_ROOT'] = str(reference_root)
        fc_os.environ['CASE06_SHARED_RUN_ROOT'] = str(run_root)
        fc_os.environ['CASE06_ASSET_ROOT'] = str(ASSET_ROOT)
        native_out = outputs / 'native_inputs'
        fc_shutil.copytree(ASSET_ROOT / 'native_inputs', native_out)
        ledger = {'schema':'case06-native-event-ledger/v2','campaign_id':fc_os.environ.get('CASE06_TRIAL_ID') or __import__('uuid').uuid4().hex,
                  'protocol':'single-state-v2','native_invocations':[], 'integration_cycles':[],
                  'direction_attempts':[], 'phase_setups':[]}
        dirs=[]; events=[]; setups=ledger['phase_setups']; states={}; timers={'active':0.0}
        reservations=[]; reserved_steps=0; reserved_atoms=0; decision={'status':'PENDING'}
        a_attempt_reserve=4; a_step_reserve=116000; a_atomstep_reserve=55680000
        candidate_attempt_cap=12; candidate_step_cap=484000
        started=fc_time.monotonic(); started_ns=fc_time.monotonic_ns(); started_utc=fc__clock_utc()
        try:
            reference_active_seconds=float(fc_os.environ['CASE06_REFERENCE_ACTIVE_SECONDS'])
            remaining_at_candidate_start=float(fc_os.environ['CASE06_REMAINING_ACTIVE_SECONDS'])
        except (KeyError,TypeError,ValueError) as exc:
            raise fc_Stop('trusted Harbor reference-time budget is unavailable') from exc
        if (not math.isfinite(reference_active_seconds) or reference_active_seconds<0
                or not math.isfinite(remaining_at_candidate_start) or remaining_at_candidate_start<=0
                or reference_active_seconds>43200):
            raise fc_Stop('trusted Harbor reference-time budget is malformed or exhausted')
        provenance=outputs/'provenance';provenance.mkdir(parents=True,exist_ok=True)
        wrapper_out=provenance/'lmp_guard_wrapper.sh'
        wrapper_out.write_text('#!/usr/bin/env bash\nexec bash "${CASE08_SOLVE:?CASE08_SOLVE is required}" --lmp-wrapper "$@"\n',encoding='utf-8')
        wrapper_out.chmod(0o755)
        if not fc_os.environ.get('CASE08_SOLVE'):
            fc_os.environ['CASE08_SOLVE']=str(fc_Path(__file__).resolve())
        fc_os.environ['CASE08_WRAPPER']=str(wrapper_out.resolve())
        (outputs/'execution-intervals.json').write_text(fc_json.dumps({'schema':'case06-execution-intervals/v1','intervals':[]},indent=2)+'\n')
        job_id=fc_os.environ.get('SLURM_JOB_ID')
        outer_start_path=outputs/'provenance'/'outer-job-start.txt'
        if job_id: outer_start_path.write_text(f'started_utc={started_utc}\njob_id={job_id}\n',encoding='utf-8')
        fc_write_json(outputs/'campaign-clock.json', {'schema':'case06-campaign-clock/v1','state':'ACTIVE',
            'start_utc':started_utc,'start_monotonic_ns':started_ns,'active_limit_seconds':43200,
            'source':'candidate controller monotonic clock inside the allocated job; scheduler queue excluded'})
        binary=Path(fc_os.environ.get('CASE08_REAL_LMP',''))
        potential=ASSET_ROOT/'native_inputs'/'SiOx_potential.yace'
        adapter=fc_types.SimpleNamespace(run_zero_md_pair=ca_run_zero_md_pair,
            prepare_one_phase=ca_prepare_one_phase, run_one_fe_cycle=ca_run_one_fe_cycle,
            review_setup=ca_review_setup, review_fe=ca_review_fe, extract_cycle=ca_extract_cycle,
            source_gate=ca_source_gate, collect_partial_native_invocations=ca_collect_partial_native_invocations)
        def flush():
            fc_write_json(outputs/'native-event-ledger.json', ledger)
            fc_write_json(outputs/'execution-reservations.json', {'schema':'case06-execution-reservations/v1',
                'reservations':reservations,'active_reserved_md_steps':reserved_steps,
                'active_reserved_atomsteps':reserved_atoms,
                'attempts_reserved':sum(x['reserved_direction_attempts'] for x in reservations if x['state']=='ACTIVE')})
        def reserve(bound, attempt_count, atoms):
            nonlocal reserved_steps, reserved_atoms
            used_steps, used_atomsteps, _ = fc__accounting_totals(ledger)
            elapsed=fc_time.monotonic()-started
            active_attempts=sum(x['reserved_direction_attempts'] for x in reservations if x['state']=='ACTIVE')
            if used_steps+reserved_steps+bound+a_step_reserve>600000: raise fc_Stop('candidate plus fixed A reservation would exceed 600k total MD steps')
            current_atoms=sum(int(seg.get('actual_steps',0))*int(seg.get('atoms',inv.get('atoms',0)))
                for inv in ledger['native_invocations'] for seg in inv.get('run_segments',[]))
            if current_atoms+reserved_atoms+bound*atoms+a_atomstep_reserve>278400000: raise fc_Stop('candidate plus fixed A atom-step reservation would exceed the frozen total ceiling')
            if len(ledger['direction_attempts'])+active_attempts+attempt_count>candidate_attempt_cap: raise fc_Stop('12 candidate direction-attempt ceiling, including retries, would be exceeded')
            if used_steps+reserved_steps+bound>candidate_step_cap: raise fc_Stop('candidate step allocation after reserving the fixed A4 allowance would be exceeded')
            if elapsed+max(1.0, bound/1000.0)>remaining_at_candidate_start: raise fc_Stop('remaining shared 12-hour evaluation budget would be exceeded')
            row={'reservation_id':f'r{len(reservations)+1:03d}','reserved_md_steps':bound,
                 'reserved_atomsteps':bound*atoms,'reserved_direction_attempts':attempt_count,
                 'reserved_utc':fc__clock_utc(),'state':'ACTIVE'}
            reservations.append(row);reserved_steps+=bound;reserved_atoms+=bound*atoms;flush()
            before=fc__accounting_totals(ledger)
            try:
                return row, before
            except Exception:
                raise
        def reconcile(row,before,failed=False):
            nonlocal reserved_steps,reserved_atoms
            after=fc__accounting_totals(ledger)
            ds=max(0,after[0]-before[0]); da=max(0,after[1]-before[1]); dt=max(0,after[2]-before[2])
            row['reconciled_native_prefix_md_steps']=min(row['reserved_md_steps'],ds)
            row['reconciled_native_prefix_atomsteps']=min(row['reserved_atomsteps'],da)
            row['reconciled_direction_attempts']=min(row['reserved_direction_attempts'],dt)
            if failed:
                row['state']='ACTIVE_UNKNOWN_TAIL'
                row['stop_utc']=fc__clock_utc()
            else:
                row['state']='RELEASED_COMPLETE';row['released_utc']=fc__clock_utc()
            reserved_steps=max(0,reserved_steps-row['reconciled_native_prefix_md_steps'])
            reserved_atoms=max(0,reserved_atoms-row['reconciled_native_prefix_atomsteps'])
            if not failed:
                reserved_steps=max(0,reserved_steps-row['reserved_md_steps']+row['reconciled_native_prefix_md_steps'])
                reserved_atoms=max(0,reserved_atoms-row['reserved_atomsteps']+row['reconciled_native_prefix_atomsteps'])
            flush()
        def invoke_reserved(bound, attempts, atoms, fn):
            row,before=reserve(bound,attempts,atoms)
            try:
                result=fn(); reconcile(row,before,False); return result
            except BaseException:
                reconcile(row,before,True); raise
        stop_reason=None; selected=None
        try:
            identity=drv_validate_installed_sources()
            if identity.get('pass') is not True:
                raise fc_Stop('installed Calphy source hashes do not match the task-pinned source map')
            binary=Path(os.environ.get('CASE08_REAL_LMP',''))
            potential=ASSET_ROOT/'native_inputs'/'SiOx_potential.yace'
            if not binary.is_file() or sha(binary)!=zero_EXPECTED_BINARY_SHA:
                raise fc_Stop('remote LAMMPS binary is missing or differs from the selected runtime SHA')
            if not potential.is_file() or sha(potential)!=POTENTIAL_SHA:
                raise fc_Stop('task-packaged Hamiltonian is missing or differs from its frozen SHA')
            provenance=outputs/'provenance'
            identity_path=Path.cwd()/'calphy-source-identity.json'
            if identity_path.is_file(): fc_shutil.copy2(identity_path,provenance/'calphy-source-identity.json')
            fc_write_json(provenance/'candidate-runtime-qualification.json',{
                'status':'PASS','calphy_source_identity':identity,'binary_sha256':sha(binary),
                'potential_sha256':sha(potential),'native_md_executed':False})
            for role in ('B','R'):
                role_root=run_root/role;role_root.mkdir()
                template_map={phase:ASSET_ROOT/'native_inputs'/f'input-template-{role}.json' for phase in fc_PHASES}
                receipts={}
                for phase in fc_PHASES:
                    receipts[phase]=fc__source_run0(adapter,role,phase,role_root,template_map[phase],ledger,timers,fc_ATOM_COUNTS[phase])
                    flush()
                for phase in fc_PHASES:
                    n=fc_ATOM_COUNTS[phase]
                    states[(role,phase)]=invoke_reserved(16000,0,n,lambda p=phase,rr=role_root,rt=template_map[phase],a=n:
                        fc__phase_setup(adapter,role,p,rr,rt,receipts[p],ledger,setups,timers,a))
                for phase in fc_PHASES:
                    n=fc_ATOM_COUNTS[phase]
                    invoke_reserved(42000,2,n,lambda p=phase,rr=role_root:
                        fc__phase_role(adapter,role,p,states[(role,p)],1,ledger,setups,dirs,timers,rr))
            decision=fc_choose_adaptive({},dirs,{k:{'status':v.get('status')} for k,v in states.items()})
            events.append({'event':'adaptive_selection','decision':decision})
            if decision.get('status')!='FROZEN': raise fc_Stop(decision.get('reason','adaptive selection did not freeze'))
            selected=decision['selected_role']; role_root=run_root/selected; role_root.mkdir()
            if selected=='S':
                templates={phase:ASSET_ROOT/'native_inputs'/'input-template-S.json' for phase in fc_PHASES}
                receipts={}
                for phase in fc_PHASES:
                    n=2*fc_ATOM_COUNTS[phase]
                    receipts[phase]=fc__source_run0(adapter,'S',phase,role_root,templates[phase],ledger,timers,n);flush()
                for phase in fc_PHASES:
                    n=2*fc_ATOM_COUNTS[phase]
                    states[('S',phase)]=invoke_reserved(16000,0,n,lambda p=phase,rr=role_root,rt=templates[phase],a=n:
                        fc__phase_setup(adapter,'S',p,rr,rt,receipts[p],ledger,setups,timers,a))
                for phase in fc_PHASES:
                    n=2*fc_ATOM_COUNTS[phase]
                    invoke_reserved(42000,2,n,lambda p=phase,rr=role_root:
                        fc__phase_role(adapter,'S',p,states[('S',p)],1,ledger,setups,dirs,timers,rr))
            else:
                for phase in fc_PHASES:
                    parent=states[('B',phase)]
                    fc__gate_pass(adapter.source_gate(role='D',phase=phase,parent_state=parent),f'D/{phase} matched B pre-FE ancestry')
                    states[('D',phase)]={**parent,'role':'D','setup_id':parent['setup_id']}
                for phase in fc_PHASES:
                    n=fc_ATOM_COUNTS[phase]
                    invoke_reserved(82000,2,n,lambda p=phase,rr=role_root:
                        fc__phase_role(adapter,'D',p,states[('D',p)],1,ledger,setups,dirs,timers,rr))
            ecal=fc__candidate_ecal(dirs,decision)
            b=[x for x in dirs if x['replicate']=='B'];r=[x for x in dirs if x['replicate']=='R'];srows=[x for x in dirs if x['replicate']==selected]
            db,hb=fc__delta(b);dr,hr=fc__delta(r);ds,_=fc__delta(srows)
            freeze={'schema':'case06-candidate-calibration-freeze/v1','campaign_id':ledger['campaign_id'],
                'protocol':'single-state-v2','frozen_utc':fc__clock_utc(),'hamiltonian_sha256':POTENTIAL_SHA,
                'matrix_sha256':'58599733bcecb0017d0863e1054ba9311858f8e6b986713af064be737e5c5d9e',
                'T_K':600,'P_bar':20000,'delta_g_baseline':db,'delta_g_repeat':dr,'delta_g_selected':ds,
                'H':max(hb,hr),'R':abs(db-dr),'E_selected':abs(ds-db),'candidate_tolerance_eV_per_atom':ecal,
                'selected_component':decision['selected_component'],'selected_role':selected,'source_run_ids':[x['run_id'] for x in b+r+srows],
                'source_row_sha256':{str(x['run_id']):fc_hashlib.sha256(fc_json.dumps(x,sort_keys=True,allow_nan=False).encode()).hexdigest() for x in b+r+srows},
                'rule':'E_cal=H+R+selected effect; grader-only A excluded from every term'}
            fc_write_json(outputs/'candidate-calibration-freeze.json',freeze)
        except BaseException as exc:
            stop_reason=f'{type(exc).__name__}: {exc}'
            events.append({'event':'fail_closed_stop','reason':stop_reason,'utc':fc__clock_utc()})
        finally:
            flush()
            end=fc_time.monotonic();end_ns=fc_time.monotonic_ns();elapsed=max(0,end-started)
            candidate_active_elapsed=(fc_time.time()-fc_datetime.fromisoformat(started_utc.replace('Z','+00:00')).timestamp()) if job_id else elapsed
            active_elapsed=reference_active_seconds+candidate_active_elapsed
            fc_write_json(outputs/'campaign-clock.json',{'schema':'case06-campaign-clock/v1',
                'state':'STOPPED' if stop_reason else 'FINISHED_PENDING_VERIFICATION','start_utc':started_utc,
                'end_utc':fc__clock_utc(),'start_monotonic_ns':started_ns,'end_monotonic_ns':end_ns,
                'controller_elapsed_seconds':elapsed,'candidate_active_elapsed_seconds':candidate_active_elapsed,
                'reference_active_seconds':reference_active_seconds,'active_elapsed_seconds':active_elapsed,'active_limit_seconds':43200,
                'active_limit_remaining_seconds':max(0,43200-active_elapsed),
                'source':'candidate controller interval inside allocated job; scheduler queue excluded'})
            calibration=None
            freeze_path=outputs/'candidate-calibration-freeze.json'
            if freeze_path.is_file():
                freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
                selected=freeze.get('selected_role')
                db=freeze.get('delta_g_baseline');dr=freeze.get('delta_g_repeat');ds=freeze.get('delta_g_selected')
                ecal=freeze.get('candidate_tolerance_eV_per_atom')
                if all(isinstance(x,(int,float)) and math.isfinite(float(x)) for x in (db,dr,ds,ecal)):
                    b=[x for x in dirs if x.get('replicate')=='B'];r=[x for x in dirs if x.get('replicate')=='R']
                    srows=[x for x in dirs if x.get('replicate')==selected]
                    calibration={**freeze,'freeze_receipt':fc_file_ref(freeze_path,outputs),
                        'delta_g_B':db,'delta_g_R':dr,'delta_g_selected':ds,'E_cal':ecal,
                        'selected_role':selected,'candidate_tolerance_eV_per_atom':ecal,
                        'H_sources':[x['run_id'] for x in b+r],'R_sources':[x['run_id'] for x in b+r],
                        'selected_sources':[x['run_id'] for x in srows]}
            fc__write_tables(outputs,dirs,decision,calibration)
            steps,atomsteps,attempts=fc__accounting_totals(ledger)
            budget={'attempts':attempts,'actual_or_reserved_md_steps':steps+reserved_steps,
                'actual_atomsteps':atomsteps,'prospective_md_cap':candidate_step_cap,'combined_md_cap':600000,'fixed_A_md_reserve':a_step_reserve,
                'prospective_attempt_cap':candidate_attempt_cap,'fixed_A_attempt_reserve':a_attempt_reserve,
                'active_elapsed_seconds':active_elapsed,'candidate_active_elapsed_seconds':candidate_active_elapsed,
                'reference_active_seconds':reference_active_seconds,'active_unlocated_reserve_seconds':0.0,
                'active_limit_seconds':43200,'active_limit_remaining_seconds':max(0,43200-active_elapsed),
                'remaining_md_steps':max(0,candidate_step_cap-steps-reserved_steps),
                'remaining_attempts':max(0,candidate_attempt_cap-attempts)}
            fc__allocation_log(outputs/'allocation_log.json',events,decision,budget,stop_reason)
            clock_ref=fc_file_ref(outputs/'campaign-clock.json',outputs)
            interval_ref=fc_file_ref(outputs/'execution-intervals.json',outputs) if (outputs/'execution-intervals.json').is_file() else None
            outer_ref=fc_file_ref(outer_start_path,outputs) if outer_start_path.is_file() else None
            execution={'active_elapsed_seconds':active_elapsed,'candidate_active_elapsed_seconds':candidate_active_elapsed,
                'reference_active_seconds':reference_active_seconds,'active_unlocated_reserve_seconds':0.0,
                'active_limit_remaining_seconds':max(0,43200-active_elapsed),
                'source':'job-local UTC/monotonic controller clock; scheduler queue excluded',
                'controller_clock':clock_ref,'execution_intervals':interval_ref,
                'outer_job_start':outer_ref,'outer_job_finish_status':'collector-owned, not yet available',
                'outer_job_finish_ref':None,'extra_active_interval_sources':[]}
            fc_write_json(outputs/'resource-receipt.json',{'schema':'case06-v2-resource-receipt/v1',
                'historical':{'reset':False,'original_admission':'EXHAUSTED_NOT_COMPLETE'},
                'prospective':{'activated':True,'active_limit_seconds':43200,'md_limit':600000},
                'execution':execution})
            fc_write_json(outputs/'summary.json',{'schema':'case06-single-state-v2-summary/v1',
                'status':'NOT_COMPLETE' if stop_reason else 'NATIVE_CAMPAIGN_FINISHED_PENDING_VERIFICATION',
                'hamiltonian_sha256':POTENTIAL_SHA,'temperature_scope_K':[600],'pressure_scope_bar':[20000],
                'phase_boundary_claim':False,'total_md_steps':steps,'total_atom_steps':atomsteps,
                'direction_trajectories':attempts,'active_elapsed_seconds':active_elapsed,'active_runtime_cap_seconds':43200,
                'remaining_budget':{'md_steps':max(0,candidate_step_cap-steps-reserved_steps),'attempts':max(0,candidate_attempt_cap-attempts)},
                'campaign_clock':clock_ref,'resource_receipt':fc_file_ref(outputs/'resource-receipt.json',outputs),
                'conclusion':'unresolved','stop_reason':stop_reason,
                'limitations':['Independent packaged reference replay remains required.']})
            fc_write_json(outputs/'verification-pending.json',{'schema':'case06-independent-v2-replay/v1','status':'PENDING','scientific_pass':False})
            fc_write_json(outputs/'outputs-manifest.json',fc__manifest(outputs))
            method_copy=outputs/'provenance'/'solve.sh';fc_shutil.copy2(Path(__file__).resolve(),method_copy)
            wrapper_out=outputs/'provenance'/'lmp_guard_wrapper.sh'
            source_manifest=outputs/'provenance'/'calphy-source-hashes.json';fc_write_json(source_manifest,drv_EXPECTED)
            identity_out=outputs/'provenance'/'calphy-source-identity.json'
            identity_path=Path.cwd()/'calphy-source-identity.json'
            if not identity_out.is_file() and identity_path.is_file():fc_shutil.copy2(identity_path,identity_out)
            runtime_receipt=outputs/'provenance'/'runtime-source-sha256.txt'
            runtime_rows=[(sha(potential),str(potential)),(sha(method_copy),str(method_copy)),(sha(wrapper_out),str(wrapper_out))]
            if binary.is_file():runtime_rows.insert(0,(sha(binary),str(binary)))
            runtime_receipt.write_text(''.join(f'{d}  {name}\n' for d,name in runtime_rows),encoding='utf-8')
            proof=run_root/'B'/'acceptance'/'native-zero-md-regression.json'
            fc_write_json(outputs/'outputs-manifest.json',fc__manifest(outputs))
            evidence={'schema':'case06-single-state-v2-campaign-evidence/v2','campaign_id':ledger['campaign_id'],
                'protocol':'single-state-v2','contract_sha256':'66f2bfefec562583aca17790bd76666af493b7605057bd658b35931d4eb92cda',
                'candidate_manifest':fc_file_ref(outputs/'outputs-manifest.json',outputs),
                'hamiltonian':fc_file_ref(native_out/'SiOx_potential.yace',outputs),
                'software':{'calphy_version':'2.1.2','calphy_wheel_sha256':drv_EXPECTED['wheel_sha256'],
                    'calphy_source_manifest':fc_file_ref(source_manifest,outputs),
                    'calphy_source_identity':fc_file_ref(identity_out,outputs) if identity_out.is_file() else None,
                    'runtime_source_receipt_ref':fc_file_ref(runtime_receipt,outputs),
                    'native_binary':{'path':str(binary),'sha256':sha(binary)},
                    'native_binary_provenance_refs':fc__global_zero_binary_refs(proof),
                    'native_zero_md_regression_ref':fc_file_ref(proof,outputs) if proof.is_file() else None,
                    'instrumenter':fc_file_ref(method_copy,outputs),'wrapper':fc_file_ref(wrapper_out,outputs)},
                'budget':{'candidate_success_target':12,'attempt_cap_including_retries':16,'candidate_attempt_cap':12,
                    'fixed_author_attempt_reserve':4,'fixed_author_md_step_reserve':116000,'attempts_used':attempts,
                    'new_md_step_cap':600000,'candidate_md_step_cap':484000,'actual_md_steps':steps,'actual_atomsteps':atomsteps,
                    'active_elapsed_seconds':active_elapsed,'candidate_active_elapsed_seconds':candidate_active_elapsed,
                    'reference_active_seconds':reference_active_seconds,'active_unlocated_reserve_seconds':0.0,
                    'active_limit_seconds':43200,'active_limit_remaining_seconds':max(0,43200-active_elapsed)},
                'phase_setups':ledger['phase_setups'],'directions':fc__public_direction_registry(dirs),
                'calibration':calibration,'adaptive_decision':{**decision,'rule':fc_file_ref(outputs/'allocation_log.json',outputs),'evidence':[]},
                'resource_receipt':fc_file_ref(outputs/'resource-receipt.json',outputs),
                'native_event_ledger':fc_file_ref(outputs/'native-event-ledger.json',outputs),
                'verification':fc_file_ref(outputs/'verification-pending.json',outputs),'status':'NOT_COMPLETE'}
            fc_write_json(outputs/'campaign-evidence.json',evidence)
            fc_write_json(outputs/'outputs-manifest.json',fc__manifest(outputs))

        return {'status':'NOT_COMPLETE' if stop_reason else 'NATIVE_CAMPAIGN_FINISHED_PENDING_VERIFICATION',
                'stop_reason':stop_reason,'selected_role':selected,'native_md_executed':bool(ledger['native_invocations'])}

    def fc_run_author_reference(outputs: Path, seed_file: Path, deadline_seconds: int) -> dict:
        """Generate the fixed four-direction A reference in the host-owned CPU worker."""
        outputs = outputs.resolve()
        if outputs.exists() and any(outputs.iterdir()):
            raise fc_Stop('author output directory is not empty')
        if not isinstance(deadline_seconds, int) or deadline_seconds <= 0 or deadline_seconds > 43200:
            raise fc_Stop('author deadline must be within the fixed 12-hour attempt window')
        seeds = fc_json.loads(seed_file.read_text())
        if (not isinstance(seeds, dict) or set(seeds) != set(fc_PHASES)
                or any(type(seeds[p]) is not int or seeds[p] <= 0 for p in fc_PHASES)
                or len(set(seeds.values())) != 2):
            raise fc_Stop('author seed file must bind one distinct positive master seed per phase')
        outputs.mkdir(parents=True, exist_ok=True)
        started = fc_time.monotonic()
        started_utc = fc__clock_utc()
        fc_os.environ['CASE06_AUTHOR_REFERENCE_WORKER'] = '1'
        fc_os.environ['CASE06_AUTHOR_SEEDS'] = fc_json.dumps(seeds, sort_keys=True)
        fc_os.environ['CASE06_OUTPUTS'] = str(outputs)
        fc_os.environ['CASE06_REFERENCE_ROOT'] = str(outputs)
        fc_os.environ['CASE06_SHARED_RUN_ROOT'] = str(outputs / 'integration_runs')
        fc_os.environ['CASE06_ASSET_ROOT'] = str(ASSET_ROOT)
        if not fc_os.environ.get('CASE08_SOLVE'):
            fc_os.environ['CASE08_SOLVE'] = str(fc_Path(__file__).resolve())
        provenance = outputs / 'provenance'
        provenance.mkdir()
        wrapper = provenance / 'lmp_guard_wrapper.sh'
        wrapper.write_text('#!/usr/bin/env bash\nexec bash "${CASE08_SOLVE:?CASE08_SOLVE is required}" --lmp-wrapper "$@"\n', encoding='utf-8')
        wrapper.chmod(0o755)
        fc_os.environ['CASE08_WRAPPER'] = str(wrapper)
        fc_os.environ['CASE08_PYTHON'] = fc_os.environ.get('CASE08_PYTHON', fc_sys.executable)
        binary = fc_Path(fc_os.environ.get('CASE08_REAL_LMP', '')).resolve()
        if not binary.is_file():
            raise fc_Stop('author CPU LAMMPS binary is unavailable')
        binary_sha = fc_sha(binary)
        if fc_os.environ.get('CASE06_AUTHOR_BINARY_SHA') != binary_sha:
            raise fc_Stop('author CPU binary differs from the host-pinned provider identity')
        potential = ASSET_ROOT / 'native_inputs' / 'SiOx_potential.yace'
        if not potential.is_file() or fc_sha(potential) != fc_POTENTIAL_SHA:
            raise fc_Stop('author public Hamiltonian differs from the frozen task input')
        run_root = outputs / 'integration_runs'
        run_root.mkdir()
        fc_shutil.copytree(ASSET_ROOT / 'phase-controls', outputs / 'phase-controls')
        native_out = outputs / 'native_inputs'
        fc_shutil.copytree(ASSET_ROOT / 'native_inputs', native_out)
        ledger = {'schema':'case06-native-event-ledger/v2',
                  'campaign_id':fc_os.environ.get('CASE06_TRIAL_ID') or __import__('uuid').uuid4().hex,
                  'protocol':'single-state-v2','native_invocations':[], 'integration_cycles':[],
                  'direction_attempts':[], 'phase_setups':[]}
        dirs=[]; setups=ledger['phase_setups']; states={}; timers={'active':0.0}
        reservations=[]; reserved_steps=0; reserved_atoms=0
        a_step_cap=116000; a_attempt_cap=4
        adapter=fc_types.SimpleNamespace(run_zero_md_pair=ca_run_zero_md_pair,
            prepare_one_phase=ca_prepare_one_phase, run_one_fe_cycle=ca_run_one_fe_cycle,
            review_setup=ca_review_setup, review_fe=ca_review_fe, extract_cycle=ca_extract_cycle,
            source_gate=ca_source_gate, collect_partial_native_invocations=ca_collect_partial_native_invocations)
        def flush():
            fc_write_json(outputs/'native-event-ledger.json',ledger)
            fc_write_json(outputs/'author-reservations.json',{'schema':'case06-author-reservations/v1',
                'reservations':reservations,'actual_or_reserved_md_steps':reserved_steps+fc__accounting_totals(ledger)[0],
                'actual_or_reserved_atomsteps':reserved_atoms+fc__accounting_totals(ledger)[1]})
        def reserve(bound, attempts, atoms):
            nonlocal reserved_steps,reserved_atoms
            used_steps,used_atoms,used_attempts=fc__accounting_totals(ledger)
            if used_steps+reserved_steps+bound>a_step_cap:
                raise fc_Stop('fixed author A4 step ceiling would be exceeded')
            if used_attempts+sum(x['attempts'] for x in reservations if x['active'])+attempts>a_attempt_cap:
                raise fc_Stop('fixed author A4 direction-attempt ceiling would be exceeded')
            elapsed=fc_time.monotonic()-started
            if elapsed+max(1.0,bound/1000.0)>deadline_seconds:
                raise fc_Stop('author phase would exceed the remaining Harbor attempt deadline')
            row={'id':f'a{len(reservations)+1:02d}','steps':bound,'attempts':attempts,'atoms':atoms,
                 'active':True,'start_utc':fc__clock_utc()}
            reservations.append(row);reserved_steps+=bound;reserved_atoms+=bound*atoms;flush()
            return row,(used_steps,used_atoms,used_attempts)
        def reconcile(row,before,failed=False):
            nonlocal reserved_steps,reserved_atoms
            after=fc__accounting_totals(ledger)
            ds=max(0,after[0]-before[0]); da=max(0,after[1]-before[1]); dt=max(0,after[2]-before[2])
            row.update({'actual_steps':ds,'actual_atomsteps':da,'actual_attempts':dt,
                        'active':False,'status':'PARTIAL_UNKNOWN' if failed else 'COMPLETE',
                        'end_utc':fc__clock_utc()})
            reserved_steps=max(0,reserved_steps-min(ds,row['steps']))
            reserved_atoms=max(0,reserved_atoms-min(da,row['steps']*row['atoms']))
            if not failed:
                reserved_steps=max(0,reserved_steps-row['steps']+min(ds,row['steps']))
                reserved_atoms=max(0,reserved_atoms-row['steps']*row['atoms']+min(da,row['steps']*row['atoms']))
            flush()
        def invoke(bound, attempts, atoms, fn):
            row,before=reserve(bound,attempts,atoms)
            try:
                value=fn();reconcile(row,before);return value
            except BaseException:
                reconcile(row,before,True);raise
        stop_reason=None
        try:
            identity=drv_validate_installed_sources()
            if identity.get('pass') is not True:
                raise fc_Stop('Calphy source identity failed')
            fc_write_json(provenance/'author-provider-identity.json',{
                'schema':'case06-author-cpu-provider/v1','provider':'task159-host-private-cpu',
                'calphy_source_identity':identity,'binary_sha256':binary_sha,
                'potential_sha256':fc_sha(potential),'worker_image_id':fc_os.environ.get('CASE06_AUTHOR_WORKER_IMAGE_ID'),
                'cache_key':fc_os.environ.get('CASE06_AUTHOR_CACHE_KEY'),
                'solve_sha256':fc_os.environ.get('CASE06_AUTHOR_SOLVE_SHA256'),
                'verifier_sha256':fc_os.environ.get('CASE06_AUTHOR_VERIFY_SHA256'),
                'started_utc':started_utc,'attempt_deadline_seconds':deadline_seconds,
                'native_md_executed':False})
            (outputs/'execution-intervals.json').write_text(fc_json.dumps({'schema':'case06-execution-intervals/v1','intervals':[]},indent=2)+'\n')
            for phase in fc_PHASES:
                role_root=run_root/'A'; role_root.mkdir(exist_ok=True)
                template=native_out/'input-template.json'
                receipt=fc__source_run0(adapter,'A',phase,role_root,template,ledger,timers,fc_ATOM_COUNTS[phase])
                flush()
                n=fc_ATOM_COUNTS[phase]
                states[phase]=invoke(16000,0,n,lambda p=phase,rr=role_root,rt=template,a=n:
                    fc__phase_setup(adapter,'A',p,rr,rt,receipt,ledger,setups,timers,a))
            for phase in fc_PHASES:
                n=fc_ATOM_COUNTS[phase]
                invoke(42000,2,n,lambda p=phase,rr=run_root/'A':
                    fc__phase_role(adapter,'A',p,states[p],1,ledger,setups,dirs,timers,rr))
            steps,atoms,attempts=fc__accounting_totals(ledger)
            if steps>116000 or attempts!=4:
                raise fc_Stop('author A raw accounting does not reconcile four directions within 116000 MD steps')
            binary_out=outputs/'native-source'/'lmp'
            binary_out.parent.mkdir(parents=True,exist_ok=True)
            fc_shutil.copy2(binary,binary_out)
            binary_out.chmod(0o500)
            if fc_sha(binary_out)!=binary_sha: raise fc_Stop('copied author CPU binary SHA changed')
            descriptor={'schema':'case06-independent-reference-precommit/v2','protocol':'single-state-v2',
                'hamiltonian_sha256':fc_POTENTIAL_SHA,'T_K':600,'P_bar':20000,
                'phase_cells':{p:{'atoms':fc_ATOM_COUNTS[p],'seed':int(seeds[p]),
                    'snapshot_sha256':states[p]['snapshot_sha256']} for p in fc_PHASES},
                'directions':dirs,'phase_setups':setups,
                'native_event_ledger':fc_file_ref(outputs/'native-event-ledger.json',outputs),
                'native_identity':{'hamiltonian_sha256':fc_POTENTIAL_SHA,
                    'provider_profile':'task159-host-private-cpu/v1',
                    'source_refs':{'binary_sha256':fc_file_ref(binary_out, outputs),
                        'calphy_identity':fc_file_ref(provenance/'calphy-source-identity.json',outputs),
                        'provider_identity':fc_file_ref(provenance/'author-provider-identity.json',outputs)}}}
            fc_write_json(outputs/'reference-precommit.json',descriptor)
            fc_write_json(outputs/'author-generation-clock.json',{'schema':'case06-author-generation-clock/v1',
                'start_utc':started_utc,'end_utc':fc__clock_utc(),
                'elapsed_seconds':fc_time.monotonic()-started,'native_md_executed':bool(ledger['native_invocations']),
                'actual_md_steps':steps,'actual_atomsteps':atoms,'attempts':attempts})
            return {'status':'RAW_READY_PENDING_REPLAY','descriptor_sha256':fc_sha(outputs/'reference-precommit.json'),
                    'actual_md_steps':steps,'actual_atomsteps':atoms,'attempts':attempts,
                    'native_md_executed':bool(ledger['native_invocations'])}
        except BaseException as exc:
            stop_reason=f'{type(exc).__name__}: {exc}'
            fc_write_json(outputs/'author-generation-failure.json',{'status':'PARTIAL_UNKNOWN',
                'reason':stop_reason,'native_md_executed':bool(ledger['native_invocations']),
                'reservations':reservations,'utc':fc__clock_utc()})
            flush()
            raise

    def kernel_main(argv=None):
        argv = list(sys.argv[1:] if argv is None else argv)
        if "--kernel" in argv:
            argv.remove("--kernel")
        if argv and argv[0] == "--wrapper-snapshot": return _wrapper_snapshot(argv[1:])
        if argv and argv[0] == "--wrapper-receipt": return _wrapper_receipt(argv[1:])
        parser = argparse.ArgumentParser(description="Remote Calphy kernel qualification; --check-runtime does not run MD")
        parser.add_argument("--check-runtime", action="store_true")
        parser.add_argument("--instrument-native", action="store_true")
        parser.add_argument("--input", type=Path)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--manifest", type=Path)
        parser.add_argument("--min-face-A", type=float, default=10.5)
        parser.add_argument("--thermo-interval", type=int, default=100)
        parser.add_argument("--invocation-id")
        parser.add_argument("--native-log", type=Path)
        parser.add_argument("--run", action="store_true")
        parser.add_argument("--author-reference", action="store_true", help="host-owned private A worker; never available to the candidate")
        parser.add_argument("--author-seed-file", type=Path)
        parser.add_argument("--author-deadline-seconds", type=int, default=43200)
        parser.add_argument("--outputs", type=Path, default=Path(os.environ.get("CASE06_OUTPUTS", "outputs")))
        args = parser.parse_args(argv)
        try:
            if args.instrument_native:
                if not all((args.input,args.output,args.manifest,args.invocation_id,args.native_log)):
                    raise Stop("instrument-native requires input/output/manifest/invocation-id/native-log")
                instr_main(["--input",str(args.input),"--output",str(args.output),"--manifest",str(args.manifest),
                    "--min-face-A",str(args.min_face_A),"--thermo-interval",str(args.thermo_interval),
                    "--invocation-id",args.invocation_id,"--native-log",str(args.native_log)])
                return 0
            if args.check_runtime:
                identity = drv_validate_installed_sources()
                if identity.get("pass") is not True:
                    raise Stop("installed Calphy source hashes do not match the task-pinned source map")
                binary = Path(os.environ.get("CASE08_REAL_LMP", ""))
                potential = ASSET_ROOT / "native_inputs" / "SiOx_potential.yace"
                if not binary.is_file() or sha(binary) != zero_EXPECTED_BINARY_SHA:
                    raise Stop("remote LAMMPS binary is missing or differs from the selected runtime SHA")
                if not potential.is_file() or sha(potential) != POTENTIAL_SHA:
                    raise Stop("task-packaged public Hamiltonian is missing or differs from its frozen SHA")
                print(json.dumps({"status":"RUNTIME_QUALIFIED_NO_MD","calphy_source_identity":identity,
                    "binary_sha256":sha(binary),"potential_sha256":sha(potential),"native_md_executed":False},indent=2))
                return 0
            if args.author_reference:
                if args.author_seed_file is None:
                    raise Stop('--author-reference requires a host-generated private seed file')
                result=fc_run_author_reference(args.outputs,args.author_seed_file,args.author_deadline_seconds)
                print(json.dumps(result,indent=2,ensure_ascii=False))
                return 0 if result.get('status')=='RAW_READY_PENDING_REPLAY' else 2
            if args.run:
                result=fc_run_candidate_campaign(args.outputs)
                print(json.dumps(result,indent=2,ensure_ascii=False))
                return 0 if result.get('status')=='NATIVE_CAMPAIGN_FINISHED_PENDING_VERIFICATION' else 2
            parser.print_help(); return 0
        except Exception as exc:
            partial=sorted(str(p) for p in args.outputs.rglob("case08-execution.*.json")) if args.run and args.outputs.exists() else []
            ledger_path=args.outputs/"native-event-ledger.json"
            ledger_started=False
            if ledger_path.is_file():
                try: ledger_started=bool(json.loads(ledger_path.read_text()).get("native_invocations"))
                except Exception: pass
            print(json.dumps({"status":"RUNTIME_BLOCKED","native_md_executed":True if (partial or ledger_started) else None,
                "reason":f"{type(exc).__name__}: {exc}","partial_native_evidence":partial,
                "ledger_has_native_invocations":ledger_started},indent=2)); return 2

if __name__ == "__main__":
    if "--kernel" in sys.argv:
        raise SystemExit(kernel_main())
    raise SystemExit(main())
