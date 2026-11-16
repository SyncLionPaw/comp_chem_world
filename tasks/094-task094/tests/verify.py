#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Recover the longitudinal dielectric response from the supplied SPC/E trajectory.
"""Independent Case 008 scoring, original-output checks, and isolated replays."""
from __future__ import annotations
import ctypes, csv, errno, hashlib, io, json, math, os, pwd, resource, shutil, signal, stat, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
PKG=HERE.parent
ASSETS=PKG/'environment'/'assets'
EXPECTED_REF='a17920533a230c1c54df7e9b53bdb1bb358e11e243708dd685a3b08b7a4fe8e8'
EXPECTED_REF_CODE='77141186935edf550341d5c6166a4b04c16a6b755b1bbe37aea5aa98944d4d86'
EXPECTED_SAMPLE='cd3d5163a42fa47117c8aca7a731e5fd1334139e8496e82787f86495f779738c'
EXPECTED_SOURCE_ACCEPTANCE='3453cc062604d9d44a318556b038afdee36b821204ee79452ce709a4ed078914'
MAX_BYTES={'analyze.py':2_000_000,'chi_k.csv':100_000,'observables.json':100_000,'analysis.log':100_000}

def finish(code,msg=''):
    logs=Path(os.environ.get('BENCH_LOGS','/logs/verifier')); logs.mkdir(parents=True,exist_ok=True)
    if code==2:
        (logs/'reward.txt').unlink(missing_ok=True); (logs/'verification.json').unlink(missing_ok=True)
    else:
        reward=int(code==0)
        (logs/'reward.txt').write_text(f'{reward}\n')
        (logs/'verification.json').write_text(json.dumps({'status':'PASS' if reward else 'FAIL','reward':reward,'message':msg})+'\n')
    return code

def read_regular(directory:Path,name:str,limit:int)->bytes:
    if name in ('','.','..') or '/' in name or '\\' in name: raise ValueError('unsafe basename')
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode): raise ValueError(f'{name} is not regular')
            if st.st_size>limit: raise ValueError(f'{name} exceeds size limit')
            chunks=[]; total=0
            while True:
                b=os.read(fd,min(1<<20,limit+1-total))
                if not b: break
                total+=len(b)
                if total>limit: raise ValueError(f'{name} exceeds size limit')
                chunks.append(b)
            return b''.join(chunks)
        finally: os.close(fd)
    finally: os.close(dfd)

def csv_curve(data):
    try:
        rows=list(csv.DictReader(io.StringIO(data.decode('utf-8'))))
        header=['n_index','k_Ainv','chi_parallel','se_1ns','se_2ns','n_directions']
        if not rows or list(rows[0])!=header or len(rows)!=62: raise ValueError('wrong CSV header or row count')
        a=np.asarray([[float(r[k]) for k in header] for r in rows],float)
        if not np.isfinite(a).all() or not np.array_equal(a[:,0],np.arange(1,63)) or np.any(a[:,5]<1) or np.any(a[:,5]!=np.floor(a[:,5])): raise ValueError('invalid CSV values')
        return a
    except Exception as e: raise ValueError(f'invalid chi_k.csv: {e}')

def close(got,want,rtol=4e-6,atol=2e-9):
    if not np.allclose(got,want,rtol=rtol,atol=atol):
        d=np.abs(np.asarray(got)-np.asarray(want)); raise ValueError(f'numeric mismatch max_abs={np.nanmax(d):.6g}')

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError(f'duplicate JSON key: {key}')
        result[key]=value
    return result

def finite_json(value,depth=0):
    if depth>24: raise ValueError('JSON nesting exceeds the output contract')
    if isinstance(value,bool): return
    if isinstance(value,(int,float)):
        try: valid=math.isfinite(value)
        except (OverflowError,TypeError,ValueError): valid=False
        if not valid: raise ValueError('nonfinite or unrepresentable JSON number')
    elif isinstance(value,dict):
        for item in value.values(): finite_json(item,depth+1)
    elif isinstance(value,list):
        for item in value: finite_json(item,depth+1)

def numeric(value,label,nullable=False):
    if value is None and nullable: return
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f'{label} must be a finite number')
    finite_json(value)

