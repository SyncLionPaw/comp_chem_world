# L1 Deliverables: Check required deliverables for completeness and parseability (including results.json, quadratures.json).
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Compare angularly weighted scattering rates and resolve forward-scattering integration.
"""Portable checks. Inputs/reference corruption is an infrastructure error (rc 2).

Analysis cases pair independent numeric expectations with typed scientific
interpretation and a private Linux replay including a secret input perturbation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import subprocess
import tomllib

try:
    import numpy as np
except ImportError:
    np = None


class ScientificFailure(Exception):
    pass

MAX_JSON_BYTES = 64 * 1024 * 1024


def strict_json(path):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError('duplicate JSON key: '+name)
            result[name] = value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON number: '+value)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('JSON exceeds 64 MiB resource ceiling')
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('nonfinite JSON number: '+value)
        return parsed
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def submission_file(final, name):
    path = final/name
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(final.resolve()),
            name+' must be a regular submission file')
    return path


def require(ok, message):
    if not ok:
        raise ScientificFailure(message)

def finite(x):
    return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)


NUMERIC_TOLERANCES = None

def configure_numeric_contract(refs, cid, params=None):
    global NUMERIC_TOLERANCES
    contract=refs.get('reference_contract')
    tolerances=refs.get('numeric_tolerances')
    expected_kind='analytic-elastic-rates-v1' if cid=='case-01-elastic-collision' else 'public-array-recomputation-v1'
    expected_derivation=('equal-speed-elastic-specialization-of-SI-equations-4-6-8'
                         if cid=='case-01-elastic-collision' else
                         'decode-sha256-verified-author-arrays-and-recompute-case-specific-observables')
    expected_values=('closed-form-from-screening-parameter-grid' if cid=='case-01-elastic-collision'
                     else 'derived-from-public-inputs-not-copied-gold-arrays')
    if (not isinstance(contract,dict) or contract.get('kind')!=expected_kind or
            contract.get('derivation')!=expected_derivation or contract.get('values')!=expected_values):
        raise ValueError('reference derivation contract missing or unsupported')
    if not isinstance(tolerances,dict): raise ValueError('numeric tolerance contract missing')
    required=({'analytic_rate_rtol','analytic_rate_atol','quadrature_weight_sum_atol','quadrature_first_moment_atol','quadrature_second_moment_atol','quadrature_refinement_relative','submitted_quadrature_rtol','submitted_quadrature_atol','rate_ratio_rtol','rate_ratio_atol'} if cid=='case-01-elastic-collision' else {'reported_value_rtol','reported_value_atol','input_grid_rtol'})
    if set(tolerances)!=required or any(not finite(v) or v<0 for v in tolerances.values()):
        raise ValueError('numeric tolerance contract is malformed')
    if cid=='case-01-elastic-collision' and (params is None or params.get('target_relative_accuracy')!=tolerances['analytic_rate_rtol']):
        raise ValueError('analytic tolerance differs from the declared public input')
    NUMERIC_TOLERANCES=tolerances
    return tolerances

def close(actual, expected, label, rtol=None, atol=None):
    if NUMERIC_TOLERANCES is None: raise ValueError("numeric reference contract was not loaded")
    rtol=NUMERIC_TOLERANCES["reported_value_rtol"] if rtol is None else rtol
    atol=NUMERIC_TOLERANCES["reported_value_atol"] if atol is None else atol
    require(finite(actual) and np.isclose(actual,expected,rtol=rtol,atol=atol),
            f'{label}: expected {expected!r}, got {actual!r}')

def decode(x):
    if isinstance(x,dict):
        if x.get('@class')=='array':
            return decode(x['data'])
        return {k:decode(v) for k,v in x.items()}
    if isinstance(x,list):
        return [decode(v) for v in x]
    return x

def concentration(x):
    require(finite(x),'invalid concentration')
    return float(x)

def key(row, with_temperature=True):
    require(isinstance(row,dict),'row is not an object')
    require(isinstance(row.get('material'),str),'material missing')
    require(row.get('axis') in ['xx','yy','zz'],'invalid axis')
    k=(row['material'],concentration(row['doping_cm3']),row['axis'])
    if with_temperature:
        require(finite(row['temperature_K']),'temperature missing')
        k+= (row['temperature_K'],)
    return k

def index(rows, with_temperature=True):
    require(isinstance(rows,list),'rows must be a list')
    result={}
    for row in rows:
        k=key(row,with_temperature)
        require(k not in result,f'duplicate condition {k}')
        result[k]=row
    return result

def tensor(d, field, i, j, axis):
    x=d[field] if field!='mobility' else d['mobility']['overall']
    return float(np.asarray(x,dtype=float)[i,j,axis,axis])

def condition(mat,n,t,axis):
    return {'material':mat,'doping_cm3':float(n),'temperature_K':float(t),'axis':['xx','yy','zz'][axis]}

def expected_analysis(cid, task, base):
    datasets={}
    for item in task['requirements']['inputs']:
        parts=Path(item['source_path']).parts
        mat=parts[-2];model=parts[-1].split('_')[0]
        d=decode(strict_json(base/item['path']))
        datasets[mat,model]=d
        n=np.asarray(d['doping'],dtype=float);t=np.asarray(d['temperatures'],dtype=float)
        if not np.isfinite(n).all() or not np.isfinite(t).all():raise ValueError('reference grid invalid')
        shape=(len(n),len(t),3,3)
        for field in ['conductivity','seebeck']:
            arr=np.asarray(d[field],dtype=float)
            if arr.shape!=shape or not np.isfinite(arr).all():raise ValueError(f'reference tensor malformed: {field}')
        for arr in d['mobility'].values():
            arr=np.asarray(arr,dtype=float)
            if arr.shape!=shape or not np.isfinite(arr).all():raise ValueError('reference mobility malformed')
    rows=[];metrics=[]
    mats=sorted({k[0] for k in datasets})
    for mat in mats:
        d=datasets[mat,'AMSET'];ns=d['doping'];ts=d['temperatures']
        for i,n in enumerate(ns):
            for j,t in enumerate(ts):
                for ax in range(3):
                    row=condition(mat,n,t,ax)
                    overall=tensor(d,'mobility',i,j,ax)
                    if cid.startswith('case-02'):
                        mechanism={k:float(np.asarray(v)[i,j,ax,ax]) for k,v in d['mobility'].items() if k!='overall'}
                        if overall<=0 or any(v<=0 for v in mechanism.values()):raise ValueError('reference mobility nonpositive')
                        harmonic=1/sum(1/v for v in mechanism.values())
                        row.update(overall=overall,mechanisms=mechanism,
                            limiting_proxy=min(mechanism,key=mechanism.get),harmonic_proxy=harmonic,
                            relative_deviation=(harmonic-overall)/overall)
                    else:
                        crt=datasets[mat,'CRT']
                        # Historical Monty and list formats have tiny float differences.
                        if not np.allclose(crt['doping'],ns,rtol=NUMERIC_TOLERANCES['input_grid_rtol']) or not np.array_equal(crt['temperatures'],ts):
                            raise ValueError('reference model grids differ')
                        if cid.startswith('case-03'):
                            srt=datasets[mat,'SRT']
                            if not np.allclose(srt['doping'],ns,rtol=NUMERIC_TOLERANCES['input_grid_rtol']) or not np.array_equal(srt['temperatures'],ts):
                                raise ValueError('SRT reference grids differ')
                            row.update(mu_amset=overall,mu_crt=tensor(crt,'mobility',i,j,ax),mu_srt=tensor(srt,'mobility',i,j,ax))
                        else:
                            s=tensor(d,'seebeck',i,j,ax);sc=tensor(crt,'seebeck',i,j,ax)
                            sigma=tensor(d,'conductivity',i,j,ax)
                            if sigma<=0:raise ValueError('reference conductivity nonpositive')
                            from_mu=abs(n)*1e6*1.602176634e-19*overall*1e-4
                            row.update(S_amset=s,S_crt=sc,delta_S=s-sc,sigma_S_m=sigma,
                                       mu_cm2_Vs=overall,sigma_from_mu_S_m=from_mu,
                                       relative_residual=(from_mu-sigma)/sigma)
                    rows.append(row)
            if cid.startswith('case-03'):
                for ax in range(3):
                    curves={model:np.asarray(dd['mobility']['overall'],dtype=float)[i,:,ax,ax]
                            for (mm,model),dd in datasets.items() if mm==mat}
                    if any(np.any(x<=0) for x in curves.values()):raise ValueError('reference curve nonpositive')
                    lo=int(np.argmin(ts));hi=int(np.argmax(ts))
                    m={'material':mat,'doping_cm3':float(n),'axis':['xx','yy','zz'][ax]}
                    for model in ['CRT','SRT']:
                        m['log_rmse_'+model.lower()]=float(np.sqrt(np.mean(np.log10(curves[model]/curves['AMSET'])**2)))
                    for model,arr in curves.items():
                        m['slope_'+model.lower()]=float(np.log(arr[hi]/arr[lo])/np.log(ts[hi]/ts[lo]))
                    metrics.append(m)
    return {'rows':rows,**({'metrics':metrics} if metrics else {})}

def elastic(result, quadratures, params):
    expected=params['screening_parameters'];tol=NUMERIC_TOLERANCES
    require(isinstance(result,dict) and isinstance(result.get('rows'),list),'results schema invalid')
    require(isinstance(quadratures,dict) and isinstance(quadratures.get('rows'),list),'quadratures schema invalid')
    def a_index(rows):
        out={}
        for r in rows:
            require(isinstance(r,dict) and finite(r.get('a')),'invalid a')
            require(r['a'] not in out,'duplicate a')
            out[r['a']]=r
        require(set(out)==set(expected),'a grid differs from frozen input')
        return out
    results=a_index(result['rows']);quad=a_index(quadratures['rows']);ratios=[]
    for a in expected:
        levels=quad[a].get('levels')
        require(isinstance(levels,list) and len(levels)>=2,'need at least two quadrature levels')
        counts=[];rates=[]
        for level in levels:
            require(isinstance(level,dict),'invalid quadrature level')
            require(isinstance(level.get('nodes'),list) and isinstance(level.get('weights'),list),'nodes/weights invalid')
            require(all(finite(x) for x in level['nodes']+level['weights']),'nonfinite quadrature')
            x=np.asarray(level['nodes'],dtype=float);w=np.asarray(level['weights'],dtype=float)
            require(x.ndim==w.ndim==1 and len(x)==len(w) and len(x)>=8,'quadrature shapes invalid')
            require(len(x)<=200000,'quadrature exceeds contract resource ceiling')
            require(np.all(x>=-1) and np.all(x<=1) and np.all(w>0),'invalid domain or weights')
            require(len(set(x))==len(x),'duplicate nodes')
            close(float(w.sum()),2,'weight normalization',rtol=0,atol=tol['quadrature_weight_sum_atol'])
            close(float(np.dot(w,x)),0,'first moment',rtol=0,atol=tol['quadrature_first_moment_atol'])
            close(float(np.dot(w,x*x)),2/3,'second moment',rtol=0,atol=tol['quadrature_second_moment_atol'])
            kernel=1/(1-x+a)**2
            rates.append(np.array([0.5*np.dot(w,kernel),0.5*np.dot(w,(1-x)*kernel)]))
            counts.append(len(x))
        require(len(set(counts))==len(counts) and counts[-1]>counts[-2],'refinement levels must have distinct, increasing final size')
        require(np.max(np.abs((rates[-1]-rates[-2])/rates[-1]))<=tol['quadrature_refinement_relative'],'last two quadratures not converged')
        analytic=[1/(a*(a+2)),0.5*(math.log1p(2/a)+a/(a+2)-1)]
        r=results[a]
        for k,val,computed in zip(['serta_rate','mrta_rate'],analytic,rates[-1]):
            close(r.get(k),val,k,rtol=tol['analytic_rate_rtol'],atol=tol['analytic_rate_atol'])
            close(r.get(k),float(computed),k+' from submitted quadrature',rtol=tol['submitted_quadrature_rtol'],atol=tol['submitted_quadrature_atol'])
        ratio=r['mrta_rate']/r['serta_rate']
        close(r.get('rate_ratio'),ratio,'rate ratio',rtol=tol['rate_ratio_rtol'],atol=tol['rate_ratio_atol'])
        ratios.append(ratio)
    require(all(0<x<1 for x in ratios) and all(x<y for x,y in zip(ratios,ratios[1:])), 'incorrect forward-scattering trend')
    require(result.get('strongest_forward_a')==min(expected) and result.get('elastic_only') is True,'physical scope or strongest-forward diagnosis invalid')

def analysis(actual, expected, cid, final):
    require(isinstance(actual,dict),'results must be an object')
    candidate=index(actual.get('rows'));gold=index(expected['rows'])
    require(candidate.keys()==gold.keys(),'condition coverage differs (missing, extra or duplicate n/T/axis)')
    for k,g in gold.items():
        r=candidate[k]
        for field,val in g.items():
            if field in ['material','doping_cm3','temperature_K','axis']:continue
            if isinstance(val,dict):
                require(isinstance(r.get(field),dict) and r[field].keys()==val.keys(),'mechanism set differs')
                for name,v in val.items():close(r[field][name],v,f'{k}/{field}/{name}')
            elif isinstance(val,str):require(r.get(field)==val,f'{k}/{field} incorrect')
            else:close(r.get(field),val,f'{k}/{field}')
    if cid.startswith('case-03'):
        a=index(actual.get('metrics'),False);e=index(expected['metrics'],False)
        require(a.keys()==e.keys(),'metric coverage differs')
        for k,g in e.items():
            for name,v in g.items():
                if name not in ['material','doping_cm3','axis']:close(a[k].get(name),v,f'{k}/{name}')
    for name in ['analysis.py','run.log','report.md']:
        p=submission_file(final,name)
        require(p.stat().st_size>0,f'{name} missing or empty')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('submission',type=Path)
    ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1])
    args=ap.parse_args();base=args.package.resolve();final=args.submission.absolute()
    # Reference parsing and independent expectation happen before grading.
    try:
        refs=strict_json(base/'tests/refs.json')
        task=refs.get('task_metadata')
        if not isinstance(task,dict): raise ValueError('private task metadata is missing or malformed')
        cid=task['case_id']
        if cid not in {'case-01-elastic-collision','case-02-mechanism-diagnosis','case-03-relaxation-model','case-04-seebeck-validity'} or refs.get('case_id')!=cid:
            raise ValueError('reference case identity differs')
        provenance=refs.get('evidence_provenance')
        if (not isinstance(provenance,dict) or set(provenance)!={'paper','supplementary'} or
                any(not isinstance(row,dict) or set(row)!={'source_path','sha256'} or
                    not isinstance(row.get('source_path'),str) or not isinstance(row.get('sha256'),str) or
                    len(row['sha256'])!=64 for row in provenance.values())):
            raise ValueError('reference evidence provenance is missing or malformed')
        if refs.get('public_input_hashes') != {item['path']:item['sha256'] for item in task['requirements']['inputs']}:
            raise ValueError('reference input declarations differ')
        integrity=refs.get('scoring_integrity')
        if not isinstance(integrity,dict) or set(integrity)!={'tests/verify.py','tests/test.sh'}:
            raise ValueError('scoring integrity declarations are missing')
        for rel,expected_sha in integrity.items():
            source=base/rel
            if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected_sha:
                raise ValueError('scoring source is missing or corrupt: '+rel)
        if np is None:
            raise ValueError('NumPy unavailable')
        for item in task['requirements']['inputs']:
            p=base/item['path']
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('public input missing or corrupt: '+item['path'])
            if refs['public_input_hashes'].get(item['path'])!=item['sha256']:
                raise ValueError('reference input hash declaration differs')
        expected_documents={'environment/assets/literature/paper.pdf','environment/assets/literature/supplementary.pdf'}
        if set(refs['evidence_documents'])!=expected_documents:
            raise ValueError('public literature document declarations are invalid')
        for rel,document in refs['evidence_documents'].items():
            path=base/rel
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=document['sha256']:
                raise ValueError('public literature evidence missing or corrupt: '+rel)
        if cid.startswith('case-01'):
            params=strict_json(base/task['requirements']['inputs'][0]['path']);configure_numeric_contract(refs,cid,params);expected=None
        else:
            configure_numeric_contract(refs,cid)
            expected=expected_analysis(cid,task,base)
    except Exception as exc:
        print(json.dumps({'status':'ENVIRONMENT_ERROR','reason':str(exc)},ensure_ascii=False))
        return 2
    try:
        require(final.is_dir() and not final.is_symlink(), 'final must be a regular submission directory')
        result=strict_json(submission_file(final,'results.json'))
        if cid.startswith('case-01'):
            quadratures=strict_json(submission_file(final,'quadratures.json'))
            elastic(result,quadratures,params)
            verdict={'status':'PASS','layers':['L1','L2','L3'],'reward':1,'runtime_bound':False}
        else:
            analysis(result,expected,cid,final)
            def parse_report(text):
                def pairs(items):
                    d={}
                    for k,v in items:
                        if k in d:raise ValueError('duplicate report key')
                        d[k]=v
                    return d
                return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite report')))
            try:
                review(cid,expected,submission_file(final,'report.md'),parse_report)
                log=strict_json(submission_file(final,'run.log'))
                sources={item['source_path']:item['sha256'] for item in task['requirements']['inputs']}
                require(len(log['inputs'])==len(sources) and {r['path']:r['sha256'] for r in log['inputs']}==sources,'submitted provenance input hashes differ')
                script=submission_file(final,'analysis.py')
                require(script.stat().st_size<=2*1024*1024,'analysis.py exceeds 2 MiB ceiling')
                require(log.get('script_sha256')==hashlib.sha256(script.read_bytes()).hexdigest(),'submitted script hash differs')
                require(log.get('case_id')==cid and log.get('row_count')==len(expected['rows']),'submitted provenance case/row count differs')
                require(isinstance(log.get('command'),list) and '--inputs' in log['command'] and '--output' in log['command'],'submitted command not declared CLI')
                require(isinstance(log.get('python_version'),str) and log['python_version'].startswith('3.'),'submitted Python version missing')
                checks=replay(script,base,task,expected_analysis,analysis,strict_json)
                verdict={'status':'PASS','reward':1,'layers':['L1','L2','L3'],'numeric_checks':'PASS',
                         'scientific_interpretation':'PASS','execution_replay':checks,'overall_scientific_pass':True,'runtime_bound':False}
            except ReplayUnavailable as exc:
                print(json.dumps({'status':'ENVIRONMENT_ERROR','reason':str(exc)},ensure_ascii=False));return 2
            except (OSError, shutil.Error, subprocess.SubprocessError) as exc:
                print(json.dumps({'status':'ENVIRONMENT_ERROR','reason':'evaluator replay infrastructure failed: '+str(exc)},ensure_ascii=False));return 2
            except (ScientificFailure,ReplayFailure,ValueError,KeyError,TypeError) as exc:
                verdict={'status':'FAIL','reward':0,'numeric_checks':'PASS','overall_scientific_pass':False,
                         'reason':str(exc),'remaining':['valid execution and scientific interpretation'],
                         'runtime_bound':False}
        print(json.dumps(verdict,ensure_ascii=False))
        return 0 if verdict.get('status')=='PASS' else 1
    except (ScientificFailure,OSError,ValueError,KeyError,TypeError,ZeroDivisionError,OverflowError,RecursionError) as exc:
        print(json.dumps({'status':'FAIL','reward':0,'reason':str(exc)},ensure_ascii=False))
        return 1




# Inlined scientific interpretation contract and isolated replay implementation.
"""Evidence-backed, typed scientific interpretation; no prose keyword grading.

