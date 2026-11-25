#!/usr/bin/env python3
"""Independent numerical checks for supported scientific candidate fields.

Open scientific interpretations remain JUDGE_REQUIRED. A numeric PASS here only
means the checked quantities were recomputed from the trusted public inputs.
"""
from __future__ import annotations

import csv, hashlib, importlib.util, json, math, os, re, shutil, tempfile
from pathlib import Path

class CandidateError(ValueError):
    """A submitted numeric value or schema cannot support its scientific claim."""

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _strict_json_text(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError(f'duplicate JSON key {key}')
            out[key]=value
        return out
    def reject(x): raise ValueError(f"nonfinite JSON constant {x}")
    def finite_float(s):
        x=float(s)
        if not math.isfinite(x): raise ValueError('nonfinite JSON number')
        return x
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite_float)

def _read_json(path): return _strict_json_text(path.read_text(encoding='utf-8'))

def _discover_csv(root: Path, required_headers: set[str]):
    for path in sorted(root.rglob('*.csv')):
        if path.is_symlink(): continue
        try:
            with path.open(newline='',encoding='utf-8') as stream:
                header=next(csv.reader(stream),[])
        except (OSError,UnicodeError,csv.Error): continue
        if required_headers <= set(header): return path
    return None

def _discover_json(root: Path, required_paths: tuple[str,...]):
    for path in sorted(root.rglob('*.json')):
        if path.is_symlink(): continue
        try: data=_read_json(path)
        except (OSError,UnicodeError,ValueError): continue
        if isinstance(data,dict) and all(_nested(data,key.split('.')) is not None for key in required_paths): return path,data
    return None,None

def _nested(obj, parts):
    for part in parts:
        if not isinstance(obj,dict) or part not in obj: return None
        obj=obj[part]
    return obj

def _summary_stats(text):
    m=re.fullmatch(r'\s*mean\s*=\s*([-+0-9.eE]+)\s*;\s*sd\s*=\s*([-+0-9.eE]+)\s*;\s*range\s*=\s*\[\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\]\s*',str(text))
    if not m: raise ValueError('candidate feature summary is not parseable')
    return tuple(_num(v,'candidate feature summary') for v in m.groups())

def _num(value, label):
    if isinstance(value, bool): raise CandidateError(f'{label} is boolean')
    try: x=float(value)
    except (TypeError,ValueError,OverflowError) as exc: raise CandidateError(f'{label} is not numeric') from exc
    if not math.isfinite(x): raise CandidateError(f'{label} is nonfinite')
    return x

def _close(a,b,tol=1e-5):
    return math.isclose(_num(a,'candidate numeric value'),_num(b,'trusted recomputation'),rel_tol=0,abs_tol=tol)

def _entry(summary, checked=None, sources=None):
    return {'status':'PASS','summary':summary,'checked_values':checked or {},'source_hashes':sources or {}}

def _judge(summary): return {'status':'JUDGE_REQUIRED','summary':summary,'checked_values':{},'source_hashes':{}}

def _fail(summary, checked=None, sources=None):
    return {'status':'FAIL','summary':summary,'checked_values':checked or {},'source_hashes':sources or {}}

def _case02_output_time_errors(package_dir,payload):
    """Independently check each output row uses one of its two bound source times."""
    import numpy as np
    descriptor_path=package_dir/'environment/assets/g4-descriptors.csv'
    trace_path=package_dir/'environment/assets/g4-native-traces.npz'
    with descriptor_path.open(newline='',encoding='utf-8') as stream:
        descriptors=list(csv.DictReader(stream))
    with np.load(trace_path,allow_pickle=False) as archive:
        trace_times=np.asarray(archive['time_ps'],dtype=float)
    descriptor_times=np.asarray([float(row['time_ps']) for row in descriptors],dtype=float)
    nearest=np.searchsorted(trace_times,descriptor_times)
    nearest=np.clip(nearest,0,len(trace_times)-1)
    left=np.maximum(nearest-1,0)
    nearest=np.where(np.abs(trace_times[left]-descriptor_times)<np.abs(trace_times[nearest]-descriptor_times),left,nearest)
    native_times=trace_times[nearest]
    if np.max(np.abs(native_times-descriptor_times))>0.01 or len(set(map(int,nearest)))!=len(nearest):
        raise RuntimeError('trusted descriptor/native trace time join invalid')
    allowed={str(row['frame_index']):(float(row['time_ps']),float(native_times[i])) for i,row in enumerate(descriptors)}
    models={'a','b','c'}; columns={'node0','node1','node2','sw','swb','swc'}
    expected={(frame,model,column) for frame in allowed for model in models for column in columns}
    path=payload/'model-output-audit.csv'
    with path.open(newline='',encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream))
    errors=[]; seen=set()
    for row in rows:
        key=(str(row.get('frame_index','')),str(row.get('model_id','')),str(row.get('native_column','')))
        if key in seen: errors.append({'row':key,'field':'duplicate_key'})
        seen.add(key)
        if key not in expected:
            errors.append({'row':key,'field':'unknown_source_row'})
            continue
        try:
            reported=float(row['time_ps'])
            if not np.isfinite(reported): raise ValueError
        except (TypeError,ValueError,KeyError):
            errors.append({'row':key,'field':'time_ps','reported':row.get('time_ps')})
            continue
        descriptor_time,native_time=allowed[key[0]]
        if min(abs(reported-descriptor_time),abs(reported-native_time))>1e-6:
            errors.append({'row':key,'field':'time_ps','reported':reported,'allowed_source_times_ps':[descriptor_time,native_time]})
    if seen!=expected:
        errors.append({'field':'missing_or_extra_rows','missing_count':len(expected-seen)})
    return {'rows_checked':len(rows),'expected_rows':len(expected),'errors':errors}

def _pbc(a,b,box):
    import numpy as np
    d=np.asarray(a,dtype=float)-np.asarray(b,dtype=float)
    return (d@np.linalg.inv(box)-np.round(d@np.linalg.inv(box)))@box

def _switch(r,n,m):
    if abs(r-.25)<1e-12: return n/m
    return (1-(r/.25)**n)/(1-(r/.25)**m)

def _g4_frame_features(npz, frame_row):
    import numpy as np
    center=npz['ligand_carbon_geometric_center_nm'][frame_row]; box=npz['box_vectors_nm'][frame_row]
    inv=np.linalg.inv(box); axis=np.array([2.0136,2.0136,2.0]); raw=center-axis; frac=raw@inv; d=(frac-np.round(frac))@box; values={}
    lig=npz['ligand_xyz_nm'][frame_row]; waters=npz['water_OHH_xyz_nm'][frame_row,:,0,:]
    def distances(point):
        delta=waters-point; fractional=delta@inv
        return np.linalg.norm((fractional-np.round(fractional))@box,axis=1)
    for ix,atom_id in enumerate((2,3,11,14),1):
        ds=distances(lig[atom_id-1]); values[f'L{ix}']=float(sum(_switch(float(x),6,10) for x in ds if x<1.0))
    for ix in range(8):
        point=np.array([2.0136,2.0136,2.0+.25*ix]); ds=distances(point)
        values[f'V{ix+1}']=float(sum(_switch(float(x),2,6) for x in ds if x<1.0))
    return float(d[2]),float(np.linalg.norm(d[:2])),values

def _run_verifier(package_dir, rel_script, submission, case_id=None):
    test_root=Path(os.environ.get('TESTS',package_dir/'tests'))
    script=test_root/Path(rel_script).name
    spec=importlib.util.spec_from_file_location('_trusted_numeric_verifier',script)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if case_id=='case-03-binding-free-energy-stop-rule':
        # This trusted verifier expects its public NPZ under the submission
        # root. Build a temporary replay tree with copied trusted input bytes
        # and frozen candidate outputs; never read public data from APP writes.
        with tempfile.TemporaryDirectory(prefix='ccb-d03-replay-') as td:
            root=Path(td); public=Path(package_dir)/'environment/assets/g4-thermodynamic-records.npz'
            if public.is_symlink() or not public.is_file(): raise RuntimeError('trusted public thermodynamic NPZ missing/unsafe')
            asset_dir=root/'environment/assets'; asset_dir.mkdir(parents=True)
            shutil.copyfile(public,asset_dir/public.name)
            for name in ('FES.csv','blocks.csv','thermodynamics.json','sensitivity.csv','sampling-decision.json','audit-report.md','provenance.json'):
                src=Path(submission)/name
                if src.is_file(): shutil.copyfile(src,root/name)
            return module.check(root)
    return module.check(submission)