def validate_source_acceptance(app):
    path=HERE/'_data'/'source_acceptance.json'
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED_SOURCE_ACCEPTANCE:
        raise RuntimeError('trusted corrected-source acceptance SHA256 mismatch or not yet accepted')
    receipt=json.loads(data,object_pairs_hook=unique_object)
    checks=('native_exclusions','native_settings','production_completed','trajectory_frames','temperature','density')
    if receipt.get('schema')!='ihf008-source-acceptance/v1' or receipt.get('status')!='PASS' or any(receipt.get('checks',{}).get(k) is not True for k in checks):
        raise RuntimeError('corrected production scientific-source acceptance incomplete')
    public=receipt.get('public_sha256',{})
    required={'trajectory_sample.npz','analysis_contract.json','source_manifest.json','production.log','production.tpr','production.gro','topol.top'}
    if set(public)!=required: raise RuntimeError('source acceptance public asset set is incomplete')
    for name,expected in public.items():
        if hashlib.sha256((app/'assets'/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f'scientific source asset SHA256 mismatch: {name}')
    manifest=json.loads((app/'assets'/'source_manifest.json').read_bytes(),object_pairs_hook=unique_object)
    source=manifest['source']
    if source['slurm_job_id']!=receipt['source_job_id'] or str(source['slurm_job_id'])=='8932':
        raise RuntimeError('legacy or mismatched production job is not accepted')
    if source['trajectory']['sha256']!=receipt['source_xtc_sha256'] or source['tpr']['sha256']!=receipt['source_tpr_sha256']:
        raise RuntimeError('production provenance does not match scientific acceptance')
    native=receipt.get('actual_native_audits',{})
    exclusions=native.get('exclusions',{}); settings=native.get('settings',{})
    if exclusions.get('status')!='PASS' or exclusions.get('sha256')!=receipt['source_tpr_sha256'] or settings.get('status')!='PASS' or settings.get('tpr_sha256')!=receipt['source_tpr_sha256']:
        raise RuntimeError('native audit is not of the accepted actual production TPR')
    if exclusions.get('all_intramolecular_nonbonded_pairs_excluded') is not True:
        raise RuntimeError('actual production TPR intramolecular exclusions were not accepted')
    if source.get('energy_file',{}).get('sha256')!=receipt.get('source_edr_sha256') or not receipt.get('source_edr_sha256'):
        raise RuntimeError('completed production energy-source provenance is missing or mismatched')
    if source['trajectory'].get('frames')!=20001 or source['trajectory'].get('time_range_ps')!=[0,20000]:
        raise RuntimeError('source trajectory is not the accepted complete 20 ns production')
    if 'Finished mdrun' not in (app/'assets'/'production.log').read_text():
        raise RuntimeError('production log does not attest to normal completion')
    if public['production.tpr']!=receipt['source_tpr_sha256'] or public['trajectory_sample.npz']!=EXPECTED_SAMPLE or receipt['reference_sha256']!=EXPECTED_REF:
        raise RuntimeError('sample, actual production TPR or independent reference acceptance mismatch')

def validate_original(final:Path,submitted:dict,base):
    curve=csv_curve(submitted['chi_k.csv'])
    if not np.array_equal(curve[:,5],base['counts']): raise ValueError('chi_k.csv reciprocal direction counts are wrong')
    close(curve[:,1],base['k']); close(curve[:,2],base['chi']); close(curve[:,3],base['se1']); close(curve[:,4],base['se2'])
    try:
        obs=json.loads(submitted['observables.json'],object_pairs_hook=unique_object,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))
        finite_json(obs)
    except Exception as e: raise ValueError(f'invalid observables.json: {e}')
    keys={'schema','temperature_K','selected_frames','selected_source_frame_indices','saved_interval_ps','block_length_ps','blocks_1ns','blocks_2ns','box_A','volume_A3','reciprocal_sampling','uncertainty','observables'}
    if not isinstance(obs,dict) or set(obs)!=keys or obs['schema']!='ihf008-observables/v1': raise ValueError('observables JSON top-level schema/keys invalid')
    if not isinstance(obs.get('observables'),dict) or set(obs['observables'])!={'eps_w','k_min_Ainv','chi_min','k_max_Ainv','delta_k_Ainv'}: raise ValueError('observable key set invalid')
    if not isinstance(obs.get('reciprocal_sampling'),dict) or not isinstance(obs.get('uncertainty'),dict): raise ValueError('reciprocal/statistics metadata must be objects')
    if not isinstance(obs['uncertainty'].get('feature_bootstrap'),dict): raise ValueError('feature_bootstrap must be an object')
    for key in ('temperature_K','selected_frames','saved_interval_ps','block_length_ps','blocks_1ns','blocks_2ns','volume_A3'):
        numeric(obs[key],key)
    if not isinstance(obs['box_A'],list) or len(obs['box_A'])!=3: raise ValueError('box_A must contain three lengths')
    for x in obs['box_A']: numeric(x,'box_A length')
    for key in ('n_min','n_max'): numeric(obs['reciprocal_sampling'].get(key),key)
    for key in ('selected_source_frame_indices',):
        if not isinstance(obs[key],list): raise ValueError(f'{key} must be an array')
        for x in obs[key]: numeric(x,key)
    counts=obs['reciprocal_sampling'].get('directions_per_shell')
    if not isinstance(counts,list): raise ValueError('directions_per_shell must be an array')
    for x in counts: numeric(x,'directions_per_shell')
    if obs['selected_frames']!=base['nframes'] or obs['blocks_1ns']!=base['nblocks'] or obs['blocks_2ns']!=base['nblocks']//2 or obs['temperature_K']!=300 or obs['block_length_ps']!=ref.BLOCK_PS: raise ValueError('sample/block metadata invalid')
    close(obs['box_A'],base['box'],rtol=0,atol=0.002)
    close([obs['volume_A3']],[base['volume']],rtol=2e-7,atol=1e-5)
    if obs['reciprocal_sampling']['directions_per_shell']!=base['counts'].tolist(): raise ValueError('mode-count metadata invalid')
    if obs['reciprocal_sampling'].get('mode_vectors_sha256')!=base['vector_hash'] or obs['reciprocal_sampling'].get('n_min')!=1 or obs['reciprocal_sampling'].get('n_max')!=62: raise ValueError('reciprocal vector metadata invalid')
    if obs['selected_source_frame_indices']!=base['indices'] or abs(obs['saved_interval_ps']-base['dt'])>1e-8: raise ValueError('selected frame/time metadata invalid')
    u=obs['uncertainty']
    numeric(u.get('blocks_1ns'),'uncertainty.blocks_1ns')
    for key in ('resamples','seed','resolution_floor_k_Ainv','resolution_floor_delta_k_Ainv'):
        numeric(u['feature_bootstrap'].get(key),f'feature_bootstrap.{key}')
    if u.get('blocks_1ns')!=base['nblocks'] or u.get('feature_bootstrap',{}).get('resamples')!=ref.BOOT_REPS or u.get('feature_bootstrap',{}).get('seed')!=ref.BOOT_SEED: raise ValueError('uncertainty protocol metadata invalid')
    if not np.isclose(u['feature_bootstrap'].get('resolution_floor_k_Ainv',np.nan),(base['k'][1]-base['k'][0])/np.sqrt(12)) or not np.isclose(u['feature_bootstrap'].get('resolution_floor_delta_k_Ainv',np.nan),(base['k'][1]-base['k'][0])/np.sqrt(6)): raise ValueError('finite-k resolution floor metadata invalid')
    for name in obs['observables']:
        item=obs['observables'][name]
        if not isinstance(item,dict) or not {'value','standard_error','units','status','reason'}<=set(item): raise ValueError(f'{name} observable schema invalid')
        for key in ('value','standard_error','independent_2ns_value','independent_2ns_standard_error','valid_bootstrap_replicates','bootstrap_standard_error','finite_k_resolution_floor'):
            if key in item: numeric(item[key],f'{name}.{key}',nullable=True)
        if item['reason'] is not None and not isinstance(item['reason'],str): raise ValueError(f'{name} reason must be text or null when resolved')
        if item.get('status')=='unresolved' and (not isinstance(item['reason'],str) or not item['reason']): raise ValueError(f'{name} unresolved reason must be nonempty text')
        units='dimensionless' if name in ('eps_w','chi_min') else 'Angstrom^-1'
        if item.get('units')!=units: raise ValueError(f'{name} units invalid')
        if item.get('status') not in ('resolved','unresolved') or (item['value'] is None and (item['status']!='unresolved' or not item['reason'])) or (item['value'] is not None and item['status']!='resolved'): raise ValueError(f'{name} resolution/status mismatch')
    eo=obs['observables']['eps_w']; close([eo['value'],eo['standard_error']],[base['eps'],base['eps_se']],rtol=2e-7,atol=1e-8)
    for key in ('independent_2ns_value','independent_2ns_standard_error'):
        if key not in eo: raise ValueError(f'eps_w must report {key} for the 2 ns independent check')
    close([eo['independent_2ns_value'],eo['independent_2ns_standard_error']],[base['eps2'],base['eps_se2']],rtol=2e-7,atol=1e-8)
    for name,key in [('k_min_Ainv','k_min_Ainv'),('chi_min','chi_min'),('k_max_Ainv','k_max_Ainv'),('delta_k_Ainv','delta_k_Ainv')]:
        a=obs['observables'][name]; val=base['features'][key]
        if val is None:
            if a['value'] is not None or a['status']!='unresolved' or not a['reason']: raise ValueError(f'{name} unresolved/null semantics invalid')
        else: close([a['value']],[val],rtol=2e-5,atol=1e-8)
        other=base['features2'][key]
        if a.get('independent_2ns_status')!=('unresolved' if other is None else 'resolved'):
            raise ValueError(f'{name} 2 ns resolution/status mismatch')
        if other is None:
            if a.get('independent_2ns_value') is not None: raise ValueError(f'{name} 2 ns unresolved value must be null')
        else: close([a.get('independent_2ns_value')],[other],rtol=2e-5,atol=1e-8)
        se=base['feature_se'].get(name)
        bootname={'k_min_Ainv':'k_min_Ainv','chi_min':'chi_min','k_max_Ainv':'k_max_Ainv','delta_k_Ainv':'delta_k_Ainv'}[name]
        # Replicate validity counts and raw bootstrap spreads are part of the uncertainty contract.
        expected_n=base['boot_n'][bootname]
        if a.get('valid_bootstrap_replicates')!=expected_n: raise ValueError(f'{name} valid-bootstrap count mismatch')
        if se is None:
            if a['standard_error'] is not None: raise ValueError(f'{name} should have null uncertainty after bootstrap rejection')
        else: close([a['standard_error']],[se],rtol=2e-5,atol=1e-8)
    log=submitted['analysis.log'].decode('utf-8')
    for token in (f"input_sha256={base['input_hash']}",f"frames_used={base['nframes']}",'time_range_ps=','saved_interval_ps=','block_length_ps=','box_A=','mode_vectors_sha256=','elapsed_seconds=','status=complete'):
        if token not in log: raise ValueError(f'analysis.log missing {token}')
    for name in ('k_min_Ainv','chi_min','k_max_Ainv','delta_k_Ainv'):
        field=obs['observables'][name]; sd=base['boot_sd'][name]
        expected_sd=sd if base['boot_n'][name]>=max(100,int(.8*ref.BOOT_REPS)) else None
        got_sd=field.get('bootstrap_standard_error')
        if expected_sd is None:
            if got_sd is not None: raise ValueError(f'{name} raw bootstrap spread should be null')
        elif got_sd is None or not np.isclose(got_sd,expected_sd,rtol=2e-5,atol=1e-8): raise ValueError(f'{name} raw bootstrap spread mismatch')
    for name,denom in [('k_min_Ainv',12),('k_max_Ainv',12),('delta_k_Ainv',6)]:
        floor=obs['observables'][name].get('finite_k_resolution_floor')
        if floor is None or not np.isclose(floor,(base['k'][1]-base['k'][0])/np.sqrt(denom)): raise ValueError(f'{name} finite-grid floor missing or wrong')

