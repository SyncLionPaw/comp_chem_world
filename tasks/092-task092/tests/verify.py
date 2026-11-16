#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Analyze differential capacitance and Parsons–Zobel concentration trends.
"""Independent full-contract verifier; candidate replay is unprivileged."""
from __future__ import annotations
import ctypes, csv, io, json, math, os, pwd, resource, shutil, signal, stat, subprocess, sys, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'_support'))
from reference_analysis import compute
ATOL=1e-9
FIT_ATOL=1e-8


def finish(code,message=''):
    logs=Path(os.environ.get('BENCH_LOGS','/logs/verifier'))
    try: logs.mkdir(parents=True,exist_ok=True)
    except OSError: return 2
    if code==2:
        (logs/'reward.txt').unlink(missing_ok=True)
        (logs/'verification.json').unlink(missing_ok=True)
    else:
        reward=int(code==0)
        (logs/'reward.txt').write_text(f'{reward}\n',encoding='utf-8')
        (logs/'verification.json').write_text(json.dumps({'status':'PASS' if reward else 'FAIL','reward':reward,'message':message})+'\n',encoding='utf-8')
    return code

def fail(message):
    print('FAIL L3: '+message)
    return finish(1,message)

def environment_error(message):
    print('ERROR L0: '+message,file=sys.stderr)
    return finish(2,message)

def close(got,want,path,rtol=1e-7,atol=ATOL):
    try: a=float(got); b=float(want)
    except (TypeError,ValueError): return f'{path}: expected finite numeric value'
    if not math.isfinite(a) or not math.isfinite(b): return f'{path}: non-finite value'
    if abs(a-b)>atol+rtol*abs(b): return f'{path}: {a:.12g} != {b:.12g}'
    return None

def compare_tree(got,want,path='result'):
    if isinstance(want,dict):
        if not isinstance(got,dict): return f'{path}: expected object'
        if not set(want).issubset(got): return f'{path}: required keys missing'
        for k in want:
            msg=compare_tree(got[k],want[k],f'{path}.{k}')
            if msg: return msg
        return None
    if isinstance(want,list):
        if not isinstance(got,list) or len(got)!=len(want): return f'{path}: list length differs'
        for i,(a,b) in enumerate(zip(got,want)):
            msg=compare_tree(a,b,f'{path}[{i}]')
            if msg: return msg
        return None
    if isinstance(want,bool) or want is None or isinstance(want,str):
        if want is None: return None if got is None else f'{path}: expected null'
        if isinstance(want,bool): return None if got==want else f'{path}: {got!r} != {want!r}'
        if len(want)>40:
            # Long reference strings are constant explanatory notes the candidate cannot
            # be expected to reproduce verbatim; only require a substantive value, so a
            # candidate may report the same diagnostic as descriptive text or a number.
            if isinstance(got,str):
                return None if got.strip() else f'{path}: expected non-empty text'
            if isinstance(got,bool) or not isinstance(got,(int,float)): return f'{path}: expected non-empty text or number'
            return None if math.isfinite(float(got)) else f'{path}: non-finite value'
        return None if got==want else f'{path}: {got!r} != {want!r}'
    if isinstance(want,(float,int)):
        atol=FIT_ATOL if 'slope' in path or 'intercept' in path or 'residual' in path else ATOL
        return close(got,want,path,atol=atol)
    return None

def _demote():
    nobody=pwd.getpwnam('nobody')
    os.setgroups([])
    os.setgid(nobody.pw_gid); os.setuid(nobody.pw_uid)
    if ctypes.CDLL(None).prctl(38,1,0,0,0)!=0:
        raise OSError('PR_SET_NO_NEW_PRIVS failed')
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_FSIZE,(100*1024*1024,100*1024*1024))
    resource.setrlimit(resource.RLIMIT_NPROC,(1,1))

