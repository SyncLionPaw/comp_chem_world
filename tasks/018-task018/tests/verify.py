#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Analyse continuum and local-solvent effects for Reichardt's dye.
"""Native remote terminal-state and orbital verification; references stay outside images."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='2a88d8dcc7d88a59e59f3e7994e8d7a515db65af0209885d54c9f56d8d8ae509':raise RuntimeError('Private reference integrity mismatch')
REFS=json.loads(_REFS_BYTES)
#!/usr/bin/env python3
"""Parse ORCA Molden files and check native MO overlap/population without SCF."""


import hashlib
import json
import pathlib
import sys
import warnings

import numpy as np
from iodata import load_one
from iodata.overlap import compute_overlap
from iodata.periodic import num2sym

NORM_TOLERANCE = REFS['tolerances']['orbital_norm']
BOHR_TO_ANGSTROM = 0.529177210903
COORDINATE_TOLERANCE_ANGSTROM = REFS['tolerances']['molden_coordinates_angstrom']
ENERGY_TOLERANCE_HARTREE = REFS['tolerances']['energy_hartree']


def read_orca_orbital_table(path: pathlib.Path) -> dict[int, tuple[float, float]]:
    lines = path.read_text(errors="replace").splitlines()
    starts = [i for i, line in enumerate(lines) if "ORBITAL ENERGIES" in line]
    if not starts:
        raise ValueError(f"No ORBITAL ENERGIES table in {path}")
    table: dict[int, tuple[float, float]] = {}
    for line in lines[starts[-1] + 1 :]:
        fields = line.split()
        if len(fields) >= 4 and fields[0].isdigit():
            try:
                table[int(fields[0])] = (float(fields[1]), float(fields[2]))
            except ValueError:
                continue
        elif table:
            break
    if not table:
        raise ValueError(f"Could not read orbital rows from {path}")
    return table


def read_orca_xyz(path: pathlib.Path) -> tuple[list[str], np.ndarray]:
    lines = path.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("* xyz ")), None)
    if start is None:
        raise ValueError(f"No explicit ORCA * xyz block in {path}")
    atoms: list[str] = []
    coords: list[list[float]] = []
    for line in lines[start + 1 :]:
        if line.strip() == "*":
            break
        fields = line.split()
        if len(fields) < 4:
            raise ValueError(f"Malformed xyz row in {path}: {line!r}")
        atoms.append(fields[0].capitalize())
        coords.append([float(value) for value in fields[1:4]])
    return atoms, np.asarray(coords, dtype=float)


def analyze(path: pathlib.Path, input_path: pathlib.Path, output_path: pathlib.Path) -> dict[str, object]:
    # qc-iodata detects ORCA Molden/MKL files and applies the documented ORCA
    # primitive normalization and pure-spherical AO conventions before returning C.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = load_one(path)

    if data.mo is None or data.obasis is None or data.atcoords is None:
        raise ValueError(f"Missing orbitals, basis, or coordinates in {path}")
    if data.mo.kind != "restricted":
        raise ValueError(f"Expected a restricted single-determinant wavefunction: {path}")

    input_atoms, input_coords = read_orca_xyz(input_path)
    molden_atoms = [num2sym[int(z)] for z in data.atnums]
    molden_coords = np.asarray(data.atcoords) * BOHR_TO_ANGSTROM
    if input_atoms != molden_atoms or input_coords.shape != molden_coords.shape:
        raise ValueError(f"ORCA input and Molden atom order/count differ for {path}")
    coordinate_error = float(np.max(np.abs(input_coords - molden_coords)))
    if coordinate_error > COORDINATE_TOLERANCE_ANGSTROM:
        raise ValueError(
            f"ORCA input and Molden coordinates differ by {coordinate_error:.3g} A for {path}"
        )

    coeff = np.asarray(data.mo.coeffs)
    overlap = compute_overlap(data.obasis, data.atcoords)
    if coeff.shape[0] != overlap.shape[0] or overlap.shape[0] != data.obasis.nbasis:
        raise ValueError("MO coefficient and overlap dimensions do not match the AO basis")

    gram = coeff.T @ overlap @ coeff
    diagonal_norms = np.diag(gram)
    max_norm_error = float(np.max(np.abs(diagonal_norms - 1.0)))
    identity_error = float(np.max(np.abs(gram - np.eye(gram.shape[0]))))
    if max_norm_error > NORM_TOLERANCE or identity_error > NORM_TOLERANCE:
        raise ValueError(
            f"MOs fail native overlap checks: max norm error={max_norm_error:.3g}, "
            f"max orthogonality error={identity_error:.3g}, tolerance={NORM_TOLERANCE:.3g}"
        )

    occ = np.asarray(data.mo.occs)
    homo_candidates = np.flatnonzero(occ > 0)
    if homo_candidates.size == 0:
        raise ValueError(f"No occupied molecular orbital found in {path}")
    homo = int(homo_candidates[-1])
    lumo = homo + 1
    if lumo >= coeff.shape[1]:
        raise ValueError(f"No LUMO follows the HOMO in {path}")

    native_orbitals = read_orca_orbital_table(output_path)
    for index in (homo, lumo):
        if index not in native_orbitals:
            raise ValueError(f"ORCA output lacks selected orbital {index} in {output_path}")
        native_occ, native_energy = native_orbitals[index]
        if abs(native_occ - float(occ[index])) > REFS['tolerances']['occupation']:
            raise ValueError(f"Molden and ORCA occupations differ for orbital {index + 1} in {path}")
        if abs(native_energy - float(data.mo.energies[index])) > ENERGY_TOLERANCE_HARTREE:
            raise ValueError(f"Molden and ORCA energies differ for orbital {index + 1} in {path}")

    ao_population = coeff * (overlap @ coeff)
    atom_population = np.zeros((int(data.natom), coeff.shape[1]))
    ao_offset = 0
    for shell in data.obasis.shells:
        nfunc = int(shell.nbasis)
        center = int(shell.icenter)
        if center < 0 or center >= int(data.natom):
            raise ValueError(f"Invalid AO center index {center} in {path}")
        atom_population[center] += ao_population[ao_offset : ao_offset + nfunc].sum(axis=0)
        ao_offset += nfunc
    if ao_offset != coeff.shape[0]:
        raise ValueError(f"AO shell walk covered {ao_offset} rows, expected {coeff.shape[0]}")

    def describe_orbital(index: int) -> dict[str, object]:
        native_occ, native_energy = native_orbitals[index]
        return {
            "orbital_1_based": index + 1,
            "occupation": float(occ[index]),
            "energy_hartree": float(data.mo.energies[index]),
            "orca_output_occupation": native_occ,
            "orca_output_energy_hartree": native_energy,
            "orca_energy_abs_delta_hartree": abs(float(data.mo.energies[index]) - native_energy),
            "c_transpose_S_c": float(diagonal_norms[index]),
            "dye_atoms_1_72_percent": float(atom_population[:72, index].sum() * 100.0),
            "solvent_atoms_73_78_percent": float(atom_population[72:78, index].sum() * 100.0),
            "all_atom_total_percent": float(atom_population[:, index].sum() * 100.0),
        }

    return {
        "file": path.name,
        "molden_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "orca_input": input_path.name,
        "orca_input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "orca_output": output_path.name,
        "orca_output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "atom_mapping": [
            {"atom_1_based": index + 1, "atomic_number": int(z), "element": num2sym[int(z)]}
            for index, z in enumerate(data.atnums)
        ],
        "atom_mapping_sha256": hashlib.sha256(
            json.dumps([int(z) for z in data.atnums], separators=(",", ":")).encode()
        ).hexdigest(),
        "coordinates_match_orca_input": True,
        "molden_vs_input_max_abs_coordinate_error_angstrom": coordinate_error,
        "natom": int(data.natom),
        "nao": int(data.obasis.nbasis),
        "nmo": int(coeff.shape[1]),
        "homo": describe_orbital(homo),
        "lumo": describe_orbital(lumo),
        "all_mo_max_abs_norm_error": max_norm_error,
        "all_mo_max_abs_orthogonality_error": identity_error,
        "all_mo_native_orthonormality_pass": True,
        "parser_warnings": [str(item.message) for item in caught],
    }


#!/usr/bin/env python3
"""Trusted scorer for case-05 fixed-geometry native-evidence analysis."""
import hashlib, json, math, os, re, sys
import subprocess, tempfile
from pathlib import Path, PurePosixPath

APP=Path(os.environ.get('APP','/app'))
LOGS=Path(os.environ.get('LOGS','/logs/verifier'))
FINAL=APP/'final'
TRUST=Path('/trusted/remote-evidence')
CONTEXT=Path('/trusted/runner-context.json')
ANALYSIS_SCHEMA='case05-analysis/v1'
NORM_TOL=REFS['tolerances']['orbital_norm']
POP_TOL_PP=REFS['tolerances']['reported_population_percentage_points']
POP_RANGE_MARGIN_PP=REFS['tolerances']['classification_margin_percentage_points']
ENERGY_TOL=REFS['tolerances']['energy_hartree']

class EnvError(Exception): pass
class CandidateError(Exception): pass

def scoped_observed_jobs(jobs, author_mode):
    if author_mode:
        if any(not isinstance(j,dict) or j.get('historical_source') is not True or j.get('in_answer') is not False or j.get('in_answer_interval') is not False for j in jobs):
            raise EnvError('author replay rows must be explicitly historical, not labeled as current-answer jobs')
        return [j for j in jobs if j.get('observed') is True and j.get('historical_source') is True]
    return [j for j in jobs if isinstance(j,dict) and j.get('observed') is True and j.get('in_answer') is True and j.get('in_answer_interval',True) is True]

def linked_file_records(records_by_hash, digest, job_id):
    records=records_by_hash.get(str(digest),[])
    return [r for r in records if str(job_id) in set(str(x) for x in r.get('observed_job_ids',[])) or str(r.get('job_id',''))==str(job_id)]

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def finite_number(value, where):
    try: valid=not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
    except (OverflowError,TypeError,ValueError): valid=False
    if not valid:
        raise CandidateError(f'{where} must be a finite numeric value')
    return float(value)

def ensure_finite_json(value,where='analysis.json'):
    if isinstance(value,bool) or value is None or isinstance(value,str): return
    if isinstance(value,(int,float)):
        finite_number(value,where); return
    if isinstance(value,list):
        for i,item in enumerate(value): ensure_finite_json(item,f'{where}[{i}]')
        return
    if isinstance(value,dict):
        for key,item in value.items(): ensure_finite_json(item,f'{where}.{key}')
        return
    raise CandidateError(f'{where} contains unsupported JSON value type')

def orbital_classification(dye_percent, solvent_percent):
    if any(x < -POP_RANGE_MARGIN_PP or x > 100.0+POP_RANGE_MARGIN_PP for x in (dye_percent,solvent_percent)):
        return 'AMBIGUOUS'
    if dye_percent >= REFS['reference']['classification_percent']['dye_dominant_min']: return 'DYE_DOMINANT'
    if dye_percent <= REFS['reference']['classification_percent']['solvent_dominant_max_dye'] and solvent_percent >= REFS['reference']['classification_percent']['solvent_dominant_min']: return 'SOLVENT_DOMINANT'
    return 'MIXED'

def env_finite(value, where):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise EnvError(f'{where} is not finite numeric evaluator metadata')
    return float(value)

def json_file(path, env=False):
    exc=EnvError if env else CandidateError
    try:
        if path.is_symlink() or not path.is_file(): raise exc(f'missing or non-regular file: {path}')
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,UnicodeError,json.JSONDecodeError) as e: raise exc(f'invalid JSON/file {path}: {e}')

def validate_public_assets(assets_root):
    manifest_path=assets_root/'public-artifact-manifest.json'
    manifest=json_file(manifest_path,True)
    if not isinstance(manifest,dict) or manifest.get('schema')!='case05-public-artifact-manifest/v1' or manifest.get('revision')!=5:
        raise EnvError('mounted public asset manifest schema/revision mismatch')
    rows=manifest.get('files')
    if not isinstance(rows,list) or len(rows)!=28: raise EnvError('mounted public asset manifest must list 28 files')
    seen=set()
    for row in rows:
        if not isinstance(row,dict): raise EnvError('malformed public asset manifest row')
        rel=row.get('path'); expected=row.get('sha256'); size=row.get('bytes')
        if not isinstance(rel,str) or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts or not PurePosixPath(rel).parts or PurePosixPath(rel).as_posix()!=rel:
            raise EnvError('unsafe public asset manifest path')
        if rel in seen: raise EnvError('duplicate public asset manifest path')
        seen.add(rel); path=assets_root/rel
        if any(parent.is_symlink() for parent in (path,*path.parents) if parent not in (assets_root,assets_root.parent)):
            raise EnvError(f'public asset path contains symlink: {rel}')
        if not path.resolve().is_relative_to(assets_root.resolve()) or path.is_symlink() or not path.is_file():
            raise EnvError(f'public asset missing or non-regular: {rel}')
        if type(size) is not int or size<0 or path.stat().st_size!=size or not isinstance(expected,str) or sha(path)!=expected:
            raise EnvError(f'public asset digest/size mismatch: {rel}')
    return manifest

def trusted_inputs():
    try:
        import numpy, scipy, iodata
        from iodata.overlap import compute_overlap  # noqa: F401
    except Exception as e: raise EnvError(f'required orbital scoring dependency unavailable: {e}')
    validate_public_assets(APP/'assets')
    ctx=json_file(CONTEXT,True); manifest_path=TRUST/'manifest.json'
    if ctx.get('schema')!='compchembench.runner-context/v2': raise EnvError('runner context v2 required')
    if ctx.get('evidence_mode') not in ('case05-candidate-v5-8','case05-author-supplement-v1-10'): raise EnvError('unknown runner-selected evidence mode')
    manifest=json_file(manifest_path,True)
    if manifest.get('schema')!='compchembench.remote-evidence/v1': raise EnvError('remote evidence schema mismatch')
    collection=manifest.get('collection_status')
    if collection=='out_of_scope' and manifest.get('collection_error_owner')=='candidate': raise CandidateError('remote jobs or workdirs escaped the authorized attempt scope')
    if collection!='complete': raise EnvError(f'trusted remote evidence is {collection!r}; infrastructure scope is unavailable/incomplete')
    if sha(manifest_path)!=ctx.get('remote_evidence_manifest_sha256'): raise EnvError('trusted remote manifest digest mismatch')
    if manifest.get('resource_policy_id')!=ctx.get('resource_policy_id'): raise EnvError('resource policy binding mismatch')
    scope=manifest.get('scope')
    if not isinstance(scope,dict) or scope.get('complete') is not True: raise EnvError('trusted evidence scope missing or incomplete')
    started=env_finite(ctx.get('answer_started_at_epoch'),'answer start')
    ended=env_finite(ctx.get('answer_ended_at_epoch'),'answer end')
    if started>ended: raise EnvError('invalid answer interval')
    if ctx.get('remote_evidence_scope')!=scope: raise EnvError('runner context is not bound to the exact trusted remote scope')
    if ctx.get('evidence_mode')=='case05-candidate-v5-8':
        for key in ('answer_started_at_epoch','answer_ended_at_epoch'):
            if env_finite(scope.get(key),f'scope.{key}')!=env_finite(ctx.get(key),key): raise EnvError(f'trusted scope {key} mismatch')
        if manifest.get('resource_policy_id')!='case05-candidate-v5-8': raise EnvError('wrong candidate resource policy id')
    else:
        if manifest.get('resource_policy_id')!='case05-author-supplement-v1-10': raise EnvError('wrong author replay resource policy id')
    author_mode=ctx.get('evidence_mode')=='case05-author-supplement-v1-10'
    expected_limit=10 if author_mode else 8
    if type(manifest.get('allocation_limit')) is not int or manifest.get('allocation_limit')!=expected_limit or type(manifest.get('max_concurrent_jobs')) is not int or manifest.get('max_concurrent_jobs')!=1: raise EnvError('case-05 resource policy metadata mismatch')
    jobs=manifest.get('jobs')
    if not isinstance(jobs,list): raise EnvError('trusted jobs must be an array')
    observed_jobs=scoped_observed_jobs(jobs,author_mode)
    count=sum(j.get('count_for_cap') is True for j in observed_jobs)
    if manifest.get('observed_allocations_total')!=count: raise EnvError('trusted allocation total disagrees with counted tagged jobs')
    if manifest.get('resource_violations') or any(j.get('resource_violations') for j in observed_jobs): raise CandidateError('trusted Slurm ledger records a resource-policy violation')
    limit=8
    if ctx.get('evidence_mode')=='case05-author-supplement-v1-10':
        limit=10
        policy=manifest.get('author_exception')
        expected_ids={str(j.get('job_id')) for j in observed_jobs if j.get('count_for_cap') is True}
        allowed_ids=set(str(x) for x in policy.get('authorized_job_ids',[])) if isinstance(policy,dict) and isinstance(policy.get('authorized_job_ids'),list) else set()
        ledger_ids=set(str(x) for x in policy.get('allocation_ids',[])) if isinstance(policy,dict) and isinstance(policy.get('allocation_ids'),list) else set()
        hashes=('whitelist_sha256','bundle_sha256','source_manifest_sha256','scheduler_snapshot_sha256')
        valid_hashes=isinstance(policy,dict) and all(re.fullmatch(r'[0-9a-f]{64}',str(policy.get(key,''))) for key in hashes)
        ledger=policy.get('allocation_ledger') if isinstance(policy,dict) else None
        ledger_map={str(x.get('job_id')):(str(x.get('state','')).upper(),str(x.get('exit_code',''))) for x in ledger if isinstance(x,dict)} if isinstance(ledger,list) else {}
        job_map={str(j.get('job_id')):(str(j.get('state','')).upper(),str(j.get('exit_code',''))) for j in observed_jobs if j.get('count_for_cap') is True}
        canceled_ids={jid for jid,(state,_) in job_map.items() if 'CANCEL' in state}
        declared_canceled=set(str(x) for x in policy.get('canceled_job_ids',[])) if isinstance(policy,dict) and isinstance(policy.get('canceled_job_ids'),list) else set()
        condition_map=policy.get('condition_job_ids') if isinstance(policy,dict) else None
        expected_condition_map=REFS['reference']['historical_author_condition_job_ids']
        ledger_rows=len(ledger) if isinstance(ledger,list) else 0
        auth_rows=policy.get('authorized_job_ids',[]) if isinstance(policy,dict) else []
        alloc_rows=policy.get('allocation_ids',[]) if isinstance(policy,dict) else []
        if not isinstance(policy,dict) or policy.get('whitelist_verified') is not True or policy.get('allocation_limit')!=10 or manifest.get('observed_allocations_total')!=10 or count!=10 or len(auth_rows)!=10 or len(alloc_rows)!=10 or ledger_rows!=10 or allowed_ids!=expected_ids or ledger_ids!=expected_ids or not valid_hashes or ledger_map!=job_map or declared_canceled!=canceled_ids or condition_map!={k:v for k,v in expected_condition_map.items()}:
            raise EnvError('author replay lacks exact ten-allocation whitelist evidence')
    elif ctx.get('evidence_mode')!='case05-candidate-v5-8':
        raise EnvError('unknown runner-selected evidence mode')
    if manifest.get('observed_allocations_total',count)>limit or count>limit: raise CandidateError('remote allocation budget exceeded')
    _validate_resource_ledger(observed_jobs)
    # Integrity-check every canonical file before allowing any parser to consume it.
    file_records=manifest.get('files')
    if not isinstance(file_records,list): raise EnvError('trusted files must be an array')
    by_rel={}
    for rec in file_records:
        if not isinstance(rec,dict): raise EnvError('malformed trusted file record')
        rel=rec.get('path'); digest=rec.get('sha256'); size=rec.get('bytes')
        if not isinstance(rel,str) or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts: raise EnvError('unsafe trusted relative path')
        p=TRUST/rel
        if any(parent.is_symlink() for parent in (p,*p.parents) if parent!=TRUST.parent and parent!=TRUST): raise EnvError(f'trusted file path contains a symlink: {rel}')
        if not p.resolve().is_relative_to(TRUST.resolve()) or not p.is_file(): raise EnvError(f'trusted file absent/nonregular/outside mount: {rel}')
        if type(size) is not int or size<0 or p.stat().st_size!=size or not isinstance(digest,str) or sha(p)!=digest: raise EnvError(f'trusted file integrity mismatch: {rel}')
        if rel in by_rel: raise EnvError(f'duplicate trusted file path: {rel}')
        by_rel[rel]=p
    return ctx,manifest,by_rel

def _validate_resource_ledger(jobs):
    import datetime
    intervals=[]
    for job in jobs:
        if job.get('count_for_cap') is not True: continue
        jid=str(job.get('job_id',''))
        if not jid.isdigit(): raise EnvError('trusted parent allocation has malformed job ID')
        try: cpus=int(job.get('alloc_cpus'))
        except (ValueError,TypeError): raise EnvError(f'job {jid} AllocCPUS is malformed')
        if cpus<1 or cpus>4: raise CandidateError(f'job {jid} exceeds the 4-CPU cap')
        try: nodes=int(job.get('nodes',job.get('nnodes',1)) or 1)
        except (ValueError,TypeError): raise EnvError(f'job {jid} node count is malformed')
        if nodes!=1: raise CandidateError(f'job {jid} exceeds the one-node cap')
        mem=str(job.get('req_mem','')).strip().upper()
        match=re.fullmatch(r'(\d+(?:\.\d+)?)([KMGTP]?)([CN]?)',mem)
        if not match: raise EnvError(f'job {jid} ReqMem is malformed')
        amount=float(match.group(1)); unit=match.group(2); per=match.group(3)
        factors={'K':1/1024/1024,'M':1/1024,'G':1,'T':1024,'P':1024*1024,'':1/1024/1024/1024}
        gib=amount*factors[unit]
        if per=='C': gib*=cpus
        elif per=='N':
            gib*=nodes
        if gib<=0 or gib>8: raise CandidateError(f'job {jid} exceeds the 8-GiB memory cap')
        timelimit=str(job.get('time_limit',job.get('timelimit','')))
        try:
            day_match=re.fullmatch(r'(\d+)-(\d{1,2}):(\d{2}):(\d{2})',timelimit)
            if day_match:
                days,hours,mins,secs=map(int,day_match.groups()); limit_seconds=days*86400+hours*3600+mins*60+secs
            else:
                parts=timelimit.split(':')
                if len(parts)==3: hours,mins,secs=map(int,parts); limit_seconds=hours*3600+mins*60+secs
                elif len(parts)==2: mins,secs=map(int,parts); limit_seconds=mins*60+secs
                else: raise ValueError('expected HH:MM:SS, MM:SS or D-HH:MM:SS')
        except (ValueError,IndexError): raise EnvError(f'job {jid} time limit malformed')
        if limit_seconds>1800: raise CandidateError(f'job {jid} exceeds the 30-minute wall limit')
        start=job.get('start'); end=job.get('end')
        state=str(job.get('state','')).upper()
        if not start or str(start).lower() in ('unknown','none','null',''):
            if 'CANCEL' in state or state in ('PENDING','CONFIGURING','SUSPENDED'): continue
            raise EnvError(f'job {jid} missing start timestamp')
        if not end or str(end).lower() in ('unknown','none','null',''):
            if state in ('PENDING','CONFIGURING','SUSPENDED','RUNNING','COMPLETING'): continue
            raise EnvError(f'job {jid} missing end timestamp')
        try:
            a=datetime.datetime.fromisoformat(str(start)); b=datetime.datetime.fromisoformat(str(end))
        except ValueError: raise EnvError(f'job {jid} has malformed start/end')
        if b<a: raise EnvError(f'job {jid} ends before it starts')
        intervals.append((a,b,jid))
    times=sorted({x for a,b,_ in intervals for x in (a,b)})
    for a,b in zip(times,times[1:]):
        mid=a+(b-a)/2
        concurrent=sum(1 for s,e,_ in intervals if s<=mid<e)
        if concurrent>1: raise CandidateError('remote jobs overlapped; concurrency cap is one')

def candidate_files():
    required=['execution-record.json','analysis.json','analysis.md']
    for name in required:
        p=FINAL/name
        if p.is_symlink() or not p.is_file(): raise CandidateError(f'required final artifact missing: {name}')
    data=json_file(FINAL/'analysis.json')
    ensure_finite_json(data)
    if data.get('schema_version')!=ANALYSIS_SCHEMA: raise CandidateError('analysis.json schema_version mismatch')
    if not isinstance(data.get('conditions'),dict) or set(data['conditions'])!={'A','B','C','D','E'}: raise CandidateError('analysis.json must provide exactly conditions A-E')
    if not isinstance(data.get('md_observations'),dict): raise CandidateError('analysis.json md_observations object missing')
    scope=data.get('evidence_scope')
    if not isinstance(scope,dict): raise CandidateError('analysis.json evidence_scope object missing')
    expected_limits={'optical_prediction':False,'equilibrium_ensemble_claim':False,'generalized_mechanism_claim':False,'E_is_field_matched':False,'trajectory_is_equilibrated':False,'a_b_same_meoh_dye_geometry':True,'c_d_same_meoh_frame':True,'d_is_constructed_h_rotation':True,'e_is_distinct_mecn_md':True}
    if any(scope.get(k) is not v for k,v in expected_limits.items()): raise CandidateError('analysis.json evidence scope must preserve the frozen claim limits and geometry relationships')
    if scope.get('conclusion') not in ('SUPPORTS_LOCAL','REFUTES_LOCAL','INCONCLUSIVE'): raise CandidateError('analysis.json conclusion must be evidence-bounded')
    return data

def verify_output_bytes(manifest, trusted_files):
    trusted_hashes={sha(p) for p in trusted_files.values()}
    if not FINAL.is_dir() or FINAL.is_symlink(): raise CandidateError('final output directory missing or symlinked')
    def require(rel):
        p=FINAL/rel
        if any(parent.is_symlink() for parent in (p,*p.parents) if parent!=FINAL.parent and parent!=FINAL): raise CandidateError(f'candidate output path contains a symlink: {rel}')
        if not p.resolve().is_relative_to(FINAL.resolve()) or not p.is_file(): raise CandidateError(f'required native candidate file absent/nonregular/outside final: {rel}')
        if sha(p) not in trusted_hashes: raise CandidateError(f'candidate artifact is not byte-identical to trusted remote evidence: {rel}')
        return p
    context=json.loads(CONTEXT.read_text(encoding='utf-8'))
    def require_stage(rel, stage):
        p=require(rel)
        if context.get('evidence_mode')!='case05-candidate-v5-8': return p
        digest=sha(p)
        records=[r for r in manifest.get('files',[]) if isinstance(r,dict) and r.get('sha256')==digest]
        expected=[j for j in manifest.get('jobs',[]) if isinstance(j,dict) and str(j.get('job_name','')).endswith(stage) and j.get('count_for_cap') is True]
        if len(expected)!=1: raise CandidateError(f'candidate must provide one unique {stage} allocation; observed {len(expected)}')
        jid=str(expected[0].get('job_id'))
        if not any(str(r.get('remote_relative_path','')).strip('/').startswith(f'stages/{stage}/') and jid in set(str(x) for x in r.get('observed_job_ids',[])) for r in records):
            raise CandidateError(f'{rel} is not linked to its trusted {stage} job/workdir')
        return p
    exec_path=FINAL/'execution-record.json'
    if exec_path.is_symlink() or not exec_path.is_file(): raise CandidateError('required execution-record.json missing/nonregular')
    # These are the retained native trajectory/control artifacts, not a summary-only handoff.
    for solvent in ('meoh','mecn'):
        for name in ('system.prmtop','system.inpcrd','system.pdb'):
            require_stage(f'md/{solvent}/{name}','prep')
        require_stage(f'md/{solvent}/build.leap','prep')
        for name in ('min.in','min.out','min.rst','heat.in','heat.out','heat.rst','heat.mdcrd','short.in','short.out','short.rst','short.mdcrd','native-sha256.txt','tleap.log'):
            require_stage(f'md/{solvent}/{name}',f'{solvent}-md')
    for name in ('topology-sha256.txt','parameters/antechamber.log','parameters/parmchk2.log','parameters/dye.mol2','parameters/dye.frcmod','parameters/ch3cn.prep','parameters/ch3cn.frcmod','parameters/ch3cn_210.pdb'):
        require_stage(f'md/{name}','prep')
    for name in ('preparation-execution-record.json','topology-summary.json'):
        p=FINAL/'md'/name
        if p.is_symlink() or not p.is_file(): raise CandidateError(f'required preparation record missing: {name}')
    prep_record=json_file(FINAL/'md/preparation-execution-record.json')
    top_summary=json_file(FINAL/'md/topology-summary.json')
    if not isinstance(prep_record,dict) or not isinstance(top_summary,dict): raise CandidateError('MD preparation records must be JSON objects')
    jobs_by_id={str(j.get('job_id')):j for j in manifest.get('jobs',[]) if isinstance(j,dict)}
    prep_job=jobs_by_id.get(str(prep_record.get('job_id')))
    if not prep_job or prep_job.get('count_for_cap') is not True: raise CandidateError('preparation execution record is not linked to a counted trusted Slurm allocation')
    prep_exit=prep_job.get('exit_code')
    try: prep_exit_int=int(str(prep_exit).split(':',1)[0])
    except ValueError: raise EnvError('trusted preparation exit code is malformed')
    try: declared_prep_exit=int(prep_record.get('slurm_job_exit_code',prep_record.get('exit_code')))
    except (ValueError,TypeError): raise CandidateError('preparation record Slurm exit code is malformed')
    if declared_prep_exit!=prep_exit_int: raise CandidateError('preparation summary does not preserve the trusted parent allocation exit code')
    if prep_record.get('native_tleap_exit_code')!=0 or prep_record.get('native_tleap_errors')!=0 or prep_record.get('native_tleap_warnings')!=0:
        raise CandidateError('native tleap stage did not pass its recorded posthoc review')
    systems=top_summary.get('systems')
    if not isinstance(systems,dict) or set(systems)!={'meoh','mecn'}: raise CandidateError('topology summary must cover both solvent systems')
    qdm=FINAL/'qm-derived'
    require('qm-derived/manifest.json')
    for stem in ('bare-meoh','bare-mecn','meoh-donor-candidate','meoh-constructed-oh-rotated-off','mecn-nearest'):
        for ext in ('.inp','.xyz'):
            require(f'qm-derived/{stem}{ext}')
    for stem in ('bare-meoh','bare-mecn','meoh-donor-candidate','meoh-constructed-oh-rotated-off','mecn-nearest'):
        for ext in ('.inp','.xyz','.out','.gbw','.molden.input'):
            qid={'bare-meoh':'A','bare-mecn':'B','meoh-donor-candidate':'C','meoh-constructed-oh-rotated-off':'D','mecn-nearest':'E'}[stem]
            require_stage(f'qm/{stem}{ext}',f'qm-{qid}')
        p=FINAL/'qm'/f'{stem}.job-record.json'
        if p.is_symlink() or not p.is_file(): raise CandidateError(f'required QM job metadata missing: qm/{stem}.job-record.json')
        record=json_file(p)
        if not isinstance(record,dict) or record.get('condition')!=stem: raise CandidateError(f'qm/{stem}.job-record.json condition mismatch')
        try: int(str(record.get('exit_code')).split(':',1)[0])
        except (ValueError,TypeError): raise CandidateError(f'qm/{stem}.job-record.json parent/native exit code is malformed')
        if 'native_exit_code' in record and record.get('native_exit_code')!=0: raise CandidateError(f'qm/{stem}.job-record.json reports a nonzero native ORCA exit')
        native_names={f'{stem}{ext}' for ext in ('.inp','.xyz','.out','.gbw','.molden.input','.sha256')}
        if not isinstance(record.get('native_files'),list) or set(record['native_files'])!=native_names: raise CandidateError(f'qm/{stem}.job-record.json native file list mismatch')
        if not isinstance(record.get('job_id'),(str,int)) or not str(record['job_id']).isdigit(): raise CandidateError(f'qm/{stem}.job-record.json job ID malformed')
    execution=json_file(FINAL/'execution-record.json')
    if not isinstance(execution,dict): raise CandidateError('execution record root must be an object')
    if execution.get('schema_version')!='case05-execution-record/v1': raise CandidateError('execution record schema version mismatch')
    if execution.get('software',{}).get('orca','')!='6.0.1': raise CandidateError('execution record must identify ORCA 6.0.1')
    allocs=execution.get('allocations')
    if not isinstance(allocs,list): raise CandidateError('execution record allocations array missing')
    claimed={str(a.get('job_id')) for a in allocs if isinstance(a,dict)}
    mode=json.loads(CONTEXT.read_text()).get('evidence_mode')
    if mode=='case05-author-supplement-v1-10':
        expected={str(j.get('job_id')) for j in manifest.get('jobs',[]) if isinstance(j,dict) and j.get('observed') is True and j.get('historical_source') is True and j.get('in_answer') is False and j.get('count_for_cap') is True}
    else:
        expected={str(j.get('job_id')) for j in manifest.get('jobs',[]) if isinstance(j,dict) and j.get('observed') is True and j.get('in_answer') is True and j.get('in_answer_interval',True) is True and j.get('count_for_cap') is True}
    if len(claimed)!=len(allocs) or claimed!=expected: raise CandidateError('execution record does not enumerate exactly the trusted in-scope allocation IDs')
    trusted_by_id={str(j.get('job_id')):j for j in manifest.get('jobs',[]) if isinstance(j,dict)}
    for item in allocs:
        if not isinstance(item,dict): raise CandidateError('execution record allocation rows must be objects')
        jid=str(item.get('job_id')); trusted=trusted_by_id[jid]
        if str(item.get('state','')).upper()!=str(trusted.get('state','')).upper() or str(item.get('exit_code',''))!=str(trusted.get('exit_code','')):
            raise CandidateError(f'execution record state/exit code for job {jid} disagrees with trusted Slurm evidence')
        if str(item.get('job_name',''))!=str(trusted.get('job_name','')): raise CandidateError(f'execution record name for job {jid} disagrees with trusted Slurm evidence')
        if str(item.get('alloc_cpus',''))!=str(trusted.get('alloc_cpus','')): raise CandidateError(f'execution record CPU allocation for job {jid} disagrees with trusted Slurm evidence')
        if str(item.get('req_mem',''))!=str(trusted.get('req_mem','')): raise CandidateError(f'execution record memory request for job {jid} disagrees with trusted Slurm evidence')
        if str(item.get('time_limit',''))!=str(trusted.get('time_limit','')): raise CandidateError(f'execution record time limit for job {jid} disagrees with trusted Slurm evidence')
    conditions=execution.get('conditions')
    analysis=json_file(FINAL/'analysis.json')
    if not isinstance(conditions,dict) or set(conditions)!={'A','B','C','D','E'}: raise CandidateError('execution record must map all five conditions')
    stems={'A':'bare-meoh','B':'bare-mecn','C':'meoh-donor-candidate','D':'meoh-constructed-oh-rotated-off','E':'mecn-nearest'}
    for cid,stem in stems.items():
        row=conditions[cid]
        if not isinstance(row,dict) or str(row.get('job_id'))!=str(analysis['conditions'][cid].get('native_job_id')) or row.get('stem')!=stem:
            raise CandidateError(f'execution record condition mapping disagrees for {cid}')
    inputs=execution.get('inputs')
    public_manifest=APP/'assets/public-artifact-manifest.json'
    if public_manifest.is_symlink() or not public_manifest.is_file(): raise EnvError('mounted public manifest is missing or non-regular')
    if not isinstance(inputs,dict) or inputs.get('public_artifact_manifest_sha256')!=sha(public_manifest) or inputs.get('qm_derived_manifest_sha256')!=sha(FINAL/'qm-derived/manifest.json'):
        raise CandidateError('execution record input manifest hashes are missing or inconsistent')
    output_record=execution.get('outputs')
    output_map=output_record.get('files') if isinstance(output_record,dict) else None
    if not isinstance(output_map,dict): raise CandidateError('execution record outputs.files map missing')
    actual_output_map={}
    for p in FINAL.rglob('*'):
        if p.is_symlink(): raise CandidateError(f'final output tree contains a symlink: {p.relative_to(FINAL)}')
        rel=p.relative_to(FINAL).as_posix()
        if p.is_file() and rel!='execution-record.json': actual_output_map[rel]=sha(p)
    if output_map!=actual_output_map: raise CandidateError('execution record outputs.files is not the exact final artifact path/hash inventory')
    return execution

SELECTOR_FLOAT_FIELDS = frozenset(('time_ps_from_short_segment', 'H_to_dyeO_A',
                                   'O_H_dyeO_angle_deg', 'closest_acceptor_or_donor_distance_A'))
SELECTOR_REPLAY_ABS_TOL = REFS['tolerances']['selector_replay_abs']

def selector_field_matches(field, actual, expected):
    if field in SELECTOR_FLOAT_FIELDS and expected is not None:
        return abs(finite_number(actual, f'selector.{field}') -
                   env_finite(expected, f'replayed selector.{field}')) <= SELECTOR_REPLAY_ABS_TOL
    return type(actual) is type(expected) and actual == expected

def replay_md_and_geometry():
    # The selector is a hash-pinned, read-only public asset mounted by the runner;
    # it is never run from candidate output. It deterministically reselects from
    # the submitted native trajectory under the evaluator's copy of the algorithm.
    tool=APP/'assets/tools/select_md_frames.py'
    prep=APP/'assets/tools/prepare_inputs.py'
    if tool.is_symlink() or prep.is_symlink() or not tool.is_file() or not prep.is_file(): raise EnvError('trusted public selector/preparation assets are unavailable')
    with tempfile.TemporaryDirectory(prefix='case05-selector-') as td:
        work=Path(td); env=dict(os.environ); env['PYTHONPATH']=str(tool.parent)
        cmd=[sys.executable,str(tool),'--meoh',str(FINAL/'md/meoh'),'--mecn',str(FINAL/'md/mecn'),'--out',str(work/'qm-derived')]
        proc=subprocess.run(cmd,cwd=str(APP),env=env,text=True,capture_output=True,timeout=180)
        if proc.returncode!=0: raise CandidateError(f'native trajectory selector replay failed: {proc.stderr[-1200:]}')
        replay=work/'qm-derived'; claimed=json_file(FINAL/'qm-derived/manifest.json')
        expected=json_file(replay/'manifest.json')
        if [j.get('id') for j in claimed.get('jobs',[])]!=['A','B','C','D','E']: raise CandidateError('candidate QM selector manifest must contain A-E')
        for key in ('meoh','mecn'):
            actual=claimed.get('selection_sources',{}).get(key); ref=expected.get('selection_sources',{}).get(key)
            if not isinstance(actual,dict) or not isinstance(ref,dict): raise CandidateError(f'{key} selector provenance missing')
            fields=('frame_1based','time_ps_from_short_segment','source_topology_sha256','source_pdb_sha256','source_trajectory_sha256','solvent_residue_atom_indices_1based','explicit_hbond_candidate','donor_H_index_1based','H_to_dyeO_A','O_H_dyeO_angle_deg','closest_acceptor_or_donor_distance_A')
            for field in fields:
                if not selector_field_matches(field,actual.get(field),ref.get(field)): raise CandidateError(f'{key} candidate selection differs from trusted selector replay: {field}')
        for stem in ('bare-meoh','bare-mecn','meoh-donor-candidate','meoh-constructed-oh-rotated-off','mecn-nearest'):
            for ext in ('.xyz','.inp'):
                got=(FINAL/'qm-derived'/f'{stem}{ext}').read_text(errors='replace')
                want=(replay/f'{stem}{ext}').read_text(errors='replace')
                # Ignore only comments/headers; coordinates and executable chemistry settings must match.
                if ext=='.xyz':
                    ga=got.splitlines(); wa=want.splitlines()
                    if ga[0]!=wa[0] or len(ga)!=len(wa): raise CandidateError(f'{stem}.xyz atom count mismatch')
                    for row,(g,w) in enumerate(zip(ga[2:],wa[2:]),3):
                        gf=g.split(); wf=w.split()
                        if gf[0]!=wf[0] or len(gf)<4 or any(abs(float(a)-float(b))>REFS['tolerances']['geometry_replay_angstrom'] for a,b in zip(gf[1:4],wf[1:4])): raise CandidateError(f'{stem}.xyz coordinate mismatch at row {row}')
                else:
                    # Preserve all keyword/settings/coordinates, permitting the stale comment-only first line in executed history.
                    gn='\n'.join(got.splitlines()[1:]); wn='\n'.join(want.splitlines()[1:])
                    if gn!=wn: raise CandidateError(f'{stem}.inp differs from replayed method/geometry after title comment')
        return claimed

def validate_md_native(manifest,evidence_mode='case05-author-supplement-v1-10'):
    # Minimal independent structure, cap, and trajectory-frame checks. Native byte
    # authenticity is separately enforced against the trusted collector snapshot.
    prep_record=json_file(FINAL/'md/preparation-execution-record.json')
    top_summary=json_file(FINAL/'md/topology-summary.json')
    if not isinstance(prep_record,dict) or not isinstance(top_summary,dict): raise CandidateError('MD preparation records must be JSON objects')
    systems=top_summary.get('systems')
    if not isinstance(systems,dict) or set(systems)!={'meoh','mecn'}: raise CandidateError('topology summary must cover both solvent systems')
    jobs_by_id={str(j.get('job_id')):j for j in manifest.get('jobs',[]) if isinstance(j,dict)}
    prep_job=jobs_by_id.get(str(prep_record.get('job_id')))
    if not prep_job or prep_job.get('count_for_cap') is not True: raise CandidateError('preparation execution record is not linked to a counted trusted Slurm allocation')
    try: prep_exit_int=int(str(prep_job.get('exit_code','')).split(':',1)[0]); declared_prep_exit=int(prep_record.get('slurm_job_exit_code',prep_record.get('exit_code')))
    except (ValueError,TypeError): raise CandidateError('preparation summary/Slurm exit code is malformed')
    if declared_prep_exit!=prep_exit_int: raise CandidateError('preparation summary does not preserve the trusted parent allocation exit code')
    if prep_record.get('native_tleap_exit_code')!=0 or prep_record.get('native_tleap_errors')!=0 or prep_record.get('native_tleap_warnings')!=0:
        raise CandidateError('native tleap stage did not pass its recorded posthoc review')
    for solv in ('meoh','mecn'):
        root=FINAL/'md'/solv
        hash_lines=(root/'native-sha256.txt').read_text(errors='replace').splitlines()
        hashes={}
        for line in hash_lines:
            m=re.fullmatch(r'([0-9a-f]{64})\s+\*?([^\s]+)',line.strip())
            if not m or m.group(2) in hashes: raise CandidateError(f'{solv} native checksum manifest is malformed or duplicated')
            hashes[m.group(2)]=m.group(1)
        required_native=('system.prmtop','system.inpcrd','system.pdb','min.in','min.out','min.rst','heat.in','heat.out','heat.rst','heat.mdcrd','short.in','short.out','short.rst','short.mdcrd')
        if not set(required_native).issubset(hashes): raise CandidateError(f'{solv} native checksum manifest omits required native files')
        for name in required_native:
            if hashes[name]!=sha(root/name): raise CandidateError(f'{solv} native checksum mismatch for {name}')
        top=(root/'system.prmtop').read_text(errors='replace').splitlines()
        ptr=next((i for i,x in enumerate(top) if x.strip()=='%FLAG POINTERS'),None)
        if ptr is None: raise CandidateError(f'{solv} PRMTOP lacks POINTERS')
        natom=int(top[ptr+2].split()[0])
        if natom>3000 or natom<78: raise CandidateError(f'{solv} NATOM violates published atom cap/minimum')
        row=systems[solv]
        if not isinstance(row,dict) or row.get('natom',row.get('atom_count'))!=natom or row.get('formal_dye_charge') not in (None,0):
            raise CandidateError(f'{solv} topology summary identity/atom count mismatch')
        if row.get('native_leap_errors') not in (None,0) or row.get('native_leap_warnings') not in (None,0): raise CandidateError(f'{solv} topology summary reports tleap errors/warnings')
        for extension in ('prmtop','inpcrd','pdb'):
            digest=row.get(f'{extension}_sha256')
            if digest is not None and digest!=sha(root/f'system.{extension}'):
                raise CandidateError(f'{solv} topology summary hash mismatch for {extension}')
        leap_log=(root/'tleap.log').read_text(errors='replace')
        if not re.search(r'Exiting LEaP:\s*Errors\s*=\s*0;\s*Warnings\s*=\s*0',leap_log,re.I):
            raise CandidateError(f'{solv} native tleap log does not report a clean topology build')
        pdb=[x for x in (root/'system.pdb').read_text(errors='replace').splitlines() if x.startswith(('ATOM  ','HETATM'))]
        if len(pdb)!=natom or len(pdb)<78: raise CandidateError(f'{solv} PDB/topology atom count mismatch')
        short=(root/'short.mdcrd').read_text(errors='replace').splitlines()
        if len(short)<2: raise CandidateError(f'{solv} trajectory is empty')
        nums=[]
        for line in short[1:]: nums.extend(re.findall(r'[-+]?(?:\d+\.\d*|\.\d+)(?:[Ee][-+]?\d+)?',line))
        strides=[3*natom+box for box in (3,6,0) if (3*natom+box)>0 and len(nums)%(3*natom+box)==0 and len(nums)//(3*natom+box)==100]
        if not strides: raise CandidateError(f'{solv} must retain exactly 100 short-MD frames')
        for logfile in ('min.out','heat.out','short.out'):
            txt=(root/logfile).read_text(errors='replace')
            if not re.search(r'\b5\.\s+TIMINGS\b',txt): raise CandidateError(f'{solv}/{logfile} missing Amber completion marker')
        minin=(root/'min.in').read_text(errors='replace')
        heatin=(root/'heat.in').read_text(errors='replace'); shortin=(root/'short.in').read_text(errors='replace')
        def namelist(text):
            values={}
            for key,val in re.findall(r'\b([A-Za-z][A-Za-z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)',text):
                values[key.lower()]=float(val)
            return values
        mn,ht,sh=namelist(minin),namelist(heatin),namelist(shortin)
        mx=re.search(r'maxcyc\s*=\s*(\d+)',minin,re.I)
        if not mx or not 1<=int(mx.group(1))<=200: raise CandidateError(f'{solv} minimization must not exceed the 200-cycle cap')
        if mn.get('imin')!=1 or mn.get('ncyc',0)>mn.get('maxcyc',0): raise CandidateError(f'{solv} minimization control settings mismatch')
        for label,vals in (('warm-start',ht),('diagnostic',sh)):
            if vals.get('nstlim')!=100 or vals.get('dt')!=0.002 or vals.get('ntwx')!=1 or vals.get('ioutfm')!=0:
                raise CandidateError(f'{solv} {label} must be 100 x 2-fs steps with per-step ASCII trajectory output')
            if vals.get('ntb')!=1 or vals.get('ntp')!=0 or vals.get('ntt')!=3 or vals.get('gamma_ln')!=2:
                raise CandidateError(f'{solv} {label} does not match the published constant-volume Langevin protocol')
        if ht.get('irest')!=0 or ht.get('ntx')!=1 or ht.get('tempi')!=50 or ht.get('temp0')!=298:
            raise CandidateError(f'{solv} warm-start initialization settings mismatch')
        if sh.get('irest')!=1 or sh.get('ntx')!=5 or sh.get('temp0')!=298:
            raise CandidateError(f'{solv} diagnostic restart/temperature settings mismatch')
        # All retained restarts must be readable and agree with the topology.
        import numpy as np
        def restart_coordinates(path):
            if path.read_bytes()[:3]==b'CDF':
                try:
                    from scipy.io import netcdf_file
                    with netcdf_file(str(path),mode='r',mmap=False) as nc:
                        rn=int(nc.dimensions.get('atom',0)); xyz=np.asarray(nc.variables['coordinates'][:],dtype=float).copy(); tm=float(np.asarray(nc.variables['time'].data).item())
                    if rn!=natom or xyz.shape!=(natom,3) or not math.isfinite(tm) or not np.isfinite(xyz).all(): raise ValueError('dimension or finite-value check failed')
                    return xyz.reshape(-1).tolist()
                except Exception as e: raise CandidateError(f'{solv} NetCDF restart {path.name} is malformed: {e}')
            lines=path.read_text(errors='replace').splitlines()
            if len(lines)<3: raise CandidateError(f'{solv} restart {path.name} is truncated')
            try:
                rn=int(lines[1].split()[0]); vals=[]
                for line in lines[2:]: vals.extend(float(line[i:i+12]) for i in range(0,len(line.rstrip()),12) if line[i:i+12].strip())
            except (ValueError,IndexError): raise CandidateError(f'{solv} restart {path.name} header/coordinates are malformed')
            if rn!=natom or len(vals)<3*natom or not all(math.isfinite(x) for x in vals): raise CandidateError(f'{solv} restart {path.name} coordinate count or values are invalid')
            return vals[:3*natom]
        for phase in ('min','heat'): restart_coordinates(root/f'{phase}.rst')
        restart_flat=restart_coordinates(root/'short.rst')
        traj_values=[float(x) for x in nums]
        valid_strides=[3*natom+box for box in (3,6,0) if (3*natom+box)>0 and len(traj_values)%(3*natom+box)==0 and len(traj_values)//(3*natom+box)==100]
        stride=valid_strides[0]; last=traj_values[-stride:][:3*natom]
        if any(abs(a-b)>REFS['tolerances']['short_restart_coordinates_angstrom'] for a,b in zip(last,restart_flat)): raise CandidateError(f'{solv} short restart coordinates do not match the final trajectory frame')
        md_record=json_file(root/'execution-record.json')
        if not isinstance(md_record,dict) or md_record.get('solvent')!=solv: raise CandidateError(f'{solv} MD execution record condition mismatch')
        scheduler=md_record.get('scheduler')
        if not isinstance(scheduler,dict): raise CandidateError(f'{solv} MD scheduler record missing')
        md_job=jobs_by_id.get(str(scheduler.get('job_id')))
        if not md_job or md_job.get('count_for_cap') is not True: raise CandidateError(f'{solv} MD execution record is not linked to a counted trusted allocation')
        if evidence_mode=='case05-candidate-v5-8' and not str(md_job.get('job_name','')).endswith(f'{solv}-md'):
            raise CandidateError(f'{solv} MD record refers to another solvent stage')
        try: scheduler_exit=int(str(md_job.get('exit_code','')).split(':',1)[0]); declared_exit=int(scheduler.get('exit_code'))
        except (ValueError,TypeError): raise CandidateError(f'{solv} MD scheduler exit code is malformed')
        if scheduler_exit!=declared_exit: raise CandidateError(f'{solv} MD summary does not preserve the trusted parent allocation exit code')
        if md_record.get('warm_start_steps')!=100 or md_record.get('production_diagnostic_steps')!=100 or md_record.get('timestep_fs')!=2 or md_record.get('equilibrium_claim') is not False:
            raise CandidateError(f'{solv} MD execution summary contradicts the fixed short diagnostic protocol')
    topology_hashes={}
    for line in (FINAL/'md/topology-sha256.txt').read_text(errors='replace').splitlines():
        m=re.fullmatch(r'([0-9a-f]{64})\s+\*?([^\s]+)',line.strip())
        if not m: raise CandidateError('topology checksum manifest is malformed')
        parts=PurePosixPath(m.group(2)).parts
        if len(parts)<2: raise CandidateError('topology checksum path is malformed')
        rel='/'.join(parts[-2:])
        if rel in topology_hashes: raise CandidateError('topology checksum manifest is duplicated')
        topology_hashes[rel]=m.group(1)
    expected_topology={f'{s}/system.{ext}' for s in ('meoh','mecn') for ext in ('prmtop','inpcrd','pdb')}
    if set(topology_hashes)!=expected_topology: raise CandidateError('topology checksum manifest must cover exactly both native Amber structures')
    for rel,digest in topology_hashes.items():
        solv,name=rel.split('/')
        if sha(FINAL/'md'/solv/name)!=digest: raise CandidateError(f'topology checksum mismatch: {rel}')

def validate_report_claims(data,selected):
    md=data['md_observations']
    refs=selected.get('selection_sources',{}) if isinstance(selected,dict) else {}
    for label,key in (('meoh','meoh'),('mecn','mecn')):
        claim=md.get(label); ref=refs.get(key)
        if not isinstance(claim,dict) or not isinstance(ref,dict): raise CandidateError(f'md_observations.{label} is missing')
        fields=('frame_1based','time_ps_from_short_segment','source_topology_sha256','source_pdb_sha256','source_trajectory_sha256','solvent_residue_atom_indices_1based','explicit_hbond_candidate','donor_H_index_1based','H_to_dyeO_A','O_H_dyeO_angle_deg','closest_acceptor_or_donor_distance_A')
        for field in fields:
            actual=claim.get(field); expected=ref.get(field)
            if isinstance(expected,(int,float)) and not isinstance(expected,bool):
                if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isfinite(actual) or abs(float(actual)-float(expected))>REFS['tolerances']['replayed_numeric_claim']:
                    raise CandidateError(f'md_observations.{label}.{field} disagrees with replayed trajectory selection')
            elif actual!=expected: raise CandidateError(f'md_observations.{label}.{field} disagrees with replayed trajectory selection')
    errors=[]; classes={}
    for cid,rec in data['conditions'].items():
        if not isinstance(rec,dict): raise CandidateError(f'{cid} condition must be an object')
        for field in ('orca_total_energy_hartree','homo_index_1based','homo_occupation','homo_energy_hartree','lumo_index_1based','lumo_occupation','lumo_energy_hartree'):
            finite_number(rec.get(field),f'{cid}.{field}')
        for field in ('homo_index_1based','lumo_index_1based','native_job_id'):
            if type(rec.get(field)) is not int: raise CandidateError(f'{cid}.{field} must be an integer')
        homo=rec['homo']; lumo=rec['lumo']
        for orb in (homo,lumo):
            for field in ('index_1based','occupation','energy_hartree','dye_percent','solvent_percent'):
                finite_number(orb.get(field),f'{cid}.{field}')
            if type(orb.get('index_1based')) is not int: raise CandidateError(f'{cid} orbital index must be an integer')
            if orb['index_1based']<1 or orb['occupation']<0: raise CandidateError(f'{cid} has invalid orbital identity')
            total=orb['dye_percent']+orb['solvent_percent']
            if abs(total-100)>POP_TOL_PP: raise CandidateError(f'{cid} orbital signed fragment populations do not sum to 100%')
            expected_class=orbital_classification(orb['dye_percent'],orb['solvent_percent'])
            if orb.get('classification')!=expected_class: raise CandidateError(f'{cid} orbital classification disagrees with signed populations')
        if homo['index_1based']!=rec['homo_index_1based'] or lumo['index_1based']!=rec['lumo_index_1based']: raise CandidateError(f'{cid} duplicated orbital index inconsistent')
        if cid in ('A','B'):
            if rec.get('solvent_atom_range') is not None or homo['solvent_percent']!=0 or lumo['solvent_percent']!=0: raise CandidateError(f'{cid} bare dye must not invent solvent fragment')
        elif rec.get('solvent_atom_range')!=[73,78]: raise CandidateError(f'{cid} explicit cluster solvent atoms must be 73-78')
        if rec.get('dye_atom_range')!=[1,72]: raise CandidateError(f'{cid} dye atom range must be 1-72')
        for key in ('native_input_sha256','native_output_sha256','molden_sha256','gbw_sha256'):
            if not isinstance(rec.get(key),str) or not re.fullmatch('[0-9a-f]{64}',rec[key]): raise CandidateError(f'{cid}.{key} missing/invalid SHA-256')
        classes[cid]={'homo_dye':homo['dye_percent'],'lumo_dye':lumo['dye_percent']}
    arithmetic=data.get('comparisons')
    if not isinstance(arithmetic,dict): raise CandidateError('explicit comparison arithmetic missing')
    for key in ('A_minus_B','C_minus_D'):
        item=arithmetic.get(key)
        if not isinstance(item,dict): raise CandidateError(f'{key} comparison missing')
        for field in ('delta_total_energy_hartree','delta_homo_energy_hartree','delta_lumo_energy_hartree'):
            finite_number(item.get(field),f'{key}.{field}')
        left,right=('A','B') if key=='A_minus_B' else ('C','D')
        for field,operand in (('delta_total_energy_hartree','orca_total_energy_hartree'),('delta_homo_energy_hartree','homo_energy_hartree'),('delta_lumo_energy_hartree','lumo_energy_hartree')):
            expected=data['conditions'][left][operand]-data['conditions'][right][operand]
            if abs(item[field]-expected)>REFS['tolerances']['replayed_numeric_claim']: raise CandidateError(f'{key}.{field} arithmetic mismatch')
        if item.get('sign_convention')!='left_minus_right' or item.get('units')!='hartree': raise CandidateError(f'{key} comparison lacks sign convention/units')
    if data['evidence_scope'].get('local_mechanism_conclusion') not in ('SUPPORTS_LOCAL_HB','REFUTES_LOCAL_HB','INCONCLUSIVE'):
        raise CandidateError('evidence_scope.local_mechanism_conclusion missing or unsupported')
    if data['evidence_scope']['local_mechanism_conclusion']=='SUPPORTS_LOCAL_HB' and md['meoh'].get('explicit_hbond_candidate') is not True:
        raise CandidateError('cannot support a local hydrogen-bond interpretation without the replayed MeOH donor geometry')
    text=(FINAL/'analysis.md').read_text(encoding='utf-8',errors='replace').lower()
    # Direct negation is a statement of the study's limits, not an overclaim.
    negation_guard=r"(?<!not )(?<!n't )(?<!n’t )(?<!never )"
    positive_patterns=(negation_guard+r'predict(?:s|ed|ing)? (?:an? )?(?:optical )?absorption',negation_guard+r'(?:is|are) (?:an? )?equilibrium ensemble',negation_guard+r'proves? (?:a )?(?:general|universal) mechanism',r'e is field matched')
    english_positive=any(re.search(pattern,text) for pattern in positive_patterns)
    cjk_positive=False
    for pattern in (r'预测.{0,6}(?:吸收|光谱|激发)',r'(?:证明|证实).{0,8}(?:一般|普遍|通用).{0,6}机制',r'(?:处于|属于|代表).{0,4}平衡(?:态|系综)'):
        for match in re.finditer(pattern,text):
            prefix=text[max(0,match.start()-10):match.start()]
            if not any(neg in prefix for neg in ('不','未','非','不能','没有','not','no ','without','cannot')): cjk_positive=True
    if english_positive or cjk_positive: raise CandidateError('analysis.md asserts an unsupported optical, ensemble, generalization or E-matching claim')
    if not text.strip(): raise CandidateError('analysis.md is empty')
    return classes

def check_against_trusted(data, manifest, files):
    # Native evidence hashes are authoritative. Files are listed by the trusted collector,
    # never selected by candidate-controlled paths.
    ctx=json_file(CONTEXT,True)
    available={sha(p) for p in files.values()}
    for cid,rec in data['conditions'].items():
        for field in ('native_input_sha256','native_output_sha256','molden_sha256'):
            if rec[field] not in available: raise CandidateError(f'{cid} {field} does not match collected native evidence')
    # Independently reconstruct populations from trusted native ORCA files. The
    # candidate's numerical claims are only compared to this calculation.
    lookup={sha(p):p for p in files.values()}
    file_records={}
    for record in manifest.get('files',[]):
        if isinstance(record,dict): file_records.setdefault(str(record.get('sha256')),[]).append(record)
    job_records={str(j.get('job_id')):j for j in manifest.get('jobs',[]) if isinstance(j,dict)}
    stems={'A':'bare-meoh','B':'bare-mecn','C':'meoh-donor-candidate','D':'meoh-constructed-oh-rotated-off','E':'mecn-nearest'}
    total_energies={}
    if ctx.get('evidence_mode')=='case05-author-supplement-v1-10':
        policy=manifest.get('author_exception',{})
        condition_job_ids=policy.get('condition_job_ids') if isinstance(policy,dict) else None
        if not isinstance(condition_job_ids,dict) or set(condition_job_ids)!={'A','B','C','D','E'}:
            raise EnvError('author condition-to-job whitelist is malformed')
        for cid in ('A','B','C','D','E'):
            if str(data['conditions'][cid].get('native_job_id'))!=str(condition_job_ids[cid]):
                raise CandidateError(f'{cid} native job ID differs from the pinned author condition map')
    for cid,rec in data['conditions'].items():
        native_job=str(rec.get('native_job_id',''))
        job=job_records.get(native_job)
        if ctx.get('evidence_mode')=='case05-author-supplement-v1-10':
            job_in_scope=isinstance(job,dict) and job.get('historical_source') is True and job.get('in_answer') is False
        else:
            job_in_scope=isinstance(job,dict) and job.get('in_answer') is True and job.get('in_answer_interval',True) is True
        if not native_job.isdigit() or not job or job.get('observed') is not True or not job_in_scope or job.get('count_for_cap') is not True:
            raise CandidateError(f'{cid} native job ID is not a trusted allocation in the selected evidence scope')
        stem=stems[cid]
        job_record=json_file(FINAL/'qm'/f'{stem}.job-record.json')
        if str(job_record.get('job_id'))!=native_job: raise CandidateError(f'{cid} job record ID differs from the trusted native job ID')
        if str(job_record.get('condition'))!=stem: raise CandidateError(f'{cid} job record condition identity mismatch')
        try: native_exit=int(str(job.get('exit_code','')).split(':',1)[0]); reported_exit=int(str(job_record.get('exit_code')).split(':',1)[0])
        except (ValueError,TypeError): raise CandidateError(f'{cid} native job record exit code is malformed')
        if native_exit!=reported_exit: raise CandidateError(f'{cid} job record does not preserve the trusted Slurm parent exit code')
        if job_record.get('state') is not None and str(job_record.get('state')).upper()!=str(job.get('state','')).upper():
            raise CandidateError(f'{cid} job record does not preserve the trusted Slurm parent state')
        if str(job_record.get('exit_code')) not in ('0','0:0'): raise CandidateError(f'{cid} job record does not report successful exit')
        if ctx.get('evidence_mode')=='case05-author-supplement-v1-10':
            if cid in ('B','E') and 'derived from pinned Slurm allocation ledger' not in str(job_record.get('source','')):
                raise CandidateError(f'{cid} author job record must disclose its derived status source')
        else:
            # A condition is bound to its own collector-enforced WorkDir, job-name
            # suffix, and canonical stage subtree; another successful ORCA job
            # cannot be substituted merely because all outputs are visible.
            stage=f'qm-{cid}'
            if not str(job.get('job_name','')).endswith(stage): raise CandidateError(f'{cid} trusted job name is not bound to its QM stage')
            work=str(job.get('work_dir','')).rstrip('/')
            if not work.endswith(f'/stages/{stage}'): raise CandidateError(f'{cid} trusted work directory is not bound to its QM stage')
        in_path=lookup[rec['native_input_sha256']]; out_path=lookup[rec['native_output_sha256']]; mo_path=lookup[rec['molden_sha256']]
        for digest in (rec['native_input_sha256'],rec['native_output_sha256'],rec['molden_sha256'],rec.get('gbw_sha256')):
            linked_records=linked_file_records(file_records,digest,native_job)
            if not linked_records: raise CandidateError(f'{cid} trusted file/job association mismatch')
            if ctx.get('evidence_mode')=='case05-candidate-v5-8' and not any(f'/stages/qm-{cid}/' in ('/'+str(r.get('remote_relative_path','')).strip('/')+'/') for r in linked_records):
                raise CandidateError(f'{cid} native file is outside its trusted QM stage')
        # Verify the native checksum sidecar against the bytes it names. It is an
        # ordinary retained native artifact; posthoc job-record JSON is not.
        sidecar_path=lookup.get(sha((FINAL/'qm'/f'{stems[cid]}.sha256')))
        if sidecar_path is None: raise CandidateError(f'{cid} native SHA-256 sidecar is not in the trusted snapshot')
        sidecar=sidecar_path.read_text(errors='replace')
        side_lines={}
        for line in sidecar.splitlines():
            m=re.fullmatch(r'([0-9a-f]{64})\s+\*?([^\s]+)',line.strip())
            if not m: raise CandidateError(f'{cid} native SHA-256 sidecar is malformed')
            side_lines[m.group(2)]=m.group(1)
        for ext in ('.inp','.xyz','.out','.gbw','.molden.input'):
            native_path=FINAL/'qm'/f'{stems[cid]}{ext}'
            if side_lines.get(native_path.name)!=sha(native_path): raise CandidateError(f'{cid} native checksum sidecar disagrees with {native_path.name}')
        side_digest=sha(FINAL/'qm'/f'{stems[cid]}.sha256')
        side_linked=linked_file_records(file_records,side_digest,native_job)
        if not side_linked: raise CandidateError(f'{cid} native SHA-256 sidecar is absent from trusted evidence/job association')
        if ctx.get('evidence_mode')=='case05-candidate-v5-8' and not any(str(r.get('remote_relative_path','')).strip('/').startswith(f'stages/qm-{cid}/') for r in side_linked):
            raise CandidateError(f'{cid} native checksum sidecar is outside its trusted QM stage')
        # Verify the ORCA deck actually describes the same atom ordering and
        # coordinates as the trusted selector's staged geometry.
        staged_xyz=FINAL/'qm-derived'/f'{stems[cid]}.xyz'
        staged_inp=FINAL/'qm-derived'/f'{stems[cid]}.inp'
        inp=in_path.read_text(errors='replace')
        if not staged_xyz.is_file() or not staged_inp.is_file(): raise CandidateError(f'{cid} staged QM geometry/deck is absent')
        def xyz_rows(path):
            lines=path.read_text(errors='replace').splitlines()
            if not lines or not lines[0].strip().isdigit(): raise CandidateError(f'{cid} malformed XYZ atom count in {path.name}')
            n=int(lines[0].strip()); rows=[]
            if len(lines)<n+2: raise CandidateError(f'{cid} truncated XYZ in {path.name}')
            for row in lines[2:2+n]:
                col=row.split()
                if len(col)<4: raise CandidateError(f'{cid} malformed XYZ coordinate row in {path.name}')
                vals=[finite_number(float(x),f'{cid} XYZ') for x in col[1:4]]
                rows.append((col[0],vals))
            return rows
        submitted=xyz_rows(FINAL/'qm'/f'{stems[cid]}.xyz'); staged=xyz_rows(staged_xyz)
        if len(submitted)!=len(staged) or any(a[0]!=b[0] or any(abs(x-y)>REFS['tolerances']['geometry_replay_angstrom'] for x,y in zip(a[1],b[1])) for a,b in zip(submitted,staged)):
            raise CandidateError(f'{cid} native XYZ differs from selector-replayed staged geometry')
        def without_title(path): return '\n'.join(path.read_text(errors='replace').splitlines()[1:]).strip()
        if without_title(in_path)!=without_title(staged_inp): raise CandidateError(f'{cid} native ORCA deck differs from selector-replayed staged deck')
        deck_xyz=[]
        in_lines=inp.splitlines(); star=next((i for i,x in enumerate(in_lines) if x.strip().lower().startswith('* xyz ')),None)
        if star is None: raise CandidateError(f'{cid} ORCA deck lacks xyz block')
        try:
            for row in in_lines[star+1:]:
                if row.strip().startswith('*'): break
                col=row.split()
                if col: deck_xyz.append((col[0],[float(v) for v in col[1:4]]))
        except (ValueError,IndexError): raise CandidateError(f'{cid} malformed ORCA coordinate block')
        if len(deck_xyz)!=len(submitted) or any(a[0]!=b[0] or any(abs(x-y)>REFS['tolerances']['geometry_replay_angstrom'] for x,y in zip(a[1],b[1])) for a,b in zip(deck_xyz,submitted)):
            raise CandidateError(f'{cid} native ORCA input coordinates differ from native XYZ')
        gbw=lookup.get(rec.get('gbw_sha256'))
        if gbw is None or not gbw.name.endswith('.gbw'): raise CandidateError(f'{cid} GBW is missing from trusted native evidence')
        if in_path.suffix!='.inp' or out_path.suffix!='.out' or not mo_path.name.endswith('.molden.input'): raise CandidateError(f'{cid} hashes do not identify the expected ORCA native artifact types')
        if in_path.name!=stems[cid]+'.inp' or out_path.name!=stems[cid]+'.out' or mo_path.name!=stems[cid]+'.molden.input': raise CandidateError(f'{cid} native files have incorrect condition identity')
        rawout=out_path.read_text(errors='replace')
        final=re.findall(r'FINAL SINGLE POINT ENERGY\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)',rawout,re.I)
        if not final or 'ORCA TERMINATED NORMALLY' not in rawout: raise CandidateError(f'{cid} native ORCA output lacks successful final energy/termination')
        energy=float(final[-1])
        if not math.isfinite(energy): raise CandidateError(f'{cid} native ORCA energy is nonfinite')
        inp=in_path.read_text(errors='replace')
        kwline=next((line.strip()[1:].strip() for line in inp.splitlines() if line.strip().startswith('!')),None)
        if kwline is None or set(kwline.split())!=set(('BP86','def2-SVP','def2/J','RI','TightSCF',f'CPCM({"Methanol" if cid in ("A","C","D") else "Acetonitrile"})','SP')) or '* xyz 0 1' not in inp:
            raise CandidateError(f'{cid} native ORCA input violates frozen method/charge/spin contract')
        echoed=re.search(r'>\s*!\s*(.+)',rawout)
        if not echoed or ' '.join(echoed.group(1).split())!=' '.join(kwline.split()): raise CandidateError(f'{cid} native ORCA echo disagrees with submitted method deck')
        charge=re.search(r'Total Charge\s+Charge\s*\.\.\.\.\s*([-+]?\d+)',rawout)
        mult=re.search(r'Multiplicity\s+Mult\s*\.\.\.\.\s*(\d+)',rawout)
        if not charge or int(charge.group(1))!=0 or not mult or int(mult.group(1))!=1: raise CandidateError(f'{cid} native ORCA output charge/spin echo invalid')
        try:
            actual=analyze(mo_path,in_path,out_path)
        except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as e:
            raise CandidateError(f'{cid} native Molden/ORCA evidence cannot be parsed or fails its AO-metric checks: {e}')
        for key,source in (('homo','homo'),('lumo','lumo')):
            claim=rec[key]; native=actual[source]
            if claim['index_1based']!=native['orbital_1_based']: raise CandidateError(f'{cid} {key} MO index inconsistent with native occupation')
            if abs(claim['occupation']-native['occupation'])>REFS['tolerances']['occupation']: raise CandidateError(f'{cid} {key} occupation mismatch')
            if abs(claim['energy_hartree']-native['energy_hartree'])>ENERGY_TOL: raise CandidateError(f'{cid} {key} energy mismatch')
            if abs(claim['dye_percent']-native['dye_atoms_1_72_percent'])>POP_TOL_PP: raise CandidateError(f'{cid} {key} dye population mismatch')
            if abs(claim['solvent_percent']-native['solvent_atoms_73_78_percent'])>POP_TOL_PP: raise CandidateError(f'{cid} {key} solvent population mismatch')
            expected_class=orbital_classification(native['dye_atoms_1_72_percent'],native['solvent_atoms_73_78_percent'])
            if claim.get('classification')!=expected_class: raise CandidateError(f'{cid} {key} classification mismatch')
            if abs(rec[f'{key}_index_1based']-native['orbital_1_based'])!=0: raise CandidateError(f'{cid} duplicated {key} index mismatch')
            if abs(rec[f'{key}_occupation']-native['occupation'])>REFS['tolerances']['occupation'] or abs(rec[f'{key}_energy_hartree']-native['energy_hartree'])>ENERGY_TOL: raise CandidateError(f'{cid} duplicated {key} metadata mismatch')
        if actual['all_mo_max_abs_orthogonality_error']>NORM_TOL or actual['all_mo_max_abs_norm_error']>NORM_TOL: raise CandidateError(f'{cid} native Molden AO metric check failed')
        total_energies[cid]=energy
        if abs(rec['orca_total_energy_hartree']-energy)>ENERGY_TOL: raise CandidateError(f'{cid} total energy does not match native ORCA output')
    # Check explicit solvent CPCM labels against condition identity.
    for cid,solvent in (('A','Methanol'),('B','Acetonitrile'),('C','Methanol'),('D','Methanol'),('E','Acetonitrile')):
        rec=data['conditions'][cid]; inp=lookup[rec['native_input_sha256']].read_text(errors='replace')
        if f'CPCM({solvent})' not in inp: raise CandidateError(f'{cid} CPCM solvent does not match the condition definition')
    observed=manifest.get('observed_allocations_total')
    if type(observed) is not int or observed<0: raise EnvError('invalid observed allocation count')
    if not isinstance(manifest.get('resource_policy_id'),str) or not manifest.get('resource_policy_id'): raise EnvError('missing resource policy id')

def main():
    try:
        ctx,manifest,files=trusted_inputs()
    except CandidateError as e:
        return emit('FAIL',0,str(e),1)
    except Exception as e:
        return emit('ENV_INVALID',None,str(e),2)
    try:
        verify_output_bytes(manifest,files)
        validate_md_native(manifest,ctx.get('evidence_mode'))
        selected=replay_md_and_geometry()
        data=candidate_files(); validate_report_claims(data,selected); check_against_trusted(data,manifest,files)
        return emit('PASS',1.0,'All five native-linked fixed-geometry comparisons and claims satisfy the scoring contract.',0)
    except CandidateError as e:
        return emit('FAIL',0,str(e),1)
    except (KeyError,TypeError,IndexError,AttributeError,ValueError) as e:
        return emit('FAIL',0,f'candidate schema/native evidence malformed: {e}',1)
    except Exception as e:
        return emit('ENV_INVALID',None,f'trusted scoring dependency or evaluator failure: {e}',2)

def emit(status,reward,reason,code):
    LOGS.mkdir(parents=True,exist_ok=True)
    result={'schema_version':'case05-verification/v1','status':status,'reason':reason,'reward':reward,'evidence_mode':None}
    try:
        c=json.loads(CONTEXT.read_text()); result['evidence_mode']=c.get('evidence_mode')
    except Exception: pass
    (LOGS/'verification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if reward is not None: (LOGS/'reward.txt').write_text(f'{reward:.1f}\n')
    else: (LOGS/'reward.txt').unlink(missing_ok=True)
    print(json.dumps(result,indent=2,allow_nan=False))
    return code

if __name__=='__main__': sys.exit(main())