def summarize_cached(powers,dipoles,times,box,indices,input_hash,vectors):
    order=np.argsort(times,kind='stable'); powers=powers[order]; dipoles=dipoles[order]; times=np.asarray(times)[order]; box=box[order]; indices=np.asarray(indices)[order]
    shell=np.rint(np.sqrt(np.sum(np.asarray(vectors,dtype=np.int64)**2,axis=1))).astype(int)
    shell_n=int(shell.max()); sp=np.stack([powers[:,shell==n].mean(axis=1) for n in range(1,shell_n+1)],axis=1)
    ids,labels,dt=ref.groups(times); L=float(np.mean(box[0,:3])); V=L**3*1e-30
    k=2*np.pi*np.arange(1,shell_n+1)/L; km=k*1e10
    factor=1.602176634e-19**2/(ref.EPS0*ref.KB*ref.T*V*km**2)
    bc=np.stack([sp[ids==b].mean(axis=0)*factor for b in labels]); curve=sp.mean(axis=0)*factor
    se1=np.std(bc,axis=0,ddof=1)/np.sqrt(len(labels))
    ids2=np.floor((times-times.min()+1e-8)/(2*ref.BLOCK_PS)).astype(int); lab2=np.unique(ids2)
    bc2=np.stack([sp[ids2==b].mean(axis=0)*factor for b in lab2]); curve2=bc2.mean(axis=0); se2=np.std(bc2,axis=0,ddof=1)/np.sqrt(len(lab2))
    epsf=1/(3*ref.EPS0*V*ref.KB*ref.T)
    def epstat(d):
        cent=d.mean(axis=0); val=1+epsf*np.sum((d-cent)**2,axis=1); point=float(val.mean()); jk=[]
        return point,val,jk
    eps,ev,_=epstat(dipoles); j1=[]
    for b in labels:
        keep=ids!=b; d=dipoles[keep]; m=d.mean(axis=0); j1.append(1+epsf*np.mean(np.sum((d-m)**2,axis=1)))
    j1=np.asarray(j1); epsse=float(np.sqrt((len(j1)-1)/len(j1)*np.sum((j1-j1.mean())**2)))
    j2=[]
    for b in lab2:
        keep=ids2!=b; d=dipoles[keep]; m=d.mean(axis=0); j2.append(1+epsf*np.mean(np.sum((d-m)**2,axis=1)))
    j2=np.asarray(j2); eps2=float((1+epsf*np.sum((dipoles-dipoles.mean(axis=0))**2,axis=1)).mean()); epsse2=float(np.sqrt((len(j2)-1)/len(j2)*np.sum((j2-j2.mean())**2)))
    feat=ref.features(k,curve,se1); feat2=ref.features(k,curve2,se2)
    rng=np.random.default_rng(ref.BOOT_SEED); names=('k_min_Ainv','chi_min','k_max_Ainv','delta_k_Ainv'); boot={n:[] for n in names}
    for _ in range(ref.BOOT_REPS):
        pick=bc[rng.integers(0,len(bc),size=len(bc))]; f=ref.features(k,pick.mean(axis=0),np.std(pick,axis=0,ddof=1)/np.sqrt(len(pick)))
        for n in names:
            if f[n] is not None and np.isfinite(f[n]): boot[n].append(float(f[n]))
    grid=k[1]-k[0]; floors={'k_min_Ainv':grid/np.sqrt(12),'chi_min':0.0,'k_max_Ainv':grid/np.sqrt(12),'delta_k_Ainv':grid/np.sqrt(6)}
    feature_se={}; boot_n={}; boot_sd={}
    for n in names:
        vals=np.asarray(boot[n]); ok=len(vals)>=max(100,int(.8*ref.BOOT_REPS))
        boot_n[n]=len(vals); boot_sd[n]=float(vals.std(ddof=1)) if len(vals)>1 else None
        feature_se[n]=max(boot_sd[n],floors[n]) if ok and len(vals)>1 else None
    for name, fields in [('k_min_Ainv',('k_min_Ainv','chi_min')),('k_max_Ainv',('k_max_Ainv',)),('delta_k_Ainv',('delta_k_Ainv',))]:
        if len(boot[name])<max(100,int(.8*ref.BOOT_REPS)):
            for f in fields: feat[f]=None
            if name=='k_min_Ainv': feat['k_min_status']=feat['chi_min_status']='unresolved'; feat['k_min_reason']=feat['chi_min_reason']='fewer than 80% of fixed-seed block-bootstrap samples resolved the low-k trough'
            elif name=='k_max_Ainv': feat['k_max_status']='unresolved'; feat['k_max_reason']='fewer than 80% of fixed-seed block-bootstrap samples resolved the overscreening peak'
            else: feat['delta_k_status']='unresolved'; feat['delta_k_reason']='fewer than 80% of fixed-seed block-bootstrap samples bracketed both half-maximum crossings'
    return {'chi':curve,'k':k,'se1':se1,'se2':se2,'eps':eps,'eps_se':epsse,'eps2':eps2,'eps_se2':epsse2,
      'features':feat,'features2':feat2,'feature_se':feature_se,'boot_n':boot_n,'boot_sd':boot_sd,'nframes':len(times),'nblocks':len(labels),'box':box[0,:3],
      'volume':L**3,'indices':[int(indices.min()),int(indices.max())],'dt':dt,'counts':np.bincount(shell,minlength=shell_n+1)[1:],
      'vector_hash':hashlib.sha256(np.asarray(vectors,dtype='<i2').tobytes()).hexdigest(),'input_hash':input_hash}

