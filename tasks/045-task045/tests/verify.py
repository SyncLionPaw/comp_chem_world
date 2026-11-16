#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including plan.json, run-ledger.json, topology.json).
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Investigate molecular-centre-of-mass diffusion and its identifiability within a finite budget.
"""Standalone Case04 evaluator and submission-bound review adapter.

The automatic directory is a DATA-only runtime location. Scientific algorithms,
policy checks, scheduler validation, and budget checks are defined in this file.
"""
from __future__ import annotations

# The terminal adapter is installed only in the separate CompChemBench verifier image.
if __name__ == "__main__" and __import__("sys").argv[1:] == ["--terminal"]:
    import runpy as _runpy
    from pathlib import Path as _Path
    import sys as _sys
    _entry = _Path(__file__).resolve().parent / "harbor_runtime" / "entry.py"
    if not _entry.is_file():
        raise SystemExit("The pinned CompChemBench verifier image is required for terminal grading.")
    _sys.argv = [str(_entry)]
    _runpy.run_path(str(_entry), run_name="__main__")
    raise SystemExit(0)


import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent

def _build_trajectory_namespace():
    """Independent orthogonal-cell molecular COM and correlation reconstruction."""
    import math
    from collections import Counter, deque
    from pathlib import Path
    import numpy as np


    def min_image(d, lengths): return d-lengths*np.rint(d/lengths)

    def topology(structure: Path, policy: dict):
        types_by_id={}; xyz_by_id={}; bounds={}; in_atoms=False
        for line in structure.read_text().splitlines():
            w=line.split()
            if not w: continue
            if len(w)>=4 and w[-2:] in (['xlo','xhi'],['ylo','yhi'],['zlo','zhi']): bounds[w[-2][0]]=(float(w[0]),float(w[1]))
            if w[0]=='Atoms': in_atoms=True; continue
            if not in_atoms or w[0].startswith('#'): continue
            try: aid,typ=int(w[0]),int(w[1]); xyz=np.array([float(x) for x in w[2:5]])
            except (ValueError,IndexError):
                if w[0][0].isalpha(): in_atoms=False
                continue
            if aid in types_by_id: raise ValueError('duplicate atom id in structure')
            types_by_id[aid]=typ; xyz_by_id[aid]=xyz
        n=policy['system']['atoms']; ids=sorted(types_by_id)
        if ids!=list(range(1,n+1)) or set(bounds)!={'x','y','z'}: raise ValueError('structure atom/box inventory invalid')
        L=np.array([bounds[k][1]-bounds[k][0] for k in 'xyz'])
        if not np.isfinite(L).all() or np.any(L<=0): raise ValueError('invalid structure cell')
        types=np.array([types_by_id[i] for i in ids],dtype=np.int64); xyz=np.array([xyz_by_id[i] for i in ids])
        cfg=policy['system']; tmap={int(k):v for k,v in cfg['type_to_element'].items()}; masses=cfg['atomic_masses']; formulas={s:Counter(f) for s,f in cfg['species_formulas'].items()}
        heavy=np.flatnonzero(np.isin(types,[t for t,e in tmap.items() if e not in ('H','Cl')]))
        adj=[set() for _ in types]
        cutoff=float(cfg['heavy_atom_graph_cutoff_A'])
        for q,i in enumerate(heavy):
            d=min_image(xyz[heavy[q+1:]]-xyz[i],L); ds=np.einsum('ij,ij->i',d,d)
            for j in heavy[q+1:][ds<=cutoff**2+1e-12]: adj[int(i)].add(int(j));adj[int(j)].add(int(i))
        for i in np.flatnonzero([tmap[int(t)]=='H' for t in types]):
            d=min_image(xyz[heavy]-xyz[i],L); ds=np.einsum('ij,ij->i',d,d)
            order=np.lexsort((heavy,ds)); j=int(heavy[order[0]])
            if math.sqrt(float(ds[order[0]]))>cfg['hydrogen_nearest_heavy_cutoff_A']+1e-12: raise ValueError('hydrogen has no nearby heavy atom')
            adj[int(i)].add(j);adj[j].add(int(i))
        seen=set(); mols=[]
        for i in range(n):
            if i in seen: continue
            q=deque([i]);seen.add(i); comp=[]
            while q:
                a=q.popleft();comp.append(a)
                for b in adj[a]:
                    if b not in seen: seen.add(b);q.append(b)
            formula=Counter(tmap[int(types[a])] for a in comp)
            match=[s for s,f in formulas.items() if f==formula]
            if len(match)!=1: raise ValueError(f'unclassified molecular component {formula}')
            sp=match[0]; comp=np.asarray(sorted(comp),dtype=np.int64)
            mols.append({'species':sp,'ids':comp,'allowed':set(map(int,comp)),'adj':adj,'mass':np.array([masses[tmap[int(types[a])]] for a in comp])})
        mols.sort(key=lambda m:(m['species'],int(m['ids'][0])))
        counts=Counter(m['species'] for m in mols)
        if dict(counts)!=cfg['species_counts']: raise ValueError(f'molecular counts mismatch: {dict(counts)}')
        return types,L,mols

    def parse_dump(path: Path, types, mols, expected_n, dt_ps, cfg):
        steps=[]; p=[]; v=[]; raw=[]; expected_cols=['id','type','x','y','z','ix','iy','iz','xu','yu','zu','vx','vy','vz']; nat=len(types)
        with path.open() as f:
            while True:
                line=f.readline()
                if not line: break
                if line.strip()!='ITEM: TIMESTEP': raise ValueError(f'bad trajectory frame header {path}')
                step_s=f.readline().strip()
                if not step_s.isdigit(): raise ValueError('noninteger timestep')
                step=int(step_s)
                if f.readline().strip()!='ITEM: NUMBER OF ATOMS': raise ValueError('missing atom count header')
                if int(f.readline())!=nat: raise ValueError('trajectory atom count mismatch')
                bh=f.readline().split()
                if bh[:3]!=['ITEM:','BOX','BOUNDS']: raise ValueError('bad box bounds header')
                triclinic=bh[3:6]==['xy','xz','yz']
                flags=bh[6:] if triclinic else bh[3:]
                if flags!=['pp','pp','pp']: raise ValueError('trajectory is not fully periodic')
                rows=np.array([[float(x) for x in f.readline().split()] for _ in range(3)])
                n_box_cols=3 if triclinic else 2
                if rows.shape!=(3,n_box_cols) or not np.isfinite(rows).all(): raise ValueError('nonorthogonal or nonfinite cell unsupported')
                if triclinic and np.any(np.abs(rows[:,2])>1e-12): raise ValueError('nonzero triclinic tilt unsupported')
                L=rows[:,1]-rows[:,0]
                if not np.isfinite(L).all() or np.any(L<=0): raise ValueError('invalid cell lengths')
                if len(steps)==0: box=L.copy()
                elif not np.allclose(L,box,rtol=0,atol=1e-8): raise ValueError('changing-volume trajectory unsupported')
                ch=f.readline().split()
                if ch[:2]!=['ITEM:','ATOMS'] or ch[2:]!=expected_cols: raise ValueError('unexpected trajectory columns')
                a=np.empty((nat,14),float)
                for k in range(nat):
                    w=f.readline().split()
                    if len(w)!=14: raise ValueError('truncated atom record')
                    a[k]=[float(x) for x in w]
                if not np.isfinite(a).all(): raise ValueError('nonfinite native frame')
                ids=a[:,0]; typ=a[:,1]
                if not np.equal(ids,np.rint(ids)).all() or not np.equal(typ,np.rint(typ)).all(): raise ValueError('noninteger id/type values')
                order=np.argsort(ids); a=a[order]
                if not np.array_equal(a[:,0],np.arange(1,nat+1)) or not np.array_equal(a[:,1].astype(np.int64),types): raise ValueError('atom ID/type mismatch')
                wrapped=a[:,2:5]; image=a[:,5:8]; unwrapped=a[:,8:11]; atomv=a[:,11:14]
                if not np.equal(image,np.rint(image)).all() or np.max(np.abs(wrapped+image*L-unwrapped))>2e-7: raise ValueError('wrapped/image/unwrapped identity failed')
                framep=np.empty((len(mols),3)); framev=np.empty_like(framep)
                for mi,m in enumerate(mols):
                    root=int(m['ids'][0]); pos={root:wrapped[root].copy()}; todo=deque([root])
                    while todo:
                        i=todo.popleft()
                        for j in m['adj'][i]:
                            if j in m['allowed'] and j not in pos:
                                pos[j]=pos[i]+min_image(wrapped[j]-wrapped[i],L);todo.append(j)
                    if len(pos)!=len(m['ids']): raise ValueError('disconnected molecule graph')
                    xyz=np.array([pos[int(j)] for j in m['ids']]); framep[mi]=np.average(xyz,axis=0,weights=m['mass']);framev[mi]=np.average(atomv[m['ids']],axis=0,weights=m['mass'])
                p.append(np.mod(framep,L));v.append(framev);steps.append(step)
                rawframe={'step':step,'id_type':a[:,:2].copy(),'wrapped':wrapped.copy(),'image':image.copy(),'unwrapped':unwrapped.copy(),'velocity':atomv.copy(),'lengths':L.copy()}
                if len(steps)==1: raw.append(rawframe)
                elif len(steps)==2: raw.append(rawframe)
                else: raw[-1]=rawframe
        if len(steps)<2: raise ValueError('trajectory requires at least two frames')
        dif=np.diff(steps)
        if np.any(dif<=0) or len(set(dif.tolist()))!=1: raise ValueError('trajectory steps must strictly increase at fixed stride')
        stride=int(dif[0]); expected=np.arange(steps[0],steps[-1]+stride,stride,dtype=np.int64)
        if not np.array_equal(np.array(steps),expected): raise ValueError('trajectory stride is irregular')
        if cfg.get('expected_stride_steps') is not None and stride!=cfg['expected_stride_steps']: raise ValueError('trajectory stride differs from native config')
        if cfg.get('start_step') is not None and steps[0]!=cfg['start_step']: raise ValueError('trajectory start differs from native run')
        if cfg.get('end_step') is not None and steps[-1]!=cfg['end_step']: raise ValueError('trajectory end differs from native run')
        pos=np.array(p); un=np.empty_like(pos);un[0]=pos[0]
        for k in range(1,len(steps)): un[k]=un[k-1]+min_image(pos[k]-pos[k-1],box)
        t=np.asarray(steps,dtype=float)*dt_ps
        return {'steps':np.array(steps,dtype=np.int64),'time':t,'pos':un,'vel':np.array(v),'lengths':np.repeat(box[None,:],len(steps),axis=0),'first_raw':raw[0],'last_raw':raw[-1],'stride_steps':stride,'box':box}

    def merge(parent, ext, tol=1e-8):
        a,b=parent['last_raw'],ext['first_raw'];L=a['lengths']
        checks={'step':a['step']==b['step'],'wrapped':float(np.max(np.abs(min_image(a['wrapped']-b['wrapped'],L))))<=tol,'unwrapped':float(np.max(np.abs(a['unwrapped']-b['unwrapped'])))<=tol,'velocity':float(np.max(np.abs(a['velocity']-b['velocity'])))<=tol,'box':float(np.max(np.abs(a['lengths']-b['lengths'])))<=tol,'image':bool(np.array_equal(a['image'],b['image'])),'id_type':bool(np.array_equal(a['id_type'],b['id_type']))}
        if not all(checks.values()): raise ValueError(f'continuation boundary mismatch: {checks}')
        off=parent['pos'][-1]-ext['pos'][0]
        return {'steps':np.r_[parent['steps'],ext['steps'][1:]],'time':np.r_[parent['time'],ext['time'][1:]],'pos':np.concatenate([parent['pos'],ext['pos'][1:]+off]),'vel':np.concatenate([parent['vel'],ext['vel'][1:]]),'lengths':np.concatenate([parent['lengths'],ext['lengths'][1:]])},checks

    def validate_fresh_adaptive_seed(run_id: str, run: dict, attempts: dict):
        """Require a fresh-seed branch to add a new same-temperature initialization."""
        seed = run.get('seed')
        temperature = float(run.get('T_K', -1))
        if seed is None or not math.isfinite(temperature):
            raise ValueError(f'{run_id}: fresh adaptive seed or temperature is invalid')
        for other_id, other in attempts.items():
            if other_id == run_id or other.get('stage') not in {'pilot', 'adaptive', 'confirmation'}:
                continue
            if (float(other.get('T_K', -2)) == temperature and other.get('seed') == seed):
                raise ValueError(f'{run_id}: fresh adaptive seed duplicates another executed same-temperature seed')

    def correlations(ds, mols, origins_ps, maxlag_ps, dt_ps):
        pos,vel,t=ds['pos'],ds['vel'],ds['time']; masses=np.array([sum(m['mass']) for m in mols]); species={s:np.array([i for i,m in enumerate(mols) if m['species']==s],dtype=int) for s in sorted({m['species'] for m in mols})}
        nlag=int(round(maxlag_ps/dt_ps)); system_pos=np.average(pos,axis=1,weights=masses);system_vel=np.average(vel,axis=1,weights=masses); out={}
        for sp,ix in species.items():
            arrays={k:np.zeros(nlag+1) for k in ('msd_A2','msd_drift_corrected_A2','vacf_A2_per_ps2','vacf_drift_corrected_A2_per_ps2')}; counts=np.zeros(nlag+1,dtype=np.int64)
            for lagidx in range(nlag+1):
                lag=lagidx*dt_ps; starts=np.flatnonzero((t>=origins_ps[0]-1e-9)&(t<=origins_ps[1]+1e-9)&(np.arange(len(t))+lagidx<len(t)))
                counts[lagidx]=len(starts)
                if len(starts)==0: raise ValueError('requested estimator has zero time origins')
                dp=pos[starts[:,None]+lagidx,ix[None,:]]-pos[starts[:,None],ix[None,:]]; drift=system_pos[starts+lagidx]-system_pos[starts]
                vv=vel[:,ix,:];vc=vv-system_vel[:,None,:]
                arrays['msd_A2'][lagidx]=np.mean(np.sum(dp*dp,axis=2));arrays['msd_drift_corrected_A2'][lagidx]=np.mean(np.sum((dp-drift[:,None,:])**2,axis=2))
                arrays['vacf_A2_per_ps2'][lagidx]=np.mean(np.sum(vv[starts]*vv[starts+lagidx],axis=2));arrays['vacf_drift_corrected_A2_per_ps2'][lagidx]=np.mean(np.sum(vc[starts]*vc[starts+lagidx],axis=2))
            arrays['lag_ps']=np.arange(nlag+1)*dt_ps;arrays['origin_count']=counts;out[sp]=arrays
        return out
    return SimpleNamespace(topology=topology, parse_dump=parse_dump, merge=merge, correlations=correlations,
                           validate_fresh_adaptive_seed=validate_fresh_adaptive_seed)