def _replay_d07_summary(package_dir, payload, protocol, tests):
    """Replay D07's declared bounded summaries, without executing candidate code."""
    import numpy as np
    summary_path,summary=_discover_json(payload/'supporting-analysis',(
        'cv_pairwise_signed_pearson_r','water_model.metrics','thermodynamics.deltaG_kcal_mol',
        'thermodynamics.burn_in_sensitivity.alternative_burn_in_ps','matched_geometry.frame_a'))
    if summary is None:
        return {'status':'JUDGE_REQUIRED','summary':'No integrated summary with the supported numeric schema was found; review the declared supporting files.'}
    mismatches=[]; values={}; trace=package_dir/'environment/assets/g4-native-traces.npz'; coords=package_dir/'environment/assets/g4-coordinate-samples.npz'
    with np.load(trace,allow_pickle=False) as z:
        arrays={k:np.asarray(z[k],dtype=float) for k in ('sw','swb','swc')}
        for a,b in (('sw','swb'),('sw','swc'),('swb','swc')):
            actual=float(np.corrcoef(arrays[a],arrays[b])[0,1]); got=summary['cv_pairwise_signed_pearson_r'].get(f'{a}:{b}')
            values.setdefault('cv_pairwise_signed_pearson_r',{})[f'{a}:{b}']={'reported':got,'recomputed':actual}
            if got is None or not _close(got,actual,1e-6): mismatches.append(f'cv:{a}:{b}')
    with np.load(coords,allow_pickle=False) as z:
        frame_map={int(v):i for i,v in enumerate(z['frame_index'])}
        pair=summary['matched_geometry']; fa=int(pair['frame_a']); fb=int(pair['frame_b'])
        if fa not in frame_map or fb not in frame_map: raise CandidateError('D07 matched geometry references an unknown public frame')
        za,ra,va=_g4_frame_features(z,frame_map[fa]); zb,rb,vb=_g4_frame_features(z,frame_map[fb]); dv=float(np.sqrt(sum((va[f'V{i}']-vb[f'V{i}'])**2 for i in range(1,9))))
        geometry={'frame_a':fa,'frame_b':fb,'abs_delta_z_nm':abs(za-zb),'abs_delta_radius_nm':abs(ra-rb),'V1_V8_euclidean_delta_CN':dv}
        values['matched_geometry']=geometry
        for key,want in geometry.items():
            if key.startswith('frame_'): continue
            if pair.get(key) is None or not _close(pair[key],want,1e-5): mismatches.append('matched_geometry:'+key)
    obs=package_dir/'environment/assets/water-model-observations.csv'
    rows=list(csv.DictReader(obs.open(newline='',encoding='utf-8')))
    if len(rows)!=6: raise RuntimeError('trusted water-model observation table has unexpected row count')
    exp=np.asarray([_num(r['experimental_kcal_mol'],'trusted experimental energy') for r in rows]); water={}
    for name,column in [('TIP3P','TIP3P_mean_kcal_mol'),('TIP4P_EW','TIP4P_EW_mean_kcal_mol')]:
        pred=np.asarray([_num(r[column],'trusted predicted energy') for r in rows]); err=pred-exp; offset=float(err.mean()); centered=err-offset
        concordant=discordant=0
        for i in range(6):
            for j in range(i+1,6):
                q=(pred[i]-pred[j])*(exp[i]-exp[j]); concordant+=q>0; discordant+=q<0
        water[name]={'absolute_rmse_kcal_mol':float(np.sqrt(np.mean(err**2))),'offset_kcal_mol':offset,
                     'offset_rmse_kcal_mol':float(np.sqrt(np.mean(centered**2))),
                     'kendall_tau_a':float((concordant-discordant)/15)}
        observed=summary['water_model']['metrics'].get(name,{})
        for key,want in water[name].items():
            if observed.get(key) is None or not _close(observed[key],want,1e-6): mismatches.append(f'water_model:{name}:{key}')
    values['water_model_metrics']=water
    thermo_script=tests/'decision03_verify.py'
    if thermo_script.is_symlink() or not thermo_script.is_file(): raise RuntimeError('trusted D03 recomputation module missing/unsafe')
    spec=importlib.util.spec_from_file_location('_trusted_d03_recompute',thermo_script)
    if spec is None or spec.loader is None: raise RuntimeError('trusted D03 recomputation module cannot be loaded')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    npz=package_dir/'environment/assets/g4-native-traces.npz'; base=mod.recompute(npz,20000.0,72,None)
    sensitivity=summary['thermodynamics']['burn_in_sensitivity']; alternative=_num(sensitivity['alternative_burn_in_ps'],'D07 sensitivity burn-in')
    alt=mod.recompute(npz,alternative,72,None)
    thermo={'baseline_deltaG_kcal_mol':base['deltaG_kcal'],'reported_baseline_deltaG_kcal_mol':summary['thermodynamics'].get('deltaG_kcal_mol'),
            'alternative_burn_in_ps':alternative,'alternative_deltaG_kcal_mol':alt['deltaG_kcal'],'reported_alternative_deltaG_kcal_mol':sensitivity.get('deltaG_kcal_mol')}
    if thermo['reported_baseline_deltaG_kcal_mol'] is None or not _close(thermo['reported_baseline_deltaG_kcal_mol'],base['deltaG_kcal'],1e-6): mismatches.append('thermodynamics:baseline')
    if thermo['reported_alternative_deltaG_kcal_mol'] is None or not _close(thermo['reported_alternative_deltaG_kcal_mol'],alt['deltaG_kcal'],1e-6): mismatches.append('thermodynamics:sensitivity')
    values['thermodynamics']=thermo
    evidence={'summary_path':summary_path.relative_to(payload).as_posix(),'summary_sha256':sha(summary_path),'recomputed':values}
    hashes={'environment/assets/g4-native-traces.npz':sha(trace),'environment/assets/g4-coordinate-samples.npz':sha(coords),'environment/assets/water-model-observations.csv':sha(obs),'candidate_artifact:'+summary_path.relative_to(payload).as_posix():sha(summary_path)}
    return {'status':'FAIL' if mismatches else 'JUDGE_REQUIRED','summary':'D07 bounded CV, matched-coordinate, six-ligand water-model and thermodynamic claims were independently recomputed; scientific adequacy and conclusions remain for the LLM scientific judge.','checked_values':{'mismatches':mismatches,'evidence':evidence},'source_hashes':hashes}