def published_vectors():
    return np.asarray([v for n in range(1,63) for v in ((n,0,0),(0,n,0),(0,0,n))],dtype=np.int16)

def demote():
    u=pwd.getpwnam('nobody'); os.setgroups([]); os.setgid(u.pw_gid); os.setuid(u.pw_uid)
    if ctypes.CDLL(None).prctl(38,1,0,0,0)!=0: raise OSError('PR_SET_NO_NEW_PRIVS failed')
    resource.setrlimit(resource.RLIMIT_CPU,(180,180)); resource.setrlimit(resource.RLIMIT_FSIZE,(20_000_000,20_000_000)); resource.setrlimit(resource.RLIMIT_NPROC,(1,1)); resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))

def replay(source:bytes, npz:Path, vectors:Path|None, timeout=240):
    with tempfile.TemporaryDirectory(prefix='ihf008-run-') as td:
        root=Path(td); os.chmod(root,0o755); ws=root/'ws'; ws.mkdir(mode=0o777); os.chmod(ws,0o777)
        script=ws/'analyze.py'; script.write_bytes(source); script.chmod(0o644)
        inp=ws/'sample.npz'; shutil.copyfile(npz,inp); inp.chmod(0o644)
        out=ws/'out'; out.mkdir(mode=0o777); os.chmod(out,0o777)
        argv=[sys.executable,str(script),'--input',str(inp),'--out',str(out)]
        if vectors is not None:
            local_vectors=ws/'vectors.csv'; shutil.copyfile(vectors,local_vectors); local_vectors.chmod(0o644)
            argv += ['--vectors',str(local_vectors)]
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'PYTHONNOUSERSITE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        stdout_path=root/'stdout.log'; stderr_path=root/'stderr.log'
        with stdout_path.open('wb') as so,stderr_path.open('wb') as se:
            p=subprocess.Popen(argv,cwd=ws,env=env,stdout=so,stderr=se,start_new_session=True,preexec_fn=demote)
            try: p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL); p.wait(); raise ValueError('candidate analysis timed out')
            finally:
                try: os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError: pass
        stderr=stderr_path.read_bytes()[-4096:].decode('utf-8','replace')
        if p.returncode: raise ValueError(f'candidate exited {p.returncode}: {stderr[-1000:]}')
        outputs={name:read_regular(out,name,MAX_BYTES[name]) for name in ('chi_k.csv','observables.json','analysis.log')}
        return outputs