report.md is a single JSON scientific report inside a Markdown fence. Unknown
fields or ungraded prose cannot acquire full credit. The frozen scientific
questions are unchanged; this representation makes their answers decidable.
"""
import json
import math
import re

def expected_report(cid, expected):
    rows=expected['rows']
    common={'schema':'carrier-scientific-report/v1','case_id':cid,
            'scope':{'calculation':'analysis_of_author_arrays','new_dft_or_scattering':False,
                     'reproduces_full_paper_statistics':False},'physics':{},'evidence':[]}
    if cid.startswith('case-02'):
        common['physics']={'limiting_proxy':'minimum_single_mechanism_mobility',
            'proxy_is_microscopic_rate_fraction':False,'matthiessen_domain':'same_state_inverse_lifetime',
            'mobility_harmonic_sum_exact':False,'averaging':'velocity_energy_and_state_weighted',
            'axes':'native_xx_yy_zz_not_assumed_crystal_abc'}
        for mat in sorted({r['material'] for r in rows}):
            subset=[r for r in rows if r['material']==mat]
            n=min({r['doping_cm3'] for r in subset},key=abs);t=min(r['temperature_K'] for r in subset)
            sample=sorted([r for r in subset if r['doping_cm3']==n and r['temperature_K']==t],key=lambda r:r['axis'])
            endpoints=[]
            for doping in sorted({r['doping_cm3'] for r in subset},key=abs):
                curve=sorted([r for r in subset if r['doping_cm3']==doping and r['axis']=='xx'],key=lambda r:r['temperature_K'])
                for r in [curve[0]] if len(curve)==1 else [curve[0],curve[-1]]:
                    endpoints.append({k:r[k] for k in ['doping_cm3','temperature_K','limiting_proxy']})
            common['evidence'].append({'material':mat,'proxy_endpoints_xx':endpoints,
                'deviation_range':[min(r['relative_deviation'] for r in subset),max(r['relative_deviation'] for r in subset)],
                'directional_sample':{'doping_cm3':n,'temperature_K':t,
                    'overall_xx_yy_zz':[r['overall'] for r in sample]}})
    elif cid.startswith('case-03'):
        common['physics']={'error_reference':'author_AMSET_not_experiment','CRT_lifetime_fs':10,
            'SRT_temperature_scale':{'reference_K':300,'power':-1,'equals_CRT_at_reference':True},
            'SRT_guarantees_accuracy_improvement':False,'invent_missing_300K_point':False,
            'full_paper_MSE_or_Spearman_inferred':False}
        for m in sorted(expected['metrics'],key=lambda m:(m['material'],abs(m['doping_cm3']),m['axis'])):
            common['evidence'].append({**m,'SRT_log_RMSE_assessment':'improves' if m['log_rmse_srt']<m['log_rmse_crt'] else 'does_not_improve'})
        common['scaling_max_relative_deviation']=max(abs(r['mu_srt']/(r['mu_crt']*300/r['temperature_K'])-1) for r in rows)
        common['available_temperatures_K']={mat:sorted({r['temperature_K'] for r in rows if r['material']==mat}) for mat in sorted({r['material'] for r in rows})}
    else:
        common['physics']={'negative_doping':'electrons','positive_doping':'holes',
            'constant_lifetime_scale_cancels_in_Seebeck':True,'energy_dependent_lifetime_cancels':False,
            'reason':'energy_dependence_changes_Onsager_moment_weights',
            'diffusive_only_materials':['CdS','Si'],'phonon_drag_included':False,
            'unit_factors':{'n_cm3_to_m3':1e6,'mu_cm2_to_m2':1e-4,'e_C':1.602176634e-19},
            'nominal_net_doping_residual_forced_zero':False}
        for mat in sorted({r['material'] for r in rows}):
            subset=[r for r in rows if r['material']==mat]
            n=min({r['doping_cm3'] for r in subset},key=abs);t=min(r['temperature_K'] for r in subset)
            sample=sorted([r for r in subset if r['doping_cm3']==n and r['temperature_K']==t],key=lambda r:r['axis'])
            common['evidence'].append({'material':mat,'carrier':'electrons' if n<0 else 'holes',
                'S_range_microvolt_K':[min(r['S_amset'] for r in subset),max(r['S_amset'] for r in subset)],
                'delta_S_range_microvolt_K':[min(r['delta_S'] for r in subset),max(r['delta_S'] for r in subset)],
                'max_abs_conductivity_residual':max(abs(r['relative_residual']) for r in subset),
                'directional_sample':{'doping_cm3':n,'temperature_K':t,'S_xx_yy_zz':[r['S_amset'] for r in sample]}})
    return common

def compare(actual, expected, where='scientific_report'):
    if isinstance(expected,dict):
        if not isinstance(actual,dict) or set(actual)!=set(expected):raise ValueError(where+': field set differs')
        for k,v in expected.items():compare(actual[k],v,where+'.'+k)
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected):raise ValueError(where+': list coverage differs')
        # Evidence and other arrays use the contract's declared deterministic order.
        for i,(a,b) in enumerate(zip(actual,expected)):compare(a,b,where+f'[{i}]')
    elif isinstance(expected,(int,float)) and not isinstance(expected,bool):
        if type(actual) not in (int,float) or not math.isfinite(actual) or not math.isclose(actual,expected,rel_tol=1e-6,abs_tol=1e-8):
            raise ValueError(where+': numeric evidence differs')
    elif type(actual)!=type(expected) or actual!=expected:
        raise ValueError(where+': scientific proposition differs')

def review(cid, expected, report, strict_parse):
    if report.stat().st_size>4*1024*1024:raise ValueError('scientific report exceeds 4 MiB ceiling')
    text=report.read_text()
    match=re.fullmatch(r'\s*# 科学分析\s*\n```json\s*\n([\s\S]*?)\n```\s*',text)
    if not match:raise ValueError('report.md must contain only the declared scientific JSON report; ungraded prose needs review')
    parsed=strict_parse(match.group(1))
    compare(parsed,expected_report(cid,expected))

REPORT_CONTRACT='''
完整科学评分新增可判定报告表示；科学目标、公开输入及既有数值契约保持不变。
report.md 必须为 `# 科学分析` 标题和唯一一个 ```json 代码块；不含未核验的附加文字。
JSON 使用 schema=carrier-scientific-report/v1、case_id、scope、physics、evidence。
scope 字段：calculation（本题计算类型）、new_dft_or_scattering（布尔）、reproduces_full_paper_statistics（布尔）。
数组按材料字典序排序；材料内浓度按绝对值升序，方向 xx/yy/zz，温度升序。
具体结构与字段名称由本题附加的科学报告契约逐项列出；数值证据容差 rtol=1e-6、atol=1e-8。
report.md 最多4 MiB，analysis.py 最多2 MiB；隔离回放单进程、20秒CPU、35秒墙钟、2 GiB内存。
科学报告或隔离回放未通过时为 FAIL/0；科学报告、输入扰动核验和隔离回放全部通过才为 PASS/1。
analysis.py 使用既有 CLI，并实际读取公开数组；run.log 为 JSON，含 case_id、command、python_version、
inputs=[{path:原始suite-relative路径,sha256:实际输入哈希}]、script_sha256、row_count。
评价方隔离回放只提供候选脚本、公开输入与空输出目录；隐藏参考不可访问。
'''

def contract(cid, expected):
    model=expected_report(cid,expected)
    def shape(value):
        if isinstance(value,dict):return {k:shape(v) for k,v in value.items()}
        if isinstance(value,list):return [shape(value[0])] if value else []
        if isinstance(value,bool):return 'boolean'
        if isinstance(value,(int,float)):return 'number'
        return 'string'
    fields=shape(model);fields['schema']='carrier-scientific-report/v1';fields['case_id']=cid
    choices={'calculation':['analysis_of_author_arrays','new_first_principles_scattering'],
             'carrier / negative_doping / positive_doping':['electrons','holes'],
             'limiting_proxy':['minimum_single_mechanism_mobility','maximum_single_mechanism_mobility','microscopic_rate_fraction'],
             'matthiessen_domain':['same_state_inverse_lifetime','macroscopic_inverse_mobility','unrestricted'],
             'averaging':['velocity_energy_and_state_weighted','unweighted_arithmetic_mean'],
             'axes':['native_xx_yy_zz_not_assumed_crystal_abc','crystal_abc_in_array_order'],
             'error_reference':['author_AMSET_not_experiment','experimental_measurements'],
             'reason':['energy_dependence_changes_Onsager_moment_weights','all_lifetime_functions_are_common_factors'],
             'SRT_log_RMSE_assessment':['improves','does_not_improve']}
    return REPORT_CONTRACT+'\n字段结构（类型占位符不是答案；示意数组单项应按以下覆盖规则扩展）：\n\n```json\n'+json.dumps(fields,ensure_ascii=False,indent=2)+'\n```\n\n'+\
        '字符串选项（自行判断；适用字段必须取其允许选项）：\n\n```json\n'+json.dumps(choices,ensure_ascii=False,indent=2)+'\n```\n\n'+\
        '02：每材料 deviation_range 为所有条件相对偏差的 min/max；proxy_endpoints_xx 覆盖每个浓度最低/最高温度，单温度只列一次；directional_sample 取最低绝对浓度及最低温度。\n'+\
        '03：evidence 覆盖 results 的全部 metrics 并判断 SRT 的 log RMSE 是否严格更小；available_temperatures_K 保留各材料实际全部温度；scaling_max_relative_deviation=max(abs(mu_srt/(mu_crt*300/T)-1))。理论缩放与作者数组的小偏差需区分。\n'+\
        '04：每材料 S/delta_S 的范围及电导残差绝对值最大值覆盖全部数据；directional_sample 取最低绝对浓度及最低温度。diffusive_only_materials 按字典序列出本题仅比较扩散项的材料；不强迫名义掺杂与实际载流子归一化残差为零。\n'+\
        '所有必需科学字段必须回答，不能用没有依据的文字替换数值证据。科学等效分析算法均可使用这一结果表示；其他自由文字报告仍可留待人工审查，但自动完整通过要求本可判定契约。\n'


"""Linux chroot + uid drop + seccomp replay; never execute candidates on host.