def _build_scheduler_namespace():
    """Cross-check candidate-submitted Case04 scheduler evidence.

    This module establishes an artifact-consistency result, not host attestation.
    Reference executions use the same checks and must match the runner answer mode.
    """

    import hashlib
    import json
    import math
    import re
    import shlex
    from dataclasses import dataclass, field
    from datetime import datetime
    from pathlib import Path, PurePosixPath


    RECEIPT = "execution/candidate-scheduler-receipt.json"
    RECEIPT_SCHEMA = "case04-candidate-scheduler-receipt/v1"
    RECORD_SCHEMA = "case04-candidate-scheduler-record/v1"
    ORDER_SCHEMA = "case04-execution-order/v1"
    ORIGIN = "candidate-submitted-crosschecked"
    TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"}


    class CandidateEvidenceError(ValueError):
        """Candidate evidence is absent, malformed, or internally inconsistent."""


    @dataclass(frozen=True)
    class CandidateSchedule:
        """Typed output of validate(); scorer must not accept arbitrary mappings."""

        jobs: list[dict]
        manifest_sha256: str
        attempt_id: str
        receipt_sha256: str
        gpu_basis: dict = field(default_factory=dict)
        gpu_errors: list[str] = field(default_factory=list)
        origin: str = ORIGIN


    def _sha(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()


    def _canonical_hash(value) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


    def _contained_file(app: Path, value, label: str) -> Path:
        if not isinstance(value, str):
            raise CandidateEvidenceError(f"{label}: path must be a string")
        rel = PurePosixPath(value)
        if rel.is_absolute() or not rel.parts or rel.parts[0] != "execution" or ".." in rel.parts or "\\" in value:
            raise CandidateEvidenceError(f"{label}: path must be contained under execution/")
        try:
            root = app.resolve(strict=True)
        except OSError as exc:
            raise CandidateEvidenceError(f"{label}: APP root is unavailable") from exc
        path = root.joinpath(*rel.parts)
        cur = root
        if cur.is_symlink():
            raise CandidateEvidenceError(f"{label}: APP root is a symlink")
        for part in rel.parts:
            cur = cur / part
            if cur.is_symlink():
                raise CandidateEvidenceError(f"{label}: symlink path component")
        if not path.is_file():
            raise CandidateEvidenceError(f"{label}: required candidate file is missing")
        return path


    def _read_json(path: Path, label: str):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateEvidenceError(f"{label}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise CandidateEvidenceError(f"{label}: JSON object required")
        return value


    def _hash_ref(app: Path, ref, label: str) -> Path:
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise CandidateEvidenceError(f"{label}: expected path and sha256")
        path = _contained_file(app, ref["path"], label)
        try:
            actual = _sha(path)
        except OSError as exc:
            raise CandidateEvidenceError(f"{label}: candidate file is unreadable") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", str(ref["sha256"])) or actual != ref["sha256"]:
            raise CandidateEvidenceError(f"{label}: content hash mismatch")
        return path


    def _time(value, label):
        if not isinstance(value, str):
            raise CandidateEvidenceError(f"{label}: timestamp must be a string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CandidateEvidenceError(f"{label}: invalid timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CandidateEvidenceError(f"{label}: timestamp needs an explicit timezone")
        return parsed


    def _duration(value):
        if type(value) is int:
            return value
        if not isinstance(value, str):
            raise CandidateEvidenceError("scheduler walltime must be seconds or Slurm duration")
        match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
        if not match:
            raise CandidateEvidenceError("invalid scheduler walltime")
        days, hours, minutes, seconds = (int(v or 0) for v in match.groups())
        if minutes >= 60 or seconds >= 60:
            raise CandidateEvidenceError("invalid scheduler walltime")
        return days * 86400 + hours * 3600 + minutes * 60 + seconds


    def _directive_values(script: str):
        result = {}
        aliases = {
            "-N": "nodes", "--nodes": "nodes", "-n": "tasks", "--ntasks": "tasks",
            "--ntasks-per-node": "tasks", "-c": "cpus_per_task", "--cpus-per-task": "cpus_per_task",
            "--mem": "memory", "--mem-per-cpu": "memory_per_cpu", "-t": "walltime", "--time": "walltime",
            "--gres": "gres", "--gpus": "gpus", "--gpus-per-node": "gpus",
        }
        unsupported_resources = {
            "-B", "--extra-node-info", "--cpus-per-gpu", "--gpus-per-task", "--ntasks-per-core",
            "--ntasks-per-socket", "--sockets-per-node", "--cores-per-socket", "--threads-per-core",
            "--gpus-per-socket", "--mem-per-gpu", "--exclusive", "--oversubscribe",
        }
        resource_prefixes = ("--node", "--ntask", "--cpu", "--mem", "--time", "--gres", "--gpu")
        for line in script.splitlines():
            match = re.match(r"^\s*#SBATCH\s+(.+?)\s*$", line)
            if not match:
                continue
            try:
                tokens = shlex.split(match.group(1), comments=True)
            except ValueError as exc:
                raise CandidateEvidenceError("malformed #SBATCH directive") from exc
            i = 0
            while i < len(tokens):
                token = tokens[i]
                if token == "-a" or (token.startswith("-a") and not token.startswith("-A")) or token == "--array" or token.startswith("--array="):
                    raise CandidateEvidenceError("Slurm job arrays are not allowed")
                if token in unsupported_resources or any(token.startswith(x + "=") for x in unsupported_resources):
                    raise CandidateEvidenceError(f"unsupported resource-affecting Slurm option {token}")
                key = None
                value = None
                if token.startswith("--") and "=" in token:
                    option, value = token.split("=", 1)
                    key = aliases.get(option)
                elif token in aliases:
                    key = aliases[token]
                    i += 1
                    if i >= len(tokens):
                        raise CandidateEvidenceError(f"#SBATCH {token} lacks a value")
                    value = tokens[i]
                elif len(token) > 2 and token[:2] in ("-N", "-n", "-c", "-t"):
                    key = aliases[token[:2]]
                    value = token[2:].lstrip("=")
                    if not value:
                        raise CandidateEvidenceError(f"#SBATCH {token[:2]} lacks a value")
                if key is None and token.startswith(resource_prefixes):
                    raise CandidateEvidenceError(f"unsupported resource-affecting Slurm option {token}")
                if key is None and token.startswith(("-N", "-n", "-c", "-t", "-B")) and token not in ("-N", "-n", "-c", "-t"):
                    raise CandidateEvidenceError(f"unsupported resource-affecting Slurm option {token}")
                if key:
                    result.setdefault(key, []).append(value)
                i += 1
        return result


    def _mem_gib(value):
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGTP]?)", str(value).strip(), re.I)
        if not match:
            raise CandidateEvidenceError("invalid Slurm memory request")
        amount = float(match.group(1)); unit = match.group(2).upper()
        # Slurm interprets a suffix-less --mem value as MiB.
        scale = {"": 1 / 1024, "K": 1 / (1024 ** 2), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 ** 2}[unit]
        return amount * scale


    def _check_batch(path: Path, resources: dict, budget: dict):
        try:
            directives = _directive_values(path.read_text(encoding="utf-8", errors="strict"))
        except CandidateEvidenceError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
            raise CandidateEvidenceError("invalid batch script resource directive") from exc
        for key, count in directives.items():
            if len(count) != 1:
                raise CandidateEvidenceError(f"batch script repeats #SBATCH {key}")
        nodes = int((directives.get("nodes") or [0])[0])
        tasks = int((directives.get("tasks") or [1])[0])
        cpt = int((directives.get("cpus_per_task") or [1])[0])
        cpus = tasks * cpt
        if directives.get("memory") and directives.get("memory_per_cpu"):
            raise CandidateEvidenceError("batch script cannot combine --mem and --mem-per-cpu")
        if directives.get("memory_per_cpu"):
            mem = _mem_gib(directives["memory_per_cpu"][0]) * cpus
        else:
            mem = _mem_gib((directives.get("memory") or [""])[0])
        walltime = _duration((directives.get("walltime") or [""])[0])
        gpus = []
        for raw in directives.get("gres", []):
            m = re.fullmatch(r"gpu(?::[^:]+)?:(\d+)", raw, re.I)
            if not m:
                raise CandidateEvidenceError("unrecognized #SBATCH --gres GPU request")
            gpus.append(int(m.group(1)))
        for raw in directives.get("gpus", []):
            if not raw.isdecimal():
                raise CandidateEvidenceError("unrecognized #SBATCH GPU request")
            gpus.append(int(raw))
        if nodes != 1 or cpus < 1 or cpus > budget["cpus"] or mem <= 0 or mem > budget["memory_gib"] or walltime < 1 or walltime > budget["walltime_seconds"]:
            raise CandidateEvidenceError("batch resource request exceeds or omits Case04 scheduler budget")
        if len(gpus) > 1 or any(g != 1 for g in gpus):
            raise CandidateEvidenceError("batch script may request at most one GPU")
        requested_gpus = gpus[0] if gpus else 0
        observed = {"nodes": nodes, "cpus": cpus, "memory_gib": mem, "walltime_seconds": walltime}
        if any(resources.get(key) != value for key, value in observed.items()):
            raise CandidateEvidenceError("scheduler resources disagree with submitted batch script")
        if resources.get("gpus") not in (None, requested_gpus):
            raise CandidateEvidenceError("scheduler GPU allocation disagrees with batch request")
        return {"nodes": nodes, "cpus": cpus, "memory_gib": mem, "walltime_seconds": walltime, "gpus": requested_gpus}


    def _parse_tres(raw):
        out = {}
        for item in raw.split(","):
            if "=" not in item:
                raise CandidateEvidenceError("malformed AllocTRES")
            key, value = item.split("=", 1)
            if not key or key in out:
                raise CandidateEvidenceError("duplicate or empty AllocTRES field")
            out[key] = value
        return out


    def validate(app: Path, policy: dict, manifest: list, runs: list, ledger: dict, verify_gpu_request, *, answer_mode='agent') -> CandidateSchedule:
        """Validate candidate artifacts and normalize them for the shared gate."""
        if not isinstance(ledger, dict) or not isinstance(runs, list) or not runs:
            raise CandidateEvidenceError("candidate run ledger is missing or malformed")
        receipt_path = _contained_file(app, RECEIPT, "candidate scheduler receipt")
        receipt = _read_json(receipt_path, "candidate scheduler receipt")
        required = {"schema", "origin", "evidence_mode", "attempt_id", "ledger_sha256", "execution_order", "attempts"}
        if answer_mode not in {"agent", "oracle"}:
            raise CandidateEvidenceError("unsupported runner answer mode")
        contract = policy["candidate_scheduler_evidence"]
        missing=set(required)-set(receipt)
        if missing-{"origin","evidence_mode"} or set(receipt)-required:
            raise CandidateEvidenceError("candidate scheduler receipt fields mismatch")
        # Origin and mode are trusted runner facts. Public submissions may omit
        # these redundant fields; only omission receives the trusted default.
        origin=receipt.get("origin",contract["origin"])
        evidence_mode=receipt.get("evidence_mode",answer_mode)
        if (receipt.get("schema") != contract["schema"] or origin != contract["origin"]
                or evidence_mode != answer_mode):
            raise CandidateEvidenceError("candidate scheduler receipt schema/origin/mode mismatch")
        attempt_id = receipt.get("attempt_id")
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
            raise CandidateEvidenceError("candidate attempt_id must be 32 lowercase hex characters")
        if receipt.get("ledger_sha256") != _canonical_hash(ledger):
            raise CandidateEvidenceError("candidate receipt ledger hash mismatch")
        order_ref = receipt.get("execution_order")
        if not isinstance(order_ref,dict) or not {'path','sha256'}.issubset(order_ref):
            raise CandidateEvidenceError('execution order: expected path and sha256')
        order_path = _hash_ref(app, {'path':order_ref['path'],'sha256':order_ref['sha256']}, "execution order")
        order = _read_json(order_path, "execution order")
        if order.get("schema") != ORDER_SCHEMA or order.get("attempt_id") != receipt.get("attempt_id") or not isinstance(order.get("attempts"), list):
            raise CandidateEvidenceError("execution order schema/attempt binding mismatch")
        if any(k in order_ref and order_ref[k]!=order.get(k) for k in ('schema','attempts')):
            raise CandidateEvidenceError('receipt execution-order summary differs from its hash-bound file')
        ledger_ids = [r.get("run_id") for r in runs]
        if len(ledger_ids) != len(set(ledger_ids)) or any(not isinstance(x, str) or not x for x in ledger_ids):
            raise CandidateEvidenceError("ledger run IDs are invalid")
        items = receipt.get("attempts")
        sb = policy["candidate_scheduler_evidence"]["resource_budget"]
        budget = {"nodes": sb["nodes"], "cpus": sb["cpus"], "memory_gib": sb["memory_gib"], "walltime_seconds": sb["walltime_seconds"]}
        max_allocations = sb["max_allocations"]
        if not isinstance(items, list) or len(items) != len(runs) or len(items) > max_allocations:
            raise CandidateEvidenceError(f"receipt must include every attempt and stay within {max_allocations} allocations")
        by_run = {}
        allocations = set(); job_ids = set(); rows = []; intervals = []; gpu_basis = {}; gpu_errors = []
        run_by_id = {r["run_id"]: r for r in runs}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"run_id", "allocation_id", "scheduler_record", "batch_script", "stdout", "stderr"}:
                raise CandidateEvidenceError("attempt evidence fields are incomplete or unknown")
            rid = item["run_id"]
            if not isinstance(rid, str) or rid not in run_by_id or rid in by_run:
                raise CandidateEvidenceError("receipt run IDs must exactly and uniquely cover the ledger")
            by_run[rid] = item
            record_path = _hash_ref(app, item["scheduler_record"], f"{rid} scheduler record")
            batch_path = _hash_ref(app, item["batch_script"], f"{rid} batch script")
            _hash_ref(app, item["stdout"], f"{rid} stdout")
            _hash_ref(app, item["stderr"], f"{rid} stderr")
            record = _read_json(record_path, f"{rid} scheduler record")
            fields = {"schema", "attempt_id", "run_id", "job_id", "allocation_id", "submitted_at", "started_at", "ended_at", "state", "exit_code", "partition", "allocation_tres", "resources", "array"}
            if not fields.issubset(record) or record.get("schema") != RECORD_SCHEMA or record.get("array") is not False:
                raise CandidateEvidenceError(f"{rid}: malformed scheduler record or array allocation")
            for raw_key in ('raw_sacct','raw_scontrol'):
                raw_rel=record.get(raw_key)
                if raw_rel is None: continue
                raw_path=_contained_file(app,raw_rel,f'{rid} {raw_key}')
                sums_path=app/'execution'/'scheduler-records'/'SHA256SUMS'
                if not raw_path.is_file() or not sums_path.is_file():
                    raise CandidateEvidenceError(f'{rid}: referenced raw scheduler evidence is missing')
                sums={line.split(None,1)[1].strip().lstrip('*'):
                      line.split(None,1)[0].lower() for line in sums_path.read_text(errors='replace').splitlines()
                      if len(line.split(None,1))==2 and re.fullmatch(r'[0-9a-fA-F]{64}',line.split(None,1)[0])}
                if sums.get(PurePosixPath(raw_rel).name)!=_sha(raw_path):
                    raise CandidateEvidenceError(f'{rid}: raw scheduler record hash is not bound by SHA256SUMS')
            job = str(record.get("job_id"))
            allocation = record.get("allocation_id")
            if rid != record.get("run_id") or not re.fullmatch(r"[0-9]+", job) or not isinstance(allocation, str) or not allocation:
                raise CandidateEvidenceError(f"{rid}: scheduler identity mismatch")
            if allocation != item["allocation_id"] or allocation in allocations or job in job_ids:
                raise CandidateEvidenceError("allocations and job IDs must be unique and receipt-bound")
            allocations.add(allocation); job_ids.add(job)
            run = run_by_id[rid]
            if str(run.get("job_id")) != job or run.get("allocation_id") != allocation:
                raise CandidateEvidenceError(f"{rid}: scheduler, receipt, and ledger job/allocation IDs disagree")
            times = [_time(record[k], f"{rid} {k}") for k in ("submitted_at", "started_at", "ended_at")]
            if not times[0] <= times[1] <= times[2]:
                raise CandidateEvidenceError(f"{rid}: invalid scheduler chronology")
            raw_exit=record.get('exit_code')
            if type(raw_exit) is int:
                exit_status,exit_signal=raw_exit,0
            elif isinstance(raw_exit,str) and re.fullmatch(r'\d+:\d+',raw_exit):
                exit_status,exit_signal=(int(x) for x in raw_exit.split(':',1))
            else:
                raise CandidateEvidenceError(f"{rid}: scheduler exit code is malformed")
            exit_value=0 if exit_status==0 and exit_signal==0 else (exit_status or exit_signal or 1)
            if record["state"] not in TERMINAL:
                raise CandidateEvidenceError(f"{rid}: scheduler status is not terminal")
            resources = record.get("resources")
            if not isinstance(resources, dict) or set(resources) != {"nodes", "cpus", "memory_gib", "walltime_seconds", "gpus"}:
                raise CandidateEvidenceError(f"{rid}: scheduler resource record malformed")
            if times[2] < times[1] or (times[2] - times[1]).total_seconds() > resources.get("walltime_seconds", budget["walltime_seconds"]):
                raise CandidateEvidenceError(f"{rid}: scheduler walltime exceeds allocation")
            if type(resources["nodes"]) is not int or resources["nodes"] != budget["nodes"] or type(resources["cpus"]) is not int or not 1 <= resources["cpus"] <= budget["cpus"]:
                raise CandidateEvidenceError(f"{rid}: scheduler CPU/node allocation exceeds budget")
            memory_gib = resources["memory_gib"]
            if type(memory_gib) is int:
                memory_valid = 0 < memory_gib <= budget["memory_gib"]
            elif type(memory_gib) is float:
                memory_valid = math.isfinite(memory_gib) and 0 < memory_gib <= budget["memory_gib"]
            else:
                memory_valid = False
            if not memory_valid:
                raise CandidateEvidenceError(f"{rid}: scheduler memory allocation exceeds budget")
            if type(resources["walltime_seconds"]) is not int or not 1 <= resources["walltime_seconds"] <= budget["walltime_seconds"] or (resources["gpus"] is not None and (type(resources["gpus"]) is not int or not 0 <= resources["gpus"] <= sb["gpus"])):
                raise CandidateEvidenceError(f"{rid}: scheduler time/GPU allocation exceeds budget")
            batch_resource = _check_batch(batch_path, resources, budget)
            tres = record["allocation_tres"]
            if not isinstance(tres, str):
                raise CandidateEvidenceError(f"{rid}: AllocTRES must be preserved as text")
            tres_map = _parse_tres(tres)
            cpu = tres_map.get("cpu")
            node = tres_map.get("node", tres_map.get("nodes"))
            mem = tres_map.get("mem")
            try:
                if cpu is not None and int(cpu) != resources["cpus"]: raise CandidateEvidenceError(f"{rid}: AllocTRES CPU count disagrees")
                if node is not None and int(node) != resources["nodes"]: raise CandidateEvidenceError(f"{rid}: AllocTRES node count disagrees")
            except (ValueError, TypeError, OverflowError) as exc:
                raise CandidateEvidenceError(f"{rid}: invalid AllocTRES CPU/node count") from exc
            if mem is not None and abs(_mem_gib(mem) - resources["memory_gib"]) > 0.01: raise CandidateEvidenceError(f"{rid}: AllocTRES memory disagrees")
            tres_gpu = re.search(r"(?:^|,)gres/gpu(?::[^=,]+)?=(\d+)(?:,|$)", tres)
            recorded = tres_gpu is not None
            gpu_count = int(tres_gpu.group(1)) if recorded else None
            if recorded and gpu_count != resources["gpus"]: raise CandidateEvidenceError(f"{rid}: AllocTRES GPU count disagrees")
            attempt_id = receipt["attempt_id"]
            if record.get("attempt_id") != attempt_id:
                raise CandidateEvidenceError(f"{rid}: scheduler record attempt_id mismatch")
            good = run.get("status") == "complete"
            if good != (record["state"] == "COMPLETED" and exit_value == 0):
                raise CandidateEvidenceError(f"{rid}: scheduler and ledger terminal status disagree")
            if batch_resource["gpus"] != run.get("gpu_count"):
                raise CandidateEvidenceError(f"{rid}: batch and ledger GPU requests disagree")
            if good:
                if batch_resource["gpus"] == 0:
                    if recorded and gpu_count != 0:
                        gpu_errors.append(f"{rid}: CPU run has a nonzero GPU allocation")
                    gpu_basis[rid] = {"basis": "cpu_execution_and_zero_gpu_request", "gpu_count": 0, "scheduler_recorded_gpu_count": gpu_count, "gpu_allocation_recorded": recorded, "partition": record["partition"]}
                elif recorded:
                    if resources["gpus"] != 1:
                        gpu_errors.append(f"{rid}: completed run does not request exactly one GPU")
                    if gpu_count != 1: gpu_errors.append(f"{rid}: completed run does not have exactly one scheduler-recorded GPU")
                    gpu_basis[rid] = {"basis": "candidate_scheduler_recorded_alloc_tres", "gpu_count": gpu_count, "scheduler_recorded_gpu_count": gpu_count, "gpu_allocation_recorded": True, "partition": record["partition"]}
                else:
                    try:
                        gpu_basis[rid] = verify_gpu_request(app, run)
                        gpu_basis[rid]["partition"] = record["partition"]
                        gpu_basis[rid]["scheduler_recorded_gpu_count"] = None
                        gpu_basis[rid]["gpu_allocation_recorded"] = False
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        msg = f"{rid}: one-GPU runtime/request proof failed: {exc}"
                        gpu_errors.append(msg)
                        gpu_basis[rid] = {"basis": "unverified", "partition": record["partition"], "error": msg}
            intervals.append((times[1], times[2], rid))
            rows.append({"run_id": rid, "job_id": job, "submitted_at": record["submitted_at"], "started_at": record["started_at"], "ended_at": record["ended_at"], "state": record["state"], "exit_code": exit_value, "gpu_count": gpu_count, "gpu_allocation_recorded": recorded, "scheduler_recorded_gpu_count": gpu_count, "partition": record["partition"], "allocation_tres": tres, "allocation_id": allocation, "reported_resources": resources, "resources": batch_resource})
        if set(by_run) != set(ledger_ids):
            raise CandidateEvidenceError("receipt run coverage differs from ledger attempts")
        ordered = sorted(intervals, key=lambda x: x[0])
        if order["attempts"] != [rid for _, _, rid in ordered]:
            raise CandidateEvidenceError("execution-order record does not exactly match chronological attempts")
        events = []
        for start, end, rid in ordered:
            if start < end:
                events.extend(((start, 1, rid), (end, -1, rid)))
        active = set()
        for _, delta, rid in sorted(events, key=lambda event: (event[0], event[1])):
            if delta < 0:
                active.discard(rid)
            else:
                active.add(rid)
                if len(active) > sb["max_concurrent_jobs"]:
                    raise CandidateEvidenceError("scheduler running intervals exceed max_concurrent_jobs")
        return CandidateSchedule(jobs=rows, manifest_sha256=_canonical_hash(manifest), attempt_id=attempt_id,
                                 receipt_sha256=_sha(receipt_path), gpu_basis=gpu_basis, gpu_errors=gpu_errors)
    return SimpleNamespace(CandidateSchedule=CandidateSchedule, validate=validate, ORIGIN=ORIGIN)

def _project_frozen_decision_plan(plan, ledger, results, policy):
    """Add lossless in-memory aliases for the public scientific precommit fields.

    The submitted object and its frozen digest remain byte-for-byte untouched;
    this view only normalizes already-declared equivalent fields for checks.
    """
    import copy
    view=copy.deepcopy(plan)
    view['_raw_plan_for_hash']=copy.deepcopy(plan)
    contract=view.get('automatic_decision_contract')
    raw_contract=plan.get('automatic_decision_contract')
    if not isinstance(contract,dict) or not isinstance(raw_contract,dict):
        return view
    pre=contract.get('precommit')
    raw_pre=raw_contract.get('precommit')
    ap=plan.get('analysis_precommit')
    if not isinstance(pre,dict) or not isinstance(ap,dict):
        return view
    # Resolve duplicated exclusions only when they are numerically identical.
    ex_values=[x for x in (ap.get('excluded_time_ps'), plan.get('method',{}).get('excluded_time_ps')) if x is not None]
    if ex_values and any(float(x)!=float(ex_values[0]) for x in ex_values):
        raise ValueError('frozen analysis and method exclusion values conflict')
    if 'fixed_exclusion_ps' not in pre and ex_values:
        pre['fixed_exclusion_ps']=float(ex_values[0])
    method=plan.get('method',{})
    estimator=str(ap.get('estimator','')).lower()
    if ('method_id' not in pre and isinstance(method,dict) and
        all(k in method for k in ('analysis_windows_ps','vacf_cutoffs_ps','trajectory_stride_steps','units')) and
        'msd' in estimator and 'vacf' in estimator):
        pre['method_id']=policy['estimators']['method']
    if 'series' not in pre:
        origins=ap.get('origin_intervals_ps',{})
        limits=ap.get('lag_limits_ps',{})
        windows=ap.get('windows_ps',method.get('analysis_windows_ps'))
        cutoffs=ap.get('vacf_cutoffs_ps',method.get('vacf_cutoffs_ps'))
        run_rows={x.get('run_id'):x for x in ap.get('runs',[]) if isinstance(x,dict)}
        ledger_rows={x.get('run_id'):x for x in ledger.get('runs',[]) if isinstance(x,dict)}
        rows=results.get('runs',{}) if isinstance(results,dict) else {}
        series=[]
        if isinstance(origins,dict) and isinstance(windows,list) and isinstance(cutoffs,list) and isinstance(rows,dict):
            for sid in rows:
                merged=sid.endswith('_merged')
                base=sid[:-7] if merged else sid
                row=run_rows.get(base); actual=ledger_rows.get(base)
                if row is None or actual is None: continue
                if merged:
                    origin_key='adaptive_extension_merged_series'; parent=actual.get('parent_run_id') or row.get('source_run_id')
                    if parent not in ledger_rows: continue
                    ids=[parent,base]
                else:
                    if row.get('stage') not in ('pilot','confirmation') and actual.get('stage') not in ('pilot','confirmation'): continue
                    origin_key='pilot_and_confirmation'; ids=[base]
                interval=origins.get(origin_key); maxlag=limits.get(origin_key)
                if not (isinstance(interval,list) and len(interval)==2 and isinstance(maxlag,(int,float))): continue
                series.append({'series_id':sid,'run_ids':ids,'origins_ps':list(interval),
                               'maximum_lag_ps':float(maxlag),'windows_ps':windows,
                               'vacf_cutoffs_ps':cutoffs,'merge_segments':merged})
        if series: pre['series']=series
    if not isinstance(pre.get('claim_rules'),list) and isinstance(ap.get('claim_rules'),dict):
        view['_claim_rule_semantic_review']=True
    # Preserve the raw object separately for all canonical-hash checks.
    return view