def isolation_probe():
    if os.geteuid()!=0: raise RuntimeError('verifier must run as root to demote candidate')
    with tempfile.TemporaryDirectory(prefix='ihf008-isolation-') as td:
        root=Path(td); os.chmod(root,0o755); scratch=root/'scratch'; scratch.mkdir(mode=0o777); os.chmod(scratch,0o777)
        marker=scratch/'result.json'; probe=scratch/'probe.py'
        probe.write_text(
            'import json,os,pathlib\n'
            f'p=pathlib.Path({str(HERE / "_data" / "private_reference.npz")!r})\n'
            f'd=pathlib.Path({str(HERE)!r})\n'
            f'r=pathlib.Path({str(Path(os.environ.get("BENCH_LOGS","/logs/verifier")) / "reward.txt")!r})\n'
            'o={}\n'
            'try: p.read_bytes(); o["private_read"]="yes"\nexcept Exception: o["private_read"]="no"\n'
            'try: list(d.iterdir()); o["private_list"]="yes"\nexcept Exception: o["private_list"]="no"\n'
            'try: r.write_text("1\\n"); o["reward_write"]="yes"\nexcept Exception: o["reward_write"]="no"\n'
            'try: pid=os.fork(); (os._exit(0) if pid==0 else None); o["fork"]="yes"\nexcept Exception: o["fork"]="no"\n'
            f'pathlib.Path({str(marker)!r}).write_text(json.dumps(o))\n',encoding='utf-8')
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'PYTHONNOUSERSITE':'1'}
        with (root/'out').open('wb') as out:
            p=subprocess.Popen([sys.executable,str(probe)],cwd=scratch,env=env,stdout=out,stderr=out,preexec_fn=demote)
            if p.wait(timeout=10)!=0 or not marker.is_file(): raise RuntimeError('nobody isolation probe did not complete')
        got=json.loads(marker.read_text())
        if got!={'private_read':'no','private_list':'no','reward_write':'no','fork':'no'}: raise RuntimeError(f'candidate isolation probe failed: {got}')
    return 'private-read/list, reward-write, and fork denied for nobody'

