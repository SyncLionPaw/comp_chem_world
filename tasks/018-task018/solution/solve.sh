#!/bin/sh
# Real remote Oracle; no historical output copying and no trusted-context fabrication.
set -eu
: "${CCB_HPC_SSH_TARGET:?Configure the authorized SSH target}"
: "${CCB_HPC_REMOTE_ATTEMPT_ROOT:?Host runner must supply a fresh attempt root}"
: "${CCB_HPC_JOB_NAME_PREFIX:?Host runner must supply the job-name prefix}"
: "${CCB_HPC_ACCOUNT:?Configure the authorized scheduler account}"
: "${CCB_HPC_PARTITION:?Configure the authorized scheduler partition}"
python3 - <<'REMOTE_ORACLE_PY'
from __future__ import annotations
#!/usr/bin/env python3
"""Parse ORCA Molden files and check native MO overlap/population without SCF."""


import argparse
import hashlib
import json
import pathlib
import sys
import warnings
from importlib.metadata import version

import numpy as np
from iodata import load_one
from iodata.overlap import compute_overlap
from iodata.periodic import num2sym

NORM_TOLERANCE = 1e-4
BOHR_TO_ANGSTROM = 0.529177210903
COORDINATE_TOLERANCE_ANGSTROM = 1e-6
ENERGY_TOLERANCE_HARTREE = 5e-6


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
        if abs(native_occ - float(occ[index])) > 5e-5:
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


# Real remote workflow. The trusted evidence/context must be collected by the host runner.
import json,os,re,shlex,subprocess,time
from pathlib import Path
assets=Path(os.environ.get('APP','/app'))/'assets';final=Path(os.environ.get('APP','/app'))/'final'
host=os.environ['CCB_HPC_SSH_TARGET'];root=os.environ['CCB_HPC_REMOTE_ATTEMPT_ROOT'];prefix=os.environ['CCB_HPC_JOB_NAME_PREFIX'];account=os.environ['CCB_HPC_ACCOUNT'];partition=os.environ['CCB_HPC_PARTITION']
if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*',host):raise ValueError('Invalid configured SSH target')
if not re.fullmatch(r'/[A-Za-z0-9_./-]+',root) or '..' in Path(root).parts or root=='/':raise ValueError('Invalid remote attempt root')
if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',prefix):raise ValueError('Invalid job-name prefix')
for value in (account,partition):
 if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',value):raise ValueError('Invalid account/partition')
final.mkdir(parents=True,exist_ok=True)
if any(final.iterdir()):raise ValueError('Use a fresh final directory')
WORKFLOW_WALL_SECONDS=36000;JOB_QUEUE_SECONDS=3600;TOTAL_QUEUE_SECONDS=14400
workflow_deadline=time.monotonic()+WORKFLOW_WALL_SECONDS
ledger=[];mapping={};cumulative_queue_wait=0.0
QUEUE_STATES={'PENDING','CONFIGURING','REQUEUED','RESIZING'}
TERMINAL_STATES={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
def queue_wait_increment(state,elapsed,has_run):
 # Queue time ends at the first observed RUNNING; accounting gaps before then are charged conservatively.
 return elapsed if not has_run and (state is None or state in QUEUE_STATES) else 0.0
def run(args,limit):
 remaining=workflow_deadline-time.monotonic()
 if remaining<=0:raise TimeoutError('10-hour workflow wall-clock limit reached')
 return subprocess.run(args,check=True,text=True,capture_output=True,timeout=min(limit,remaining)).stdout.strip()
def remote(args):return run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=60',host,shlex.join([str(x) for x in args])],60)
def transfer(src,dst):run(['rsync','-az','--protect-args','-e','ssh -o BatchMode=yes -o ConnectTimeout=60',str(src),str(dst)],600)
def save(name,data):p=final/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2)+'\n')
remote(['mkdir','-p',root])
if remote(['find',root,'-mindepth','1','-maxdepth','1','-print','-quit']):raise ValueError('Remote attempt root must be empty')
remote(['mkdir','-p',root+'/public-source',root+'/stages'])
transfer(str(assets)+'/',host+':'+root+'/public-source/')
def stage(name):
 p=root+'/stages/'+name;remote(['mkdir','-p',p]);remote(['cp','-a',root+'/public-source/tools',p+'/tools']);return p