def _build_decisions_namespace():
    """Versioned deterministic decision rules; no language-model adjudication.

    The numerical cutoffs describe this automatic contract. They do not certify
    equilibrium, physical diffusion, or a calibrated confidence interval.
    """
    import hashlib
    import json
    import math
    from pathlib import Path
    from datetime import datetime

    import numpy as np


    ACTION_RULES = {
        'extend': ('long_lag_support', 'finite_window_bias', 'compare_frozen_adjacent_windows'),
        'fresh_seed': ('velocity_seed_spread', 'shared_geometry_bias', 'report_descriptive_seed_ranges'),
        'new_temperature': ('temperature_support', 'non_diffusive_endpoint_bias', 'establish_endpoint_regime_first'),
        'control': ('estimator_sensitivity', 'confounded_control_change', 'same_source_and_frozen_estimator'),
    }
    ACTION_PREDICTIONS = {
        'extend': ('late_window_alpha', 'increase_lag_support'),
        'fresh_seed': ('seed_D_range', 'resolve_seed_spread'),
        'new_temperature': ('arrhenius_temperature_support', 'increase_temperature_support'),
        'control': ('estimator_sensitivity', 'resolve_control_difference'),
    }


    def _canonical_hash(obj):
        return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()


    def adjacent_relative_spread(values):
        return max((abs(a-b)/max(abs(a),abs(b),1e-30)
                    for a,b in zip(values,values[1:])), default=0.0) if values else None

    def frozen_plan_hash(plan):
        plan = plan.get('_raw_plan_for_hash', plan)
        contract = plan['automatic_decision_contract']
        pre = json.loads(json.dumps(contract['precommit']))
        pre.pop('frozen_plan_sha256', None)
        return _canonical_hash({'precommit': pre, 'alternatives': contract['alternatives'],
                                'selection_rule_id': contract['selection_rule_id']})

    def classify_route(pilot_flags, group_flags, claim_statuses, selected_action, selection_rule):
        """Only the complete legacy all-triggered extension outcome is automatic."""
        registered = selection_rule == 'extend_if_any_pilot_window_unstable_else_fresh_seed'
        automatic = (registered and bool(pilot_flags) and all(pilot_flags)
                     and bool(group_flags) and all(group_flags)
                     and all(status == 'inconclusive' for status in claim_statuses)
                     and selected_action == 'extend')
        return 'automatic_inconclusive' if automatic else 'REVIEW_REQUIRED'


    def evaluate(app, policy, plan, trace, decision, ledger, results, numeric, scheduler_obj,
                 historical_equivalence=None, historical_pilot_arrays=None):
        errors = []
        diagnostics = {}
        if isinstance(decision,dict):
            decision=json.loads(json.dumps(decision))
            for claim in decision.get('claims',{}).values():
                if isinstance(claim,dict) and 'reason_code' not in claim and claim.get('reason_id') in {
                    'activation_energy_not_identifiable_without_common_diffusive_regime',
                    'finite_window_diagnostics_triggered_all_pilot_and_confirmation_groups',
                    'descriptive_two_endpoint_trend_not_a_converged_transport_claim'}:
                    claim['reason_code']={'activation_energy_not_identifiable_without_common_diffusive_regime':'activation_energy_not_identified',
                        'finite_window_diagnostics_triggered_all_pilot_and_confirmation_groups':'finite_window_nonidentifiable',
                        'descriptive_two_endpoint_trend_not_a_converged_transport_claim':'temperature_trend_not_identified'}[claim['reason_id']]
            nxt=decision.get('next_action')
            if isinstance(nxt,dict) and 'competing_hypotheses' not in nxt and isinstance(nxt.get('hypotheses'),list):
                supported=str(nxt.get('supported_trigger_rule','')).lower()
                if 'finite-window' in supported and 'non-identifiability' in supported and 'physical d/ea' in supported:
                    nxt['competing_hypotheses']=[{'hypothesis_id':h.get('hypothesis_id'),
                        'observable_id':h.get('observable_id'),'predicted_direction':h.get('expected_direction'),
                        'trigger_rule_id':'finite_window_nonidentifiable'} for h in nxt['hypotheses']]
        runs = ledger['runs']
        completed = [r for r in runs if r['status'] == 'complete']
        temperatures = sorted({float(r['T_K']) for r in completed})
        diagnostics['global__temperature_count'] = len(temperatures)
        diagnostics['global__velocity_initializations'] = len({(r['T_K'], r['seed']) for r in completed})
        cfg = policy['decision_numeric_policy']
        contract = plan.get('automatic_decision_contract')
        pre = contract.get('precommit', {}) if isinstance(contract, dict) else {}
        series = pre.get('series', []) if isinstance(pre, dict) else []
        if not series:
            return {'errors': ['No execution-bound machine decision contract: cannot automatically adjudicate free text.'],
                    'diagnostics': diagnostics}
        if pre.get('method_id') != policy['estimators']['method']:
            errors.append('Precommitted estimator method differs from the implemented method.')
        exclusion = pre.get('fixed_exclusion_ps')
        if type(exclusion) not in (int, float) or not math.isfinite(exclusion) or exclusion < 0:
            errors.append('Invalid fixed exclusion interval.')
            exclusion = 0
        # The contract is hashed without its self-reference; native drivers must
        # capture this exact value at execution, independently of final decisions.
        frozen = frozen_plan_hash(plan)
        if pre.get('frozen_plan_sha256') != frozen:
            errors.append('Frozen machine-plan digest does not match its actual content.')
        coverage = set()
        group_ids = []
        triggered = []
        pilot_triggered = []
        pilot_covered = set()
        pilot_ids = {r['run_id'] for r in completed if r['stage'] == 'pilot'}
        by_run = {r['run_id']: r for r in completed}
        phase_estimates = {}
        with np.load(Path(app) / 'msd-vacf.npz', allow_pickle=False) as archive:
            arrays = {}
            for name in archive.files:
                sep='::' if '::' in name else '__' if '__' in name else None
                if sep is None: continue
                parts=name.split(sep)
                if len(parts)!=3: continue
                sid,sp,field=parts
                if field in ('msd_lags_ps','lag_ps'): field='lag_ps'
                key=f'{sid}__{sp}__{field}'
                if key in arrays: errors.append(f'{key}: duplicate serialized aliases')
                arrays[key]=archive[name]
        if historical_pilot_arrays:
            for name, values in historical_pilot_arrays.items():
                if name in arrays:
                    errors.append(f'{name}: historical pilot overlay duplicates a candidate array')
                arrays[name] = values
        if arrays:
            for spec in series:
                sid = spec.get('series_id')
                constituents = spec.get('run_ids', [])
                coverage.update(constituents)
                pilot_only = len(constituents) == 1 and constituents[0] in pilot_ids
                if pilot_only:
                    pilot_covered.add(constituents[0])
                origins = spec.get('origins_ps', [])
                if len(origins) != 2 or float(origins[0]) < exclusion:
                    errors.append(f'{sid}: origins violate the frozen exclusion.')
                windows = spec.get('windows_ps', [])
                if len(windows) < 2 or len({tuple(w) for w in windows}) != len(windows):
                    errors.append(f'{sid}: at least two distinct frozen windows are required.')
                for species in policy['system']['species_counts']:
                    prefix = f'{sid}__{species}__'
                    t, m = arrays[prefix + 'lag_ps'], arrays[prefix + 'msd_A2']
                    fitted = []
                    for lo, hi in windows:
                        use = (t >= lo - 1e-9) & (t <= hi + 1e-9)
                        if lo <= 0 or hi <= lo or use.sum() < 3:
                            errors.append(f'{prefix}: invalid frozen window {lo}, {hi}.')
                            continue
                        x, y = t[use], m[use]
                        slope = float(np.dot(x-x.mean(), y-y.mean()) / np.dot(x-x.mean(), x-x.mean()))
                        alpha = float(math.log(y[-1]/y[0])/math.log(x[-1]/x[0])) if y[0] > 0 and y[-1] > 0 else None
                        fitted.append({'lag_ps': [lo, hi], 'D_m2_s': slope/6*1e-8, 'alpha': alpha})
                    ds = [w['D_m2_s'] for w in fitted]
                    spread = adjacent_relative_spread(ds)
                    nonidentifiable = bool(fitted) and (
                        any(w['alpha'] is None or abs(w['alpha']-1) > cfg['alpha_deviation_from_one'] for w in fitted)
                        or any(d <= 0 for d in ds)
                        or spread > cfg['window_D_relative_spread'])
                    did = prefix + 'window_comparison'
                    diagnostics[did] = {'windows': fitted, 'relative_D_spread': spread,
                                        'finite_window_nonidentifiable': nonidentifiable}
                    group_ids.append(did)
                    triggered.append(nonidentifiable)
                    if pilot_only:
                        pilot_triggered.append(nonidentifiable)
                    if len(constituents) == 1:
                        run = by_run[constituents[0]]
                        if run['stage'] in ('pilot', 'confirmation'):
                            for w in fitted:
                                label = (float(run['T_K']), species, tuple(w['lag_ps']))
                                phase_estimates.setdefault(label, {'pilot': [], 'confirmation': []})[run['stage']].append(w['D_m2_s'])
        contrasts = []
        for (temperature, species, window), phases in sorted(phase_estimates.items()):
            if not phases['pilot'] or not phases['confirmation']:
                continue
            pilot_mean = float(np.mean(phases['pilot']))
            contrasts.append({'T_K': temperature, 'species': species, 'window_ps': list(window),
                              'pilot_initializations': len(phases['pilot']),
                              'confirmation_initializations': len(phases['confirmation']),
                              'pilot_D_range_m2_s': [min(phases['pilot']), max(phases['pilot'])],
                              'confirmation_D_range_m2_s': [min(phases['confirmation']), max(phases['confirmation'])],
                              'confirmation_minus_pilot_mean_D_m2_s': [d-pilot_mean for d in phases['confirmation']],
                              'scope': 'descriptive velocity-seed contrast; not a population confidence interval'})
        diagnostics['global__pilot_confirmation_contrasts'] = contrasts
        if not contrasts:
            errors.append('No matching frozen windows permit pilot/fresh-confirmation numerical contrasts.')
        if coverage != {r['run_id'] for r in completed}:
            errors.append('Frozen series omit completed native segments or include unknown runs.')
        if pilot_covered != pilot_ids:
            errors.append('Every pilot needs a separate frozen-window diagnostic; merged followup data cannot choose the action.')
        selection_rule = contract.get('selection_rule_id')
        if selection_rule not in policy['decision_contract']['selection_rules']:
            errors.append('Unsupported or unregistered pilot adaptation selection rule.')
        if not pilot_triggered:
            errors.append('Pilot-only numeric data do not cover any frozen series/species group.')
        all_pilot_triggered = bool(pilot_triggered) and all(pilot_triggered)
        mixed_pilot = bool(pilot_triggered) and any(pilot_triggered) and not all_pilot_triggered
        finite_window_failure = bool(triggered) and any(triggered)
        all_groups_triggered = bool(triggered) and all(triggered)
        if isinstance(decision.get('claims'),dict):
            for claim in decision['claims'].values():
                if not isinstance(claim,dict): continue
                mapped=[]
                for diagnostic_id in claim.get('diagnostic_ids',[]):
                    parts=str(diagnostic_id).split(':')
                    if len(parts)==4 and parts[0]=='diag' and parts[3]=='finite_window_triggered':
                        target=f'{parts[1]}__{parts[2]}__window_comparison'
                        mapped.append(target if target in diagnostics else diagnostic_id)
                    else: mapped.append(diagnostic_id)
                claim['diagnostic_ids']=mapped
        diagnostics['global__finite_window_classification'] = {
            'scope': 'at least one listed group fails its frozen-window rule; this does not mean every group fails',
            'all_pilot_groups_triggered': all_pilot_triggered,
            'mixed_pilot_groups': mixed_pilot,
            'all_completed_groups_triggered': all_groups_triggered,
            'triggered_group_ids': [gid for gid, flag in zip(group_ids, triggered) if flag],
            'stable_group_ids': [gid for gid, flag in zip(group_ids, triggered) if not flag],
        }
        rules = {
            'finite_window_nonidentifiable': finite_window_failure,
            'temperature_trend_not_identified': finite_window_failure,
            'activation_energy_not_identified': finite_window_failure or len(temperatures) < 3,
        }
        claim_rule = {
            'diffusive_regime': 'finite_window_nonidentifiable',
            'temperature_trend': 'temperature_trend_not_identified',
            'activation_energy': 'activation_energy_not_identified',
        }
        allowed_statuses = set(policy['decision_contract']['claim_statuses'])
        for cid, required_rule in claim_rule.items():
            row = decision.get('claims', {}).get(cid, {})
            status = row.get('status')
            if status not in allowed_statuses:
                errors.append(f'{cid}: claim status is outside the registered review schema.')
            elif status in ('supported', 'contradicted'):
                if row.get('reason_code') not in policy['decision_contract']['review_candidate_rule_ids']:
                    errors.append(f'{cid}: physical conclusion lacks the registered review-candidate reason code.')
            elif row.get('reason_code') != required_rule:
                errors.append(f'{cid}: unknown or mismatched deterministic reason code.')
            elif not rules[required_rule]:
                review_claim = True
            ids = row.get('diagnostic_ids', [])
            if not ids or any(x not in diagnostics for x in ids):
                errors.append(f'{cid}: diagnostic IDs must reference actual evaluated diagnostics.')
            if cid in ('diffusive_regime', 'temperature_trend') and not set(group_ids).issubset(ids):
                errors.append(f'{cid}: must report every sampled series/species window comparison.')
        rep = results.get('replication', {})
        if (rep.get('confidence_intervals') is not None or
                rep.get('molecules_and_time_origins_are_not_replicates') is not True or
                rep.get('shared_starting_coordinates') is not True):
            errors.append('This scope requires descriptive velocity-seed comparisons and explicit shared geometry; no calibrated CI.')
        observed = {str(int(t)): len({r['seed'] for r in completed if float(r['T_K']) == t}) for t in temperatures}
        if rep.get('initializations_per_temperature') != observed:
            errors.append('Reported initialization counts differ from actual unique temperature/velocity seeds.')
        jobs = {j['run_id']: j for j in scheduler_obj['jobs']}
        pilots = [r for r in completed if r['stage'] == 'pilot']
        adapted = [r for r in completed if r['stage'] == 'adaptive']
        confirmed = [r for r in completed if r['stage'] == 'confirmation']
        stamp = lambda rid, field: datetime.fromisoformat(jobs[rid][field].replace('Z', '+00:00'))
        if not pilots or not adapted or not confirmed:
            errors.append('Pilot, implemented adaptation and fresh confirmation are all required.')
        else:
            if max(stamp(r['run_id'], 'ended_at') for r in pilots) > min(stamp(r['run_id'], 'submitted_at') for r in adapted):
                errors.append('Adaptation was submitted before pilot observations completed.')
            if max(stamp(r['run_id'], 'ended_at') for r in adapted) > min(stamp(r['run_id'], 'submitted_at') for r in confirmed):
                errors.append('Confirmation was submitted before adapted observations completed.')
        historical_native = None
        if isinstance(historical_equivalence, dict):
            bindings = historical_equivalence.get('native_runtime_sha256_by_run')
            if (historical_equivalence.get('schema') == 'case04-native-plan-source-equivalence/v1'
                    and historical_equivalence.get('frozen_plan_sha256') == frozen
                    and isinstance(bindings, dict)):
                historical_native = bindings
        for r in completed:
            trajectory_ref=r.get('native_artifacts',{}).get('trajectory',{}).get('path','')
            native_path = Path(app) / PurePosixPath(trajectory_ref).parent / 'native-runtime.json'
            native = json.loads(native_path.read_text())
            if native.get('automatic_plan_sha256') != frozen:
                manifest_path=native_path.parent/'input-manifest.json'
                manifest=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
                source_plan=('execution/precommit/plan.pre-pilot.json' if r.get('stage')=='pilot'
                             else 'execution/shared/plan.post-pilot.json')
                frozen_path=Path(app)/source_plan
                verified_binding=(manifest.get('runtime_plan_sha256')==native.get('plan_sha256')
                    and frozen_path.is_file() and hashlib.sha256(frozen_path.read_bytes()).hexdigest()==native.get('plan_sha256'))
                if not verified_binding and (historical_native is None or historical_native.get(r['run_id']) != hashlib.sha256(native_path.read_bytes()).hexdigest()):
                    errors.append(f"{r['run_id']}: native execution lacks the frozen automatic-plan binding.")
        alternatives = contract.get('alternatives', [])
        for alt in alternatives:
            _action_check(alt, policy, errors, 'alternative')
        chosen = next((a for a in alternatives if a.get('alternative_id') == contract.get('chosen_alternative_id')), None)
        if chosen:
            action_kind = chosen.get('action_kind')
            should_extend = any(pilot_triggered)
            expected_action = 'extend' if should_extend else 'fresh_seed'
            if action_kind != expected_action:
                errors.append('Chosen action does not follow the frozen pilot-driven selector.')
            for r in adapted:
                trajectory_ref=r.get('native_artifacts',{}).get('trajectory',{}).get('path','')
                native_path=Path(app)/PurePosixPath(trajectory_ref).parent/'native-runtime.json'
                native = json.loads(native_path.read_text())
                expected_native_kind = 'continuation' if action_kind == 'extend' else 'fresh'
                actual_kind=native.get('kind',native.get('start_kind'))
                if actual_kind != expected_native_kind:
                    errors.append('Chosen pilot-driven action does not match its native execution kind.')
            implemented_cost = sum(r['executed_steps'] for r in adapted + confirmed)
            if chosen.get('cost_steps') != implemented_cost:
                errors.append('Chosen allocation cost differs from actual adaptive plus confirmation work.')
            if set(chosen.get('target_temperatures_K', [])) != {r['T_K'] for r in adapted + confirmed}:
                errors.append('Chosen allocation targets differ from actual followup temperatures.')
        nxt = decision.get('next_action', {})
        _action_check(nxt, policy, errors, 'next_action')
        # Under the implemented nonidentifiable finite-lag rule, longer endpoint
        # lag support tests two specific rival explanations; no optimality claim.
        expected_next_action = 'extend' if any(pilot_triggered) else 'fresh_seed'
        expected_observable = 'late_window_alpha' if expected_next_action == 'extend' else 'seed_D_range'
        if nxt.get('action_kind') != expected_next_action or nxt.get('observable_id') != expected_observable:
            errors.append('Next action does not follow the frozen pilot-only action rule.')
        hyps = nxt.get('competing_hypotheses', [])
        if (len(hyps)!=2 or len({h.get('hypothesis_id') for h in hyps})!=2
                or len({h.get('predicted_direction') for h in hyps})!=2
                or not all(h.get('predicted_direction') in policy['decision_contract']['hypothesis_directions'] for h in hyps)):
            errors.append('Next action needs two distinct, opposed scientific predictions.')
        if any(h.get('observable_id') != expected_observable for h in hyps):
            errors.append('Competing hypotheses do not reference the selected bottleneck observable.')
        if expected_next_action == 'extend' and any(h.get('trigger_rule_id') != 'finite_window_nonidentifiable' for h in hyps):
            errors.append('Extension hypotheses do not reference the finite-window trigger rule.')
        if expected_next_action == 'fresh_seed' and any(h.get('trigger_rule_id') != 'velocity_seed_spread_unresolved' for h in hyps):
            errors.append('Fresh-seed hypotheses do not reference the registered seed-spread question.')
        route = classify_route(pilot_triggered, triggered,
                               [decision.get('claims', {}).get(cid, {}).get('status') for cid in claim_rule],
                               chosen.get('action_kind') if chosen else None, selection_rule)
        if plan.get('_claim_rule_semantic_review'):
            diagnostics['global__claim_rule_review_reason']='frozen natural-language claim rules are preserved but not forced into unequal private enumerations'
            route='REVIEW_REQUIRED'
        if route == 'REVIEW_REQUIRED':
            diagnostics['global__adjudication_route'] = 'REVIEW_REQUIRED'
        else:
            diagnostics['global__adjudication_route'] = 'automatic_inconclusive'
        return {'errors': errors, 'diagnostics': diagnostics,
                'review_required': route == 'REVIEW_REQUIRED'}


    def _action_check(action, policy, errors, label):
        kind = action.get('action_kind')
        if kind not in ACTION_RULES:
            errors.append(f'{label}: unsupported action kind.')
            return
        targets = action.get('target_temperatures_K', [])
        if (not targets or len(set(targets)) != len(targets) or
                not set(targets).issubset(policy['budgets']['allowed_temperatures_K'])):
            errors.append(f'{label}: invalid target temperatures.')
        duration, steps, dt = action.get('duration_ps'), action.get('cost_steps'), action.get('dt_fs', .5)
        if (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0 or
                type(steps) is not int or steps <= 0 or type(dt) not in (int, float) or
                not math.isfinite(dt) or not 0 < dt <= policy['budgets']['max_dt_fs'] or
                not math.isclose(steps*dt/1000, duration, rel_tol=1e-9, abs_tol=1e-9)):
            errors.append(f'{label}: total MD cost, duration and timestep disagree.')
        info, risk, mitigation = ACTION_RULES[kind]
        if label == 'alternative' and (action.get('information_target'), action.get('bias_risk'), action.get('mitigation')) != (info, risk, mitigation):
            errors.append(f'{label}: action information/risk/mitigation codes are not the defined tradeoff.')
        if label == 'alternative' and (action.get('observable_id'), action.get('predicted_direction')) != ACTION_PREDICTIONS[kind]:
            errors.append(f'{label}: prediction does not match the action observable and information target.')
    return SimpleNamespace(evaluate=evaluate, classify_route=classify_route, adjacent_relative_spread=adjacent_relative_spread)

def _build_budget_namespace(budget_numeric_refs):
    """Deterministic budget/trace checks. Native execution and scientific judgement remain manual."""
    import hashlib
    import json
    import math
    import re
    import numpy as np
    from pathlib import Path, PurePosixPath

    def pilot_evidence_valid(submission, row):
        if not isinstance(row,dict): return False
        refs=[]; inline=False; value=row.get('pilot_evidence')
        if row.get('pilot_evidence_path') is not None or row.get('pilot_evidence_sha256') is not None:
            refs.append((row.get('pilot_evidence_path'),row.get('pilot_evidence_sha256')))
        if isinstance(value,dict):
            if 'path' in value or 'sha256' in value: refs.append((value.get('path'),value.get('sha256')))
            else: inline=bool(value)
        elif isinstance(value,(list,str)): inline=bool(value)
        elif value is not None: return False
        if not refs: return inline
        for raw,digest in refs:
            rel=PurePosixPath(str(raw or ''))
            if rel.is_absolute() or not rel.parts or '..' in rel.parts or '\\' in str(raw): return False
            path=Path(submission).joinpath(*rel.parts); current=Path(submission)
            for part in rel.parts:
                current=current/part
                if current.is_symlink(): return False
            if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)
                    or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest): return False
        return True

    def diagnose(submission, protocol):
        numeric_refs=budget_numeric_refs
        checks=[]
        def check(name, ok, detail=''):
            checks.append({'check':name,'passed':bool(ok),'detail':detail})
        for name in ['plan.json','topology.json','results.json']:
            obj=json.loads((submission/name).read_text())
            check('L1.parse.'+name,isinstance(obj,dict) and bool(obj))
        series='msd-vacf.npz' if protocol['case_id']=='reline-04-diffusion' else 'correlations.npz'
        with np.load(submission/series,allow_pickle=False) as data:
            check('L1.finite_series',bool(data.files) and all(data[k].size>0 and (not np.issubdtype(data[k].dtype,np.number) or np.isfinite(data[k]).all()) for k in data.files))
        policy=protocol['budget_policy']
        ledger=json.loads((submission/'run-ledger.json').read_text())
        runs=ledger['runs']
        if not isinstance(runs,list) or not runs:raise ValueError('nonempty runs required')
        ids=[r['run_id'] for r in runs]
        check('L1.unique_run_ids',len(ids)==len(set(ids)))
        charged_steps=0;charged_ps=0;complete=[]
        for r in runs:
            requested=r['requested_steps'];executed=r.get('executed_steps');dt=r['dt_fs']
            if isinstance(requested,bool) or not isinstance(requested,int) or requested<=0:raise ValueError('requested_steps must be positive integer')
            if not isinstance(dt,(int,float)) or isinstance(dt,bool) or not math.isfinite(dt) or not 0<dt<=.5:raise ValueError('finite 0<dt_fs<=0.5 required')
            if r['status'] not in ['complete','failed','unknown']:raise ValueError('invalid attempt status')
            if executed is not None and (isinstance(executed,bool) or not isinstance(executed,int) or not 0<=executed<=requested):raise ValueError('invalid executed_steps')
            # Unknown or failed attempts consume their entire declared reservation;
            # this deliberately prevents releasing quota on an unauditable attempt.
            charged=requested if r['status']!='complete' else executed
            if charged is None:raise ValueError('complete runs require executed_steps')
            charged_steps+=charged;charged_ps+=charged*dt/1000
            if r['status']=='complete':
                complete.append(r)
                paths=r['native_artifacts']
                required=['input','log','trajectory','restart']
                check('L2.native_manifest.'+r['run_id'],all(k in paths for k in required))
                for kind in required:
                    if kind not in paths:continue
                    item=paths[kind];p=Path(item['path']);target=submission/p
                    safe=not p.is_absolute() and '..' not in p.parts and p.parts and p.parts[0]=='execution'
                    good=safe and target.is_file() and not target.is_symlink() and target.stat().st_size>0
                    if good:good=hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']
                    check('L2.native_hash.'+r['run_id']+'.'+kind,good)
        check('L3.total_step_budget',charged_steps<=policy['max_md_steps'],str(charged_steps))
        check('L3.total_time_budget',charged_ps<=policy['max_aggregate_ps']+1e-9,str(charged_ps))
        check('L3.single_gpu_per_run',all(isinstance(r.get('gpu_count'),int) and not isinstance(r['gpu_count'],bool) and 0<=r['gpu_count']<=1 for r in runs))
        check('L3.reported_budget',math.isclose(float(ledger['charged_ps']),charged_ps,rel_tol=numeric_refs['reported_time_rtol'],abs_tol=numeric_refs['reported_time_atol_ps']) and ledger['charged_steps']==charged_steps)
        duration=lambda r:r['executed_steps']*r['dt_fs']/1000
        pilot=[r for r in complete if r['stage']=='pilot']
        confirm=[r for r in complete if r['stage']=='confirmation']
        adaptive=[r for r in complete if r['stage']=='adaptive']
        check('L3.confirmation_unique_seed',len({(float(r['T_K']),int(r['seed'])) for r in confirm})==len(confirm))
        check('L3.actual_adaptive_tranche',bool(adaptive) and sum(map(duration,adaptive))>=policy['minimum_adaptive_ps'])
        check('L3.actual_confirmation',len(confirm)>=policy['minimum_confirmation_runs'] and all(duration(r)>=policy['minimum_confirmation_run_ps'] for r in confirm))
        keys=lambda rs:{(float(r['T_K']),int(r['seed'])) for r in rs}
        check('L3.confirmation_fresh_seed',not (keys(confirm)&keys([r for r in complete if r['stage']!='confirmation'])))
        check('L3.pilot_distinct_seed',len(keys(pilot))==len(pilot))
        if protocol['case_id']=='reline-04-diffusion':
            check('L3.pilot_coverage',all(sum(float(r['T_K'])==t and duration(r)>=policy['pilot_run_ps'] for r in pilot)>=policy['pilot_min_runs_per_temperature'] for t in policy['pilot_temperatures_K']))
        else:
            check('L3.pilot_coverage',len(pilot)>=policy['pilot_min_runs_per_temperature'] and all(float(r['T_K'])==363 and duration(r)>=policy['pilot_run_ps'] for r in pilot))
            pairs=[r for r in complete if r['stage']=='intervention']
            check('L3.controlled_intervention',len(pairs)>=2 and all(duration(r)>=policy['minimum_control_run_ps'] for r in pairs) and len({r['control_setting'] for r in pairs})>=2 and len({r['parent_checkpoint_sha256'] for r in pairs})==1 and all(len(r['parent_checkpoint_sha256'])==64 for r in pairs))
            check('L3.fixed_temperature',all(float(r['T_K'])==363 for r in complete))
        check('L3.allowed_temperature',all(float(r['T_K']) in policy['temperatures_K'] for r in complete))
        probes=ledger.get('author_probe_frame_ids',[])
        check('L3.ensemble_probe_budget',isinstance(probes,list) and len(probes)<=policy['max_author_ensemble_probe_frames'])
        decision=json.loads((submission/'decision.json').read_text())
        claims=decision['claims']
        check('L1.core_claims',set(policy['required_claim_ids']).issubset(claims))
        for cid in policy['required_claim_ids']:
            row=claims.get(cid,{})
            check('L3.reasoned_claim.'+cid,row.get('status') in ['supported','contradicted','inconclusive'] and bool(row.get('scope')) and bool(row.get('evidence')) and bool(row.get('reason')))
        trace_obj=json.loads((submission/'decision-trace.json').read_text())
        trace=trace_obj.get('decisions',[]) if isinstance(trace_obj,dict) else trace_obj
        def has_pilot_evidence(row):
            return pilot_evidence_valid(submission,row)
        check('L3.explicit_tradeoff',bool(trace) and all(len(x.get('alternatives',[]))>=2 and x.get('chosen') and has_pilot_evidence(x) and x.get('prediction') and x.get('followup_run_ids') and set(x['followup_run_ids']).issubset(set(ids)) for x in trace))
        check('L3.next_action',bool(decision.get('next_action')) and bool(decision.get('expected_information_gain')))
        return checks
    return SimpleNamespace(diagnose=diagnose)