The fresh grader must be Linux root with CAP_SYS_CHROOT. Each child receives a
private library-only root, read-only declared arrays, and a blank writable output.
No model credentials, tests, answers, parent processes or network are available.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import sysconfig
import tempfile

class ReplayUnavailable(RuntimeError):pass
class ReplayFailure(ValueError):pass

BOOTSTRAP=r'''
import ctypes, errno, os, platform, runpy, sys
class Filter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
class Program(ctypes.Structure):
    _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
arch=platform.machine()
if arch=='aarch64':
    audit=0xc00000b7
    denied=[198,199,200,201,202,203,206,207,210,211,212,220,221,281,435,117,270,271,40,39,268,97,129,130,131,265,280,425,426,427]
elif arch=='x86_64':
    audit=0xc000003e
    denied=[41,42,43,44,45,46,47,48,49,50,53,56,57,58,59,322,435,101,310,311,165,166,308,272,62,200,234,304,321,425,426,427]
else:
    sys.exit(125)
filters=[Filter(0x20,0,0,4),Filter(0x15,1,0,audit),Filter(0x06,0,0,0x80000000),Filter(0x20,0,0,0),
         Filter(0x35,0,1,0x40000000),Filter(0x06,0,0,0x00050000|errno.EPERM)]
for nr in denied:filters.extend([Filter(0x15,0,1,nr),Filter(0x06,0,0,0x00050000|errno.EPERM)])
filters.append(Filter(0x06,0,0,0x7fff0000))
array=(Filter*len(filters))(*filters);program=Program(len(filters),array)
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(22,2,ctypes.byref(program),0,0)!=0:
    sys.exit(125)
sys.argv=['/analysis.py','--inputs','/inputs','--output','/output']
runpy.run_path('/analysis.py',run_name='__main__')
'''