def submit(name,template,args):
 global cumulative_queue_wait
 if len(ledger)>=8:raise RuntimeError('Eight-allocation limit reached; no retries are allowed')
 if cumulative_queue_wait>=TOTAL_QUEUE_SECONDS:raise RuntimeError('Cumulative queue-wait cap (14400 s) reached; stop before submitting another allocation')
 p=root+'/stages/'+name
 cmd=['sbatch','--parsable','--account='+account,'--partition='+partition,'--chdir='+p,'--job-name='+prefix+name,'--output='+p+'/slurm.%j.out','--error='+p+'/slurm.%j.err',p+'/'+template,*args]
 jid=remote(cmd).split(';')[0]
 if not jid.isdigit():raise RuntimeError('Scheduler did not return a parent job ID')
 row={'job_id':jid,'stage':name};ledger.append(row);save('scheduler-ledger.json',ledger)
 queue_wait=0.0;last_poll=time.monotonic();job_deadline=None;has_run=False;last_observed_state=None
 while time.monotonic()<workflow_deadline:
  rows=remote(['sacct','-n','-P','-j',jid,'--format=JobIDRaw,JobName,State,ExitCode,AllocCPUS,ReqMem,Timelimit']).splitlines()
  parent=next((s.split('|') for s in rows if s.startswith(jid+'|')),None)
  now=time.monotonic();elapsed=now-last_poll;last_poll=now
  observed_state=parent[2].split()[0] if parent else None
  queue_wait+=queue_wait_increment(last_observed_state,elapsed,has_run)
  if observed_state=='RUNNING' and job_deadline is None:
   has_run=True;job_deadline=now+1800+120
  row.update(queue_wait_seconds=round(queue_wait,1),cumulative_queue_wait_seconds=round(cumulative_queue_wait+queue_wait,1),observed_state=(parent[2] if parent else 'ACCOUNTING_PENDING'))
  save('scheduler-ledger.json',ledger)
  if parent:
   _,jobname,state,exitcode,cpus,mem,limit,*_=parent
   if state.split()[0] in TERMINAL_STATES:
    cumulative_queue_wait+=queue_wait
    row.update(job_name=jobname,state=state,exit_code=exitcode,alloc_cpus=cpus,req_mem=mem,time_limit=limit,queue_wait_seconds=round(queue_wait,1),cumulative_queue_wait_seconds=round(cumulative_queue_wait,1));save('scheduler-ledger.json',ledger)
    if state!='COMPLETED' or exitcode!='0:0':raise RuntimeError('Remote stage failed; preserve its allocation and logs: '+str(row))
    return row
  last_observed_state=observed_state
  if not has_run and (queue_wait>=JOB_QUEUE_SECONDS or cumulative_queue_wait+queue_wait>=TOTAL_QUEUE_SECONDS):raise RuntimeError('Queue-wait limit reached before first RUNNING; preserve allocation and stop: '+str(row))
  if job_deadline is not None and now>=job_deadline:raise TimeoutError('Remote allocation exceeded 1800 s runtime plus 120 s accounting grace; preserve allocation and do not submit further jobs: '+str(row))
  time.sleep(min(10,max(0,workflow_deadline-time.monotonic())))
 cumulative_queue_wait+=queue_wait
 raise TimeoutError('10-hour workflow wall-clock limit reached; stop before further submission and inspect allocation '+jid)
prep=stage('prep')
# The public preparation template accepts only the output workspace; stage its inputs locally.
remote(['cp','-a',root+'/public-source/inputs',prep+'/inputs'])
preprow=submit('prep','tools/templates/amber-prepare.sbatch',[prep+'/md'])
(final/'md').mkdir();transfer(host+':'+prep+'/md/',str(final/'md')+'/')
for solvent in ('meoh','mecn'):
 p=stage(solvent+'-md');remote(['mkdir','-p',p+'/md']);remote(['cp','-a',prep+'/md/'+solvent,p+'/md/'+solvent])
 submit(solvent+'-md','tools/templates/amber-short-md.sbatch',[solvent,p+'/md'])
 transfer(host+':'+p+'/md/'+solvent+'/',str(final/'md'/solvent)+'/')
qdm=root+'/qm-derived'
remote(['python3',root+'/public-source/tools/select_md_frames.py','--meoh',root+'/stages/meoh-md/md/meoh','--mecn',root+'/stages/mecn-md/md/mecn','--out',qdm])
(final/'qm-derived').mkdir();transfer(host+':'+qdm+'/',str(final/'qm-derived')+'/')
selected=json.loads((final/'qm-derived/manifest.json').read_text());(final/'qm').mkdir()
for job in selected['jobs']:
 cid=job['id'];stem=job['condition'];p=stage('qm-'+cid)
 remote(['cp',root+'/public-source/inputs/qm/templates/orca-singlepoint.sbatch',p+'/orca-singlepoint.sbatch'])
 row=submit('qm-'+cid,'orca-singlepoint.sbatch',[qdm+'/'+stem+'.inp',p+'/native'])
 transfer(host+':'+p+'/native/',str(final/'qm')+'/');mapping[cid]={'job_id':row['job_id'],'stem':stem}
# Retain scheduler-derived facts and parse actual preparation diagnostics.
record=json.loads((final/'md/preparation-execution-record.json').read_text());record['slurm_job_exit_code']=int(preprow['exit_code'].split(':')[0]);errors=[];warnings=[]
for solvent in ('meoh','mecn'):
 text=(final/'md'/solvent/'tleap.log').read_text();matches=re.findall(r'Exiting LEaP:\s*Errors\s*=\s*(\d+);\s*Warnings\s*=\s*(\d+)',text,re.I)
 if not matches:raise ValueError('No native TLeap completion summary')
 error,warning=map(int,matches[-1]);errors.append(error);warnings.append(warning)