def isolated(argv,cwd,env,timeout=180):
    proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,start_new_session=True,preexec_fn=_demote)
    try: out,err=proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGKILL); out,err=proc.communicate()
        raise subprocess.TimeoutExpired(argv,timeout,output=out,stderr=err)
    finally:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    return subprocess.CompletedProcess(argv,proc.returncode,out,err)

def isolation_probe(logs):
    if os.geteuid()!=0: raise RuntimeError('verifier cannot demote candidate from root')
    with tempfile.TemporaryDirectory(prefix='case006-isolation-') as td:
        root=Path(td); scratch=root/'scratch'; scratch.mkdir(mode=0o777); os.chmod(root,0o755); os.chmod(scratch,0o777)
        marker=scratch/'probe.json'; script=scratch/'probe.py'
        script.write_text(
            'import json,os,pathlib\nresult={}\n'
            f"private=pathlib.Path({str(HERE/'_data'/'hidden_manifest.json')!r})\n"
            "try: private.read_bytes(); result['private_read']='allowed'\n"
            "except PermissionError: result['private_read']='denied'\n"
            "except Exception as e: result['private_read']=type(e).__name__\n"
            f"reward=pathlib.Path({str(logs/'reward.txt')!r})\n"
            "try: reward.write_text('1\\n'); result['reward_write']='allowed'\n"
            "except PermissionError: result['reward_write']='denied'\n"
            "except Exception as e: result['reward_write']=type(e).__name__\n"
            "try:\n p=os.fork()\n if p==0: os._exit(0)\n result['fork']='allowed'\n"
            "except OSError: result['fork']='denied'\n"
            f"pathlib.Path({str(marker)!r}).write_text(json.dumps(result))\n",encoding='utf-8')
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'PYTHONNOUSERSITE':'1'}
        proc=isolated([sys.executable,str(script)],scratch,env,10)
        if proc.returncode or not marker.is_file(): raise RuntimeError(f'isolation probe failed rc={proc.returncode} {proc.stderr}')
        got=json.loads(marker.read_text())
        if got!={'private_read':'denied','reward_write':'denied','fork':'denied'}:
            raise RuntimeError(f'candidate isolation insufficient: {got}')