def copy_runtime(root):
    def copy(path):
        p=Path(path)
        if not p.is_file():return
        dest=root/str(p).lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():shutil.copyfile(p.resolve(),dest)
        if os.access(p,os.X_OK):dest.chmod(0o755)
    copy(sys.executable)
    # venv interpreter base and its libpython, stdlib and NumPy extensions only.
    std=Path(sysconfig.get_path('stdlib'))
    shutil.copytree(std,root/str(std).lstrip('/'),ignore=shutil.ignore_patterns('site-packages','dist-packages','__pycache__'),dirs_exist_ok=True)
    cfg=Path(sys.prefix)/'pyvenv.cfg'
    if cfg.is_file():copy(cfg)
    import numpy
    numpy_root=Path(numpy.__file__).parent
    for p in [numpy_root,numpy_root.parent/'numpy.libs']:
        if p.is_dir():shutil.copytree(p,root/str(p).lstrip('/'),ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    binaries=[Path(sys.executable),*list(std.glob('lib-dynload/*.so')),*list(numpy_root.rglob('*.so'))]
    for p in binaries:
        output=subprocess.run(['ldd',str(p)],capture_output=True,text=True,timeout=5).stdout
        for lib in re.findall(r'(/[^\s()]+)',output):copy(lib)
    # Never import candidate modules while building the evaluator runtime.
    for directory in root.rglob('*'):
        if directory.is_dir():directory.chmod(0o755)

def _limits_and_root(root):
    os.chroot(root);os.chdir('/')
    os.setgroups([]);os.setgid(65534);os.setuid(65534)
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU,(20,20))
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))