def main(app:Path):
    logs=Path(os.environ.get('BENCH_LOGS','/logs/verifier')); logs.mkdir(parents=True,exist_ok=True)
    p=app/'assets'/'trajectory_sample.npz'
    private=HERE/'_data'/'private_reference.npz'
    try:
        validate_source_acceptance(app)
        if hashlib.sha256((HERE/'_support'/'reference.py').read_bytes()).hexdigest()!=EXPECTED_REF_CODE: raise RuntimeError('private reference code SHA256 mismatch')
        if hashlib.sha256(private.read_bytes()).hexdigest()!=EXPECTED_REF: raise RuntimeError('private reference SHA256 mismatch')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=EXPECTED_SAMPLE: raise RuntimeError('public sample SHA256 mismatch')
        global ref
        sys.path.insert(0,str(HERE/'_support')); import reference as ref
        os.chmod(HERE,0o700)
        isolation=isolation_probe()
    except Exception as e:
        print(f'ERROR L0: reference/input integrity failure: {e}',file=sys.stderr); return finish(2,str(e))
    try:
        with np.load(p,allow_pickle=False) as z:
            positions=z['positions_A']; box=z['box_dimensions_A_deg']; q=z['charges_e']; times=z['times_ps']; indices=z['frame_indices']
        if positions.shape!=(200,27099,3) or box.shape!=(200,6) or q.shape!=(27099,) or times.shape!=(200,) or indices.shape!=(200,):
            raise RuntimeError('trusted public sample dimensions are invalid')
        if any(not np.isfinite(a).all() for a in (positions,box,q,times)) or not np.array_equal(indices,np.arange(0,20000,100)) or not np.array_equal(times,indices):
            raise RuntimeError('trusted public sample values or time selection are invalid')
        if not np.allclose(box[:,:3],box[0,:3],rtol=0,atol=.002) or not np.allclose(box[:,:3],box[0,:3].mean(),rtol=0,atol=.002) or not np.allclose(box[:,3:],90.,rtol=0,atol=.002) or np.any(box[:,:3]<=0):
            raise RuntimeError('trusted public sample does not have a fixed orthogonal cubic box')
        if not np.allclose(q,np.tile([-.8476,.4238,.4238],9033),rtol=0,atol=2e-4):
            raise RuntimeError('trusted public sample charges do not match SPC/E')
        with np.load(private,allow_pickle=False) as r:
            raw_grouped=r['raw_mode_power']; dip=r['dipoles_SI']; ref_curve=r['chi']; ref_se1=r['se1']
            ref_se2=r['se2']; ref_k=r['k']; ref_shells=r['mode_shells']
        if raw_grouped.shape!=(200,186) or dip.shape!=(200,3) or any(a.shape!=(62,) for a in (ref_curve,ref_se1,ref_se2,ref_k)) or any(not np.isfinite(a).all() for a in (raw_grouped,dip,ref_curve,ref_se1,ref_se2,ref_k)) or np.any(raw_grouped<0) or np.any(ref_se1<0) or np.any(ref_se2<0):
            raise RuntimeError('trusted reference shape or finite-value contract failed')
        grouped=ref.canonical_vectors(); pub=published_vectors(); gmap={tuple(v):i for i,v in enumerate(grouped)}
        perm=np.asarray([gmap[tuple(v)] for v in pub]); raw=raw_grouped[:,perm]
        base=summarize_cached(raw,dip,times,box,indices,hashlib.sha256(p.read_bytes()).hexdigest(),pub)
        close(base['chi'],ref_curve); close(base['se1'],ref_se1)
        close(base['se2'],ref_se2); close(base['k'],ref_k)
        if not np.array_equal(ref_shells,np.rint(np.sqrt(np.sum(grouped.astype(np.int64)**2,axis=1))).astype(int)):
            raise RuntimeError('trusted reference mode shell schema mismatch')
    except Exception as e:
        print(f'ERROR L0: trusted input/reference consistency failure: {e}',file=sys.stderr); return finish(2,str(e))
    final=app/'final'
    try: submitted={n:read_regular(final,n,lim) for n,lim in MAX_BYTES.items()}
    except Exception as e: print(f'FAIL: unsafe or missing submitted artifact: {e}'); return finish(1,str(e))
    try:
        validate_original(final,submitted,base)
        src=submitted['analyze.py']
        # Reversed rows must preserve time grouping and physics.
        with tempfile.TemporaryDirectory(prefix='ihf008-hidden-') as td:
            rev=Path(td)/'reverse.npz'
            np.savez_compressed(rev,positions_A=positions[::-1],box_dimensions_A_deg=box[::-1],charges_e=q,times_ps=times[::-1],frame_indices=indices[::-1])
            out=replay(src,rev,None)
            b=summarize_cached(raw[::-1],dip[::-1],times[::-1],box[::-1],indices[::-1],hashlib.sha256(rev.read_bytes()).hexdigest(),pub)
            validate_original(Path('/unused'),out,b)
        # Authentic every-other saved frame; still 20 equally populated 1 ns blocks.
        with tempfile.TemporaryDirectory(prefix='ihf008-hidden-') as td:
            sub=Path(td)/'subset.npz'; ix=np.arange(0,200,2)
            np.savez_compressed(sub,positions_A=positions[ix],box_dimensions_A_deg=box[ix],charges_e=q,times_ps=times[ix],frame_indices=indices[ix])
            out=replay(src,sub,None)
            b=summarize_cached(raw[ix],dip[ix],times[ix],box[ix],indices[ix],hashlib.sha256(sub.read_bytes()).hexdigest(),pub)
            validate_original(Path('/unused'),out,b)
        # Translation invariance, retaining float64 precision after integer-box shifts.
        with tempfile.TemporaryDirectory(prefix='ihf008-hidden-') as td:
            L=float(np.mean(box[0,:3]))
            trans=Path(td)/'translated.npz'; shifted=positions.astype(np.float64); shifts=np.arange(positions.shape[1],dtype=np.int64)%3-1; shifted+=shifts[None,:,None]*L
            np.savez_compressed(trans,positions_A=shifted,box_dimensions_A_deg=box,charges_e=q,times_ps=times,frame_indices=indices)
            out=replay(src,trans,None); b=dict(base); b['input_hash']=hashlib.sha256(trans.read_bytes()).hexdigest(); validate_original(Path('/unused'),out,b)
        # Same shell norms but additional non-axis reciprocal direction.
        with tempfile.TemporaryDirectory(prefix='ihf008-hidden-') as td:
            vecfile=Path(td)/'vectors.csv'; vecs=pub.tolist(); vecs.append([3,4,0])
            with vecfile.open('w') as f:
                f.write('nx,ny,nz\n'); f.writelines(f'{a},{b},{c}\n' for a,b,c in vecs)
            out=replay(src,p,vecfile); got=csv_curve(out['chi_k.csv'])
            extra=ref.structure_factors(positions,q,L,np.asarray([[3,4,0]],dtype=int))[:,0]
            b=summarize_cached(np.column_stack((raw,extra)),dip,times,box,indices,hashlib.sha256(p.read_bytes()).hexdigest(),np.asarray(vecs))
            validate_original(Path('/unused'),out,b)
        # Finite negative controls: a fabricated scientific value or forged input provenance
        # must fail the same validator used for the candidate's original deliverables.
        curve_rows=list(csv.reader(io.StringIO(submitted['chi_k.csv'].decode('utf-8'))))
        curve_rows[1][2]=str(float(curve_rows[1][2])+1.0)
        bad_curve=io.StringIO(); csv.writer(bad_curve,lineterminator='\n').writerows(curve_rows)
        attacked=dict(submitted); attacked['chi_k.csv']=bad_curve.getvalue().encode('utf-8')
        try: validate_original(Path('/unused'),attacked,base)
        except ValueError: pass
        else: raise RuntimeError('finite counterexample failed: corrupted chi(k) value was accepted')
        log=submitted['analysis.log'].decode('utf-8')
        token=f"input_sha256={base['input_hash']}"
        if token not in log: raise RuntimeError('candidate analysis.log lacks input hash needed for provenance counterexample')
        attacked=dict(submitted); attacked['analysis.log']=log.replace(token,'input_sha256='+'0'*64,1).encode('utf-8')
        try: validate_original(Path('/unused'),attacked,base)
        except ValueError: pass
        else: raise RuntimeError('finite counterexample failed: forged input SHA256 was accepted')
        print('PASS: original artifacts match independent scalar reference; reversed, subset, translation and alternate-vector replays passed; corrupted chi(k) and forged input SHA256 rejected')
        print(isolation)
        return finish(0,'original outputs and 4 isolated scientific replays match independent reference; corrupted chi(k) and forged input SHA256 rejected; nobody cannot read private data, alter rewards, or fork')
    except OSError as e:
        if e.errno == errno.ENOSPC:
            print(f'ERROR L0: verifier scratch space exhausted: {e}',file=sys.stderr)
            return finish(2,str(e))
        print(f'FAIL: {e}'); return finish(1,str(e))
    except (ValueError,KeyError,AssertionError,TypeError) as e:
        print(f'FAIL: {e}'); return finish(1,str(e))
    except Exception as e:
        print(f'ERROR L0: {type(e).__name__}: {e}',file=sys.stderr); return finish(2,str(e))

if __name__=='__main__':
    try: code=main(Path(sys.argv[1] if len(sys.argv)>1 else '/app'))
    except Exception as e:
        print(f'ERROR L0: {type(e).__name__}: {e}',file=sys.stderr); code=2
    sys.exit(finish(2) if code==2 else code)