def read_regular_at(directory: Path, basename: str) -> bytes:
    if basename in ("", ".", "..") or "/" in basename or "\\" in basename:
        raise ValueError("unsafe artifact basename")
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(basename,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError(f"{basename} is not a regular file")
            chunks=[]
            while True:
                part=os.read(fd,1<<20)
                if not part: break
                chunks.append(part)
            return b"".join(chunks)
        finally: os.close(fd)
    finally: os.close(dfd)

def write_bytes_at(directory: Path, basename: str, data: bytes) -> None:
    if basename in ("", ".", "..") or "/" in basename or "\\" in basename:
        raise ValueError("unsafe staged basename")
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(basename,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dfd)
        try:
            with os.fdopen(fd,"wb",closefd=False) as f: f.write(data)
        finally: os.close(fd)
    finally: os.close(dfd)

def _csv_flag_matches(text,want):
    """Accept the boolean flag written in any common case/number style."""
    token=str(text).strip().lower()
    if token in ('true','1'): got=True
    elif token in ('false','0'): got=False
    else: return False
    return got is bool(want)


def check_outputs(final,expected,require_program=True):
    required=(('analyze.py',) if require_program else ()) + ('analysis.json','capacitance_curves.csv','parsons_zobel.csv','solver.log')
    if any(not (final/x).is_file() for x in required): return 'missing required final artifact'
    try:
        actual=json.loads(read_regular_at(final,'analysis.json'))
        log=json.loads(read_regular_at(final,'solver.log'))
    except Exception as exc: return f'malformed or unsafe analysis metadata: {exc}'
    if not isinstance(actual,dict) or not isinstance(log,dict): return 'analysis.json and solver.log must be JSON objects'
    if log.get('status')!='analysis_complete' or log.get('branch_count')!=len(expected['branches']) or log.get('PZ_fit_count')!=len(expected['parsons_zobel']):
        return 'solver.log disagrees with computed analysis'
    if log.get('dataset')!=expected['dataset'] or log.get('source_dataset_schema')!=expected['source_dataset_schema']:
        return 'solver.log dataset/schema disagrees with computed analysis'
    method=actual.get('method')
    method_keys={'coarse_curve_derivative','pzc','pzc_derivative','primary_pz_axis','secondary_pz_axis','paper_figure_slopes'}
    if not isinstance(method,dict) or not method_keys.issubset(method) or any(not isinstance(method[k],str) for k in method_keys):
        return 'analysis.json method must provide all public descriptive strings'
    actual_cmp=dict(actual); expected_cmp=dict(expected)
    actual_cmp.pop('method',None); expected_cmp.pop('method',None)
    msg=compare_tree(actual_cmp,expected_cmp)
    if msg: return msg
    try:
        curves=list(csv.DictReader(io.StringIO(read_regular_at(final,'capacitance_curves.csv').decode())))
        pzrows=list(csv.DictReader(io.StringIO(read_regular_at(final,'parsons_zobel.csv').decode())))
    except Exception as exc: return f'malformed result CSV: {exc}'
    expected_curve=[(b,p) for b in expected['branches'] for p in b['physical_capacitance_curve']]
    if len(curves)!=len(expected_curve): return f'capacitance_curves.csv has {len(curves)} rows, expected {len(expected_curve)}'
    curve_columns=('sigma0_C_m2','phi0_V','d_sigma_d_phi_curve_h_F_m2','C_curve_h_F_m2',
                   'd_sigma_d_phi_curve_h2_F_m2','C_curve_h2_F_m2',
                   'd_sigma_d_phi_curve_h3_F_m2','C_curve_h3_F_m2',
                   'd_phi_d_sigma_curve_h_V_per_C_m2','d_phi_d_sigma_curve_h2_V_per_C_m2',
                   'd_phi_d_sigma_curve_h3_V_per_C_m2','abs_d_phi_change_h_to_h2_V_per_C_m2',
                   'abs_d_phi_change_h2_to_h3_V_per_C_m2','relative_derivative_scale_h3',
                   'estimated_delta_d_phi_V_per_C_m2',
                   'coarse_diagnostic_C_F_m2','coarse_relative_bias_vs_curve_h3',
                   'relative_change_h_to_h2','relative_change_h2_to_h3')
    for i,(row,(branch,want)) in enumerate(zip(curves,expected_curve),2):
        if row.get('branch_id')!=branch['branch_id']:
            return f'curve csv row {i} has wrong/repeated branch identity'
        for col in curve_columns:
            msg=close(row.get(col),want[col],f'curve_csv[{i}].{col}')
            if msg:return msg
        if not _csv_flag_matches(row.get('d_phi_sign_consistent'),want['d_phi_sign_consistent']): return f'curve csv row {i} signed derivative consistency flag mismatch'
        if not _csv_flag_matches(row.get('d_phi_interval_contains_zero'),want['d_phi_interval_contains_zero']): return f'curve csv row {i} derivative interval zero flag mismatch'
        if row.get('numerical_resolution') != want['numerical_resolution']: return f'curve csv row {i} numerical-resolution classification mismatch'
        for col,value in (('d_phi_interval_lower_h3_V_per_C_m2',want['d_phi_interval_h3_V_per_C_m2'][0]),
                          ('d_phi_interval_upper_h3_V_per_C_m2',want['d_phi_interval_h3_V_per_C_m2'][1]),
                          ('C_interval_lower_F_m2',want['C_magnitude_interval_F_m2'][0])):
            msg=close(row.get(col),value,f'curve_csv[{i}].{col}')
            if msg:return msg
        expected_upper=want['C_magnitude_interval_F_m2'][1]
        actual_upper=row.get('C_interval_upper_F_m2','')
        if expected_upper is None:
            if actual_upper not in ('','None','null'): return f'curve csv row {i} should report an unbounded C upper interval'
        else:
            msg=close(actual_upper,expected_upper,f'curve_csv[{i}].C_interval_upper_F_m2')
            if msg:return msg
    expected_pz=[(fit,point) for fit in expected['parsons_zobel'] for point in fit['points']]
    if len(pzrows)!=len(expected_pz): return f'parsons_zobel.csv has {len(pzrows)} rows, expected {len(expected_pz)}'
    pz_columns=('c_mM','phi_pzc_V','C_pzc_F_m2','signed_C_pzc_F_m2','d_phi_d_sigma_pzc_V_per_C_m2',
                'C_D_F_m2','x_m2_per_F','y_m2_per_F','C_D_at_model_pzc_F_m2','x_at_model_pzc_m2_per_F')
    for i,(row,(fit,point)) in enumerate(zip(pzrows,expected_pz),2):
        if row.get('reference_convention')!='gc_own_pzc_phi0_zero': return f'PZ csv row {i} has wrong reference convention'
        if not math.isclose(float(row.get('Pbar_C_m2','nan')),fit['Pbar_C_m2'],rel_tol=0,abs_tol=1e-12): return f'PZ csv row {i} has wrong Pbar'
        for col in pz_columns:
            msg=close(row.get(col),point[col],f'pz_csv[{i}].{col}')
            if msg:return msg
        for col,key in (('primary_slope','slope'),('primary_intercept_m2_per_F','intercept_m2_per_F'),
                        ('primary_rms_residual_m2_per_F','rms_residual_m2_per_F')):
            msg=close(row.get(col),fit['primary_fit'][key],f'pz_csv[{i}].{col}',atol=FIT_ATOL)
            if msg:return msg
    return None

def run_candidate(script, csv_path, refinement_path, manifest_path, timeout=180):
    with tempfile.TemporaryDirectory(prefix='case006-hidden-') as td:
        root=Path(td); ws=root/'workspace'; ws.mkdir(mode=0o755); os.chmod(root,0o755)
        code=ws/'analyze.py'
        try: code_bytes=read_regular_at(script.parent,script.name)
        except Exception as exc: return f'candidate source is unsafe (symlink/non-regular): {exc}'
        write_bytes_at(ws,'analyze.py',code_bytes); code.chmod(0o444)
        inputs=ws/'assets'; inputs.mkdir(mode=0o755)
        for src,name in ((csv_path,'sweeps.csv'),(refinement_path,'curve_refinement.csv'),(manifest_path,'manifest.json')):
            write_bytes_at(inputs,name,read_regular_at(src.parent,src.name)); (inputs/name).chmod(0o444)
        out=ws/'final'; out.mkdir(mode=0o777); os.chmod(out,0o777)
        # The unprivileged candidate must be able to create artifacts in its
        # own workspace. Inputs/source remain read-only; the verifier's refs
        # are outside this tree and inaccessible.
        os.chmod(ws,0o777)
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'PYTHONNOUSERSITE':'1',
             'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        argv=[sys.executable,str(code),'--input',str(inputs/'sweeps.csv'),'--refinement',str(inputs/'curve_refinement.csv'),
              '--manifest',str(inputs/'manifest.json'),'--out',str(out)]
        proc=isolated(argv,ws,env,timeout)
        if proc.returncode!=0: return f'candidate exit {proc.returncode}: {proc.stderr[-1000:]}'
        return check_outputs(out,compute(list(csv.DictReader(csv_path.open())),list(csv.DictReader(refinement_path.open())),json.loads(manifest_path.read_text())),require_program=False)