def _replay_unwrapped(script, inputs, task, expected_fn, validate_fn, strict_fn):
    if sys.platform!='linux' or os.geteuid()!=0 or platform.machine() not in ['aarch64','x86_64']:
        raise ReplayUnavailable('secure replay requires a Linux evaluator with chroot capability; host fallback is forbidden')
    receipts=[]
    with tempfile.TemporaryDirectory(prefix='carrier-replay-') as directory:
        work=Path(directory);root=work/'root';root.mkdir(mode=0o755);work.chmod(0o755)
        copy_runtime(root)
        try:
            script_bytes=script.read_bytes()
        except OSError as exc:
            raise ReplayFailure('candidate analysis.py is unreadable: '+str(exc)) from exc
        (root/'analysis.py').write_bytes(script_bytes);(root/'analysis.py').chmod(0o444)
        (root/'bootstrap.py').write_text(BOOTSTRAP);(root/'bootstrap.py').chmod(0o444)
        input_dir=root/'inputs';input_dir.mkdir(mode=0o755)
        originals={}
        for item in task['requirements']['inputs']:
            rel=item['source_path'];p=input_dir/rel;p.parent.mkdir(parents=True,exist_ok=True)
            originals[rel]=(inputs/item['path']).read_bytes();p.write_bytes(originals[rel]);p.chmod(0o444)
        for challenge in ['original','perturbed']:
            for rel,blob in originals.items():
                p=input_dir/rel;p.chmod(0o644)
                if challenge=='original':p.write_bytes(blob)
                else:
                    # Secret random amplitude forces data consumption, not cached output.
                    amplitude=1.01+int.from_bytes(os.urandom(2),'big')/65535*0.02
                    d=json.loads(blob)
                    def scale(v,factor):
                        if isinstance(v,dict) and v.get('@class')=='array':v['data']=scale(v['data'],factor);return v
                        if isinstance(v,list):return [scale(x,factor) for x in v]
                        return v*factor
                    for k in d['mobility']:d['mobility'][k]=scale(d['mobility'][k],amplitude)
                    d['conductivity']=scale(d['conductivity'],amplitude)
                    d['seebeck']=scale(d['seebeck'],amplitude)
                    p.write_text(json.dumps(d,allow_nan=False))
                p.chmod(0o444)
            output=root/'output';shutil.rmtree(output,ignore_errors=True);output.mkdir(mode=0o700);os.chown(output,65534,65534)
            with (work/'stdout').open('wb') as out,(work/'stderr').open('wb') as err:
                try:
                    proc=subprocess.run([sys.executable,'-I','-B','/bootstrap.py'],env={'PATH':'/usr/bin','HOME':'/output',
                        'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'},
                        stdin=subprocess.DEVNULL,stdout=out,stderr=err,preexec_fn=lambda:_limits_and_root(str(root)),timeout=35)
                except subprocess.TimeoutExpired:raise ReplayFailure('isolated analysis timed out')
                except subprocess.SubprocessError as e:raise ReplayUnavailable('chroot/uid isolation could not start: '+str(e))
            if proc.returncode==125:raise ReplayUnavailable('seccomp could not be enabled')
            if proc.returncode!=0:
                error=(work/'stderr').read_bytes()[-2048:].decode(errors='replace')
                raise ReplayFailure(f'isolated analysis failed ({proc.returncode}): {error}')
            # Recompute from the actual arrays delivered to the child, not its log.
            challenge_task=json.loads(json.dumps(task))
            for item in challenge_task['requirements']['inputs']:item['path']='inputs/'+item['source_path']
            expected=expected_fn(task['case_id'],challenge_task,root)
            result_path=output/'results.json'
            if result_path.is_symlink() or not result_path.is_file():raise ReplayFailure('isolated script did not produce regular results.json')
            try:
                result=strict_fn(result_path)
            except OSError as exc:
                raise ReplayFailure('isolated script results.json is unreadable: '+str(exc)) from exc
            try:
                validate_fn(result,expected,task['case_id'],output)
            except OSError as exc:
                raise ReplayFailure('isolated script output is unreadable: '+str(exc)) from exc
            log_path=output/'run.log'
            if log_path.is_symlink() or not log_path.is_file():raise ReplayFailure('isolated script did not produce regular run.log')
            try:
                log=strict_fn(log_path)
            except OSError as exc:
                raise ReplayFailure('isolated script run.log is unreadable: '+str(exc)) from exc
            expected_hashes={rel:hashlib.sha256((input_dir/rel).read_bytes()).hexdigest() for rel in originals}
            if {r['path']:r['sha256'] for r in log['inputs']}!=expected_hashes:raise ReplayFailure('replayed input provenance differs')
            if log.get('script_sha256')!=hashlib.sha256(script_bytes).hexdigest():raise ReplayFailure('replayed script provenance differs')
            receipts.append({'challenge':challenge,'status':'PASS','result_sha256':hashlib.sha256(result_path.read_bytes()).hexdigest(),
                             'input_hashes':expected_hashes,'isolation':'chroot+uid65534+seccomp; single process; no network; no hidden reference'})
    return receipts