def _build_scorer_namespace(trajectory, scheduler, decisions, budget_checks, numeric_refs):
    """Deterministic Case04 hard gates plus an explicitly bound scientific review."""
    import argparse, csv, hashlib, json, math, os, re, sys
    from datetime import datetime
    from pathlib import Path, PurePosixPath

    import numpy as np
    AUTO_DIR=HERE/'automatic'  # DATA ONLY: automatic/policy.json and trusted scheduler evidence.
    topology, parse_dump, merge, correlations = trajectory.topology, trajectory.parse_dump, trajectory.merge, trajectory.correlations
    candidate_scheduler = scheduler
    SCHEMA = "case04-automatic-scoring-policy/v1"
    NUMERIC_REFS=numeric_refs

    def sha(path: Path) -> str:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()

    def canonical_hash(obj) -> str:
        return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

    def reject_symlink_path(path: Path):
        cur=Path(path.anchor)
        for part in path.parts[1:]:
            cur=cur/part
            if cur.is_symlink(): raise ValueError(f'path contains symlink: {cur}')

    def safe_json(path: Path):
        reject_symlink_path(path)
        if not path.is_file(): raise ValueError(f"missing JSON: {path.name}")
        return json.loads(path.read_text(encoding='utf-8'))

    def safe_app_execution_path(app: Path, value: str, label: str) -> Path:
        rel=PurePosixPath(str(value))
        if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='execution':
            raise ValueError(f'{label}: path must be a safe execution/ relative path')
        path=app.joinpath(*rel.parts); reject_symlink_path(path)
        return path

    def pilot_evidence_refs(item):
        """Return direct/nested references and distinguish them from inline evidence."""
        refs=[]; inline=False; malformed=False
        if not isinstance(item,dict): return refs,inline,True
        direct_path=item.get('pilot_evidence_path'); direct_sha=item.get('pilot_evidence_sha256')
        if direct_path is not None or direct_sha is not None:
            refs.append((direct_path,direct_sha,'pilot evidence'))
        value=item.get('pilot_evidence')
        if isinstance(value,dict):
            if 'path' in value or 'sha256' in value:
                refs.append((value.get('path'),value.get('sha256'),'pilot evidence'))
            else:
                inline=bool(value)
        elif isinstance(value,(list,str)):
            inline=bool(value)
        elif value is not None:
            malformed=True
        return refs,inline,malformed

    def validate_pilot_evidence(app: Path, item):
        refs,inline,malformed=pilot_evidence_refs(item)
        if malformed or (not refs and not inline): return False
        for raw,digest,label in refs:
            try:
                rel=PurePosixPath(str(raw or ''))
                if rel.is_absolute() or not rel.parts or '..' in rel.parts or '\\' in str(raw): return False
                path=app.joinpath(*rel.parts); reject_symlink_path(path)
                if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)
                        or not path.is_file() or sha(path)!=digest): return False
            except (OSError,ValueError,TypeError): return False
        return True

    def audit_native_model_identity(app: Path, run_dir: Path, cfg: dict, runtime: dict,
                                    log_text: str, ledger_run: dict, plan: dict):
        """Bind positive-step DeepMD selections to supplied model bytes when evidence allows."""
        supplied_dir=app/'inputs'/'models'
        supplied={}
        if supplied_dir.is_dir():
            for candidate in supplied_dir.iterdir():
                if candidate.is_file() and not candidate.is_symlink():
                    supplied[sha(candidate)]=candidate.relative_to(app).as_posix()
        if not supplied:
            return {'status':'unresolved','reason':'supplied model files are unavailable for hash binding',
                    'positive_loop_models':[],'probe_diagnostics':[],'review_required':True}

        manifest_hashes={}
        def add_manifest_hash(name,digest):
            manifest_hashes.setdefault(str(name),set()).add(digest.lower())
        manifest_path=None
        manifest_rel=cfg.get('input_manifest')
        if manifest_rel:
            try:
                manifest_path=safe_app_execution_path(app,manifest_rel,'model input manifest')
                expected=cfg.get('input_manifest_sha256')
                if not manifest_path.is_file() or not expected or sha(manifest_path)!=expected:
                    manifest_path=None
                else:
                    manifest=safe_json(manifest_path)
                    entries=manifest.get('files',manifest.get('inputs',{}))
                    if isinstance(entries,dict):
                        for name,value in entries.items():
                            digest=value.get('sha256') if isinstance(value,dict) else value
                            if isinstance(digest,str) and re.fullmatch(r'[0-9a-fA-F]{64}',digest):
                                add_manifest_hash(name,digest)
                    declared=manifest.get('source_hashes',{})
                    if isinstance(declared,dict):
                        for group in ('files','models'):
                            group_entries=declared.get(group,{})
                            if isinstance(group_entries,dict):
                                for name,digest in group_entries.items():
                                    if isinstance(digest,str) and re.fullmatch(r'[0-9a-fA-F]{64}',digest): add_manifest_hash(name,digest)
                        for name in ('runner_sha256','batch_script_sha256'):
                            digest=manifest.get(name)
                            if isinstance(digest,str) and re.fullmatch(r'[0-9a-fA-F]{64}',digest): add_manifest_hash(name,digest)
            except (OSError,ValueError,KeyError,TypeError):
                manifest_path=None
        runtime_hashes=runtime.get('source_hashes') or runtime.get('input_sha256',{})
        if not isinstance(runtime_hashes,dict): runtime_hashes={}
        for name,digest in runtime_hashes.items():
            if isinstance(digest,dict): digest=digest.get('sha256')
            if isinstance(digest,str) and re.fullmatch(r'[0-9a-fA-F]{64}',digest):
                add_manifest_hash(name,digest)

        def model_operands(text):
            rows=[]
            for line in text.splitlines():
                line=line.split('#',1)[0].strip()
                m=re.match(r'^(?:\s*|.*?\s)pair_style\s+deepmd\s+(.+)$',line,re.I)
                if not m: continue
                operands=[]
                for token in m.group(1).split():
                    if token.lower() in {'out_freq','atomic','fparam','aparam','relative','model_devi','compress','type_map','sel','atomic_virial'}:
                        break
                    operands.append(token.strip('"\''))
                if operands: rows.append(operands)
            return rows

        def identity_for(token):
            token=str(token).strip().strip('"\'')
            path=Path(token)
            app_root=app.resolve()
            simple_basename=(not path.is_absolute() and '/' not in token and '\\' not in token
                             and '..' not in path.parts)
            candidates=[]
            if path.is_absolute():
                candidates.append(path)
            else:
                candidates.extend((run_dir/path,app/path,run_dir/'inputs'/path))
            for candidate in candidates:
                try:
                    lexical=candidate.absolute()
                    try: rel=lexical.relative_to(app.absolute())
                    except ValueError: rel=None
                    if rel is not None:
                        cursor=app.absolute()
                        if cursor.is_symlink() or any((cursor:=cursor/part).is_symlink() for part in rel.parts):
                            return None,{'basis':'symlink_model_operand','path':token,'external':True}
                    resolved=candidate.resolve(strict=True)
                    if resolved.is_relative_to(app_root) and resolved.is_file():
                        digest=sha(resolved)
                        if digest in supplied: return digest,{'basis':'delivered_file_hash','path':resolved.relative_to(app_root).as_posix()}
                        return digest,{'basis':'delivered_file_hash','path':resolved.relative_to(app_root).as_posix(),'external':True}
                except (OSError,RuntimeError,ValueError):
                    pass
            keyed=[]
            exact=[(name,digest) for name,digests in manifest_hashes.items()
                   if name in {token,Path(token).as_posix()} for digest in digests]
            if exact:
                exact_hashes={digest for _,digest in exact}
                if len(exact_hashes)>1:
                    return None,{'basis':'conflicting_exact_hash_sources','path':token,
                                 'candidate_sha256':sorted(exact_hashes),'hash_conflict':True}
                keyed=exact
            elif simple_basename:
                keyed=[(name,digest) for name,digests in manifest_hashes.items()
                       if name==Path(token).name or Path(name).name==Path(token).name
                       for digest in digests]
            unique={digest for _,digest in keyed}
            if len(unique)==1:
                digest=next(iter(unique))
                return digest,{'basis':'hashed_input_manifest_or_native_source_hash',
                               'paths':[name for name,value in keyed if value==digest]}
            if len(unique)>1:
                return None,{'basis':'ambiguous_manifest_basename','path':token,
                             'candidate_sha256':sorted(unique)}
            # Only a pathless canonical supplied filename can identify the
            # public model without a copied byte or exact-path manifest hash.
            canonical=[(digest,name) for digest,name in supplied.items() if Path(name).name==Path(token).name]
            if simple_basename and len(canonical)==1:
                return canonical[0][0],{'basis':'canonical_supplied_model_path','path':canonical[0][1]}
            if path.is_absolute():
                return None,{'basis':'unresolved_absolute_model_operand','path':token}
            return None,{'basis':'unresolved_model_operand','path':token}

        # A positive Loop is attributed to the most recently active pair_style.
        # This deliberately ignores zero-step force probes when identifying production.
        active=None; selections=[]; loops=[]
        event=re.compile(r'^\s*(pair_style\s+deepmd\s+.+|Loop time of\s+[0-9.eE+-]+.*?for\s+(\d+)\s+steps)',re.I)
        for line_no,line in enumerate(log_text.splitlines(),1):
            m=event.search(line)
            if not m: continue
            if m.group(1).lower().startswith('pair_style'):
                parsed=model_operands(line)
                active=parsed[-1] if parsed else None
            else:
                nsteps=int(m.group(2)); loops.append({'steps':nsteps,'line':line_no})
                if nsteps>0:
                    if not active:
                        selections.append({'steps':nsteps,'line':line_no,'status':'unresolved','models':[]})
                    else:
                        models=[]; status='verified'
                        for token in active:
                            digest,evidence=identity_for(token)
                            row={'operand':token,'sha256':digest,'evidence':evidence}
                            models.append(row)
                            if evidence.get('external') or evidence.get('hash_conflict') or (digest and digest not in supplied): status='conflict'
                            elif digest is None and status!='conflict': status='unresolved'
                        selections.append({'steps':nsteps,'line':line_no,'status':status,'models':models})

        # Require selection consistency across all actual positive-step loops.
        known=[tuple(sorted(row['sha256'] for row in block['models'] if row.get('sha256'))) for block in selections]
        if len(set(known))>1 and all(block['status']=='verified' for block in selections):
            return {'status':'conflict','reason':'production model selection changed across positive-step runs',
                    'positive_loop_models':selections,'probe_diagnostics':[],'review_required':False}
        if any(block['status']=='conflict' for block in selections):
            return {'status':'conflict','reason':'positive-step model operand is not bound to supplied model bytes',
                    'positive_loop_models':selections,'probe_diagnostics':[],'review_required':False}

        # Compare the production choice with any model-bearing frozen driver/config/plan
        # references already present. No new candidate field is required.
        frozen_sources=[]
        for key in ('driver','input','native_input','lammps_input','input_file'):
            value=cfg.get(key)
            if isinstance(value,str) and value:
                try:
                    rel=PurePosixPath(value)
                    if not rel.is_absolute() and '..' not in rel.parts:
                        src=app.joinpath(*rel.parts)
                        reject_symlink_path(src)
                        if src.is_file() and not src.is_symlink():
                            src_hash=sha(src)
                            hash_bound=src_hash in {digest for values in manifest_hashes.values() for digest in values}
                            frozen_sources.append((value,src.read_text(errors='replace'),src_hash,hash_bound))
                except (OSError,ValueError): pass
        frozen_refs=[]; frozen_source_model_bindings=[]; frozen_unknown=False
        for source_name,text,source_sha,source_bound in frozen_sources:
            for row in model_operands(text):
                row_hashes=[]
                for token in row:
                    digest,evidence=identity_for(token)
                    if evidence.get('external') or evidence.get('hash_conflict'):
                        return {'status':'conflict','reason':'frozen input selects an external model path/hash or conflicting exact hashes',
                                'positive_loop_models':selections,'frozen_model_refs':frozen_refs,
                                'probe_diagnostics':[],'review_required':False}
                    if digest is None:
                        frozen_unknown=True
                    row_hashes.append(digest)
                    frozen_refs.append((source_name,token,digest))
                frozen_source_model_bindings.append({'path':source_name,'sha256':source_sha,
                    'manifest_bound':source_bound,'model_hashes':row_hashes})
        def visit_model_refs(value,key='',model_context=False):
            if isinstance(value,dict):
                for child_key,child in value.items():
                    lowered=str(child_key).lower()
                    excluded=any(x in lowered for x in ('available','public','supplied','author_models','all_model','candidate_models'))
                    selected_context=model_context or ('model' in lowered and not excluded)
                    if isinstance(child,(dict,list)) or selected_context:
                        visit_model_refs(child,str(child_key),selected_context)
            elif isinstance(value,list):
                for child in value: visit_model_refs(child,key,model_context)
            elif isinstance(value,str) and model_context:
                digest=value.lower() if re.fullmatch(r'[0-9a-fA-F]{64}',value) else identity_for(value)[0]
                if digest: frozen_refs.append((key,value,digest))
        visit_model_refs(cfg.get('frozen_config',{}))
        visit_model_refs(plan)
        selected={digest for row in selections for digest in (m.get('sha256') for m in row['models']) if digest}
        frozen_hashes={digest for _,_,digest in frozen_refs if digest in supplied}
        if any(digest and digest not in supplied for _,_,digest in frozen_refs):
            return {'status':'conflict','reason':'frozen model identity points outside supplied model hashes',
                    'positive_loop_models':selections,'frozen_model_refs':frozen_refs,
                    'probe_diagnostics':[],'review_required':False}
        if frozen_hashes and selected and frozen_hashes!=selected:
            return {'status':'conflict','reason':'native positive-step model hashes conflict with frozen model identity',
                    'positive_loop_models':selections,'frozen_model_refs':frozen_refs,
                    'probe_diagnostics':[],'review_required':False}

        probe_diagnostics=[]; review_required=any(row['status']!='verified' for row in selections) or frozen_unknown
        compatibility=runtime.get('model_compatibility',[])
        if compatibility is None: compatibility=[]
        if not isinstance(compatibility,list):
            return {'status':'conflict','reason':'model_compatibility is malformed',
                    'positive_loop_models':selections,'probe_diagnostics':[],'review_required':False}
        charged=int(ledger_run.get('executed_steps',0))
        probe_step_total=0
        for index,probe in enumerate(compatibility):
            if not isinstance(probe,dict):
                review_required=True;probe_diagnostics.append({'index':index,'status':'unresolved','reason':'malformed optional probe'});continue
            digest=probe.get('sha256',probe.get('model_sha256',probe.get('source_sha256')))
            digest=digest.lower() if isinstance(digest,str) else None
            probe_path=probe.get('path',probe.get('model_path'))
            if digest is None and isinstance(probe_path,str):
                digest,path_evidence=identity_for(probe_path)
                if path_evidence.get('external') or path_evidence.get('hash_conflict') or (digest and digest not in supplied):
                    return {'status':'conflict','reason':'optional model probe resolves to an external model hash',
                            'positive_loop_models':selections,'probe_diagnostics':probe_diagnostics,'review_required':False}
            steps=probe.get('md_steps',0)
            if isinstance(steps,bool) or not isinstance(steps,int) or steps<0 or steps>charged:
                return {'status':'conflict','reason':'optional model probe has invalid or unaccounted MD steps',
                        'positive_loop_models':selections,'probe_diagnostics':probe_diagnostics,'review_required':False}
            probe_step_total+=steps
            finite=probe.get('forces_finite')
            probe_status=str(probe.get('status','')).strip().lower()
            probe_failed=(probe.get('success') is False or probe_status in {'failed','error','incompatible'}
                          or finite is False)
            if digest and digest not in supplied:
                return {'status':'conflict','reason':'optional model probe names an external model hash',
                        'positive_loop_models':selections,'probe_diagnostics':probe_diagnostics,'review_required':False}
            if digest is None:
                review_required=True;probe_diagnostics.append({'index':index,'status':'unresolved','md_steps':steps})
            elif finite is not True or probe_failed:
                review_required=True;probe_diagnostics.append({'index':index,'status':'probe_failed','sha256':digest,'md_steps':steps})
                if digest in selected:
                    return {'status':'conflict','reason':'production model is reported to have nonfinite compatibility forces',
                            'positive_loop_models':selections,'probe_diagnostics':probe_diagnostics,'review_required':False}
            else:
                probe_diagnostics.append({'index':index,'status':'verified','sha256':digest,'md_steps':steps})
        if probe_step_total>charged:
            return {'status':'conflict','reason':'model compatibility probe MD steps exceed ledger-charged execution',
                    'positive_loop_models':selections,'probe_diagnostics':probe_diagnostics,'review_required':False}
        frozen_source_bound=any(row['manifest_bound'] and row['model_hashes']
                                for row in frozen_source_model_bindings)
        unresolved=(not selections or any(row['status']!='verified' for row in selections)
                    or not selected or not frozen_hashes and not frozen_source_bound)
        review_required=review_required or unresolved
        status='verified' if not review_required else 'unresolved'
        return {'status':status,'positive_loop_models':selections,'frozen_model_refs':frozen_refs,
                'frozen_driver_sources':[{'path':name,'sha256':digest,'manifest_bound':bound}
                                         for name,_,digest,bound in frozen_sources],
                'frozen_source_model_bindings':frozen_source_model_bindings,
                'model_compatibility_probes':probe_diagnostics,
                'review_required':review_required,
                'reason':'production model identity is hash-bound to supplied inputs' if status=='verified'
                         else 'model identity/frozen selection evidence is incomplete; independent scientific review required'}

    def outputs_manifest(app: Path, expected: list[str]):
        rows=[]
        for name in expected:
            rel=name.rstrip('/')
            p=app/rel
            reject_symlink_path(p)
            if p.is_symlink() or not p.exists(): raise ValueError(f"missing or symlink output: {name}")
            paths=[p] if p.is_file() else sorted(x for x in p.rglob('*') if x.is_file())
            if not paths or any(x.is_symlink() for x in paths): raise ValueError(f"empty output or symlink: {name}")
            for x in paths:
                q=x.relative_to(app).as_posix()
                if '..' in PurePosixPath(q).parts: raise ValueError("output escapes APP")
                rows.append({'path':q,'sha256':sha(x),'size':x.stat().st_size})
        rows.sort(key=lambda x:x['path'])
        trace_path=app/'decision-trace.json'
        if trace_path.is_file() and not trace_path.is_symlink():
            trace=safe_json(trace_path)
            decisions=trace.get('decisions',[]) if isinstance(trace,dict) else []
            for item in decisions if isinstance(decisions,list) else []:
                if not isinstance(item,dict): continue
                refs=[]
                pilot_refs,_,pilot_malformed=pilot_evidence_refs(item)
                if pilot_malformed: raise ValueError('malformed inline pilot evidence')
                refs.extend(pilot_refs)
                pre=item.get('precommit')
                if isinstance(pre,dict) and (pre.get('path') is not None or pre.get('sha256') is not None):
                    refs.append((pre.get('path'),pre.get('sha256'),'precommit'))
                for raw,digest,label in refs:
                    rel=PurePosixPath(str(raw or ''))
                    if rel.is_absolute() or not rel.parts or '..' in rel.parts or '\\' in str(raw):
                        raise ValueError(f'unsafe decision trace evidence path: {label}')
                    path=app.joinpath(*rel.parts); reject_symlink_path(path)
                    if not path.is_file() or not re.fullmatch(r'[0-9a-f]{64}',str(digest or '')) or sha(path)!=digest:
                        raise ValueError(f'decision trace evidence path/hash mismatch: {label}')
                    q=rel.as_posix(); record={'path':q,'sha256':digest,'size':path.stat().st_size}
                    existing=next((x for x in rows if x['path']==q),None)
                    if existing is not None and existing['sha256']!=digest:
                        raise ValueError(f'decision evidence conflicts with output manifest: {q}')
                    if existing is None: rows.append(record)
        rows.sort(key=lambda x:x['path'])
        if len({x['path'] for x in rows})!=len(rows): raise ValueError("duplicate output path")
        return rows

    def review_output_manifest(native_manifest):
        """Match the shared review runner's path/SHA manifest schema exactly."""
        return [{'path': row['path'], 'sha256': row['sha256']} for row in native_manifest]

    def validate_review(app: Path, tests: Path, protocol: dict, manifest: list[dict[str, str]]):
        """Apply only an explicit, submission-bound scientific review."""
        review_path = tests / 'scientific-review.json'
        if review_path.is_symlink(): raise ValueError('trusted scientific review is a symlink')
        if not review_path.exists():
            return 'REVIEW_REQUIRED', {'reason': 'No trusted submission-specific scientific review is recorded.'}
        if not review_path.is_file(): raise ValueError('trusted scientific review is not a regular file')
        review = safe_json(review_path)
        if not isinstance(review, dict) or review.get('schema') != 'scientific-review/v1':
            raise ValueError('trusted scientific review schema mismatch')
        if review.get('case_id') != protocol.get('case_id'):
            raise ValueError('trusted scientific review case_id mismatch')
        if review.get('protocol_sha256') != sha(tests / 'assessment-protocol.json'):
            raise ValueError('trusted scientific review protocol hash mismatch')
        manifest_sha = canonical_hash(manifest)
        if review.get('submission_manifest_sha256') != manifest_sha:
            raise ValueError('trusted scientific review submission manifest mismatch')
        necessary = {c.get('criterion') for c in protocol.get('criteria', [])
                     if isinstance(c, dict) and c.get('necessary') is True}
        if not necessary or None in necessary:
            raise ValueError('trusted protocol has no valid necessary review criteria')
        rows = review.get('criteria')
        if not isinstance(rows, list): raise ValueError('trusted review criteria must be an array')
        seen = set()
        manifest_rows = {row['path']: row['sha256'] for row in manifest}
        for row in rows:
            if not isinstance(row, dict): raise ValueError('trusted review criterion must be an object')
            name = row.get('criterion')
            if not isinstance(name, str) or name not in necessary or name in seen:
                raise ValueError(f'unknown or repeated review criterion: {name!r}')
            seen.add(name)
            if row.get('verdict') not in {'PASS', 'FAIL'}:
                raise ValueError(f'invalid review verdict for {name}')
            if not isinstance(row.get('reviewer'), str) or not row['reviewer'].strip():
                raise ValueError(f'missing reviewer identity for {name}')
            if not isinstance(row.get('reason'), str) or not row['reason'].strip():
                raise ValueError(f'review reason missing for {name}')
            evidence = row.get('evidence')
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f'missing evidence references for {name}')
            for item in evidence:
                if not isinstance(item, dict): raise ValueError(f'malformed evidence reference for {name}')
                rel = PurePosixPath(str(item.get('path', '')))
                if rel.is_absolute() or '..' in rel.parts or not rel.parts:
                    raise ValueError(f'evidence path escapes APP for {name}')
                path = app.joinpath(*rel.parts)
                reject_symlink_path(path)
                if (rel.as_posix() not in manifest_rows or not path.is_file() or path.is_symlink()
                        or sha(path) != item.get('sha256') or manifest_rows[rel.as_posix()] != item.get('sha256')):
                    raise ValueError(f'evidence hash mismatch: {rel.as_posix()}')
        if seen != necessary:
            raise ValueError(f'trusted review has missing criteria: {sorted(necessary - seen)}')
        verdicts = {row['verdict'] for row in rows}
        decision = 'FAIL' if 'FAIL' in verdicts else 'PASS'
        return decision, {'reviewer': review.get('reviewer', 'criterion-level reviewers'),
                          'protocol_sha256': review['protocol_sha256'],
                          'submission_manifest_sha256': manifest_sha, 'criteria': rows}

    def score_outcome(hard_gate_failed: bool, review_required: bool, review_status: str | None = None):
        """Keep pending review rewardless and never let review bypass hard failures."""
        if hard_gate_failed:
            return 'FAIL', 0
        if not review_required:
            return 'PASS', 1
        if review_status is None or review_status == 'REVIEW_REQUIRED':
            return 'REVIEW_REQUIRED', None
        if review_status not in {'PASS', 'FAIL'}:
            raise ValueError('invalid terminal scientific review status')
        return review_status, 1 if review_status == 'PASS' else 0

    def check_trusted_references(app: Path, tests: Path, answer_mode='oracle'):
        refs=safe_json(tests/'reference-hashes.json')
        if not isinstance(refs,dict) or not refs: raise ValueError("reference-hashes.json must be a nonempty object")
        bad=[]
        for name,want in refs.items():
            if name.startswith('tests/'):
                rel=PurePosixPath(name[6:]); root=tests
            elif name.startswith('inputs/'):
                rel=PurePosixPath(name); root=app
            else: raise ValueError(f"unsupported reference path {name}")
            if rel.is_absolute() or '..' in rel.parts: raise ValueError(f"unsafe reference path {name}")
            p=root.joinpath(*rel.parts)
            reject_symlink_path(p)
            if p.is_symlink() or not p.is_file() or sha(p)!=want: bad.append(name)
        if bad: raise RuntimeError("trusted evaluator/public assets corrupted: "+", ".join(bad))
        return refs

    def validate_public_policy(app: Path, policy: dict, protocol: dict):
        budget=protocol.get('budget_policy',{})
        b=policy.get('budgets',{})
        s=policy.get('system',{})
        for key,source in [('max_md_steps','max_md_steps'),('max_ps','max_aggregate_ps'),('max_dt_fs','max_dt_fs')]:
            if float(b.get(key,-1))!=float(budget.get(source,-2)): raise RuntimeError(f'automatic policy/public budget mismatch: {key}')
        if s.get('atoms')!=budget.get('atoms') or b.get('atoms',s.get('atoms'))!=budget.get('atoms'): raise RuntimeError('automatic policy atom count differs from public budget')
        if sorted(b.get('allowed_temperatures_K',[]))!=sorted(budget.get('temperatures_K',[])): raise RuntimeError('automatic policy temperature grid differs from public budget')
        if b.get('pilot_temperatures_K')!=budget.get('pilot_temperatures_K') or b.get('minimum_pilot_runs_per_temperature')!=budget.get('pilot_min_runs_per_temperature'): raise RuntimeError('automatic policy pilot requirements differ from public budget')
        if b.get('minimum_pilot_ps_each')!=budget.get('pilot_run_ps') or b.get('minimum_confirmation_runs')!=budget.get('minimum_confirmation_runs') or b.get('minimum_confirmation_ps_each')!=budget.get('minimum_confirmation_run_ps'): raise RuntimeError('automatic policy minimum-work requirements differ from public budget')
        if b.get('max_gpus_per_run')!=budget.get('max_gpus_per_run'): raise RuntimeError('automatic policy GPU cap differs from public budget')
        spec=safe_json(app/'inputs'/'system-spec.json')
        composition=spec.get('composition',{})
        if composition.get('atoms')!=s.get('atoms'): raise RuntimeError('automatic policy/system-spec atom count mismatch')
        if policy.get('test_only') is True:
            expected_mols=composition.get('species_counts')
            if not isinstance(expected_mols,dict) or not expected_mols: raise RuntimeError('test fixture composition requires explicit species counts')
        else:
            if set(s.get('species_counts',{}))!={'choline','chloride','urea'}: raise RuntimeError('production policy species inventory mismatch')
            expected_mols={'choline':composition.get('choline_chloride_pairs'),'chloride':composition.get('choline_chloride_pairs'),'urea':composition.get('urea_molecules')}
        if s.get('species_counts')!=expected_mols: raise RuntimeError('automatic policy molecular counts differ from public system specification')

    def parse_time(v):
        if not isinstance(v,str): raise ValueError('scheduler timestamps must be strings')
        s=v.replace('Z','+00:00')
        t=datetime.fromisoformat(s)
        if t.tzinfo is None: raise ValueError('scheduler timestamps require timezone')
        return t

    def verify_frozen_gpu_request(app: Path, run: dict):
        """Verify visible one-GPU runtime plus the exact hashed one-GPU Slurm request."""
        rid=run['run_id']
        traj_ref=run.get('native_artifacts',{}).get('trajectory',{}).get('path','')
        traj_path=safe_app_execution_path(app,traj_ref,f'{rid} trajectory')
        run_dir=traj_path.parent
        if run_dir != app/'execution'/rid: raise ValueError(f'{rid}: trajectory path does not establish its native run directory')
        nr=run_dir/'native-runtime.json'; manifest_path=run_dir/'input-manifest.json'
        for path,label in ((nr,'native runtime'),(manifest_path,'native input manifest')):
            reject_symlink_path(path)
            if not path.is_file(): raise ValueError(f'{rid}: {label} is missing')
        native=safe_json(nr); cfg=safe_json(manifest_path)
        devices=native.get('gpu_devices'); visible=str(native.get('cuda_visible_devices','')).strip()
        if not isinstance(devices,list) or len(devices)!=1 or not re.fullmatch(r'\d+',visible):
            raise ValueError(f'{rid}: one numeric CUDA-visible device was not recorded by the native run')
        wrapper=safe_app_execution_path(app,'execution/shared/run.sbatch',f'{rid} frozen Slurm wrapper')
        wrapper_rel=wrapper.relative_to(app); manifest_rel=manifest_path.relative_to(app)
        if not wrapper.is_file(): raise ValueError(f'{rid}: frozen Slurm wrapper is missing')
        expected=cfg.get('batch_script_sha256')
        if not expected or expected!=sha(wrapper): raise ValueError(f'{rid}: Slurm wrapper bytes differ from the native input manifest')
        if native.get('plan_sha256')!=cfg.get('runtime_plan_sha256'):
            raise ValueError(f'{rid}: native runtime and input manifest frozen-plan hashes differ')
        script=wrapper.read_text(errors='replace')
        gres=re.findall(r'^\s*#SBATCH\s+--gres\s*=\s*([^\s#]+)\s*$',script,re.M)
        gpus=re.findall(r'^\s*#SBATCH\s+--gpus(?:-per-node|-per-task)?\s*=\s*([^\s#]+)\s*$',script,re.M)
        if not ((len(gres)==1 and re.fullmatch(r'gpu(?::[A-Za-z0-9_.-]+)?:1',gres[0],re.I) and not gpus) or (gpus==['1'] and not gres)):
            raise ValueError(f'{rid}: frozen Slurm wrapper does not request exactly one GPU')
        return {'basis':'native_visible_gpu_and_frozen_single_gpu_request',
                'visible_device_count':len(devices),'cuda_visible_devices':visible,
                'wrapper_path':wrapper_rel.as_posix(),'wrapper_sha256':sha(wrapper),
                'input_manifest_path':manifest_rel.as_posix(),'input_manifest_sha256':sha(manifest_path),
                'native_runtime_path':nr.relative_to(app).as_posix(),'native_runtime_sha256':sha(nr)}

    def scheduler_gate(app: Path, tests: Path, policy: dict, manifest: list, runs: list, *, candidate_schedule=None):
        cfg=policy['trusted_scheduler_evidence']
        if candidate_schedule is None:
            p=tests/'automatic'/cfg['filename']
            obj=safe_json(p)
        else:
            if not isinstance(candidate_schedule,candidate_scheduler.CandidateSchedule):
                raise TypeError('candidate scheduler must come from candidate_scheduler.validate')
            obj={'schema':cfg['schema'],'origin':candidate_schedule.origin,
                 'submission_manifest_sha256':candidate_schedule.manifest_sha256,
                 'jobs':candidate_schedule.jobs}
        for k in cfg['required_top_fields']:
            if k not in obj: raise ValueError(f"scheduler evidence missing {k}")
        if obj['schema']!=cfg['schema']: raise ValueError('scheduler evidence schema mismatch')
        if candidate_schedule is None:
            allowed=cfg['production_origins']
            if policy.get('test_only') is True: allowed=cfg.get('test_only_origins',[])
            if obj['origin'] not in allowed: raise ValueError('scheduler evidence is not from trusted production acquisition')
        elif obj['origin']!='candidate-submitted-crosschecked':
            raise ValueError('candidate scheduler origin mismatch')
        mhash=canonical_hash(manifest)
        if obj['submission_manifest_sha256']!=mhash: raise ValueError('scheduler evidence does not bind this complete APP manifest')
        jobs=obj['jobs']
        if not isinstance(jobs,list): raise ValueError('scheduler jobs must be a list')
        byid={}
        gpu_basis={}; gpu_candidate_errors=[]
        for j in jobs:
            if not isinstance(j,dict) or any(k not in j for k in cfg['required_job_fields']): raise ValueError('malformed scheduler job record')
            rid=j['run_id']
            if not isinstance(rid,str) or rid in byid: raise ValueError('duplicate or invalid scheduler run id')
            byid[rid]=j
            if not re.fullmatch(r'[0-9]+(?:_[0-9]+)?',str(j['job_id'])): raise ValueError('invalid Slurm job id')
            ts=[parse_time(j[k]) for k in ('submitted_at','started_at','ended_at')]
            if not ts[0]<=ts[1]<=ts[2]: raise ValueError(f"invalid Slurm chronology for {rid}")
            if j['state'] not in ('COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY'): raise ValueError('unrecognized terminal Slurm state')
            if isinstance(j['exit_code'],bool) or not isinstance(j['exit_code'],int): raise ValueError('Slurm exit_code must be integer')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',str(j['partition'])): gpu_candidate_errors.append(f'{rid}: invalid scheduler partition')
            if not isinstance(j['allocation_tres'],str): raise ValueError('raw Slurm AllocTRES must be preserved as a string')
            recorded=j['gpu_allocation_recorded']; count=j['gpu_count']
            if type(recorded) is not bool: raise ValueError('gpu_allocation_recorded must be a boolean')
            if recorded:
                if isinstance(count,bool) or not isinstance(count,int) or count<0: raise ValueError('recorded Slurm GPU count must be a nonnegative integer')
                if count>policy['budgets']['max_gpus_per_run']: gpu_candidate_errors.append(f'{rid}: actual Slurm GPU allocation exceeds the per-run cap')
                tres_gpu=re.search(r'(?:^|,)gres/gpu(?::[^=,]+)?=(\d+)(?:,|$)',j['allocation_tres'])
                if not tres_gpu or int(tres_gpu.group(1))!=count: raise ValueError('Slurm GPU count disagrees with raw AllocTRES')
            elif count is not None:
                raise ValueError('unrecorded Slurm GPU allocation must use gpu_count=null')
            elif re.search(r'(?:^|,)gres/gpu(?::[^=,]+)?=\d+(?:,|$)',j['allocation_tres']):
                raise ValueError('AllocTRES reports a GPU but evidence marks it unrecorded')
        ids={r.get('run_id') for r in runs}
        if ids!=set(byid): raise ValueError('trusted scheduler run coverage differs from ledger attempts')
        for r in runs:
            j=byid[r['run_id']]
            if str(r.get('job_id'))!=str(j['job_id']): raise ValueError(f"job id mismatch for {r['run_id']}")
            good=r.get('status')=='complete'
            if good != (j['state']=='COMPLETED' and j['exit_code']==0): raise ValueError(f"scheduler/native terminal status disagreement for {r['run_id']}")
            if good:
                if r.get('gpu_count') == 0:
                    if j['resources'].get('gpus') != 0 or (j['gpu_allocation_recorded'] and j['gpu_count'] != 0):
                        gpu_candidate_errors.append(f"{r['run_id']}: CPU run and scheduler GPU allocation disagree")
                    gpu_basis[r['run_id']]={'basis':'cpu_execution_and_zero_gpu_request','gpu_count':0,'partition':j['partition']}
                elif j['gpu_allocation_recorded']:
                    if j['gpu_count']!=1: gpu_candidate_errors.append(f"{r['run_id']}: completed run does not have exactly one scheduler-recorded GPU")
                    gpu_basis[r['run_id']]={'basis':'slurm_gpu_allocation_recorded','gpu_count':j['gpu_count'],'scheduler_recorded_gpu_count':j['gpu_count'],'gpu_allocation_recorded':True,'partition':j['partition']}
                else:
                    try:
                        gpu_basis[r['run_id']]=verify_frozen_gpu_request(app,r)
                        gpu_basis[r['run_id']]['partition']=j['partition']
                        gpu_basis[r['run_id']]['scheduler_recorded_gpu_count']=None
                        gpu_basis[r['run_id']]['gpu_allocation_recorded']=False
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        msg=f"{r['run_id']}: one-GPU runtime/request proof failed: {exc}"
                        gpu_candidate_errors.append(msg)
                        gpu_basis[r['run_id']]={'basis':'unverified','partition':j['partition'],'error':msg}
        if candidate_schedule is not None:
            gpu_basis=candidate_schedule.gpu_basis
            gpu_candidate_errors.extend(candidate_schedule.gpu_errors)
        return {'manifest_sha256':mhash,'job_count':len(jobs),'origin':obj['origin'],'jobs':jobs,
                'gpu_evidence_basis':gpu_basis,'gpu_candidate_errors':gpu_candidate_errors,
                'runtime_bound':False if candidate_schedule is not None else None,
                'candidate_receipt_sha256':candidate_schedule.receipt_sha256 if candidate_schedule is not None else None,
                'attempt_id':candidate_schedule.attempt_id if candidate_schedule is not None else None}

    def budget_gate(ledger: dict, policy: dict):
        errors=[]; runs=ledger.get('runs')
        if not isinstance(runs,list) or not runs: return ['run ledger must include actual attempts']
        ids=[r.get('run_id') for r in runs]
        if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)): errors.append('run IDs must be unique nonempty strings')
        b=policy['budgets']; charged_steps=0; charged_ps=0.0; completed=[]; stage_durations={}
        for r in runs:
            if r.get('status') not in ('complete','failed','unknown'): errors.append(f"{r.get('run_id')}: invalid attempt status"); continue
            req=r.get('requested_steps'); dt=r.get('dt_fs')
            if type(req) is not int or req<=0 or type(dt) not in (int,float) or not math.isfinite(dt) or not 0<dt<=b['max_dt_fs']:
                errors.append(f"{r.get('run_id')}: invalid step reservation or timestep"); continue
            actual=r.get('executed_steps')
            if r['status']=='complete':
                if type(actual) is not int or not 0<actual<=req: errors.append(f"{r['run_id']}: complete attempt has invalid executed steps"); continue
                cost=actual; completed.append(r); dur=actual*dt/1000
                stage_durations[r.get('stage')]=stage_durations.get(r.get('stage'),0)+dur
            else:
                if actual not in (None,0): errors.append(f"{r['run_id']}: failed/unknown attempt has nonzero claimed executed steps")
                cost=req; dur=cost*dt/1000
            charged_steps+=cost; charged_ps+=dur
            if float(r.get('T_K',float('nan'))) not in set(map(float,b['allowed_temperatures_K'])): errors.append(f"{r['run_id']}: temperature outside public budget grid")
            if type(r.get('gpu_count')) is not int or not 0<=r['gpu_count']<=b['max_gpus_per_run']: errors.append(f"{r['run_id']}: invalid GPU reservation")
        if charged_steps>b['max_md_steps'] or charged_ps>b['max_ps']+1e-12: errors.append('cumulative reservations/executions exceed the public budget')
        if type(ledger.get('charged_steps')) is not int or ledger['charged_steps']!=charged_steps: errors.append('ledger charged_steps omits or misstates an attempt reservation')
        if not math.isclose(float(ledger.get('charged_ps',float('nan'))),charged_ps,rel_tol=1e-9,abs_tol=1e-9): errors.append('ledger charged_ps omits or misstates an attempt reservation')
        pilot=[r for r in completed if r.get('stage')=='pilot']; confirm=[r for r in completed if r.get('stage')=='confirmation']; adaptive=[r for r in completed if r.get('stage')=='adaptive']
        for temp in b['pilot_temperatures_K']:
            selected=[r for r in pilot if float(r['T_K'])==float(temp)]
            if len(selected)<b['minimum_pilot_runs_per_temperature'] or any(r['executed_steps']*r['dt_fs']/1000 < b['minimum_pilot_ps_each']-1e-12 for r in selected): errors.append(f'pilot coverage/minimum duration incomplete at {temp} K')
            if len({r.get('seed') for r in selected})<b['minimum_pilot_runs_per_temperature']: errors.append(f'pilot seeds are not distinct at {temp} K')
        if sum(r['executed_steps']*r['dt_fs']/1000 for r in adaptive)<b['minimum_adaptive_ps']-1e-12: errors.append('actual adaptive tranche is below the required duration')
        if len(confirm)<b['minimum_confirmation_runs'] or any(r['executed_steps']*r['dt_fs']/1000<b['minimum_confirmation_ps_each']-1e-12 for r in confirm): errors.append('fresh confirmation work is incomplete')
        initial={(float(r['T_K']),r.get('seed')) for r in completed if r.get('stage')!='confirmation'}
        confirmed=[(float(r['T_K']),r.get('seed')) for r in confirm]
        if len(set(confirmed))!=len(confirmed) or any(x in initial for x in confirmed): errors.append('confirmation seeds are repeated or not fresh')
        return errors

    def numerical_recompute(app: Path, policy: dict, plan: dict, ledger: dict, results: dict,
                            historical_pilot_reference: Path | None = None,
                            historical_arrays_out: dict | None = None,
                            historical_pilot_ids: set[str] | None = None):
        """Rebuild COM time series from every completed native dump, then compare all arrays."""
        structure=app/'inputs'/'inputs'/'strc.lmp'
        if not structure.is_file(): structure=app/'inputs'/'strc.lmp'
        types, source_box, mols=topology(structure,policy)
        topo=safe_json(app/'topology.json')
        expected_counts={s:sum(m['species']==s for m in mols) for s in sorted({m['species'] for m in mols})}
        public_structure_sha=sha(structure)
        source_obj=topo.get('source',{}) if isinstance(topo.get('source',{}),dict) else {}
        source_hashes=[x for x in (source_obj.get('sha256'),source_obj.get('structure_sha256'),topo.get('source_sha256')) if x is not None]
        if not source_hashes or any(x!=public_structure_sha for x in source_hashes): raise ValueError('topology source hash differs from public structure')
        check_obj=topo.get('checks',{}) if isinstance(topo.get('checks',{}),dict) else {}
        claimed_counts=check_obj.get('observed_species_counts',topo.get('observed_species_counts'))
        if claimed_counts is not None and claimed_counts!=expected_counts: raise ValueError('topology species counts differ from independent periodic graph')
        groups=sorted((m['species'],[int(i)+1 for i in m['ids']]) for m in mols)
        claimed=sorted((m.get('species'),m.get('atom_ids')) for m in topo.get('molecules',[]))
        if groups!=claimed: raise ValueError('topology molecule partition differs from independent periodic graph')
        attempts={r['run_id']:r for r in ledger['runs'] if r.get('status')=='complete'}
        parsed={}; native_cfg={}; native_records={}; model_identity_audits=[]
        for rid,r in attempts.items():
            art=r['native_artifacts']['trajectory']; rel=PurePosixPath(art['path'])
            if rel.is_absolute() or '..' in rel.parts: raise ValueError('unsafe trajectory path')
            path=app.joinpath(*rel.parts)
            run_dir=path.parent
            if run_dir != app/'execution'/rid: raise ValueError(f'{rid}: trajectory path does not establish a canonical native run directory')
            nrpath=run_dir/'native-runtime.json'; manifest_path=run_dir/'input-manifest.json'
            for pth,label in ((nrpath,'native runtime'),(manifest_path,'native input manifest')):
                reject_symlink_path(pth)
                if not pth.is_file(): raise ValueError(f'{rid}: {label} is missing')
            runtime=safe_json(nrpath); input_manifest=safe_json(manifest_path)
            for key in ('run_id','T_K','seed','requested_steps','dt_fs','stage'):
                if input_manifest.get(key)!=r.get(key): raise ValueError(f'{rid}: native input manifest {key} differs from the run ledger')
            input_ref=r.get('native_artifacts',{}).get('input',{})
            input_path=safe_app_execution_path(app,input_ref.get('path',''),f'{rid} native input')
            if not input_path.is_file() or sha(input_path)!=input_ref.get('sha256'):
                raise ValueError(f'{rid}: native input hash mismatch')
            cfg=dict(input_manifest)
            cfg.update({'input_manifest':manifest_path.relative_to(app).as_posix(),
                        'input_manifest_sha256':sha(manifest_path),
                        'input':'/'.join(('execution',rid,input_path.name)),
                        'driver':'execution/shared/run_case.py',
                        'trajectory_stride_steps':plan.get('method',{}).get('trajectory_stride_steps'),
                        'kind':'continuation' if input_manifest.get('start_kind')=='continuation' else 'fresh'})
            frozen_plan_path=('execution/shared/plan.post-pilot.json' if r.get('stage') in ('adaptive','confirmation')
                              else 'execution/precommit/plan.pre-pilot.json')
            if input_manifest.get('runtime_plan_sha256'):
                cfg['frozen_plan']=frozen_plan_path; cfg['frozen_plan_sha256']=input_manifest['runtime_plan_sha256']
            planned=plan.get('planned_runs',{})
            plan_row=planned.get(rid,{}) if isinstance(planned,dict) else next((x for x in planned if isinstance(x,dict) and x.get('run_id')==rid),{})
            cfg['frozen_config']={'run_id':rid,'T_K':input_manifest.get('T_K'),'seed':input_manifest.get('seed'),
                'requested_steps':input_manifest.get('requested_steps'),'dt_fs':input_manifest.get('dt_fs'),
                'kind':cfg['kind'],'source_run':plan_row.get('source_run_id'),
                'source_restart':plan_row.get('source_restart')}
            if input_manifest.get('parent_run_id') not in (None,r.get('parent_run_id')):
                raise ValueError(f'{rid}: input manifest parent differs from ledger')
            if input_manifest.get('run_id')!=rid: raise ValueError(f'{rid}: input manifest run ID mismatch')
            runtime.setdefault('kind','continuation' if runtime.get('start_kind')=='continuation' else 'fresh')
            if runtime.get('job_id') is not None and str(runtime.get('job_id'))!=str(r.get('job_id')): raise ValueError(f'{rid}: runtime job ID differs from ledger')
            if float(runtime.get('T_K',float('nan')))!=float(r.get('T_K',-999)): raise ValueError(f'{rid}: native runtime temperature differs from ledger')
            dt=float(r['dt_fs'])/1000.0
            if runtime.get('status')!='COMPLETE' or runtime.get('run_id')!=rid: raise ValueError(f'{rid}: native runtime status/identity mismatch')
            if cfg.get('run_id')!=rid or float(cfg.get('T_K',-1))!=float(r.get('T_K',-2)): raise ValueError(f'{rid}: run config identity/temperature mismatch')
            is_continuation = runtime.get('kind') == 'continuation'
            declared_seed=r.get('seed')
            got_seed=runtime.get('seed')
            if declared_seed is not None and got_seed!=declared_seed: raise ValueError(f'{rid}: native seed differs from ledger')
            if int(runtime.get('requested_steps',-1))!=int(r.get('requested_steps',-2)) or int(runtime.get('executed_steps',-1))!=int(r.get('executed_steps',-2)): raise ValueError(f'{rid}: native step accounting mismatch')
            if not math.isclose(float(runtime.get('dt_fs',dt)),float(r['dt_fs']),rel_tol=0,abs_tol=1e-12): raise ValueError(f'{rid}: native dt differs from ledger')
            start=runtime.get('initial_step'); end=runtime.get('end_step')
            logtxt=(run_dir/'log.lammps').read_text(errors='replace')
            no_integrator_failures=_positive_run_no_integrator_diagnostics(logtxt)
            if no_integrator_failures:
                raise ValueError(f'{rid}: LAMMPS no-integrator warning is associated with positive or unaccounted run output: {no_integrator_failures}')
            loop_steps=[int(x) for x in re.findall(r'Loop time of .*? for (\d+) steps',logtxt) if int(x)>0]
            if sum(loop_steps)!=int(r.get('executed_steps',0)): raise ValueError(f'{rid}: positive-step LAMMPS log accounting mismatch')
            compat=runtime.get('model_compatibility',[])
            model_audit=audit_native_model_identity(app,run_dir,cfg,runtime,logtxt,r,plan)
            if model_audit.get('status')=='conflict':
                raise ValueError(f'{rid}: native model identity conflict: {model_audit.get("reason")}')
            model_identity_audits.append({'run_id':rid,**model_audit})
            if r.get('gpu_count') == 1:
                gpu=runtime.get('gpu_devices',[])
                if not isinstance(gpu,list) or len(gpu)!=1: raise ValueError(f'{rid}: native GPU device record missing')
                identity=(run_dir/'gpu-identity.csv')
                if not identity.is_file() or identity.stat().st_size==0: raise ValueError(f'{rid}: native GPU identity evidence missing')
                idtxt=identity.read_text(errors='replace')
                if not str(runtime.get('cuda_visible_devices','')).strip() or not any(line.strip() for line in idtxt.splitlines()[1:]): raise ValueError(f'{rid}: GPU device and allocation evidence incomplete')
            elif runtime.get('execution_device') != 'cpu' or runtime.get('gpu_devices') not in ([], None):
                raise ValueError(f'{rid}: CPU execution must record its device and no GPU devices')
            ge=r.get('gpu_evidence',{})
            for name,record in ge.items():
                if not isinstance(record,dict) or not record.get('path') or not record.get('sha256'): raise ValueError(f'{rid}: malformed GPU evidence reference')
                gp=PurePosixPath(record['path'])
                if gp.is_absolute() or '..' in gp.parts: raise ValueError(f'{rid}: unsafe GPU evidence path')
                gp=app.joinpath(*gp.parts)
                if not gp.is_file() or sha(gp)!=record['sha256']: raise ValueError(f'{rid}: GPU evidence hash mismatch: {name}')
            versions=runtime.get('software_versions',{})
            if not all(versions.get(k) for k in ('tensorflow','deepmd-kit','lammps','numpy')): raise ValueError(f'{rid}: native software version evidence incomplete')
            if int(runtime.get('natoms',-1))!=len(types): raise ValueError(f'{rid}: native atom count mismatch')
            exp_stride=cfg.get('trajectory_stride_steps')
            if type(exp_stride) is not int or exp_stride<=0: raise ValueError(f'{rid}: public frozen plan lacks a positive trajectory stride')
            native_cfg[rid]=cfg
            native_records[rid]=runtime
            parsed[rid]=parse_dump(path,types,mols,len(types),dt,{'start_step':start,'end_step':end,'expected_stride_steps':exp_stride})
            if parsed[rid]['steps'][-1]-parsed[rid]['steps'][0] != int(r.get('executed_steps',0)):
                raise ValueError(f'{rid}: trajectory endpoint span does not equal executed steps')
        # Bind continuations to their predeclared source and identical native restart boundary.
        continuation_bounds={}
        for rid,r in attempts.items():
            cfg=native_cfg[rid]; native=native_records[rid]
            if r.get('stage')=='adaptive' and native.get('kind')=='continuation':
                frozen_cfg=cfg.get('frozen_config',{})
                parent_id=(frozen_cfg.get('source_run') or cfg.get('parent_run_id') or r.get('parent_run_id'))
                if not isinstance(parent_id,str) or parent_id not in attempts:
                    raise ValueError(f'{rid}: continuation must name an existing source_run')
                parent=attempts[parent_id]; pn=native_records[parent_id]
                expected_native=PurePosixPath('execution',parent_id,'native-runtime.json')
                expected_restart=PurePosixPath(str(parent.get('native_artifacts',{}).get('restart',{}).get('path','')))
                got_restart=PurePosixPath(str(frozen_cfg.get('source_restart','')))
                plan_source=safe_app_execution_path(app,cfg.get('frozen_plan',''),f'{rid} frozen plan')
                if not plan_source.is_file() or sha(plan_source)!=cfg.get('frozen_plan_sha256'):
                    raise ValueError(f'{rid}: continuation frozen plan hash mismatch')
                plan_obj=safe_json(plan_source)
                planned=plan_obj.get('planned_runs',{})
                plan_row=planned.get(rid) if isinstance(planned,dict) else next((x for x in planned if isinstance(x,dict) and x.get('run_id')==rid),None)
                if not isinstance(plan_row,dict): raise ValueError(f'{rid}: frozen plan does not define this continuation')
                plan_parent=plan_row.get('source_run_id',plan_row.get('source_run'))
                if (plan_parent!=parent_id or plan_row.get('start_kind')!='continuation' or
                    plan_row.get('source_restart')!=got_restart.as_posix()):
                    raise ValueError(f'{rid}: native continuation differs from the frozen public source run/restart')
                if (got_restart.is_absolute() or '..' in got_restart.parts or len(got_restart.parts)!=3 or
                    got_restart.parts[0] not in ('runs','execution') or got_restart.parts[1]!=parent_id or
                    got_restart.parts[2]!='final.restart' or
                    PurePosixPath('execution',parent_id,'final.restart')!=expected_restart):
                    raise ValueError(f'{rid}: continuation restart alias does not resolve to the hashed parent checkpoint')
                if native.get('plan_sha256')!=cfg.get('frozen_plan_sha256'):
                    raise ValueError(f'{rid}: native runtime does not bind the configured continuation plan')
                if (parent_id==rid or parent.get('stage') not in ('pilot','adaptive') or
                    float(parent.get('T_K',-1))!=float(r.get('T_K',-2)) or
                    native.get('kind')!='continuation' or cfg.get('kind')!='continuation' or
                    PurePosixPath('execution',parent_id,'native-runtime.json')!=expected_native or
                    PurePosixPath('execution',parent_id,'final.restart')!=expected_restart or
                    r.get('parent_run_id') not in (None,parent_id)):
                    raise ValueError(f'{rid}: continuation source, temperature, or native kind mismatch')
                parent_end=pn.get('end_step')
                if (type(parent_end) is not int or native.get('initial_step')!=parent_end or
                    parsed[rid]['steps'][0]!=parent_end or
                    int(native.get('end_step',-1))-parent_end!=int(r.get('executed_steps',0))):
                    raise ValueError(f'{rid}: continuation step lineage does not begin at parent endpoint')
                restart_record=parent['native_artifacts']['restart']
                restart_path=safe_app_execution_path(app,restart_record['path'],f'{parent_id} parent restart')
                if (not restart_path.is_file() or sha(restart_path)!=restart_record.get('sha256') or
                    r.get('parent_checkpoint_sha256')!=restart_record.get('sha256')):
                    raise ValueError(f'{rid}: continuation restart differs from the hashed parent checkpoint')
                _, checks=merge(parsed[parent_id],parsed[rid])
                continuation_bounds[f'{parent_id}->{rid}']=checks
            elif r.get('stage')=='adaptive':
                frozen_cfg=cfg.get('frozen_config',{})
                plan_source=safe_app_execution_path(app,cfg.get('frozen_plan',''),f'{rid} frozen plan')
                if (not isinstance(frozen_cfg,dict) or cfg.get('kind')!='fresh' or native.get('kind')!='fresh'
                        or not plan_source.is_file() or sha(plan_source)!=cfg.get('frozen_plan_sha256')):
                    raise ValueError(f'{rid}: fresh adaptive execution is not bound to its frozen plan')
                plan_obj=safe_json(plan_source)
                planned=plan_obj.get('planned_runs',{})
                plan_row=planned.get(rid) if isinstance(planned,dict) else next((x for x in planned if isinstance(x,dict) and x.get('run_id')==rid),None)
                if not isinstance(plan_row,dict): raise ValueError(f'{rid}: frozen plan does not define the fresh adaptive run')
                if plan_row.get('start_kind') not in ('fresh',) and plan_row.get('kind') not in ('fresh','pilot_selected'):
                    raise ValueError(f'{rid}: fresh adaptive run was not allowed by the frozen run plan')
                for key in ('run_id','T_K','seed','requested_steps','dt_fs'):
                    expected = r.get(key) if key in ('requested_steps','dt_fs') else r.get(key)
                    actual = cfg.get(key, frozen_cfg.get(key))
                    if (plan_row.get(key) is not None and plan_row.get(key) != expected) or actual != expected:
                        raise ValueError(f'{rid}: fresh adaptive {key} differs from ledger/frozen plan')
                if any(plan_row.get(key) is not None or cfg.get(key) is not None for key in
                       ('source_run','source_native','source_restart','source_seed','source_start_step')):
                    raise ValueError(f'{rid}: fresh adaptive run unexpectedly references a continuation parent')
                if (native.get('seed') != r.get('seed') or native.get('automatic_plan_sha256') != cfg.get('automatic_plan_sha256')
                        or int(native.get('initial_step', -1)) != 0
                        or int(native.get('end_step', -1)) != int(r.get('executed_steps', 0))):
                    raise ValueError(f'{rid}: fresh adaptive native seed or step range mismatch')
                trajectory.validate_fresh_adaptive_seed(rid, r, attempts)
            elif native.get('kind')=='continuation' or cfg.get('kind')=='continuation':
                raise ValueError(f'{rid}: non-adaptive stage claims native continuation')
        series_specs=[]
        contract=plan.get('automatic_decision_contract',{})
        pre=contract.get('precommit',{}) if isinstance(contract,dict) else {}
        declared=pre.get('series') if isinstance(pre,dict) else None
        if isinstance(declared,list) and declared:
            for x in declared:
                series_specs.append(dict(x))
        else:
            # Legacy candidate fallback keeps numerical verification running while the missing
            # machine contract is separately scored as FAIL.
            for dsid,row in results.get('runs',{}).items():
                series_specs.append({'series_id':dsid,'run_ids':row.get('constituent_run_ids',[]),'origins_ps':row.get('origins_ps'),'maximum_lag_ps':max((float(v.get('maximum_lag_ps',0)) for v in row.get('species',{}).values()),default=0),'windows_ps':sorted({tuple(vv.get('lag_range_ps',[])) for v in row.get('species',{}).values() for vv in v.get('windows',{}).values()}),'vacf_cutoffs_ps':sorted({float(k.removesuffix("ps")) for v in row.get('species',{}).values() for k in v.get('vacf_integrals',{}).keys()}),'merge_segments':len(row.get('constituent_run_ids',[]))>1,'_result':row})
            prefixes=set()
            with np.load(app/'msd-vacf.npz',allow_pickle=False) as z:
                prefixes={k.split('__',1)[0] for k in z.files}
            known={x['series_id'] for x in series_specs}
            sensitivity=results.get('continuation_only_sensitivity',{})
            for sprefix in sorted(prefixes-known):
                digits=''.join(ch for ch in sprefix if ch.isdigit())
                temp=int(digits) if digits else None
                sens=sensitivity.get(str(temp))
                if not isinstance(sens,dict): raise ValueError(f'cannot map analysis series {sprefix} to a declared continuation dataset')
                candidates=[r for r in attempts.values() if float(r.get('T_K'))==temp and r.get('stage')=='adaptive']
                if len(candidates)!=1: raise ValueError(f'continuation series {sprefix} has ambiguous native segment')
                series_specs.append({'series_id':sprefix,'run_ids':[candidates[0]['run_id']],'origins_ps':sens['origins_ps'],'maximum_lag_ps':max(float(v['maximum_lag_ps']) for v in sens['species'].values()),'windows_ps':sorted({tuple(vv['lag_range_ps']) for v in sens['species'].values() for vv in v.get('windows',{}).values()}),'vacf_cutoffs_ps':sorted({float(k.removesuffix("ps")) for v in sens['species'].values() for k in v.get('vacf_integrals',{}).keys()}),'merge_segments':False,'_result':sens})
        expected={}; summaries={}; bounds=dict(continuation_bounds); window_metrics={}
        for spec in series_specs:
            sid=spec['series_id']; ids=spec.get('run_ids')
            if not isinstance(ids,list) or not ids or any(rid not in parsed for rid in ids): raise ValueError(f'{sid}: invalid constituent run list')
            ds=parsed[ids[0]]
            for rid in ids[1:]: ds,bc=merge(ds,parsed[rid]); bounds[f'{ids[0]}->{rid}']=bc
            orig=spec.get('origins_ps'); maxlag=float(spec.get('maximum_lag_ps'))
            if not isinstance(orig,list) or len(orig)!=2 or not all(math.isfinite(float(v)) for v in orig): raise ValueError(f'{sid}: invalid origin interval')
            dt=float(np.median(np.diff(ds['time'])))
            if not math.isclose(maxlag/dt,round(maxlag/dt),rel_tol=0,abs_tol=1e-6): raise ValueError(f'{sid}: lag endpoint is not on the native time grid')
            vals=correlations(ds,mols,[float(orig[0]),float(orig[1])],maxlag,dt)
            for sp,arr in vals.items():
                for field,value in arr.items(): expected[f'{sid}__{sp}__{field}']=value
            row=spec.get('_result')
            if not isinstance(row,dict): row=results.get('runs',{}).get(sid) or results.get('continuation_only_sensitivity',{}).get(str(spec.get('temperature_K','')))
            summaries[sid]=vals
            if not isinstance(row,dict): raise ValueError(f'{sid}: reported summary row missing')
            candidates_t=[]
            for value in (row.get('T_K'),spec.get('T_K'),spec.get('temperature_K')):
                if value is not None: candidates_t.append(float(value))
            if not candidates_t:
                member_t={float(attempts[x]['T_K']) for x in ids}
                if len(member_t)==1: candidates_t=list(member_t)
            if len(set(candidates_t))!=1: raise ValueError(f'{sid}: cannot uniquely derive dataset temperature from its native runs')
            row_temp=candidates_t[0]
            yh_row=results.get('yeh_hummer',{}).get(str(int(row_temp))) if isinstance(results.get('yeh_hummer'),dict) else None
            thermal=app/'inputs'/'thermophysical.csv'
            with thermal.open(newline='') as f: thermal_rows={float(x['T_K']):x for x in csv.DictReader(f)}
            if row_temp not in thermal_rows: raise ValueError(f'{sid}: sampled temperature lacks public thermophysical source data')
            prop=thermal_rows[row_temp]; eta=float(prop['eta_mPa_s'])*1e-3; L=float(prop['L_A'])*1e-10
            kb=1.380649e-23
            yh_delta=2.837297*kb*row_temp/(6*math.pi*eta*L)
            if isinstance(yh_row,dict) and not np.isclose(float(yh_row.get('deltaD_m2_s',float('nan'))),yh_delta,rtol=NUMERIC_REFS['yeh_hummer_rtol'],atol=NUMERIC_REFS['yeh_hummer_atol']):
                raise ValueError(f'{sid}: conditional Yeh-Hummer correction mismatch')
            rep_species=row.get('species',{})
            if not isinstance(rep_species,dict) or set(rep_species)!=set(vals): raise ValueError(f'{sid}: results species set is incomplete or unexpected')
            rep_species={sp:dict(rep) for sp,rep in rep_species.items()}
            for sp,rep in rep_species.items():
                raw_windows=rep.get('windows')
                if isinstance(raw_windows,list):
                    rep['windows']={f'window_{i+1}':{
                        'lag_range_ps':w.get('window_ps'),
                        'MSD_slope_A2_per_ps':float(w.get('D_A2_per_ps',float('nan')))*6.0,
                        'D_MSD_m2_per_s':float(w.get('D_A2_per_ps',float('nan')))*1e-8,
                        '_reported_loglog_regression_slope':w.get('alpha')}
                        for i,w in enumerate(raw_windows) if isinstance(w,dict)}
                raw_vacf=rep.get('vacf_integrals')
                if isinstance(raw_vacf,list):
                    rep['vacf_integrals']={f"{float(w['cutoff_ps']):g}ps":{
                        'D_vacf_A2_per_ps':w.get('D_vacf_A2_per_ps')}
                        for w in raw_vacf if isinstance(w,dict) and w.get('cutoff_ps') is not None}
            declared_windows=spec.get('windows_ps')
            declared_cutoffs=spec.get('vacf_cutoffs_ps')
            for sp,rep in rep_species.items():
                if sp not in vals: raise ValueError(f'{sid}: unknown reported species {sp}')
                arr=vals[sp]; windows=rep.get('windows',{})
                window_ranges=[]
                for w in windows.values():
                    rg=w.get('lag_range_ps')
                    if isinstance(rg,list) and len(rg)==2: window_ranges.append((float(rg[0]),float(rg[1])))
                if declared_windows is not None and sorted(window_ranges)!=sorted(tuple(map(float,w)) for w in declared_windows): raise ValueError(f'{sid}/{sp}: reported windows differ from frozen precommit windows')
                cutoff_values={float(str(x).removesuffix('ps')) for x in rep.get('vacf_integrals',{})}
                if declared_cutoffs is not None and cutoff_values!=set(map(float,declared_cutoffs)): raise ValueError(f'{sid}/{sp}: reported VACF cutoffs differ from frozen precommit')
                if isinstance(rep.get('D_MD_2_4_A2_per_ps'),(int,float)):
                    late=next((w for w in windows.values() if tuple(map(float,w.get('lag_range_ps',[])))==(2.0,4.0)),None)
                    if late is None or not np.isclose(float(rep['D_MD_2_4_A2_per_ps']),float(late['D_MSD_m2_per_s'])/1e-8,rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']/1e-8):
                        raise ValueError(f'{sid}/{sp}: reported [2,4] ps MSD diffusion mismatch')
                    alpha24=rep.get('alpha_2_4')
                    mask24=(arr['lag_ps']>2+1e-9)&(arr['lag_ps']<=4+1e-9)
                    alpha24_native=(float(np.polyfit(np.log(arr['lag_ps'][mask24]),np.log(arr['msd_A2'][mask24]),1)[0])
                                    if np.count_nonzero(mask24)>=3 and np.all(arr['msd_A2'][mask24]>0) else None)
                    if alpha24 is not None and (alpha24_native is None or not np.isclose(float(alpha24),float(alpha24_native),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['endpoint_alpha_atol'])):
                        raise ValueError(f'{sid}/{sp}: reported [2,4] ps log-log regression differs from native MSD')
                reported_spreads=rep.get('adjacent_relative_spreads')
                ordered_ds=[float(w['D_MSD_m2_per_s'])/1e-8 for _,w in sorted(windows.items(),key=lambda item:tuple(map(float,item[1].get('lag_range_ps',[]))))]
                expected_spreads=[abs(a-b)/max(abs(a),abs(b),1e-30) for a,b in zip(ordered_ds,ordered_ds[1:])]
                if reported_spreads is not None and (np.shape(reported_spreads)!=np.shape(expected_spreads) or not np.allclose(reported_spreads,expected_spreads,rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol'])):
                    raise ValueError(f'{sid}/{sp}: adjacent relative-D spread summary differs from native windows')
                if isinstance(rep.get('YH_conditional_correction_A2_per_ps'),(int,float)):
                    if not np.isclose(float(rep['YH_conditional_correction_A2_per_ps']),yh_delta/1e-8,rtol=NUMERIC_REFS['yeh_hummer_rtol'],atol=NUMERIC_REFS['yeh_hummer_atol']/1e-8):
                        raise ValueError(f'{sid}/{sp}: conditional Yeh-Hummer correction differs from public viscosity/box inputs')
                if isinstance(rep.get('D_YH_conditional_A2_per_ps'),(int,float)):
                    md=rep.get('D_MD_2_4_A2_per_ps')
                    if md is None or not np.isclose(float(rep['D_YH_conditional_A2_per_ps']),float(md)+yh_delta/1e-8,rtol=NUMERIC_REFS['yeh_hummer_rtol'],atol=NUMERIC_REFS['yeh_hummer_atol']/1e-8):
                        raise ValueError(f'{sid}/{sp}: conditional Yeh-Hummer diffusion sum mismatch')
                if isinstance(rep.get('n_origins'),int):
                    origins=spec.get('origins_ps')
                    if not isinstance(origins,list) or len(origins)!=2: raise ValueError(f'{sid}/{sp}: cannot verify reported origin count')
                    actual_origins=int(np.count_nonzero((ds['time']>=float(origins[0])-1e-9)&(ds['time']<=float(origins[1])+1e-9)))
                    if rep['n_origins']!=actual_origins: raise ValueError(f'{sid}/{sp}: reported frozen-origin sample count mismatch')
                for name,w in windows.items():
                    rg=w.get('lag_range_ps')
                    if not isinstance(rg,list) or len(rg)!=2: raise ValueError(f'{sid}/{sp}/{name}: malformed window')
                    use=(arr['lag_ps']>=float(rg[0])-1e-9)&(arr['lag_ps']<=float(rg[1])+1e-9)
                    if use.sum()<3: raise ValueError(f'{sid}/{sp}/{name}: too few fit points')
                    slope=float(np.polyfit(arr['lag_ps'][use],arr['msd_A2'][use],1)[0]); d=slope/6*1e-8
                    drift_slope=float(np.polyfit(arr['lag_ps'][use],arr['msd_drift_corrected_A2'][use],1)[0])
                    intercept=float(np.polyfit(arr['lag_ps'][use],arr['msd_A2'][use],1)[1])
                    alpha_endpoint=None
                    if float(rg[0])>0 and arr['msd_A2'][use][0]>0 and arr['msd_A2'][use][-1]>0:
                        alpha_endpoint=float(np.log(arr['msd_A2'][use][-1]/arr['msd_A2'][use][0])/np.log(float(rg[1])/float(rg[0])))
                    reg_use=(arr['lag_ps']>float(rg[0])+1e-9)&(arr['lag_ps']<=float(rg[1])+1e-9)
                    logx=np.log(arr['lag_ps'][reg_use]); logy=np.log(arr['msd_A2'][reg_use])
                    alpha_regression=float(np.polyfit(logx,logy,1)[0]) if np.count_nonzero(reg_use)>=3 and np.all(arr['msd_A2'][reg_use]>0) else None
                    window_metrics[f'{sid}__{sp}__{name}']={'D_m2_s':d,'slope_A2_ps':slope,
                        'alpha_endpoint':alpha_endpoint,'alpha_candidate_regression':alpha_regression,
                        'window_ps':[float(rg[0]),float(rg[1])],
                        'origin_counts':[int(arr['origin_count'][np.flatnonzero(use)[0]]),int(arr['origin_count'][np.flatnonzero(use)[-1]])]}
                    if not np.isclose(slope,float(w['MSD_slope_A2_per_ps']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol']): raise ValueError(f'{sid}/{sp}/{name}: recomputed MSD slope mismatch')
                    if not np.isclose(d,float(w['D_MSD_m2_per_s']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}/{name}: recomputed D mismatch')
                    if 'MSD_intercept_A2' in w and not np.isclose(intercept,float(w['MSD_intercept_A2']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol']): raise ValueError(f'{sid}/{sp}/{name}: recomputed MSD intercept mismatch')
                    if 'drift_corrected_MSD_slope_A2_per_ps' in w and not np.isclose(drift_slope,float(w['drift_corrected_MSD_slope_A2_per_ps']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol']): raise ValueError(f'{sid}/{sp}/{name}: drift-corrected MSD slope mismatch')
                    if 'drift_corrected_D_MSD_m2_per_s' in w and not np.isclose(drift_slope/6*1e-8,float(w['drift_corrected_D_MSD_m2_per_s']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}/{name}: drift-corrected D mismatch')
                    if 'D_YH_conditional_m2_s' in w and not np.isclose(d+yh_delta,float(w['D_YH_conditional_m2_s']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}/{name}: conditional Yeh-Hummer D mismatch')
                    alpha_report=w.get('_reported_loglog_regression_slope',w.get('loglog_endpoint_slope'))
                    if alpha_report is not None:
                        if alpha_regression is None or not np.isclose(alpha_regression,float(alpha_report),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['endpoint_alpha_atol']):
                            raise ValueError(f'{sid}/{sp}/{name}: reported log-log regression slope mismatch')
                        if alpha_endpoint is None or not np.isclose(alpha_endpoint,float(alpha_report),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['endpoint_alpha_atol']):
                            raise ValueError(f'{sid}/{sp}/{name}: endpoint_alpha_diagnostic_mismatch; required endpoint log-slope differs from the frozen regression value')
                    cs=w.get('origin_count_at_window_start'); ce=w.get('origin_count_at_window_end')
                    legacy_pilot = (historical_pilot_ids is not None and sid in historical_pilot_ids
                                    and row.get('_legacy_pilot_summary') is True)
                    if not legacy_pilot and (cs is not None or ce is not None):
                        if type(cs) is not int or type(ce) is not int or cs!=int(arr['origin_count'][np.flatnonzero(use)[0]]) or ce!=int(arr['origin_count'][np.flatnonzero(use)[-1]]): raise ValueError(f'{sid}/{sp}/{name}: reported origin counts mismatch')
                if not windows: raise ValueError(f'{sid}/{sp}: no finite-window MSD summaries')
                ordered_items=sorted(windows.items(),key=lambda item:tuple(map(float,item[1].get('lag_range_ps',[]))))
                ordered_windows=[item[1] for item in ordered_items]
                ranges=np.asarray([w['lag_range_ps'] for w in ordered_windows],dtype=float)
                d_a2ps=np.asarray([float(w['D_MSD_m2_per_s'])/1e-8 for w in ordered_windows])
                regressions=np.asarray([window_metrics[f'{sid}__{sp}__{name}']['alpha_candidate_regression'] for name,_ in ordered_items],dtype=float)
                for field,want in (('window_ps',ranges),('window_D_A2_per_ps',d_a2ps),('window_alpha',regressions)):
                    supplied=normalized_arrays.get(f'{sid}__{sp}__{field}')
                    if supplied is not None and (np.shape(supplied)!=np.shape(want) or not np.allclose(supplied,want,rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol'],equal_nan=False)):
                        raise ValueError(f'{sid}/{sp}: NPZ {field} differs from independently checked result windows')
                adjacent=decisions.adjacent_relative_spread([float(w['D_MSD_m2_per_s']) for w in ordered_windows])
                public_trigger=(any(float(w['D_MSD_m2_per_s'])<=0 for w in ordered_windows)
                    or any(window_metrics[f'{sid}__{sp}__{name}']['alpha_endpoint'] is None or abs(float(window_metrics[f'{sid}__{sp}__{name}']['alpha_endpoint'])-1)>policy['decision_numeric_policy']['alpha_deviation_from_one'] for name,_ in ordered_items)
                    or adjacent>policy['decision_numeric_policy']['window_D_relative_spread'])
                if isinstance(rep.get('triggered'),bool) and bool(rep['triggered'])!=public_trigger:
                    raise ValueError(f'{sid}/{sp}: candidate trigger differs from public endpoint/adjacent-window diagnostics')
                supplied_trigger=normalized_arrays.get(f'{sid}__{sp}__triggered')
                if supplied_trigger is not None and (np.shape(supplied_trigger)!=(1,) or bool(supplied_trigger[0])!=public_trigger):
                    raise ValueError(f'{sid}/{sp}: NPZ triggered flag differs from public endpoint/adjacent-window diagnostics')
                vacf=rep.get('vacf_integrals',{})
                for cutoff_s,dval in vacf.items():
                    cutoff=float(str(cutoff_s).removesuffix('ps')); use=arr['lag_ps']<=cutoff+1e-10
                    if not use.any() or arr['lag_ps'][use][-1]<cutoff-1e-10: raise ValueError(f'{sid}/{sp}: VACF cutoff not represented on data grid')
                    raw_integral=float(np.trapz(arr['vacf_A2_per_ps2'][use],arr['lag_ps'][use]))
                    raw_drift_integral=float(np.trapz(arr['vacf_drift_corrected_A2_per_ps2'][use],arr['lag_ps'][use]))
                    diffusion=raw_integral/3*1e-8; drift_diffusion=raw_drift_integral/3*1e-8
                    if isinstance(dval,dict) and set(dval)=={'D_vacf_A2_per_ps'}:
                        if not np.isclose(raw_integral/3,float(dval['D_vacf_A2_per_ps']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']/1e-8):
                            raise ValueError(f'{sid}/{sp}: reported VACF diffusion in A2/ps mismatches native integral')
                    elif isinstance(dval,dict):
                        required_vacf={'integral_A2_per_ps','D_VACF_m2_per_s','drift_corrected_integral_A2_per_ps','drift_corrected_D_VACF_m2_per_s'}
                        if not required_vacf.issubset(dval): raise ValueError(f'{sid}/{sp}: VACF summary lacks raw/drift-corrected values')
                        if not np.isclose(raw_integral,float(dval['integral_A2_per_ps']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol']): raise ValueError(f'{sid}/{sp}: raw VACF integral mismatch')
                        if not np.isclose(diffusion,float(dval['D_VACF_m2_per_s']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}: VACF diffusion conversion mismatch')
                        if not np.isclose(raw_drift_integral,float(dval['drift_corrected_integral_A2_per_ps']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol']): raise ValueError(f'{sid}/{sp}: drift-corrected VACF integral mismatch')
                        if not np.isclose(drift_diffusion,float(dval['drift_corrected_D_VACF_m2_per_s']),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}: drift-corrected VACF conversion mismatch')
                    elif policy.get('test_only') is True:
                        if not np.isclose(diffusion,float(dval),rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['diffusion_atol_m2_s']): raise ValueError(f'{sid}/{sp}: VACF integral mismatch')
                    else: raise ValueError(f'{sid}/{sp}: production VACF summaries must include raw and drift-corrected fields')
        historical_ids=set(historical_pilot_ids or ())
        if historical_ids - {'pilot353a','pilot373a'}:
            raise ValueError('unsupported private historical pilot overlay identity')
        if historical_ids != {sid for sid in historical_ids if any(spec['series_id']==sid for spec in series_specs)}:
            raise ValueError('private historical pilot overlay series are not present in the frozen contract')
        historical_keys={k for k in expected if any(k.startswith(sid+'__') for sid in historical_ids)}
        if historical_ids:
            if historical_pilot_reference is None or historical_arrays_out is None:
                raise ValueError('private historical pilot series lack their fixed reference and evaluation overlay')
            with np.load(historical_pilot_reference,allow_pickle=False) as old_arrays:
                for key in sorted(historical_keys):
                    sid, species, field = key.split('__',2)
                    source_key = f'{sid}__lag_ps' if field=='lag_ps' else f'{sid}__{species}__{field}'
                    if field=='origin_count':
                        continue
                    if source_key not in old_arrays.files:
                        raise ValueError(f'fixed pilot analysis lacks its source array: {source_key}')
                    want=expected[key]; got=old_arrays[source_key]
                    if np.shape(got)!=np.shape(want) or not np.isfinite(got).all() or not np.allclose(got,want,rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol'],equal_nan=False):
                        raise ValueError(f'current native pilot recomputation differs from fixed historical source: {key}')
                    historical_arrays_out[key]=want
        candidate_keys=set(expected)-historical_keys
        species_names=set(vals)
        normalized_arrays={}
        # Public output permits the readable `run::species::field` form as well
        # as the legacy private `run__species__field` spelling. Normalize only
        # semantic arrays; never require private field names to be serialized.
        field_aliases={'msd_lags_ps':'lag_ps','vacf_lags_ps':'vacf_lags_ps',
                       'lag_ps':'lag_ps','msd_A2':'msd_A2',
                       'msd_drift_corrected_A2':'msd_drift_corrected_A2',
                       'vacf_A2_per_ps2':'vacf_A2_per_ps2',
                       'vacf_drift_corrected_A2_per_ps2':'vacf_drift_corrected_A2_per_ps2',
                       'origin_count':'origin_count'}
        core_seen=set()
        with np.load(app/'msd-vacf.npz',allow_pickle=False) as z:
            for raw_key in z.files:
                sep='::' if '::' in raw_key else '__' if '__' in raw_key else None
                if sep is None: raise ValueError(f'unsupported public correlation array key: {raw_key}')
                parts=raw_key.split(sep)
                if len(parts)!=3: raise ValueError(f'malformed public correlation array key: {raw_key}')
                sid,sp,raw_field=parts
                supplemental=set(plan.get('analysis_precommit',{}).get('adaptive_run_ids',[]))
                if (sid not in {x['series_id'] for x in series_specs} and sid not in supplemental) or sp not in species_names:
                    raise ValueError(f'correlation array references undeclared dataset/species: {raw_key}')
                if raw_field not in field_aliases and raw_field not in {'window_D_A2_per_ps','window_alpha','window_ps','triggered'}:
                    raise ValueError(f'unsupported public correlation array field: {raw_field}')
                arr=np.asarray(z[raw_key])
                if not np.isfinite(arr).all(): raise ValueError(f'nonfinite public correlation array: {raw_key}')
                if sid in supplemental and sid not in {x['series_id'] for x in series_specs}:
                    continue
                if raw_field in field_aliases:
                    field=field_aliases[raw_field]
                    key=f'{sid}__{sp}__{field}'
                    if field=='vacf_lags_ps':
                        want=expected[f'{sid}__{sp}__lag_ps'][:len(arr)]
                    else:
                        want=expected.get(key)
                    if want is None: raise ValueError(f'no native reference for correlation array: {raw_key}')
                    if np.shape(arr)!=np.shape(want): raise ValueError(f'array shape mismatch: {raw_key}')
                    if np.issubdtype(np.asarray(want).dtype,np.integer):
                        if not np.issubdtype(arr.dtype,np.integer) or not np.array_equal(arr,want): raise ValueError(f'exact integer array mismatch: {raw_key}')
                    elif not np.allclose(arr,want,rtol=NUMERIC_REFS['array_rtol'],atol=NUMERIC_REFS['array_atol'],equal_nan=False): raise ValueError(f'array mismatch: {raw_key}')
                    normalized_arrays[key]=arr
                    if raw_field in {'msd_lags_ps','msd_A2','vacf_lags_ps','vacf_A2_per_ps2'}: core_seen.add((sid,sp,raw_field))
                elif raw_field in {'window_D_A2_per_ps','window_alpha','window_ps','triggered'}:
                    normalized_arrays[f'{sid}__{sp}__{raw_field}']=arr
            needed={(spec['series_id'],sp,field) for spec in series_specs for sp in species_names
                    for field in ('msd_lags_ps','msd_A2','vacf_lags_ps','vacf_A2_per_ps2')}
            if core_seen!=needed: raise ValueError(f'NPZ core estimator coverage mismatch missing={sorted(needed-core_seen)[:8]} extra={sorted(core_seen-needed)[:8]}')
        # Independently recalculate conditional Yeh-Hummer corrections only at sampled temperatures.
        sampled=sorted({float(r['T_K']) for r in attempts.values()})
        if len(sampled)<1: raise ValueError('no sampled temperatures')
        thermal=app/'inputs'/'thermophysical.csv'
        with thermal.open(newline='') as f: rows={float(x['T_K']):x for x in csv.DictReader(f)}
        report_yh=results.get('yeh_hummer',{})
        if not isinstance(report_yh,dict): raise ValueError('results Yeh-Hummer summary is malformed')
        kb=1.380649e-23
        yh={}
        for temp in sampled:
            if temp not in rows: raise ValueError(f'missing public Yeh-Hummer data at sampled T={temp:g} K')
            eta=float(rows[temp]['eta_mPa_s'])*1e-3; L=float(rows[temp]['L_A'])*1e-10
            delta=2.837297*kb*temp/(6*math.pi*eta*L)
            y=report_yh.get(str(int(temp)))
            if isinstance(y,dict):
                if not np.isclose(float(y.get('deltaD_m2_s',float('nan'))),delta,rtol=NUMERIC_REFS['yeh_hummer_rtol'],atol=NUMERIC_REFS['yeh_hummer_atol']): raise ValueError(f'Yeh-Hummer correction mismatch at {temp:g} K')
                if y.get('source_sha256',y.get('thermophysical_sha256')) not in (None,sha(thermal)): raise ValueError('Yeh-Hummer public-property source hash mismatch')
            yh[str(int(temp))]=delta
        series_temperature={}
        for spec in series_specs:
            sid=spec.get('series_id')
            values=spec.get('run_ids',[])
            temps={float(attempts[x]['T_K']) for x in values if x in attempts}
            if spec.get('T_K') is not None:
                temps.add(float(spec['T_K']))
            if len(temps)==1:
                series_temperature[sid]=next(iter(temps))
        endpoint_groups={}
        for key, metric in window_metrics.items():
            sid, species, window_id=key.split('__',2)
            temp=series_temperature.get(sid)
            if temp is None:
                continue
            group=endpoint_groups.setdefault((species,tuple(metric['window_ps'])),{})
            group.setdefault(temp,[]).append(float(metric['D_m2_s']))
        temperature_endpoints=[]
        for (species,window), by_temp in sorted(endpoint_groups.items()):
            temps=sorted(by_temp)
            means={str(int(t)):float(np.mean(by_temp[t])) for t in temps}
            slope=None; ea=None
            if len(temps)>=2:
                low,high=temps[0],temps[-1]
                dlo,dhi=means[str(int(low))],means[str(int(high))]
                if dlo>0 and dhi>0:
                    slope=(math.log(dhi)-math.log(dlo))/(1.0/high-1.0/low)
                    ea=-0.008314462618*slope
            temperature_endpoints.append({'species':species,'window_ps':list(window),
                'mean_D_m2_s_by_temperature':means,'endpoint_delta_D_high_minus_low_m2_s':
                (means[str(int(temps[-1]))]-means[str(int(temps[0]))] if len(temps)>=2 else None),
                'two_point_lnD_vs_inverseT_slope_K':slope,'conditional_two_point_Ea_kJ_mol':ea,
                'interpretation':'descriptive endpoint arithmetic; not validation of Arrhenius shape, mechanism, or equilibrium'})
        return {'datasets_recomputed':len(series_specs),'native_segments_recomputed':len(parsed),'arrays_recomputed':len(expected),'continuation_boundaries':bounds,'topology_counts':expected_counts,'yeh_hummer_delta_m2_s':yh,'window_metrics':window_metrics,'sampled_temperatures_K':sampled,'temperature_endpoint_descriptives':temperature_endpoints,
                'model_identity_audits':model_identity_audits,
                'model_identity_review_required':any(x.get('review_required') for x in model_identity_audits)}

    def _contract(plan, trace, decision, runs, policy):
        errors=[]; c=plan.get('automatic_decision_contract')
        if not isinstance(c,dict): errors.append('plan lacks automatic_decision_contract/v1')
        else:
            if c.get('schema')!=policy['automatic_contract_schema']: errors.append('decision contract schema mismatch')
            pre=c.get('precommit')
            required=policy['decision_contract']['required_precommit_fields']
            if not isinstance(pre,dict) or any(k not in pre for k in required): errors.append('precommit contract is incomplete')
            elif pre.get('frozen_plan_sha256')!=sha_for_object(plan): errors.append('precommit frozen-plan hash mismatch')
            if c.get('selection_rule_id') not in policy['decision_contract']['selection_rules']:
                errors.append('unsupported or unregistered post-pilot selection rule')
            series=pre.get('series',[]) if isinstance(pre,dict) else []
            if not isinstance(series,list) or not series: errors.append('precommit series contract is empty')
            claim_rules=pre.get('claim_rules',[]) if isinstance(pre,dict) else []
            rulemap={x.get('claim_id'):x.get('rule_id') for x in claim_rules if isinstance(x,dict)}
            expected_rules={'diffusive_regime':'finite_window_nonidentifiable','temperature_trend':'temperature_trend_not_identified','activation_energy':'activation_energy_not_identified'}
            if rulemap!=expected_rules and not plan.get('_claim_rule_semantic_review'):
                errors.append('claim rules do not map the required claims to the implemented numeric rules')
            alts=c.get('alternatives',[])
            if not isinstance(alts,list) or len(alts)<policy['decision_contract']['minimum_alternatives']:
                errors.append('fewer than two structured alternatives')
            else:
                fields=policy['decision_contract']['required_alternative_fields']
                aid=[]
                for a in alts:
                    if not isinstance(a,dict) or any(k not in a for k in fields): errors.append('alternative contract fields missing'); continue
                    aid.append(a['alternative_id'])
                    if a['action_kind'] not in policy['decision_contract']['alternative_action_kinds']: errors.append('unknown alternative action kind')
                    cost=a['cost_steps']; dt=float(a.get('dt_fs',.5)); dur=a['duration_ps']
                    if type(cost) is not int or cost<=0 or not math.isfinite(float(dur)) or not math.isclose(cost*dt/1000,float(dur),rel_tol=1e-6,abs_tol=1e-8): errors.append('alternative cost and duration disagree')
                    if not a.get('information_target') or not a.get('bias_risk') or not a.get('mitigation'): errors.append('alternative information/risk/mitigation is not concrete')
                if len(aid)!=len(set(aid)): errors.append('alternative IDs are not unique')
            chosen=c.get('chosen_alternative_id')
            if chosen not in {a.get('alternative_id') for a in alts if isinstance(a,dict)}: errors.append('chosen alternative does not identify a declared option')
        claims=decision.get('claims') if isinstance(decision,dict) else None
        if not isinstance(claims,dict): errors.append('decision claims missing')
        else:
            expected=set(policy['decision_contract']['required_claim_ids'])
            if set(claims)!=expected: errors.append('claim set differs from required scientific claims')
            for cid,row in claims.items():
                if not isinstance(row,dict) or any(k not in row for k in policy['decision_contract']['required_claim_fields']): errors.append(f'{cid}: claim fields missing'); continue
                if row['status'] not in policy['decision_contract']['claim_statuses']: errors.append(f'{cid}: status outside the automatic-or-review schema')
                allowed_reasons=set(policy['decision_contract']['claim_rule_ids']) | set(policy['decision_contract']['review_candidate_rule_ids'])
                if row.get('reason_code') not in allowed_reasons: errors.append(f'{cid}: invalid registered rule ID')
                if not row.get('scope') or not isinstance(row.get('diagnostic_ids'),list) or not row['diagnostic_ids']: errors.append(f'{cid}: scoped diagnostics missing')
        nxt=decision.get('next_action') if isinstance(decision,dict) else None
        nf=policy['decision_contract']['required_next_action_fields']
        if not isinstance(nxt,dict) or any(k not in nxt for k in nf): errors.append('structured next_action missing')
        else:
            if nxt['action_kind'] not in policy['decision_contract']['alternative_action_kinds']: errors.append('invalid next-action kind')
            if type(nxt['cost_steps']) is not int or nxt['cost_steps']<0: errors.append('invalid next-action cost')
            hyps=nxt['competing_hypotheses']
            if not isinstance(hyps,list) or len(hyps)!=2: errors.append('next action needs two competing hypotheses')
            else:
                hf=policy['decision_contract']['required_hypothesis_fields']
                if any(not isinstance(h,dict) or any(k not in h for k in hf) for h in hyps): errors.append('hypothesis fields missing')
                elif hyps[0]['observable_id']!=hyps[1]['observable_id'] or hyps[0]['predicted_direction']==hyps[1]['predicted_direction']: errors.append('hypotheses must predict opposing directions for one observable')
        return errors

    def sha_for_object(obj):
        obj=obj.get('_raw_plan_for_hash',obj)
        c=obj.get('automatic_decision_contract',{})
        pre=json.loads(json.dumps(c.get('precommit',{})))
        pre.pop('frozen_plan_sha256',None)
        return canonical_hash({'precommit':pre,'alternatives':c.get('alternatives',[]),'selection_rule_id':c.get('selection_rule_id')})

    def run_diagnostics(app, protocol):
        return budget_checks.diagnose(app,protocol)

    def score(app: Path, tests: Path, logs: Path, *, policy_override=None):
        if any(p.is_symlink() for p in (app,tests,logs)): raise RuntimeError('APP, TESTS or LOGS root is a symlink')
        app,tests,logs=app.resolve(),tests.resolve(),logs.resolve()
        if any(p.is_symlink() for p in (app,tests,logs)): raise RuntimeError('resolved APP, TESTS or LOGS root is a symlink')
        logs.mkdir(parents=True,exist_ok=True)
        report=logs/'verification.json'; reward=logs/'reward.txt'
        for p in (report,reward):
            if p.is_symlink(): raise RuntimeError(f'unsafe stale scorer output: {p.name}')
            p.unlink(missing_ok=True)
        answer_mode=os.environ.get('CCB_ANSWER_MODE')
        if answer_mode not in ('agent','oracle'):
            raise RuntimeError('runner must set reserved CCB_ANSWER_MODE=agent or oracle')
        policy=policy_override or safe_json(tests/'automatic'/'policy.json')
        if policy.get('schema')!=SCHEMA: raise ValueError('unsupported automatic scoring policy')
        refs=check_trusted_references(app,tests,answer_mode)
        proto=safe_json(tests/'assessment-protocol.json')
        if proto.get('implementation')!='automatic-with-independent-review' or proto.get('runtime_bound') is not False: raise RuntimeError('active protocol does not declare the deterministic-plus-review scoring revision')
        validate_public_policy(app,policy,proto)
        candidate_errors=[]; manifest=[]; diag=[]; runs=[]; contract_errors=[]; numeric={}; budget_errors=['budget gate skipped: ledger could not be parsed']
        historical_projection=None; scoring_results=None; historical_pilot_arrays={}; ledger={}
        try: manifest=outputs_manifest(app,proto['expected_outputs'])
        except (OSError,ValueError,KeyError,TypeError) as exc: candidate_errors.append(str(exc))
        if manifest:
            try: diag=run_diagnostics(app,proto)
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc: candidate_errors.append('budget/native diagnostic: '+str(exc))
        try:
            # Continue through machine checks even when the structured contract is absent.
            plan=safe_json(app/'plan.json'); trace=safe_json(app/'decision-trace.json'); decision=safe_json(app/'decision.json')
            scoring_results=safe_json(app/'results.json')
            ledger=safe_json(app/'run-ledger.json'); runs=ledger.get('runs')
            if not isinstance(runs,list) or not runs: raise ValueError('run ledger attempts missing')
            budget_errors=budget_gate(ledger,policy)
            plan=_project_frozen_decision_plan(plan,ledger,scoring_results,policy)
            decision=__import__('copy').deepcopy(decision)
            reason_aliases={'activation_energy_not_identifiable_without_common_diffusive_regime':'activation_energy_not_identified',
                'finite_window_diagnostics_triggered_all_pilot_and_confirmation_groups':'finite_window_nonidentifiable',
                'descriptive_two_endpoint_trend_not_a_converged_transport_claim':'temperature_trend_not_identified'}
            for claim in decision.get('claims',{}).values():
                if isinstance(claim,dict) and 'reason_code' not in claim and claim.get('reason_id') in reason_aliases:
                    claim['reason_code']=reason_aliases[claim['reason_id']]
            nxt=decision.get('next_action')
            if isinstance(nxt,dict) and 'competing_hypotheses' not in nxt and isinstance(nxt.get('hypotheses'),list):
                supported=str(nxt.get('supported_trigger_rule','')).lower()
                if 'finite-window' in supported and 'non-identifiability' in supported and 'physical d/ea' in supported:
                    nxt['competing_hypotheses']=[{'hypothesis_id':h.get('hypothesis_id'),
                        'observable_id':h.get('observable_id'),'predicted_direction':h.get('expected_direction'),
                        'trigger_rule_id':'finite_window_nonidentifiable'} for h in nxt['hypotheses']]
            contract_errors=_contract(plan,trace,decision,runs,policy)
        except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc: candidate_errors.append('decision/ledger contract: '+str(exc))
        if runs and isinstance(plan,dict):
            try: numeric=numerical_recompute(app,policy,plan,ledger,scoring_results or safe_json(app/'results.json'),
                                             historical_projection.get('pilot_reference_npz') if historical_projection else None,
                                             historical_pilot_arrays if historical_projection else None,
                                             set(historical_projection.get('historical_pilot_ids',[])) if historical_projection else None)
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc: candidate_errors.append('native trajectory recompute: '+str(exc))
        # Reference execution submits the same native evidence as a new Agent run.
        try:
            candidate_schedule=candidate_scheduler.validate(app,policy,manifest,runs,ledger,verify_frozen_gpu_request,answer_mode=answer_mode)
            schedule=scheduler_gate(app,tests,policy,manifest,runs,candidate_schedule=candidate_schedule)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            msg=str(exc); candidate_errors.append(msg)
            schedule={'error':msg,'origin':candidate_scheduler.ORIGIN}
        candidate_errors.extend(schedule.get('gpu_candidate_errors',[]))
        decision_errors=['decision evaluator skipped because required candidate evidence did not parse']
        decision_details={}
        review_required=False
        if numeric and runs and 'error' not in schedule:
            adjudication=decisions.evaluate(app,policy,plan,trace,decision,ledger,scoring_results or safe_json(app/'results.json'),numeric,schedule,
                                          historical_equivalence=historical_projection.get('equivalence') if historical_projection else None,
                                          historical_pilot_arrays=historical_pilot_arrays if historical_projection else None)
            decision_errors=adjudication.get('errors',[]); decision_details=adjudication.get('diagnostics',{})
            review_required=bool(adjudication.get('review_required'))
        if numeric.get('model_identity_review_required'):
            review_required=True
        checks=[{'id':d.get('check','diagnostic'), 'passed':bool(d.get('passed')), 'detail':d.get('detail','')} for d in diag]
        checks.append({'id':'candidate_payload_valid','passed':not candidate_errors,'detail':candidate_errors})
        checks.append({'id':'automatic_decision_contract','passed':not contract_errors,'detail':contract_errors})
        checks.append({'id':'budget_reservation_and_stages','passed':not budget_errors,'detail':budget_errors})
        checks.append({'id':'deterministic_claim_and_decision_rules','passed':not decision_errors,'detail':{'errors':decision_errors,'diagnostics':decision_details}})
        checks.append({'id':'native_trajectory_recompute','passed':not candidate_errors,'detail':numeric if numeric else candidate_errors})
        checks.append({'id':'scheduler_evidence_crosscheck','passed':'error' not in schedule,'detail':schedule})
        checks.append({'id':'native_and_frozen_gpu_request','passed':not schedule.get('gpu_candidate_errors',[]),'detail':schedule.get('gpu_evidence_basis',{})})
        failed=[c for c in checks if not c['passed']]
        # Keep size-bearing output rows for the local scorer's evidence record;
        # the shared review continuation binds the canonical path/SHA schema.
        review_manifest = review_output_manifest(manifest)
        submission_manifest_sha = canonical_hash(review_manifest)
        review_details = None
        if review_required and not failed:
            review_status, review_details = validate_review(app, tests, proto, review_manifest)
        else:
            review_status, review_details = None, None
        status, reward_value = score_outcome(bool(failed), review_required, review_status)
        # Submitted records remain cross-checked evidence, never host attestation.
        result={'schema':'case04-score/v2','revision':policy['revision'],'status':status,'reward':reward_value,'agent_graded':True,'answer_mode':answer_mode,'runtime_bound':False,'runtime_origin':'candidate-submitted-crosschecked','testing_fixture':bool(policy.get('test_only',False)),'checks':checks,'submission_manifest_sha256':submission_manifest_sha,'trusted_asset_hashes':refs}
        if review_required:
            result.update({'diagnostics': {'checks': checks, 'native_recompute': numeric,
                                           'decision_evaluation': decision_details,
                                           'decision_errors': decision_errors},
                           'submission_manifest': review_manifest,
                           'submission_manifest_sha256': submission_manifest_sha,
                           'review': review_details or {'reason': 'Scientific adjudication is required.'}})
        report.write_text(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
        if reward_value is not None: reward.write_text(f'{reward_value}\n',encoding='utf-8')
        return result

    def main():
        ap=argparse.ArgumentParser(); ap.add_argument('--app',default=os.environ.get('APP')); ap.add_argument('--submission'); ap.add_argument('--tests',default=os.environ.get('TESTS')); ap.add_argument('--logs',default=os.environ.get('LOGS')); ap.add_argument('--answer-mode',choices=('agent','oracle'),default=os.environ.get('CCB_ANSWER_MODE')); a=ap.parse_args()
        if a.answer_mode:
            os.environ['CCB_ANSWER_MODE']=a.answer_mode
        app_arg=a.submission or a.app
        if not all((app_arg,a.tests,a.logs)): raise ValueError('APP/--submission, TESTS and LOGS are required')
        raw_app,raw_tests,raw_logs=Path(app_arg).absolute(),Path(a.tests).absolute(),Path(a.logs).absolute()
        for raw in (raw_app,raw_tests,raw_logs):
            if raw.is_symlink(): raise ValueError(f'APP/TESTS/LOGS root is a symlink: {raw}')
        app,tests,logs=raw_app.resolve(),raw_tests.resolve(),raw_logs.resolve()
        try:
            result=score(app,tests,logs); print(json.dumps(result,ensure_ascii=False,allow_nan=False)); return 0 if result['status'] in ('PASS','REVIEW_REQUIRED') else 1
        except (OSError,ValueError,KeyError,TypeError,RuntimeError,OverflowError) as exc:
            if logs.is_symlink():
                print('INFRA_ERROR: unsafe LOGS symlink',file=sys.stderr); return 2
            logs.mkdir(parents=True,exist_ok=True)
            for p in (logs/'reward.txt',logs/'verification.json'):
                if p.is_symlink():
                    print('INFRA_ERROR: unsafe scorer output symlink',file=sys.stderr); return 2
                p.unlink(missing_ok=True)
            err={'schema':'case04-automatic-score/v1','status':'INFRA_ERROR','reward':None,'agent_graded':False,'runtime_bound':False,'error':str(exc)}
            (logs/'verification.json').write_text(json.dumps(err,indent=2,ensure_ascii=False)+'\n')
            print(json.dumps(err,ensure_ascii=False),file=sys.stderr); return 2
    return SimpleNamespace(main=main, score=score, sha=sha, canonical_hash=canonical_hash,
                           validate_review=validate_review, check_trusted_references=check_trusted_references,
                           verify_frozen_gpu_request=verify_frozen_gpu_request, score_outcome=score_outcome,
                           audit_native_model_identity=audit_native_model_identity,
                           review_output_manifest=review_output_manifest, outputs_manifest=outputs_manifest)


# ---------------------------------------------------------------------------
# Private verifier mount isolation
# ---------------------------------------------------------------------------
_ISOLATION_CHILD = r'''import errno,importlib.util,json,os,sys
protected=sys.argv[1:-5]; verify,raw_data,sentinel,second,create=sys.argv[-5:]; checks=[]
def attempt(name,fn):
 try: fn()
 except OSError as exc: return {"name":name,"result":"DENIED" if exc.errno in (errno.EACCES,errno.EPERM) else "UNEXPECTED","errno":exc.errno}
 return {"name":name,"result":"ALLOWED"}
for path in protected: checks.append(attempt("read:"+os.path.basename(path),lambda p=path:open(p,"rb").read(1)))
def import_verify():
 spec=importlib.util.spec_from_file_location("case45_private_verify",verify); module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
checks.append(attempt("import:verify.py",import_verify))
checks.append(attempt("read:root-sentinel",lambda:open(sentinel,"rb").read(1)))
checks.append(attempt("overwrite:root-sentinel",lambda:open(sentinel,"wb").write(b"X")))
checks.append(attempt("create:second-sentinel",lambda:os.open(second,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
checks.append(attempt("create:private-tests",lambda:os.open(create,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
checks.append(attempt("overwrite:reference-hashes.json",lambda:open(protected[1],"wb").write(b"X")))
checks.append(attempt("overwrite:refs.json",lambda:open(protected[2],"wb").write(b"X")))
checks.append(attempt("overwrite:raw-data",lambda:open(raw_data,"wb").write(b"X")))
for path in protected:
 if os.path.basename(path)=="scientific-review.json": checks.append(attempt("overwrite:scientific-review.json",lambda p=path:open(p,"wb").write(b"X")))
print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"capeff":open("/proc/self/status").read().split("CapEff:")[1].splitlines()[0].strip(),"checks":checks},sort_keys=True))
'''


def _private_data_files(tests: Path):
    files = [tests / 'assessment-protocol.json', tests / 'reference-hashes.json',
             tests / 'refs.json', tests / 'review-rubric.md', tests / 'verify.py']
    review = tests / 'scientific-review.json'
    if review.exists() or review.is_symlink():
        files.append(review)
    for subdir in (tests / 'automatic', tests / 'evidence'):
        if subdir.exists():
            files.extend(path for path in sorted(subdir.rglob('*'))
                         if path.is_file() and path.suffix not in ('.py', '.sh'))
    return list(dict.fromkeys(files))


def _isolation_preflight(tests: Path, logs: Path):
    tests = tests.resolve()
    record = {'schema': 'case45-private-tests-preflight/v1', 'status': 'INFRA',
              'uid': os.getuid(), 'euid': os.geteuid(), 'checks': []}
    protected = _private_data_files(tests)
    sentinel = logs / ('isolation-root-' + uuid.uuid4().hex)
    second = logs / ('isolation-replay-' + uuid.uuid4().hex)
    probe = tests / ('.isolation-write-' + uuid.uuid4().hex)
    probe_created = False
    try:
        if os.geteuid() != 0 or tests.is_symlink() or not tests.is_dir():
            raise RuntimeError('private tests must be a mounted root-owned directory')
        root_info = tests.stat()
        if (root_info.st_uid, root_info.st_gid, root_info.st_mode & 0o777) != (0, 0, 0o700):
            raise RuntimeError('private tests root ownership or mode mismatch')
        for path in protected:
            info = path.lstat()
            if path.is_symlink() or not path.is_file() or (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, 0, 0o600):
                raise RuntimeError(f'unsafe private verifier/data file: {path.name}')
            path.read_bytes()
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
                raise RuntimeError(f'unexpected /tests write-probe error: {exc}') from exc
        else:
            probe_created = True
            os.close(fd)
            raise RuntimeError('private tests mount is writable')
        fd = os.open(sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'case45-root-only')
        setpriv = shutil.which('setpriv')
        if not setpriv:
            raise RuntimeError('setpriv is unavailable for private-tests isolation check')
        verify = tests / 'verify.py'
        raw_data = next(path for path in protected if path.parent.name == 'evidence')
        # The small -c body is only the unprivileged permission probe. All verifier,
        # scientific, scheduler, decision, and budget logic remains ordinary source above.
        proc = subprocess.run(
            [setpriv, '--reuid=65534', '--regid=65534', '--clear-groups', '--no-new-privs',
             '--bounding-set=-all', '--', sys.executable, '-I', '-c', _ISOLATION_CHILD,
             *map(str, protected), str(verify), str(raw_data), str(sentinel), str(second), str(probe)],
            capture_output=True, text=True, timeout=20,
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
        record['child_stdout'] = proc.stdout
        record['child_stderr'] = proc.stderr
        if proc.returncode != 0:
            raise RuntimeError(f'UID65534 isolation probe failed: {proc.stderr[-1000:]}')
        result = json.loads(proc.stdout)
        checks = result.get('checks', [])
        names = {item.get('name') for item in checks if isinstance(item, dict)}
        expected = {'read:' + path.name for path in protected}
        expected.update({'import:verify.py', 'read:root-sentinel', 'overwrite:root-sentinel',
                         'create:second-sentinel', 'create:private-tests', 'overwrite:reference-hashes.json',
                         'overwrite:refs.json', 'overwrite:raw-data'})
        if any(path.name == 'scientific-review.json' for path in protected):
            expected.add('overwrite:scientific-review.json')
        if (result.get('uid') != 65534 or result.get('gid') != 65534
                or result.get('capeff') != '0000000000000000'
                or not isinstance(checks, list) or len(checks) != len(expected) or names != expected
                or any(not isinstance(item, dict) or item.get('result') != 'DENIED'
                       or type(item.get('errno')) is not int
                       or item['errno'] not in (errno.EACCES, errno.EPERM) for item in checks)):
            raise RuntimeError('UID65534 isolation checks did not meet the exact denial contract')
        record.update({'status': 'PASS', 'child_result': result,
                       'protected_files': [path.relative_to(tests).as_posix() for path in protected],
                       'runner_tests_mount_read_only': True})
        return record
    except Exception as exc:
        record['error'] = repr(exc)
        raise
    finally:
        cleanup_errors = []
        for path in (sentinel, second):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append({'path': str(path), 'error': repr(exc)})
        if probe_created:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append({'path': str(probe), 'error': repr(exc)})
        if cleanup_errors:
            record['cleanup_errors'] = cleanup_errors
            record['status'] = 'INFRA'
        (logs / 'private-isolation.json').write_text(
            json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
        if cleanup_errors:
            raise RuntimeError('private-isolation probe cleanup failed')


def _runner_dispatch():
    value = os.environ.get('LOGS')
    if value is None and '--logs' in sys.argv:
        index = sys.argv.index('--logs')
        if index + 1 < len(sys.argv):
            value = sys.argv[index + 1]
    if not value:
        print('INFRA_ERROR: LOGS or --logs is required', file=sys.stderr)
        return 2
    logs = Path(value).absolute()
    cur = Path(logs.anchor)
    for part in logs.parts[1:]:
        cur = cur / part
        if cur.is_symlink():
            print('INFRA_ERROR: unsafe LOGS symlink path', file=sys.stderr)
            return 2
    logs.mkdir(parents=True, exist_ok=True)
    for name in ('reward.txt', 'verification.json'):
        output = logs / name
        if output.is_symlink():
            print('INFRA_ERROR: unsafe scorer output symlink', file=sys.stderr)
            return 2
        output.unlink(missing_ok=True)
    tests = Path(os.environ.get('TESTS', '/tests')).absolute()
    try:
        _ensure_components()
        _isolation_preflight(tests, logs)
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != '--runner']
        return SCORER.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
        if code == 0:
            return 0
        error = f'SystemExit: {exc.code}'
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    reward = logs / 'reward.txt'
    report = logs / 'verification.json'
    if reward.is_symlink() or report.is_symlink():
        print('INFRA_ERROR: unsafe scorer output symlink', file=sys.stderr)
        return 2
    reward.unlink(missing_ok=True)
    report.write_text(json.dumps(
        {'schema': 'case04-automatic-score/v1', 'status': 'INFRA_ERROR', 'reward': None,
         'agent_graded': False, 'runtime_bound': False, 'error': error}, indent=2) + '\n')
    print(f'INFRA_ERROR: {error}', file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Explicit construction and CLI dispatch
# ---------------------------------------------------------------------------
REFS_DATA = None
TRAJECTORY = None
SCHEDULER = None
DECISIONS = None
BUDGET_CHECKS = None
SCORER = None


def _ensure_components():
    global REFS_DATA, TRAJECTORY, SCHEDULER, DECISIONS, BUDGET_CHECKS, SCORER
    if SCORER is not None:
        return SCORER
    refs_data = json.loads((HERE / 'refs.json').read_text(encoding='utf-8'))
    trajectory = _build_trajectory_namespace()
    scheduler = _build_scheduler_namespace()
    decisions = _build_decisions_namespace()
    budget_checks = _build_budget_namespace(refs_data['budget_ledger'])
    scorer = _build_scorer_namespace(trajectory, scheduler, decisions, budget_checks,
                                     refs_data['automatic'])
    REFS_DATA, TRAJECTORY, SCHEDULER = refs_data, trajectory, scheduler
    DECISIONS, BUDGET_CHECKS, SCORER = decisions, budget_checks, scorer
    return SCORER


def main():
    if '--runner' in sys.argv[1:]:
        return _runner_dispatch()
    _ensure_components()
    if '--diagnostic' in sys.argv[1:]:
        # Diagnostic mode uses the same automatic scorer CLI; --runner is the
        # only mode that additionally runs the private-mount isolation gate.
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != '--diagnostic']
        return SCORER.main()
    return SCORER.main()


def _positive_run_no_integrator_diagnostics(log_text: str) -> list[str]:
    """Associate the no-integrator warning with its own LAMMPS run block.

    LAMMPS can emit this warning for a legal zero-step setup/force probe.  A
    warning is charged to the next Loop-time record in the same output block;
    only a positive-step block is disqualifying.
    """
    import re
    refs = REFS_DATA if isinstance(REFS_DATA, dict) else {}
    policy = refs.get("scientific_values", {}).get("native_run_log", {})
    warning_text = policy.get("warning_pattern", "No fixes with time integration, atoms won't move")
    warning = re.compile(re.escape(warning_text), re.I)
    run_command = re.compile(r"^\s*run\s+", re.I)
    run_setup = re.compile(r"Setting up\s+.+\brun\b", re.I)
    loop = re.compile(r"Loop time of\s+[0-9.eE+-]+.*?for\s+(\d+)\s+steps", re.I)
    pending = 0
    failures = []
    block = 0
    for line_no, line in enumerate(log_text.splitlines(), 1):
        if run_command.search(line):
            # An echoed new command separates an abandoned prior run.
            pending = 0
        if run_setup.search(line):
            # Verlet::init emits this warning BEFORE Verlet::setup prints its
            # heading. Retain it until this run's Loop-time accounting record.
            block += 1
        if warning.search(line):
            pending += 1
        match = loop.search(line)
        if match:
            steps = int(match.group(1))
            if pending and steps > 0:
                failures.append(f"run block {block} ({steps} steps; warning at/ before line {line_no})")
            pending = 0
    return failures




if __name__ == '__main__':
    raise SystemExit(main())