def evaluate(case_id, package_dir, candidate_root, protocol, refs):
    """Evaluate numeric evidence; unsupported open criteria stay JUDGE_REQUIRED.

    Args are Path-like package/candidate roots and trusted parsed protocol/refs dicts.
    Overall status: FAIL for a confirmed scientific mismatch, INFRA for trusted
    asset/computation errors, otherwise NEEDS_JUDGE when any criterion is open.
    """
    import numpy as np
    package_dir=Path(package_dir); candidate_root=Path(candidate_root)
    payload=candidate_root/'submission' if case_id=='case-06-water-model-free-energy' and (candidate_root/'submission').is_dir() else candidate_root
    criteria=[c['criterion'] for c in protocol.get('criteria',[]) if isinstance(c,dict) and c.get('necessary') is True]
    result={name:_judge('This scientific decision is deferred to the LLM scientific judge.') for name in criteria}
    source_refs=refs.get('source_hashes',{}) if isinstance(refs,dict) else {}
    candidate_phase=False
    try:
        # Trusted declared public inputs are verified before any scientific score.
        for rel,want in source_refs.items():
            if not str(rel).startswith('environment/'):
                continue
            p=package_dir/rel
            if p.is_symlink() or not p.is_file() or sha(p)!=want:
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':f'trusted input failed hash check: {rel}','checked_values':{},'source_hashes':{}} for k in criteria}}
        # Decompress every declared public NPZ to catch malformed scientific assets.
        for rel in source_refs:
            p=package_dir/rel
            if p.suffix=='.npz':
                with np.load(p,allow_pickle=False) as z:
                    for key in z.files: np.asarray(z[key])
        candidate_phase=True
        if case_id=='case-03-binding-free-energy-stop-rule':
            checked=_run_verifier(package_dir,'tests/verify.py',payload,case_id=case_id)
            if checked.get('status','').startswith('FAIL'):
                return {'status':'FAIL','criteria':{k:_fail(checked.get('error','numeric verifier failed')) for k in criteria}}
            sources={k:v for k,v in source_refs.items() if k.startswith('environment/')}
            for idx,c in enumerate(criteria):
                result[c]=_entry('Public-record baseline and declared non-10 ns sensitivity were independently recomputed.',checked,sources) if idx<2 else _judge('Uncertainty semantics and sampling decision remain open scientific judgments.')
            return {'status':'NEEDS_JUDGE','criteria':result}

        if case_id=='case-06-water-model-free-energy':
            import numpy as np
            src=package_dir/'environment/assets/water-model-observations.csv'
            rows=list(csv.DictReader(src.open(newline='',encoding='utf-8')))
            if len(rows)!=6: return {'status':'FAIL','criteria':{k:_fail('candidate task requires six observed ligands') for k in criteria}}
            exp=np.array([_num(x['experimental_kcal_mol'],'experimental energy') for x in rows]); metrics={}; shifts=[]
            def tau_a(a,b):
                concordant=discordant=0
                for i in range(len(a)):
                    for j in range(i+1,len(a)):
                        q=(a[i]-a[j])*(b[i]-b[j]); concordant+=q>0; discordant+=q<0
                return (concordant-discordant)/(len(a)*(len(a)-1)/2)
            for model,col in [('TIP3P','TIP3P_mean_kcal_mol'),('TIP4P_EW','TIP4P_EW_mean_kcal_mol')]:
                pred=np.array([_num(x[col],col) for x in rows]); err=pred-exp; offset=float(np.mean(err)); centered=err-offset
                pearson=float(np.corrcoef(pred,exp)[0,1]); metrics[model]={'absolute_rmse_kcal_mol':float(np.sqrt(np.mean(err**2))),'offset_kcal_mol':offset,
                    'offset_rmse_kcal_mol':float(np.sqrt(np.mean(centered**2))),'pearson_r2':pearson**2,'linear_slope':float(np.polyfit(exp,pred,1)[0]),'kendall_tau':tau_a(pred,exp)}
            shifts=[_num(x['TIP4P_EW_mean_kcal_mol'],'TIP4P_EW')-_num(x['TIP3P_mean_kcal_mol'],'TIP3P') for x in rows]
            out=_read_json(payload/'metrics.json'); per=list(csv.DictReader((payload/'per_ligand_effects.csv').open(newline='',encoding='utf-8')))
            ok=len(per)==6 and all(row.get('ligand')==f'G{i+1}' for i,row in enumerate(per))
            for model in metrics:
                for key,want in metrics[model].items():
                    got=out.get('metrics',{}).get(model,{}).get(key)
                    ok=ok and got is not None and _close(got,want,1e-6)
            for i,row in enumerate(per):
                expected={'TIP4P_EW_minus_TIP3P_kcal_mol':shifts[i],'TIP3P_minus_experiment_kcal_mol':_num(rows[i]['TIP3P_mean_kcal_mol'],'TIP3P')-exp[i],
                    'TIP4P_EW_minus_experiment_kcal_mol':_num(rows[i]['TIP4P_EW_mean_kcal_mol'],'TIP4P_EW')-exp[i]}
                ok=ok and all(row.get(k) is not None and _close(row[k],v,1e-6) for k,v in expected.items())
            c0=criteria[0]; result[c0]=_entry('Recomputed six-ligand absolute/offset errors, regression diagnostics and Kendall tau directly from the public observation CSV.',metrics,{str(src.relative_to(package_dir)):sha(src)}) if ok else _fail('Reported six-ligand metrics or per-ligand shifts differ from recomputation.',metrics)
            c1=criteria[1]; effect=_read_json(payload/'interpretation.json').get('water_model_effect',{}); want_mean=float(np.mean(shifts)); want_more=[f'G{i+1}' for i,v in enumerate(shifts) if v<0]
            interp_ok=_close(effect.get('mean_shift_kcal_mol'),want_mean,1e-6) and effect.get('more_negative_ligands')==want_more
            result[c1]=_entry('Recomputed model-shift mean and per-ligand direction from the public CSV.',{'mean_shift_kcal_mol':want_mean,'more_negative_ligands':want_more},{str(src.relative_to(package_dir)):sha(src)}) if interp_ok else _fail('Reported model shift diagnosis differs from public per-ligand values.')
            for c in criteria[2:]: result[c]=_judge('Ranking/absolute-accuracy interpretation and sampling/causality scope need trusted review.')
            return {'status':'FAIL' if any(v['status']=='FAIL' for v in result.values()) else 'NEEDS_JUDGE','criteria':result}

        if case_id in ('case-01-water-rearrangement-descriptor','case-04-g4-hydration-water-bridge','case-07-water-mechanism-holygrail'):
            g4=package_dir/'environment/assets/g4-coordinate-samples.npz'
            output=payload/'case-04-g4-hydration-water-bridge' if case_id=='case-07-water-mechanism-holygrail' else payload
            if case_id=='case-07-water-mechanism-holygrail':
                # Integrated output may carry the D04 evidence below supporting-analysis.
                output=payload/'supporting-analysis'
            geom_path=output/'geometry-evidence.csv' if case_id=='case-04-g4-hydration-water-bridge' else (payload/'geometry-check.json' if case_id=='case-01-water-rearrangement-descriptor' else _discover_csv(output,{'frame_index','partner_O_or_Br_id','distance_nm'}))
            with np.load(g4,allow_pickle=False) as z:
                if case_id=='case-01-water-rearrangement-descriptor':
                    doc=_read_json(geom_path)
                    if not isinstance(doc,dict): raise CandidateError('geometry-check.json must be a JSON object')
                    closed=doc.get('closed_form_checks',{}); closed=closed if isinstance(closed,dict) else {}
                    raw_radii=closed.get('r_nm',[]); raw6=closed.get('switch_n6_m10',[]); raw2=closed.get('switch_n2_m6',[])
                    radii=[_num(r,'closed-form radius') for r in raw_radii] if isinstance(raw_radii,list) else []
                    exact6=[_switch(r,6,10) for r in radii]; exact2=[_switch(r,2,6) for r in radii]
                    actual6=raw6 if isinstance(raw6,list) else []; actual2=raw2 if isinstance(raw2,list) else []
                    trans=doc.get('translation_invariance',{}); trans=trans if isinstance(trans,dict) else {}
                    trans_keys=('point_a_nm','point_b_nm','box_vectors_nm','lattice_translation','distance_nm','translated_distance_nm')
                    trans_present=all(k in trans for k in trans_keys)
                    if trans_present:
                        ta=np.asarray(trans['point_a_nm'],float); tb=np.asarray(trans['point_b_nm'],float); box=np.asarray(trans['box_vectors_nm'],float); lattice=np.asarray(trans['lattice_translation'],float)
                        delta=_pbc(ta,tb,box); shifted=_pbc(ta+lattice@box,tb,box); d1=float(np.linalg.norm(delta)); d2=float(np.linalg.norm(shifted))
                    else: d1=d2=None; lattice=np.zeros(3)
                    full_frame_count=len(z['frame_index'])
                    closed_present=bool(radii) and len(actual6)==len(radii) and len(actual2)==len(radii)
                    closed_mismatch=closed_present and (any(not _close(a,b,1e-10) for a,b in zip(actual6,exact6)) or any(not _close(a,b,1e-10) for a,b in zip(actual2,exact2)))
                    trans_mismatch=trans_present and (not bool(np.any(lattice)) or not _close(trans['distance_nm'],d1,1e-10) or not _close(trans['translated_distance_nm'],d2,1e-10) or not _close(d1,d2,1e-10))
                    # A declared frame count is descriptive metadata. It is not
                    # independently reproducible unless the candidate supplies
                    # the selected frame IDs; numerical claims below are replayed
                    # from those IDs instead of assuming a full-archive scan.
                    if closed_mismatch or trans_mismatch:
                        result[criteria[0]]=_fail('candidate closed-form switch values or declared lattice-translation calculation disagree',{'r_nm':radii,'actual_n6_m10':actual6,'expected_n6_m10':exact6,'actual_n2_m6':actual2,'expected_n2_m6':exact2,'recomputed_distances_nm':[d1,d2]})
                    elif closed_present and trans_present and 'nm' in str(doc.get('units','')).lower():
                        result[criteria[0]]=_entry('Recomputed the candidate-reported closed-form switching values, units and nonzero lattice-translation check from public coordinates.',{'frames':full_frame_count,'r_nm':radii,'switch_n6_m10':exact6,'switch_n2_m6':exact2,'translation_distances_nm':[d1,d2]},{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                    else:
                        result[criteria[0]]=_judge('Some units/PBC/closed-form evidence was not in a supported numeric form; inspect the complete candidate method and evidence.')
                    # Independently replay every candidate-reported feature summary over all public frames.
                    audit_path=payload/'feature-audit.csv'; audit=list(csv.DictReader(audit_path.open(newline='',encoding='utf-8')))
                    frame_features=[]
                    for fi in range(full_frame_count):
                        _,_,fv=_g4_frame_features(z,fi); frame_features.append(fv)
                    feature_ok=True; feature_values={}; feature_checked=0; feature_unparsed=False; seen_features=set()
                    for row in audit:
                        feature=row.get('feature','')
                        if feature not in frame_features[0]: feature_unparsed=True; continue
                        if feature in seen_features: feature_unparsed=True; continue
                        seen_features.add(feature)
                        vals=np.asarray([r[feature] for r in frame_features],dtype=float)
                        want=(float(vals.mean()),float(vals.std(ddof=1)),float(vals.min()),float(vals.max()))
                        try: got=_summary_stats(row.get('summary_metric',''))
                        except (ValueError,TypeError): feature_unparsed=True; continue
                        unit=' '.join(str(row.get('unit','')).strip().lower().replace('_',' ').split())
                        known_units={'smooth cn','coordination number','dimensionless','unitless','1'}
                        incompatible_units={'nm','angstrom','a','kcal/mol','kj/mol','ps','degree','degrees'}
                        feature_checked+=1; feature_values[feature]={'mean_sd_min_max':want,'reported':got,'unit':unit}
                        if unit in incompatible_units: feature_ok=False
                        elif unit not in known_units: feature_unparsed=True
                        feature_ok=feature_ok and all(_close(a,b,2e-5) for a,b in zip(got,want))
                    if not feature_ok:
                        result[criteria[1]]=_fail('A candidate-reported feature-audit summary/unit differs from full public-coordinate recomputation.',feature_values,{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                    elif feature_unparsed and feature_checked:
                        result[criteria[1]]=_judge('Numeric feature rows were independently checked, but one or more reported statistic/unit forms need scientific review.')
                        result[criteria[1]].update({'checked_values':{'checked_features':feature_values,'rows_checked':feature_checked,'source_frame_count':full_frame_count},'source_hashes':{'environment/assets/g4-coordinate-samples.npz':sha(g4)}})
                    elif feature_checked:
                        result[criteria[1]]=_entry('Recomputed the candidate-reported smooth-CN summary rows over the public coordinate frames; omitted/unsupported feature summaries remain for scientific review.',{'checked_features':feature_values,'rows_checked':feature_checked,'source_frame_count':full_frame_count},{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                    elif feature_unparsed:
                        result[criteria[1]]=_judge('Feature summary format needs scientific review; no unsupported statistic was treated as numerically verified.')
                    # Recompute the claimed matched pair from the actual coordinate frames.
                    x=doc.get('matched_geometry_contrast'); x=x if isinstance(x,dict) else None
                    if x is None:
                        result[criteria[1]]=_judge('No supported matched-geometry nested schema was supplied; inspect the candidate-selected comparisons and reported evidence.')
                        x={}
                    a=x.get('frame_a',{}); b=x.get('frame_b',{})
                    frame_indices=z['frame_index']; look={int(v):i for i,v in enumerate(frame_indices)}
                    if not a or not b:
                        pass
                    elif int(a.get('frame_index',-1)) not in look or int(b.get('frame_index',-1)) not in look:
                        result[criteria[1]]=_fail('matched coordinate frames are absent from the declared NPZ')
                    else:
                        ia,ib=look[int(a['frame_index'])],look[int(b['frame_index'])]
                        za,ra,fa=_g4_frame_features(z,ia); zb,rb,fb=_g4_frame_features(z,ib)
                        dv=math.sqrt(sum((fa[f'V{i}']-fb[f'V{i}'])**2 for i in range(1,9)))
                        details_ok=True; details_seen=False
                        for label,idx,zval,rval,features in (('frame_a',ia,za,ra,fa),('frame_b',ib,zb,rb,fb)):
                            entry=x.get(label,{})
                            for key,want in (('time_ps',z['time_ps'][idx]),('coordinate_z_nm',zval),('coordinate_radius_nm',rval)):
                                if key in entry: details_seen=True; details_ok=details_ok and _close(entry[key],want,1e-5)
                            for fname,fvalue in features.items():
                                if fname in entry: details_seen=True; details_ok=details_ok and _close(entry[fname],fvalue,1e-5)
                        tolerance_present=isinstance(x.get('pair_match_tolerance_nm'),dict) and all(k in x['pair_match_tolerance_nm'] for k in ('abs_delta_z_max','abs_delta_radius_max'))
                        if tolerance_present:
                            tol=x['pair_match_tolerance_nm']; tz=_num(tol['abs_delta_z_max'],'declared z-match tolerance'); tr=_num(tol['abs_delta_radius_max'],'declared radius-match tolerance')
                            details_ok=details_ok and tz>0 and tr>0 and abs(za-zb)<=tz and abs(ra-rb)<=tr
                        for key,want in (('abs_delta_z_nm',abs(za-zb)),('abs_delta_radius_nm',abs(ra-rb)),('V1_V8_euclidean_delta_CN',dv),('V1_V8_Euclidean_delta_CN',dv)):
                            if key in x: details_seen=True; details_ok=details_ok and _close(x[key],want,1e-5)
                        check={'frames':[int(a['frame_index']),int(b['frame_index'])],'z_nm':[za,zb],'r_nm':[ra,rb],'V_cn_euclidean_difference':dv}
                        if not details_ok:
                            result[criteria[1]]=_fail('A candidate-reported matched-pair coordinate or CN value differs from recomputation.',check,{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                        elif details_seen:
                            if result[criteria[1]]['status']!='FAIL': result[criteria[1]]=_entry('Recomputed candidate-reported pair coordinates and values; scientific meaning of the selected match remains under review.',check,{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                        else:
                            result[criteria[1]]=_judge('Candidate supplied frame IDs but no supported numeric values or match tolerance to replay.')
                else:
                    coord_rel='coordinate-observables.csv' if case_id=='case-04-g4-hydration-water-bridge' else 'coordinate-observables.csv'
                    coord_path=(payload/coord_rel) if case_id=='case-04-g4-hydration-water-bridge' else _discover_csv(payload/'supporting-analysis',{'source_frame_index','time_ps','coordinate_z_nm','coordinate_radius_nm'})
                    mapping=package_dir/'environment/assets/atom-metadata.json'; meta=_read_json(mapping)
                    coord_rows=list(csv.DictReader(coord_path.open(newline='',encoding='utf-8'))) if coord_path else []
                    frame_indices=np.asarray(z['frame_index']); frame_lookup={int(v):i for i,v in enumerate(frame_indices)}
                    coord_ok=bool(coord_rows); coord_supported=0; coord_checked={}; coord_seen=set(); coord_unsupported=[]
                    for row in coord_rows:
                        frame=int(row['source_frame_index']); i=frame_lookup.get(frame)
                        if i is None: coord_ok=False; continue
                        if frame in coord_seen: coord_ok=False
                        coord_seen.add(frame)
                        zz,rr,fv=_g4_frame_features(z,i)
                        values={'time_ps':float(z['time_ps'][i]),'coordinate_z_nm':zz,'coordinate_radius_nm':rr}
                        for key,want in values.items():
                            if row.get(key,'').strip():
                                got=_num(row[key],f'reported {key}')
                                coord_checked[f'{frame}:{key}']={'reported':got,'recomputed':want}
                                if not _close(got,want,1e-5): coord_ok=False
                                else: coord_supported+=1
                        try: reported=_strict_json_text(row.get('feature_values',''))
                        except Exception:
                            coord_ok=False; continue
                        if not isinstance(reported,dict): coord_ok=False; continue
                        for key,value in reported.items():
                            if key not in fv:
                                coord_unsupported.append({'frame':frame,'feature':key,'reported':value}); continue
                            want=fv[key]; got=_num(value,'reported coordinate CN')
                            coord_checked[f'{frame}:{key}']={'reported':got,'recomputed':want}
                            if not _close(got,want,1e-5): coord_ok=False
                            else: coord_supported+=1
                    cgeom=next((c for c in criteria if c.startswith('coordinate_geometry_atom_ids_units_and_pbc') or c.startswith('mechanism_geometry_and_water_model_uncertainty')),criteria[0])
                    if case_id=='case-07-water-mechanism-holygrail' and not coord_rows:
                        result[cgeom]=_judge('No coordinate-observation table was supplied among the D07 supporting files; inspect the independently checked analyses and candidate-selected evidence.')
                    elif not coord_ok:
                        result[cgeom]=_fail('A candidate-reported coordinate frame, z/r, or smooth-CN value differs from public PBC recomputation.',{'rows':len(coord_rows),'checked':coord_checked},{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                    elif coord_supported:
                        evidence={'rows':len(coord_rows),'candidate_reported_values_checked':coord_supported,'frames':sorted(coord_seen)[:12],'numeric_claims':coord_checked}
                        if coord_unsupported:
                            result[cgeom]=_judge('Reported coordinates and recognized quantities were numerically replayed; additional feature fields need scientific review.')
                            evidence['unverified_features']=coord_unsupported[:20]
                            result[cgeom].update({'checked_values':evidence,'source_hashes':{'environment/assets/g4-coordinate-samples.npz':sha(g4)}})
                        else:
                            result[cgeom]=_entry('Recomputed every candidate-reported source-frame coordinate z/r and named known smooth-CN value; candidate selection coverage remains method-neutral.',evidence,{'environment/assets/g4-coordinate-samples.npz':sha(g4)})
                    else:
                        result[cgeom]=_judge('Candidate coordinate observations contain no supported numeric field to replay.')
                    if case_id=='case-04-g4-hydration-water-bridge':
                        state_doc=_read_json(payload/'state-hypotheses.json')
                        if isinstance(state_doc,list):
                            hypotheses=state_doc
                        elif isinstance(state_doc,dict) and isinstance(state_doc.get('hypotheses'),list):
                            hypotheses=state_doc['hypotheses']
                        else:
                            raise CandidateError('state-hypotheses.json must be a hypothesis list or an object with a hypotheses list')
                        if any(not isinstance(hyp,dict) for hyp in hypotheses):
                            raise CandidateError('state-hypotheses.json contains a non-object hypothesis')
                        pairs=[]; pair_ok=True
                        def frame_id(value):
                            if isinstance(value,bool):
                                raise CandidateError('matched_frames must contain integer frame IDs')
                            if isinstance(value,int): return value
                            if isinstance(value,float) and math.isfinite(value) and value.is_integer():
                                return int(value)
                            if isinstance(value,str) and re.fullmatch(r'-?(?:0|[1-9][0-9]*)',value.strip()):
                                return int(value.strip())
                            raise CandidateError('matched_frames must contain exact integer frame IDs')
                        for hyp in hypotheses:
                            selected=hyp.get('matched_frames',[])
                            if not isinstance(selected,list) or len(selected)<2: continue
                            for left,right in zip(selected,selected[1:]):
                                left_i=frame_id(left); right_i=frame_id(right)
                                li=frame_lookup.get(left_i); ri=frame_lookup.get(right_i)
                                if li is None or ri is None: pair_ok=False; continue
                                lz,lr,lf=_g4_frame_features(z,li); rz,rr,rf=_g4_frame_features(z,ri)
                                pairs.append({'frames':[left_i,right_i],'z_nm':[lz,rz],'r_nm':[lr,rr],
                                    'abs_delta_z_nm':abs(lz-rz),'abs_delta_radius_nm':abs(lr-rr),
                                    'L1_L4_CN_delta':[lf[f'L{k}']-rf[f'L{k}'] for k in range(1,5)],
                                    'V1_V8_CN_delta':[lf[f'V{k}']-rf[f'V{k}'] for k in range(1,9)]})
                        cmatched=next((c for c in criteria if c.startswith('matched_z_and_radius_hydration_contrast')),criteria[1])
                        if pairs and pair_ok:
                            result[cmatched]=_judge('Candidate-selected matched coordinate and hydration values were recomputed; whether the match is scientifically adequate remains open.')
                            result[cmatched].update({'checked_values':{'pairs':pairs},'source_hashes':{'environment/assets/g4-coordinate-samples.npz':sha(g4)}})
                        elif not hypotheses:
                            result[cmatched]=_judge('No candidate-selected matched-frame claim was supplied for independent replay.')
                        else:
                            result[cmatched]=_fail('A candidate matched-frame claim references an unknown source frame.')
                    rows=list(csv.DictReader(geom_path.open(newline='',encoding='utf-8'))) if geom_path else []; frame_lookup={int(v):i for i,v in enumerate(z['frame_index'])}
                    water_ids=z['water_atom_ids_OHH_1based']; water_lookup={int(atom):wi for wi,atom in enumerate(water_ids[:,0])}
                    ligand_ids=z['ligand_atom_ids_1based']; br_id=int(meta['guest_bromine']['atom_id_1based']); br_idx=int(np.where(ligand_ids==br_id)[0][0])
                    host_ids=z['host_atom_ids_1based']; host_allowed={int(a['atom_id_1based']) for a in meta['host_oxygen_atoms']}; measurements=[]; valid_rows=True; unsupported_rows=0; checked_rows=0
                    for row in rows:
                        if not row.get('frame_index','').strip(): continue
                        checked_rows+=1
                        frame=int(row['frame_index']); i=frame_lookup.get(frame)
                        if i is None: valid_rows=False; continue
                        box=z['box_vectors_nm'][i]; partner=str(row.get('partner_O_or_Br_id','')).strip(); water_id=str(row.get('water_O_ids','')).strip(); h_id=str(row.get('water_H_ids','')).strip()
                        if not water_id and partner==f'Br:{br_id}':
                            hid_text=str(row.get('host_O_id','')).strip()
                            if not hid_text or int(hid_text) not in host_allowed: valid_rows=False; continue
                            hid=int(hid_text)
                            if hid not in set(map(int,host_ids)) or hid not in host_allowed: valid_rows=False; continue
                            hi=int(np.where(host_ids==hid)[0][0]); value=float(np.linalg.norm(_pbc(z['host_xyz_nm'][i,hi],z['ligand_xyz_nm'][i,br_idx],box))); angle=None
                        elif water_id and partner.startswith(('Br:','O:')):
                            donor=int(water_id); wi=water_lookup.get(donor); hh=int(h_id) if h_id else -1
                            if wi is None or hh not in set(map(int,water_ids[wi,1:])): valid_rows=False; continue
                            idsrow=water_ids[wi]; donor_idx=int(np.where(idsrow==donor)[0][0]); hidx=int(np.where(idsrow==hh)[0][0]); donor_o=z['water_OHH_xyz_nm'][i,wi,donor_idx]; hxyz=z['water_OHH_xyz_nm'][i,wi,hidx]
                            if partner.startswith('Br:'):
                                aid=int(partner.split(':',1)[1]);
                                if aid!=br_id: valid_rows=False; continue
                                acceptor=z['ligand_xyz_nm'][i,br_idx]
                            else:
                                aid=int(partner.split(':',1)[1]); accept_wi=water_lookup.get(aid)
                                if accept_wi is None: valid_rows=False; continue
                                accept_ids=water_ids[accept_wi]; ai=int(np.where(accept_ids==aid)[0][0]); acceptor=z['water_OHH_xyz_nm'][i,accept_wi,ai]
                            value=float(np.linalg.norm(_pbc(donor_o,acceptor,box))); vD=_pbc(donor_o,hxyz,box); vA=_pbc(acceptor,hxyz,box)
                            angle=math.degrees(math.acos(float(np.clip(np.dot(vD,vA)/(np.linalg.norm(vD)*np.linalg.norm(vA)),-1,1))))
                        elif partner.startswith('Br:') or partner.startswith('O:'):
                            valid_rows=False; continue
                        else:
                            # Preserve unsupported rows for the reviewer instead
                            # of silently skipping them and promoting other rows.
                            unsupported_rows+=1; continue
                        measurements.append({'frame_index':frame,'partner':partner,'distance_nm':value,'angle_deg':angle})
                        if not row.get('distance_nm','').strip() or not _close(row['distance_nm'],value,1e-5): valid_rows=False
                        if angle is not None and row.get('angle_deg','').strip() and not _close(row['angle_deg'],angle,0.05): valid_rows=False
                        distance_relation=str(row.get('cutoff_relation','')).strip().lower()
                        angle_relation=str(row.get('angle_relation','')).strip().lower()
                        cutoff_status=[]
                        if distance_relation=='distance_le':
                            cutoff=_num(row.get('distance_cutoff_nm'),'distance cutoff'); cutoff_status.append(value<=cutoff)
                        elif distance_relation=='distance_ge':
                            cutoff=_num(row.get('distance_cutoff_nm'),'distance cutoff'); cutoff_status.append(value>=cutoff)
                        elif distance_relation not in ('','reported_only'): valid_rows=False
                        if angle_relation=='angle_ge' and angle is not None:
                            cutoff=_num(row.get('angle_cutoff_deg'),'angle cutoff'); cutoff_status.append(angle>=cutoff)
                        elif angle_relation=='angle_le' and angle is not None:
                            cutoff=_num(row.get('angle_cutoff_deg'),'angle cutoff'); cutoff_status.append(angle<=cutoff)
                        elif angle_relation not in ('','reported_only'): valid_rows=False
                        claim=str(row.get('meets_criterion','')).strip().lower()
                        if cutoff_status and claim in ('true','false') and (all(cutoff_status)!=(claim=='true')): valid_rows=False
                        elif claim in ('true','false') and not cutoff_status: unsupported_rows+=1
                    c=next((name for name in criteria if ('water_bridge' in name or 'mechanism_geometry' in name)),criteria[-1])
                    if measurements and valid_rows and not unsupported_rows:
                        result[c]=_judge('Reported geometry values were independently recomputed; open bridge/causal interpretation and sampling limits still require scientific review.')
                        result[c].update({'checked_values':{'rows_recomputed':len(measurements),'reported_rows':checked_rows,'sample_rows':measurements[:5],'atom_mapping_sha256':sha(mapping)},'source_hashes':{'environment/assets/g4-coordinate-samples.npz':sha(g4),'environment/assets/atom-metadata.json':sha(mapping)}})
                    elif measurements and valid_rows:
                        result[c]=_judge('Some candidate-reported geometry rows use unsupported atom/criterion fields; only the listed known rows were numerically replayed.')
                        result[c].update({'checked_values':{'rows_recomputed':len(measurements),'reported_rows':checked_rows,'unsupported_rows':unsupported_rows,'sample_rows':measurements[:5]},'source_hashes':{'environment/assets/g4-coordinate-samples.npz':sha(g4),'environment/assets/atom-metadata.json':sha(mapping)}})
                    elif measurements:
                        result[c]=_fail('At least one candidate-reported atom-level distance/angle differs from source-coordinate recomputation.',{'rows_recomputed':len(measurements),'sample_rows':measurements[:5]})
                    else: result[c]=_judge('No supported geometry rows were available for independent numeric replay.')
        if case_id=='case-02-water-cv-validation':
            src=package_dir/'environment/assets/g4-native-traces.npz'; out=payload/'cv-audit.csv'
            prov_path=package_dir/'environment/assets/trace-provenance.json'; published=_read_json(prov_path)
            decision=_read_json(payload/'decision.json'); claimed=decision.get('source_provenance',{})
            with np.load(src,allow_pickle=False) as z:
                actual_n=len(z['time_ps']); actual_times=np.asarray(z['time_ps'],dtype=float); actual_keys=set(z.files)
            selected=claimed.get('selected_network_outputs',[]); mapping=claimed.get('native_column_mapping',{})
            duplicate=claimed.get('duplicate_column_audit',{})
            npz_path='environment/assets/g4-native-traces.npz'
            prov_rel='environment/assets/trace-provenance.json'
            npz_sha=sha(src); prov_sha=sha(prov_path)
            source_fields=set(published.get('fields',[]))
            network_fields={'sw','swb','swc','node0','node1','node2'}
            selected_valid=(isinstance(selected,list) and len(selected)==3
                and all(isinstance(v,str) for v in selected) and len(set(selected))==3
                and set(selected).issubset(network_fields & actual_keys))
            selected_columns=claimed.get('selected_columns',[])
            selected_columns_valid=(isinstance(selected_columns,list)
                and all(isinstance(v,str) for v in selected_columns)
                and set(selected_columns).issubset(actual_keys))
            mapping_valid=False; mapping_review=False; mapping_bad=False
            if isinstance(mapping,dict) and all(isinstance(k,str) for k in mapping):
                pairs=mapping.get('supported_affine_gauge_pairs')
                if isinstance(pairs,list):
                    mapping_review=True
                    known_metrics={'pearson_r','slope','intercept','rms_affine_residual',
                        'relative_to_native_sd','block_max_rms','cyl_z_quartile_max_rms'}
                    for pair in pairs:
                        if not isinstance(pair,dict):
                            mapping_review=True; continue
                        for field in ('native_column','model_output'):
                            allowed=actual_keys if field=='native_column' else {'sw','s_raw'}
                            if not isinstance(pair.get(field),str) or pair[field] not in allowed:
                                mapping_bad=True
                        if 'model_id' in pair and (not isinstance(pair['model_id'],str) or not pair['model_id']):
                            mapping_bad=True
                        if set(pair)-({'native_column','model_output','model_id'}|known_metrics):
                            mapping_review=True
                        for field in known_metrics & set(pair):
                            try: _num(pair[field],f'native mapping {field}')
                            except CandidateError: mapping_bad=True
                        mapping_review=mapping_review or not known_metrics.issubset(pair)
                elif all(isinstance(v,str) for v in mapping.values()) and set(mapping).issubset(source_fields):
                    mapping_valid=(set(mapping).issubset(set(selected))
                        and all(mapping.get(name)==name for name in mapping)
                        and all(name in mapping for name in selected))
                    mapping_review=not mapping_valid
                else:
                    mapping_review=True
                    # Explicit source-column references remain hard-checked even
                    # when the surrounding mapping layout is left for review.
            else:
                mapping_review=True
            native_path=claimed.get('native_record_path')
            native_sha=claimed.get('native_record_sha256')
            native_identity_ok=((native_path==published.get('path') and native_sha==published.get('sha256'))
                or (native_path==npz_path and native_sha==npz_sha))
            optional_path_hashes_ok=(
                all(claimed.get(k) in (None, expected) for k,expected in (
                    ('public_input_path',npz_path),('converted_npz_path',npz_path),
                    ('trace_provenance_path',prov_rel)))
                and all(claimed.get(k) in (None, expected) for k,expected in (
                    ('public_input_sha256',npz_sha),('converted_npz_sha256',npz_sha),
                    ('trace_provenance_sha256',prov_sha)))
                and (claimed.get('public_input_path')==npz_path or claimed.get('converted_npz_path')==npz_path or native_path==npz_path))
            provenance_ok=(native_identity_ok
                and claimed.get('acquired_colvar_path')==published.get('path')
                and claimed.get('acquired_colvar_sha256')==published.get('sha256')
                and claimed.get('source_sha256')==published.get('sha256')
                and claimed.get('public_input_sha256')==npz_sha
                and optional_path_hashes_ok
                and selected_valid and selected_columns_valid and not mapping_bad
                and claimed.get('row_count')==actual_n==published.get('rows')
                and claimed.get('time_range_ps')==[float(actual_times[0]),float(actual_times[-1])]
                and isinstance(claimed.get('available_archive_keys'),list)
                and set(claimed.get('available_archive_keys',[]))==actual_keys
                and len(claimed.get('available_archive_keys',[]))==len(set(claimed.get('available_archive_keys',[])))
                and claimed.get('archive_key_names_unique') is True)
            raw_duplicate_claim_ok=(isinstance(duplicate,dict)
                and duplicate.get('candidate_claims_raw_duplicate_values_recomputed') is False)
            trusted_sources={'environment/assets/g4-native-traces.npz':npz_sha,
                'environment/assets/trace-provenance.json':prov_sha}
            if not provenance_ok:
                result[criteria[0]]=_fail('Candidate source and conversion paths, hashes, rows, time range, keys, or native-column mapping do not match the public records.')
            elif not raw_duplicate_claim_ok:
                result[criteria[0]]=_fail('Candidate must not claim that omitted raw duplicate columns were independently recomputed from the unique-column NPZ.')
            else:
                mapping_summary=('Mapping fields are known, but this mapping layout requires independent scientific review. ' if mapping_review else 'The declared column mapping matches known source fields. ')
                result[criteria[0]]=_judge('Source paths, hashes, decoded row count/time range, available NPZ keys, and selected outputs were independently checked. '+mapping_summary+'The public record states the duplicate-column conversion policy; assess the candidate’s description of this policy and its limits from the cited evidence.')
                result[criteria[0]].update({'checked_values':{
                    'rows':actual_n,'time_range_ps':[float(actual_times[0]),float(actual_times[-1])],
                    'selected_network_outputs':selected,'raw_duplicate_values_reaudited':False,
                    'published_duplicate_field_policy':published.get('duplicate_field_policy'),
                    'candidate_duplicate_field_policy':duplicate.get('documented_policy'),
                    'candidate_duplicate_audit_status':duplicate.get('status'),
                    'candidate_claims_raw_duplicate_values_recomputed':False,
                    'npz_contains_raw_duplicate_columns':False},'source_hashes':trusted_sources})
            def ranks(values):
                vals=np.asarray(values); order=np.argsort(vals,kind='mergesort'); result=np.empty(len(vals),dtype=float); i=0
                while i<len(order):
                    j=i+1
                    while j<len(order) and vals[order[j]]==vals[order[i]]: j+=1
                    result[order[i:j]]=(i+j-1)/2+1; i=j
                return result
            with np.load(src,allow_pickle=False) as z:
                n=len(z['time_ps']); arrays={k:np.asarray(z[k],dtype=float) for k in ('sw','swb','swc')}
            rows=list(csv.DictReader(out.open(newline='',encoding='utf-8'))); passed=[]; checked_corr={}; unsupported_pairs=[]; unsupported_statistics=[]
            import re
            # Accept only the three published scalar names with either
            # slash/colon separators and harmless whitespace.  Do not fuzzy
            # match misspelled or unknown variables into a supported pair.
            def normalize_pair(value):
                if not isinstance(value,str): return None
                compact=re.sub(r'\s+','',value.strip())
                parts=re.split(r'[/ :]',compact)
                parts=[p for p in parts if p]
                if len(parts)!=2 or any(p not in arrays for p in parts) or parts[0]==parts[1]:
                    return None
                return ':'.join(sorted(parts))
            for a,b in (('sw','swb'),('sw','swc'),('swb','swc')):
                pair=f'{a}:{b}'; x,y=arrays[a],arrays[b]
                pair_rows=[r for r in rows if normalize_pair(r.get('output_pair'))==pair]
                full_rows=[]
                for r in pair_rows:
                    n_text=str(r.get('n','')).strip()
                    if not re.fullmatch(r'[0-9]+',n_text):
                        unsupported_statistics.append({'output_pair':r.get('output_pair'),'sample_count':n_text,'method':r.get('correlation_method')})
                        continue
                    row_n=int(n_text)
                    if row_n==n: full_rows.append(r)
                    else: unsupported_statistics.append({'output_pair':r.get('output_pair'),'sample_count':row_n,'method':r.get('correlation_method')})
                if not full_rows:
                    # No supported full-record statistic is a review question;
                    # it is not automatically a false numeric claim.
                    passed.append(None); continue
                pair_all_ok=True; pair_supported=False
                for row in full_rows:
                    method=row.get('correlation_method','').lower()
                    if 'spearman' in method: corr=float(np.corrcoef(ranks(x),ranks(y))[0,1]); method_name='Spearman'
                    elif 'pearson' in method: corr=float(np.corrcoef(x,y)[0,1]); method_name='Pearson'
                    else:
                        passed.append(None); continue
                    text=row.get('correlation_or_error',''); signed=re.search(r'signed_r\s*=\s*([-+0-9.eE]+)',text); absolute=re.search(r'abs_r\s*=\s*([-+0-9.eE]+)',text)
                    absolute=re.search(r'abs_r\s*=\s*([-+0-9.eE]+)',text)
                    align_text=str(row.get('sign_alignment','')).strip()
                    if align_text in ('1','+1','none','identity','same sign','same_sign'):
                        alignment=1
                    elif align_text in ('-1','negative','sign-flipped','sign_flipped'):
                        alignment=-1
                    else:
                        gauge=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*)\s*->\s*(-?)\1',align_text)
                        if gauge and gauge.group(1) in (a,b): alignment=-1 if gauge.group(2)=='-' else 1
                        else: alignment=0
                    if signed:
                        observed=float(signed.group(1))
                    elif absolute:
                        observed=float(absolute.group(1))*alignment
                    else:
                        nums=re.findall(r'(?<![A-Za-z0-9_])[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?',text)
                        observed=float(nums[0]) if nums else float('nan')
                    abs_ok=(not absolute) or math.isclose(float(absolute.group(1)),abs(corr),rel_tol=0,abs_tol=1e-6)
                    ok=(math.isfinite(observed) and math.isclose(observed,corr,rel_tol=0,abs_tol=1e-6) and abs_ok
                        and alignment==(1 if corr>=0 else -1))
                    pair_all_ok=pair_all_ok and ok; pair_supported=True
                    checked_corr.setdefault(pair,[]).append({'method':method_name,'signed_correlation':corr,'reported':observed,'sign_alignment':alignment,'sample_count':n})
                passed.append(pair_all_ok if pair_supported else None)
            for row in rows:
                raw_pair=row.get('output_pair')
                if raw_pair and normalize_pair(raw_pair) is None:
                    unsupported_pairs.append(raw_pair)
            c=criteria[1]
            if any(p is False for p in passed):
                result[c]=_fail('At least one candidate-declared full-record CV statistic, sample count or sign alignment differs from recomputation.',{'rows':int(n),'pairs':checked_corr},{'environment/assets/g4-native-traces.npz':sha(src)})
            elif any(p is None for p in passed) or unsupported_pairs or unsupported_statistics:
                result[c]=_judge('Supported full-record statistics were recomputed where declared; omitted pairs or unsupported methods remain open for scientific review.')
                result[c].update({'checked_values':{'rows':int(n),'pairs':checked_corr,'unsupported_pair_labels':unsupported_pairs,'unsupported_statistics':unsupported_statistics[:20]},'source_hashes':{'environment/assets/g4-native-traces.npz':sha(src)}})
            else:
                result[c]=_entry('Recomputed candidate-declared full-record pairwise correlation using its Pearson or Spearman method, sample count and sign alignment.',{'rows':int(n),'pairs':checked_corr},{'environment/assets/g4-native-traces.npz':sha(src)})
            time_check=_case02_output_time_errors(package_dir,payload)
            if time_check['errors']:
                result[criteria[3]]=_fail('Model-output audit rows use duplicate, unknown, or non-source time values.',time_check,{
                    'environment/assets/g4-native-traces.npz':sha(src),
                    'environment/assets/g4-descriptors.csv':sha(package_dir/'environment/assets/g4-descriptors.csv')})

        if case_id=='case-05-apo-cavity-hydration':
            # The separately maintained apo checker independently replays the
            # candidate-declared cavity, time joins, and reported graph scope.
            test_root=Path(os.environ.get('TESTS',package_dir/'tests'))
            checker=test_root/'apo_numeric.py'
            if checker.is_symlink() or not checker.is_file():
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':'trusted apo numeric checker missing/unsafe','checked_values':{},'source_hashes':{}} for k in criteria}}
            spec=importlib.util.spec_from_file_location('_trusted_apo_numeric',checker)
            if spec is None or spec.loader is None:
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':'trusted apo numeric checker cannot be loaded','checked_values':{},'source_hashes':{}} for k in criteria}}
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            apo=module.evaluate_apo(package_dir,payload,protocol,refs)
            if not isinstance(apo,dict) or apo.get('status') not in ('PASS','FAIL','INFRA','NEEDS_JUDGE') or not isinstance(apo.get('criteria'),dict):
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':'trusted apo numeric checker returned an invalid result','checked_values':{},'source_hashes':{}} for k in criteria}}
            for criterion,item in apo['criteria'].items():
                if criterion in result and isinstance(item,dict): result[criterion]=item
            if apo['status']=='INFRA': return {'status':'INFRA','criteria':result}

        if case_id=='case-07-water-mechanism-holygrail':
            tests=Path(os.environ.get('TESTS',package_dir/'tests'))
            checker=tests/'d07_split_numeric.py'
            integrated_checker=tests/'d07_integrated_numeric.py'
            for trusted_checker in (checker,integrated_checker):
                if trusted_checker.is_symlink() or not trusted_checker.is_file():
                    return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':f'trusted D07 numeric checker missing/unsafe: {trusted_checker.name}','checked_values':{},'source_hashes':{}} for k in criteria}}
            def load_checker(path, name):
                spec=importlib.util.spec_from_file_location(name,path)
                if spec is None or spec.loader is None: raise RuntimeError(f'trusted D07 checker cannot be loaded: {path.name}')
                module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
            split_module=load_checker(checker,'_trusted_d07_split_numeric')
            split=split_module.evaluate_d07_split(package_dir,payload,refs)
            if not isinstance(split,dict) or split.get('status') not in ('FAIL','INFRA','NEEDS_JUDGE') or not isinstance(split.get('criteria'),dict):
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':'trusted D07 split checker returned invalid output','checked_values':{},'source_hashes':{}} for k in criteria}}
            if split['status']=='INFRA':
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':split.get('error','trusted D07 input/recompute failure'),'checked_values':{},'source_hashes':{}} for k in criteria}}
            integrated_module=load_checker(integrated_checker,'_trusted_d07_integrated_numeric')
            integrated=integrated_module.evaluate_d07_integrated(package_dir,payload,refs)
            if not isinstance(integrated,dict) or integrated.get('status') not in ('FAIL','INFRA','NEEDS_JUDGE') or not isinstance(integrated.get('criteria'),dict):
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':'trusted D07 integrated checker returned invalid output','checked_values':{},'source_hashes':{}} for k in criteria}}
            if integrated['status']=='INFRA':
                return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':integrated.get('error','trusted D07 input/recompute failure'),'checked_values':{},'source_hashes':{}} for k in criteria}}
            split_checks=split['criteria']; integrated_item=integrated['criteria'].get('integrated_summary',{})
            integrated_values=integrated_item.get('checked_values',{}) if isinstance(integrated_item,dict) else {}
            integrated_checked=integrated_values.get('checked',{}) if isinstance(integrated_values,dict) else {}
            integrated_errors=integrated_values.get('mismatches',[]) if isinstance(integrated_values,dict) else []
            if isinstance(integrated_values,dict) and not integrated_checked and isinstance(integrated_values.get('files'),list):
                # Multi-summary results retain a checked-values block per source file.
                for file_record in integrated_values['files']:
                    item=(file_record.get('result',{}) if isinstance(file_record,dict) else {})
                    child_checked=item.get('checked_values',{}).get('checked',{}) if isinstance(item,dict) else {}
                    for section,values in child_checked.items():
                        integrated_checked.setdefault(section,[]).append({'path':file_record.get('path'),'values':values})
            def integrated_targets(error):
                if isinstance(error,dict):
                    text=(str(error.get('criterion',''))+' '+str(error.get('path',''))+' '+' '.join(map(str,error.get('errors',[])))).lower()
                else:
                    text=str(error).lower()
                if 'thermodynamic' in text or 'burn-in' in text or 'baseline' in text or 'sensitivity' in text: return {2}
                if 'cv pearson' in text or 'cv_pairwise' in text: return {1}
                if 'matched geometry' in text or 'water_model' in text or 'tip3p' in text or 'tip4p' in text: return {3}
                return {0}
            integrated_failures={}
            if isinstance(integrated_item,dict) and integrated_item.get('status')=='FAIL':
                for error in integrated_errors or ['integrated-summary numeric mismatch']:
                    for ix in integrated_targets(error): integrated_failures.setdefault(ix,[]).append(str(error))
            split_to_main={
                0:('source_provenance',),
                1:('water_model',),
                2:('thermodynamics',),
                3:('native_coordinates',),
            }
            integrated_to_main={
                0:(),
                1:('cv_pairwise_signed_pearson_r',),
                2:('thermodynamics',),
                3:('water_model','matched_geometry'),
            }
            def integrated_evidence_for(ix):
                selected={key:integrated_checked[key] for key in integrated_to_main.get(ix,()) if key in integrated_checked}
                unverified=[x for x in integrated_values.get('unverified_fields',[]) if
                    (ix==1 and str(x).startswith('cv_pairwise')) or
                    (ix==2 and str(x).startswith('thermodynamics')) or
                    (ix==3 and (str(x).startswith('water_model') or str(x).startswith('matched_geometry')))]
                summary=integrated_item.get('summary') if isinstance(integrated_item,dict) else None
                source_hashes=integrated_item.get('source_hashes',{}) if isinstance(integrated_item,dict) else {}
                if not selected and not unverified and not integrated_failures.get(ix): return None
                return {'summary':summary,'checked':selected,'unverified_fields':unverified,
                        'mismatches':integrated_failures.get(ix,[]),
                        'source_hashes':source_hashes,
                        'candidate_summary':integrated_values.get('summary_path'),
                        'candidate_files':integrated_values.get('files',[]) if isinstance(integrated_values,dict) else []}
            for ix,criterion in enumerate(criteria):
                split_names=split_to_main.get(ix,())
                items=[split_checks[name] for name in split_names if isinstance(split_checks.get(name),dict)]
                failures=[x for x in items if x.get('status')=='FAIL']
                integrated_evidence=integrated_evidence_for(ix)
                if integrated_failures.get(ix): failures.extend(integrated_failures[ix])
                if failures:
                    messages=[x.get('summary','numeric mismatch') if isinstance(x,dict) else str(x) for x in failures]
                    checked_values={'split_subchecks':{name:split_checks[name].get('checked_values',{}) for name in split_names if isinstance(split_checks.get(name),dict)}}
                    hashes={'split_subchecks':{name:split_checks[name].get('source_hashes',{}) for name in split_names if isinstance(split_checks.get(name),dict)}}
                    if integrated_evidence:
                        checked_values['integrated_summary']=integrated_evidence
                        hashes['integrated_summary']=integrated_evidence.get('source_hashes',{})
                    result[criterion]=_fail('; '.join(messages),checked_values,hashes)
                else:
                    result[criterion]=_judge('Split and recognized integrated numeric claims were independently replayed; unsupported layouts and open scientific conclusions remain for review.')
                    checked_values={'split_subchecks':{name:split_checks[name].get('checked_values',{}) for name in split_names if isinstance(split_checks.get(name),dict)}}
                    hashes={'split_subchecks':{name:split_checks[name].get('source_hashes',{}) for name in split_names if isinstance(split_checks.get(name),dict)}}
                    if integrated_evidence:
                        checked_values['integrated_summary']=integrated_evidence
                        hashes['integrated_summary']=integrated_evidence.get('source_hashes',{})
                    result[criterion].update({'checked_values':checked_values,'source_hashes':hashes})
            # The fifth D07 criterion concerns open decision quality and budget.
            result[criteria[4]]=_judge('Research-priority, resource, stop/go and falsifier claims require scientific review.')
        # Any criteria that were not numerically inspected remain explicit review items.
        for c in criteria:
            if c not in result: result[c]=_judge('Numerical evidence is present, but this criterion includes an open scientific judgment.')
        if any(x['status']=='INFRA' for x in result.values()): status='INFRA'
        elif any(x['status']=='FAIL' for x in result.values()): status='FAIL'
        else: status='NEEDS_JUDGE'
        return {'status':status,'criteria':result}
    except CandidateError as exc:
        return {'status':'FAIL','criteria':{k:_fail(str(exc)) for k in criteria}}
    except (KeyError, TypeError, IndexError, ImportError, RuntimeError, OSError) as exc:
        # Do not disguise scorer bugs, violated trusted invariants, or runtime
        # faults as a scientific failure. Candidate schemas checked by this
        # module raise CandidateError explicitly; output delivery is checked
        # before numeric evaluation.
        return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':f'{type(exc).__name__}: {exc}','checked_values':{},'source_hashes':{}} for k in criteria}}
    except (ValueError, UnicodeError, csv.Error) as exc:
        if candidate_phase:
            return {'status':'FAIL','criteria':{k:_fail(f'candidate scientific artifact is malformed: {type(exc).__name__}') for k in criteria}}
        return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':f'{type(exc).__name__}: {exc}','checked_values':{},'source_hashes':{}} for k in criteria}}
    except Exception as exc:
        return {'status':'INFRA','criteria':{k:{'status':'INFRA','summary':f'unexpected scorer exception: {type(exc).__name__}: {exc}','checked_values':{},'source_hashes':{}} for k in criteria}}