def replay(script, inputs, task, expected_fn, validate_fn, strict_fn):
    try:
        return _replay_unwrapped(script, inputs, task, expected_fn, validate_fn, strict_fn)
    except ReplayUnavailable:
        raise
    except (OSError, shutil.Error, subprocess.SubprocessError) as exc:
        raise ReplayUnavailable('evaluator replay infrastructure failed: ' + str(exc)) from exc


def strict_result(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate verifier JSON key: '+key)
            result[key]=value
        return result
    def constant(value): raise ValueError('nonfinite verifier JSON number: '+value)
    def number(value):
        parsed=float(value)
        if not math.isfinite(parsed): raise ValueError('nonfinite verifier JSON number: '+value)
        return parsed
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant,parse_float=number)


def runner_main():
    app=Path(os.environ.get('APP','/app'))
    tests=Path(os.environ.get('TESTS',Path(__file__).resolve().parent))
    logs=Path(os.environ.get('LOGS','/logs/verifier'))
    logs.mkdir(parents=True,exist_ok=True)
    for name in ('reward.txt','verification.json','verdict.json'):
        (logs/name).unlink(missing_ok=True)
    try:
        refs=strict_json(tests/'refs.json')
        task=refs.get('task_metadata')
        scope=task.get('verification',{}).get('scoring_scope') if isinstance(task,dict) else None
        if scope not in {'full','numeric-with-review'}:
            raise ValueError('invalid scoring scope')
        integrity=refs.get('scoring_integrity')
        if not isinstance(integrity,dict) or set(integrity)!={'tests/verify.py','tests/test.sh'}:
            raise ValueError('scoring integrity declarations are missing')
        for rel,expected in integrity.items():
            path=tests/Path(rel).name
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise ValueError('scoring material missing or corrupt: '+rel)
        with tempfile.TemporaryDirectory(prefix='carrier-grader-') as directory:
            package=Path(directory)
            (package/'tests').symlink_to(tests.resolve(),target_is_directory=True)
            (package/'environment').symlink_to((app/'environment').resolve(),target_is_directory=True)
            completed=subprocess.run([sys.executable,str(tests/'verify.py'),str(app/'final'),'--package',str(package)],
                                    capture_output=True,text=True,timeout=240)
        result=strict_result(completed.stdout)
        if not isinstance(result,dict): raise ValueError('verifier result must be an object')
        status=result.get('status'); reward=result.get('reward')
        if status=='PASS' and scope!='full': raise ValueError('partial scientific verifier cannot grant full PASS')
        if status in {'PASS','FAIL'}:
            expected_reward=int(status=='PASS')
            if (type(reward) not in {int,float} or not math.isfinite(reward) or reward!=expected_reward or
                    completed.returncode!=(0 if expected_reward else 1)):
                raise ValueError('inconsistent scientific status/reward/exit code')
            rc=completed.returncode
        elif (status=='NUMERIC_PASS_REVIEW_REQUIRED' and completed.returncode==0 and 'reward' not in result
              and result.get('numeric_checks')=='PASS' and result.get('overall_scientific_pass') is False
              and scope=='numeric-with-review'):
            result={**result,'scientific_status':status,'status':'ENV_INVALID',
                    'error':'trusted scientific adjudication is required but no adjudication path is configured'}
            rc=2
        elif status=='ENVIRONMENT_ERROR' and completed.returncode==2 and 'reward' not in result:
            result={**result,'scientific_status':status,'status':'ENV_INVALID'}
            rc=2
        else:
            raise ValueError('unknown/inconsistent verifier status or exit code')
        result['runtime_bound']=True
        result['scoring_integrity_sha256']=hashlib.sha256((tests/'refs.json').read_bytes()).hexdigest()
    except Exception as exc:
        result={'status':'ENV_INVALID','error':type(exc).__name__+': '+str(exc)}
        rc=2
    (logs/'verification.json').write_text(json.dumps(result,ensure_ascii=False)+'\n')
    if rc!=2: (logs/'reward.txt').write_text(str(result['reward'])+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return rc


if __name__=='__main__':
    if sys.argv[1:]==['--runner']:
        raise SystemExit(runner_main())
    if np is None:
        print(json.dumps({'status':'ENVIRONMENT_ERROR','reason':'NumPy unavailable'}))
        raise SystemExit(2)
    raise SystemExit(main())