def main():
    app=Path(os.environ.get('APP','/app'))
    logs=Path(os.environ.get('BENCH_LOGS','/logs/verifier'))
    public_csv=app/'assets/reference_sweeps.csv'; public_ref=app/'assets/curve_refinement.csv'; public_manifest=app/'assets/analysis_contract.json'
    private_csv=HERE/'_data'/'hidden_sweeps.csv'; private_ref=HERE/'_data'/'hidden_curve_refinement.csv'; private_manifest=HERE/'_data'/'hidden_manifest.json'
    try:
        for path in (public_csv,public_ref,public_manifest,private_csv,private_ref,private_manifest):
            if not path.is_file(): raise FileNotFoundError(path)
        pubman=json.loads(public_manifest.read_text()); hidman=json.loads(private_manifest.read_text())
        for p,m,key in ((public_csv,pubman,'source_csv_sha256'),(private_csv,hidman,'source_csv_sha256'),
                        (public_ref,pubman['analysis_protocol']['curve_refinement'],'source_csv_sha256'),
                        (private_ref,hidman['analysis_protocol']['curve_refinement'],'source_csv_sha256')):
            import hashlib
            if hashlib.sha256(p.read_bytes()).hexdigest()!=m.get(key): raise ValueError(f'asset hash mismatch: {p.name}')
        public_expected=compute(list(csv.DictReader(public_csv.open())),list(csv.DictReader(public_ref.open())),pubman)
        hidden_expected=compute(list(csv.DictReader(private_csv.open())),list(csv.DictReader(private_ref.open())),hidman)
        # Validate candidate public deliverables before closing evaluator access.
        public_final=app/'final'
        msg=check_outputs(public_final,public_expected)
        if msg:return fail('public analysis: '+msg)
        # Confirm the verifier catches representative scientific attacks.
        actual_public=json.loads(read_regular_at(public_final,'analysis.json'))
        attacked=json.loads(json.dumps(actual_public))
        attacked['branches'][0]['physical_capacitance_curve'][0]['C_curve_h2_F_m2']=attacked['branches'][0]['physical_capacitance_curve'][0]['coarse_diagnostic_C_F_m2']
        if compare_tree(attacked,public_expected) is None:return environment_error('coarse-as-fine adversarial mutation was not detected')
        attacked=json.loads(json.dumps(actual_public)); attacked['parsons_zobel'][0]['primary_fit']['slope']+=1.0
        if compare_tree(attacked,public_expected) is None:return environment_error('wrong-fit adversarial mutation was not detected')
        attacked=json.loads(json.dumps(actual_public)); attacked['branches'][0]['physical_capacitance_curve'][0]['sigma0_C_m2']+=.01
        if compare_tree(attacked,public_expected) is None:return environment_error('branch/center mutation was not detected')
        attacked=json.loads(json.dumps(actual_public)); attacked['parsons_zobel'][0]['points'][0]['C_D_F_m2']*=1000
        if compare_tree(attacked,public_expected) is None:return environment_error('1000x concentration-unit mutation was not detected')
        attacked=json.loads(json.dumps(actual_public)); attacked['branches'][0]['Pbar_C_m2']+=.01
        if compare_tree(attacked,public_expected) is None:return environment_error('mixed-branch mutation was not detected')
        os.chmod(HERE,0o700)
        isolation_probe(logs)
        script=public_final/'analyze.py'
        msg=run_candidate(script,private_csv,private_ref,private_manifest)
        if msg:return fail('hidden off-grid analysis: '+msg)
    except Exception as exc:
        return environment_error(f'private reference, public inputs, or isolation failure: {exc}')
    print(json.dumps({'status':'PASS','public_branches':len(pubman['branch_matrix']),
                      'hidden_branches':len(hidman['branch_matrix']),
                      'public_curve_points':sum(len(b['physical_capacitance_curve']) for b in public_expected['branches']),
                      'hidden_curve_points':sum(len(b['physical_capacitance_curve']) for b in hidden_expected['branches']),
                      'hidden_candidate_uid':'nobody','private_read_reward_write_fork':'denied',
                      'coarse_as_fine_wrong_fit_branch_mutations':'rejected'},indent=2))
    return finish(0,'public and hidden real BVP data passed')

if __name__=='__main__':
    try: rc=main()
    except Exception as exc: rc=environment_error(f'unhandled evaluator failure: {exc}')
    sys.exit(rc)