record.update(native_tleap_exit_code=0,native_tleap_errors=sum(errors),native_tleap_warnings=sum(warnings));save('md/preparation-execution-record.json',record)
if any(errors+warnings):raise ValueError('Preparation needs scientific review; do not suppress native errors/warnings')
conditions={}
def classification(dye,solvent):
 if any(v<-.1 or v>100.1 for v in (dye,solvent)):return 'AMBIGUOUS'
 return 'DYE_DOMINANT' if dye>=80 else ('SOLVENT_DOMINANT' if dye<=20 and solvent>=80 else 'MIXED')
for cid,row in mapping.items():
 stem=row['stem'];base=final/'qm'/stem;native=analyze(Path(str(base)+'.molden.input'),Path(str(base)+'.inp'),Path(str(base)+'.out'))
 energies=re.findall(r'FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)',Path(str(base)+'.out').read_text());energy=float(energies[-1])
 data={'native_job_id':int(row['job_id']),'dye_atom_range':[1,72],'solvent_atom_range':None if cid in 'AB' else [73,78],'orca_total_energy_hartree':energy}
 for field,ext in [('native_input_sha256','.inp'),('native_output_sha256','.out'),('molden_sha256','.molden.input'),('gbw_sha256','.gbw')]:data[field]=hashlib.sha256(Path(str(base)+ext).read_bytes()).hexdigest()
 for key in ['homo','lumo']:
  mo=native[key];orb={'index_1based':mo['orbital_1_based'],'occupation':mo['occupation'],'energy_hartree':mo['energy_hartree'],'dye_percent':mo['dye_atoms_1_72_percent'],'solvent_percent':mo['solvent_atoms_73_78_percent']};orb['classification']=classification(orb['dye_percent'],orb['solvent_percent']);data[key]=orb
  for field in ['index_1based','occupation','energy_hartree']:data[key+'_'+field]=orb[field]
 conditions[cid]=data
comparisons={}
for left,right in [('A','B'),('C','D')]:
 row={'sign_convention':'left_minus_right','units':'hartree'}
 for target,field in [('delta_total_energy_hartree','orca_total_energy_hartree'),('delta_homo_energy_hartree','homo_energy_hartree'),('delta_lumo_energy_hartree','lumo_energy_hartree')]:row[target]=conditions[left][field]-conditions[right][field]
 comparisons[left+'_minus_'+right]=row
observations=selected['selection_sources']
for row in observations.values():
 for field in ['H_to_dyeO_A','O_H_dyeO_angle_deg','donor_H_index_1based']:row.setdefault(field,None)
hb=observations['meoh']['explicit_hbond_candidate'];delta=comparisons['C_minus_D']['delta_total_energy_hartree'];local='INCONCLUSIVE' if not hb or abs(delta)<=1e-5 else ('SUPPORTS_LOCAL_HB' if delta<0 else 'REFUTES_LOCAL_HB')
scope={'optical_prediction':False,'equilibrium_ensemble_claim':False,'generalized_mechanism_claim':False,'E_is_field_matched':False,'trajectory_is_equilibrated':False,'a_b_same_meoh_dye_geometry':True,'c_d_same_meoh_frame':True,'d_is_constructed_h_rotation':True,'e_is_distinct_mecn_md':True,'conclusion':{'INCONCLUSIVE':'INCONCLUSIVE','SUPPORTS_LOCAL_HB':'SUPPORTS_LOCAL','REFUTES_LOCAL_HB':'REFUTES_LOCAL'}[local],'local_mechanism_conclusion':local}
save('analysis.json',{'schema_version':'case05-analysis/v1','conditions':conditions,'comparisons':comparisons,'evidence_scope':scope,'md_observations':observations})
(final/'analysis.md').write_text('Both trajectories are short diagnostic segments, not equilibrated samples. A/B compare the two CPCM media on identical selected dye coordinates; C/D compare the same sampled methanol complex with a constructed donor-H rotation. E is a distinct acetonitrile configuration and is not field-matched. Signed overlap-aware fragment populations and energies were calculated from native ORCA/Molden files, with all-MO normalization and orthogonality checks. The C-D energy screen is local and also includes geometric strain; it does not establish a general hydrogen-bond mechanism. GGA delocalization and the small non-diffuse basis limit charge-transfer interpretation. Orbital gaps are not optical excitation energies.\n\n'+json.dumps({'comparisons':comparisons,'local_screen':local,'observations':observations},indent=2)+'\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
execution={'schema_version':'case05-execution-record/v1','software':{'orca':'6.0.1','amber':'20; native SANDER headers retained'},'allocations':[{k:v for k,v in row.items() if k!='stage'} for row in ledger],'conditions':mapping,'inputs':{'public_artifact_manifest_sha256':sha(assets/'public-artifact-manifest.json'),'qm_derived_manifest_sha256':sha(final/'qm-derived/manifest.json')},'outputs':{}}
# Nested native execution-record files remain in the exact inventory.
execution['outputs']['files']={str(p.relative_to(final)):sha(p) for p in final.rglob('*') if p.is_file() and p.relative_to(final).as_posix()!='execution-record.json'}
save('execution-record.json',execution)
print('Eight real allocations completed. The host runner must independently collect trusted evidence before scoring.')

REMOTE_ORACLE_PY
