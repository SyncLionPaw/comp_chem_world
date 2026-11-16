# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Rate identifiability from photoluminescence.
"""Independent scorer for frozen observations, fitted curves, and exact degeneracy."""
from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, stat, subprocess, sys, tempfile
from pathlib import Path
try:
    import numpy as np
    from scipy.linalg import expm
    SCORER_IMPORT_ERROR = None
except ImportError as _import_error:
    np = None
    expm = None
    SCORER_IMPORT_ERROR = _import_error

EXPECTED=json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["inputs"]
SCENARIOS=('baseline','intervention_A','intervention_B')
FACTORS={'baseline':(1.,1.),'intervention_A':(3.,1.),'intervention_B':(1.,3.)}
ACCEPTANCE=json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["acceptance"]
FIT_RMS_MAX=ACCEPTANCE["fit_rms_max"]
YIELD_MIN_SEPARATION=ACCEPTANCE["absolute_fluorescence_yield_minimum_separation"]
RATE_MIN_RELATIVE_SEPARATION=ACCEPTANCE["direct_rate_measurement_minimum_relative_separation"]

class EnvironmentError(RuntimeError): pass

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read_json(p):
    try: v=json.loads(p.read_text())
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as e: raise ValueError(f'invalid or missing {p.name}: {e}')
    if not isinstance(v,dict): raise ValueError(f'{p.name} must be a JSON object')
    return v

def load_rows(p):
    with p.open(newline='') as f: rows=list(csv.DictReader(f))
    required={'time_s','scenario','fluorescence_norm','phosphorescence_norm'}
    if not rows or set(rows[0])!=required: raise ValueError('observations.csv header/rows invalid')
    parsed=[]
    for r in rows:
        x=(float(r['time_s']),r['scenario'],float(r['fluorescence_norm']),float(r['phosphorescence_norm']))
        if not all(math.isfinite(z) for z in (x[0],x[2],x[3])) or x[1] not in SCENARIOS: raise ValueError('nonfinite or unknown observation')
        parsed.append(x)
    return parsed

def predict(rates, rows):
    curves={}
    for scenario in SCENARIOS:
        ph_factor,nr_factor=FACTORS[scenario]
        selected=[r for r in rows if r[1]==scenario]
        ts=np.array([r[0] for r in selected])
        a=np.array([[-(rates['f']+rates['nrS']+rates['isc']),rates['risc']],
                    [rates['isc'],-(rates['risc']+rates['ph1']*ph_factor+rates['nr1']*nr_factor)]])
        p=np.array([expm(a*t)@np.array([1.,0.]) for t in ts])
        curves[scenario]=np.column_stack((p[:,0],p[:,1]/np.max(p[:,1])))
    return curves

def generator(rates, scenario):
    ph_factor,nr_factor=FACTORS[scenario]
    return np.array([[-(rates['f']+rates['nrS']+rates['isc']),rates['risc']],
                     [rates['isc'],-(rates['risc']+rates['ph1']*ph_factor+rates['nr1']*nr_factor)]])

def diagnosis_evidence(path, result, rates_a, rates_b, rows):
    if path.is_symlink() or not path.is_file(): raise ValueError('diagnosis.md is required')
    text=path.read_text(encoding='utf-8')
    if not text.strip(): raise ValueError('diagnosis.md must explain the scientific inference')
    # Scientific data belong in result.json; a prose report needs no status codes
    # or repeated numerical claims. Retain the former representation for replay.
    if 'practical_identifiability' in result:
        practical=result['practical_identifiability']
        if not isinstance(practical,dict) or 'noise_model' not in practical:
            raise ValueError('practical_identifiability must explicitly state its noise_model (null if not quantified)')
        noise=practical['noise_model']
        if noise is not None and (not isinstance(noise,(str,dict)) or not noise):
            raise ValueError('a quantified uncertainty needs an explicit nonempty noise model')
        gen_delta=max(float(np.max(np.abs(generator(rates_a,s)-generator(rates_b,s)))) for s in SCENARIOS)
        curves_a=predict(rates_a,rows); curves_b=predict(rates_b,rows)
        curve_delta=max(float(np.max(np.abs(curves_a[s]-curves_b[s]))) for s in SCENARIOS)
        scale=max(1.0,*[abs(v) for v in rates_a.values()])
        profile=result.get('degeneracy_profile')
        ref='parameters_fit_b_equivalent'
        if result.get(ref) is None:
            ref=next((f'degeneracy_profile[{i}]' for i,item in enumerate(profile or []) if item.get('parameters')==rates_b),None)
            if ref is None: raise ValueError('the ambiguity witness must be a reported parameter set')
        return {
            'schema_version':'1.0',
            'structural_identifiability':{
                'status':('witnessed_equivalent_generator' if gen_delta<=max(1e-8,1e-12*scale) else 'witnessed_equivalent_observations'),
                'fit_a_ref':'parameters_fit_a','fit_b_ref':ref,
                'max_generator_abs_delta_s-1':gen_delta,'max_curve_abs_delta':curve_delta,
                'max_parameter_relative_delta':max(abs(rates_a[k]-rates_b[k])/max(abs(rates_a[k]),abs(rates_b[k])) for k in rates_a),
                'invariant_explanation':text.strip()},
            'practical_identifiability':{
                'status':('not_quantified_without_noise_model' if noise is None else 'profile_quantified'),
                'noise_model':noise,'fit_window_s':result.get('fit_window_s'),
                'profile_refs':practical.get('profile_refs',[])},
            'discriminating_observable_ref':'result.discriminating_observable'}
    match=re.search(r'```json\s*\n(.*?)\n```',text,re.DOTALL)
    if not match: raise ValueError('diagnosis.md must include a fenced JSON identifiability evidence block')
    try: value=json.loads(match.group(1))
    except json.JSONDecodeError as e: raise ValueError(f'invalid identifiability evidence JSON: {e}')
    if not isinstance(value,dict) or value.get('schema_version')!='1.0': raise ValueError('identifiability evidence schema_version must be 1.0')
    return value

def rms(curves, rows):
    residual=[]
    for scenario in SCENARIOS:
        obs=[r for r in rows if r[1]==scenario]
        residual.extend((curves[scenario]-np.array([[r[2],r[3]] for r in obs])).ravel())
    return float(np.sqrt(np.mean(np.square(residual))))

def _scientific_result(result, rows):
    """Read concise scientific results; keep existing submissions compatible."""
    if 'rates' not in result:
        return result
    rate_sets=result['rates']
    if not isinstance(rate_sets,list) or len(rate_sets)<2:
        raise ValueError('rates must contain a selected fit and at least one alternative')
    fit=result.get('fit')
    if not isinstance(fit,dict): raise ValueError('fit must document the fitting procedure')
    measurement=result.get('measurement')
    if not isinstance(measurement,dict): raise ValueError('measurement must give two predicted outcomes')
    predictions=measurement.get('predictions')
    if not isinstance(predictions,list) or len(predictions)!=2:
        raise ValueError('measurement predictions must refer to the first two rate sets')
    kinds={'yield':'absolute_fluorescence_yield','rate':'direct_rate_measurement','flux':'calibrated_fluorescence_flux'}
    kind=measurement.get('type')
    if kind not in kinds: raise ValueError('measurement type must be yield, rate or flux')
    diagnostic=dict(measurement,type=kinds[kind],predictions=dict(zip(('fit_a','fit_b'),predictions)))
    diagnostic['unit']=('dimensionless' if kind=='yield' else 's^-1' if kind=='rate' else 's^-1 per initially excited molecule')
    uncertainty=result.get('uncertainty')
    if not isinstance(uncertainty,dict) or 'noise_model' not in uncertainty:
        raise ValueError('uncertainty must explicitly state a noise_model (null if not quantified)')
    profiles=[{'parameters':q,'residual_rms':rms(predict(q,rows),rows)} for q in rate_sets[1:]]
    converted={
        'parameters_fit_a':rate_sets[0],'parameters_fit_b_equivalent':rate_sets[1],
        'fit_parameterization':fit.get('description') or ', '.join(map(str,fit.get('coordinates',[]))),
        'fit_parameter_names':fit.get('coordinates'),'bounds_s-1':fit.get('bounds'),
        'fit_window_s':fit.get('window_s'),'weights':fit.get('weights'),
        'starting_guesses_s-1':fit.get('starts'),'multistart_residual_rms':fit.get('rms'),
        'residual_rms':min(fit['rms']) if isinstance(fit.get('rms'),list) and fit['rms'] else math.nan,
        'discriminating_observable':diagnostic,'practical_identifiability':dict(uncertainty)}
    if profiles:
        converted['degeneracy_profile']=profiles
        indices=uncertainty.get('profile_indices',[])
        if not isinstance(indices,list) or any(type(i) is not int or i<1 or i>=len(rate_sets) for i in indices):
            raise ValueError('profile_indices must reference alternative rate sets (indices 1 onward)')
        converted['practical_identifiability']['profile_refs']=[f'degeneracy_profile[{i-1}]' for i in indices]
    # These are deterministic consequences of the submitted rates, not additional
    # scientific claims the researcher needs to copy into another field.
    curves=predict(rate_sets[0],rows)
    converted['predicted_curves_flattened']={'fit_a':np.concatenate([curves[s].ravel() for s in SCENARIOS]).tolist()}
    return converted

def validate(final, rows):
    result=_scientific_result(read_json(final/'result.json'),rows)
    if result.get('schema_version','1.0')!='1.0' or not isinstance(result.get('model','two-state singlet/triplet kinetics'),str): raise ValueError('result schema/model missing')
    if result.get('parameter_units','s^-1')!='s^-1': raise ValueError('parameter_units must be s^-1')
    keys=('f','nrS','isc','risc','ph1','nr1')
    rates_a=result.get('parameters_fit_a')
    if not isinstance(rates_a,dict) or set(rates_a)!=set(keys): raise ValueError('parameters_fit_a must report all six rates')
    def validate_rates(rates,label):
        if not isinstance(rates,dict) or set(rates)!=set(keys): raise ValueError(f'{label} must report all six rates')
        vals=[float(rates[k]) for k in keys]
        if any(not math.isfinite(x) or x<=0 for x in vals): raise ValueError(f'{label} rates must be positive finite s^-1')
        return {k:float(rates[k]) for k in keys}
    rates_a=validate_rates(rates_a,'parameters_fit_a')
    bounds=result.get('bounds_s-1')
    if not isinstance(bounds,dict) or not bounds: raise ValueError('bounds_s-1 must declare positive finite bounds')
    bound_pairs={}
    for name,pair in bounds.items():
        if not isinstance(name,str) or not isinstance(pair,list) or len(pair)!=2:
            raise ValueError('each bound must be a named [lower, upper] pair')
        lo,hi=map(float,pair)
        if not math.isfinite(lo) or not math.isfinite(hi) or lo<=0 or hi<=lo: raise ValueError(f'invalid positive bounds for {name}')
        bound_pairs[name]=(lo,hi)
    parameterization=result.get('fit_parameterization')
    if not isinstance(parameterization,str) or not parameterization.strip(): raise ValueError('fit_parameterization must describe the fitted parameter set')
    fit_names=result.get('fit_parameter_names')
    if (not isinstance(fit_names,list) or not fit_names or len(set(fit_names))!=len(fit_names)
            or any(not isinstance(x,str) or not x.strip() for x in fit_names)):
        raise ValueError('fit_parameter_names must list the ordered fitted parameters')
    if any(name not in bound_pairs for name in fit_names): raise ValueError('every fitted parameter must have a matching declared bound')
    for name,(lo,hi) in bound_pairs.items():
        if name in rates_a: fitted=rates_a[name]
        elif name.lower() in {'alpha','f+nrS'.lower(),'f+nrs'}: fitted=rates_a['f']+rates_a['nrS']
        else: continue
        if fitted<lo or fitted>hi: raise ValueError(f'fitted {name} lies outside its declared bounds')
    fit_window=result.get('fit_window_s')
    if not isinstance(fit_window,list) or len(fit_window)!=2: raise ValueError('fit_window_s must declare two endpoints')
    tlo,thi=map(float,fit_window)
    observed_times=sorted({r[0] for r in rows})
    if (not math.isfinite(tlo) or not math.isfinite(thi) or tlo>=thi
            or tlo<observed_times[0] or thi>observed_times[-1]
            or sum(tlo<=t<=thi for t in observed_times)<2):
        raise ValueError('fit_window_s must be a valid observed interval containing at least two points')
    weights=result.get('weights')
    if isinstance(weights,str):
        if not weights.strip(): raise ValueError('weights declaration must be nonempty')
    elif isinstance(weights,dict):
        if not weights or any(not isinstance(k,str) or not math.isfinite(float(v)) or float(v)<=0 for k,v in weights.items()):
            raise ValueError('numeric weights must be a nonempty mapping of positive finite values')
    elif isinstance(weights,list):
        if not weights or any(not math.isfinite(float(v)) or float(v)<=0 for v in weights): raise ValueError('numeric weights must be positive and finite')
    else: raise ValueError('weights must document the fitting weights')
    starts=result.get('starting_guesses_s-1'); multistart=result.get('multistart_residual_rms')
    if (not isinstance(starts,list) or len(starts)<2 or not isinstance(multistart,list) or len(multistart)!=len(starts)
            or any(not isinstance(row,list) or len(row)!=len(fit_names) or any(not math.isfinite(float(x)) or float(x)<=0 for x in row) for row in starts)
            or any(not math.isfinite(float(v)) or float(v)<0 for v in multistart)):
        raise ValueError('report at least two finite positive starting guesses consistent with the declared parameterization and their fit residuals')
    if any(not bound_pairs[name][0]<=float(value)<=bound_pairs[name][1]
           for row in starts for name,value in zip(fit_names,row)):
        raise ValueError('starting guesses must lie within their declared parameter bounds')
    if min(float(v) for v in multistart)>1e-8 or not math.isclose(min(float(v) for v in multistart),float(result.get('residual_rms',math.nan)),rel_tol=2e-5,abs_tol=2e-12): raise ValueError('best multistart residual disagrees with selected fit')
    alternatives=[]
    rates_b=result.get('parameters_fit_b_equivalent')
    if rates_b is not None: alternatives.append(validate_rates(rates_b,'parameters_fit_b_equivalent'))
    profile=result.get('degeneracy_profile')
    if profile is not None:
        if not isinstance(profile,list) or not profile: raise ValueError('degeneracy_profile must be a nonempty list')
        for i,item in enumerate(profile):
            if not isinstance(item,dict): raise ValueError('degeneracy_profile entries must be objects')
            q=validate_rates(item.get('parameters'),f'degeneracy_profile[{i}] parameters')
            claimed=float(item.get('residual_rms',math.nan))
            actual=rms(predict(q,rows),rows)
            if not math.isfinite(claimed) or not math.isclose(claimed,actual,rel_tol=2e-5,abs_tol=2e-12): raise ValueError('profile residual is not independently reproducible')
            alternatives.append(q)
    if not alternatives: raise ValueError('report a second acceptable positive fit or a reproducible profile')
    curves_a=predict(rates_a,rows); residual_a=rms(curves_a,rows)
    max_delta=0.0
    distinct=[]
    for i,q in enumerate(alternatives):
        curves_q=predict(q,rows); residual_q=rms(curves_q,rows)
        curve_delta=max(float(np.max(np.abs(curves_a[s]-curves_q[s]))) for s in SCENARIOS)
        max_delta=max(max_delta,curve_delta)
        rate_scale=max(1.0,*[abs(rates_a[k]) for k in keys])
        parameter_delta=max(abs(rates_a[k]-q[k]) for k in keys)
        if parameter_delta>1e-8*rate_scale and residual_q<=1e-8 and curve_delta<=1e-8:
            distinct.append((q,curves_q,residual_q))
    if not distinct: raise ValueError('no numerically distinct positive parameter set reproduces the observations within the calibrated residual envelope')
    if residual_a>FIT_RMS_MAX: raise ValueError('fit residual exceeds the frozen-observation numerical envelope')
    if rates_b is not None:
        first_delta=max(float(np.max(np.abs(curves_a[s]-predict(validate_rates(rates_b,'fit_b'),rows)[s]))) for s in SCENARIOS)
        if not math.isclose(float(result.get('equivalence_max_curve_abs_delta',first_delta)),first_delta,rel_tol=2e-4,abs_tol=1e-13): raise ValueError('reported fit curve delta differs from independent recomputation')
    if not math.isclose(float(result.get('residual_rms',math.nan)),residual_a,rel_tol=2e-5,abs_tol=2e-12): raise ValueError('reported residual_rms differs from independent recomputation')
    scenarios=result.get('scenario_parameters')
    if scenarios is None:
        scenarios={name:{key:value*(FACTORS[name][0] if key=='ph1' else FACTORS[name][1] if key=='nr1' else 1.) for key,value in rates_a.items()} for name in SCENARIOS}
    if not isinstance(scenarios,dict) or set(scenarios)!=set(SCENARIOS): raise ValueError('scenario_parameters must list all scenarios')
    baseline=validate_rates(scenarios['baseline'],'scenario baseline')
    if not np.allclose([baseline[k] for k in keys],[rates_a[k] for k in keys],rtol=2e-12,atol=1e-9): raise ValueError('scenario baseline must equal parameters_fit_a')
    for scenario in SCENARIOS:
        q=validate_rates(scenarios[scenario],f'scenario {scenario}')
        for key in keys:
            expected=baseline[key]*(FACTORS[scenario][0] if key=='ph1' else FACTORS[scenario][1] if key=='nr1' else 1.)
            if not math.isclose(q[key],float(expected),rel_tol=1e-12,abs_tol=1e-9): raise ValueError(f'{scenario} changes an undeclared rate or has wrong intervention multiplier')
    reported=result.get('predicted_curves_flattened',{}).get('fit_a')
    if not isinstance(reported,list) or len(reported)!=len(rows)*2: raise ValueError('result must report fit curves for all observations')
    expected_flat=np.concatenate([curves_a[s].ravel() for s in SCENARIOS])
    if not np.allclose(np.asarray(reported,float),expected_flat,rtol=1e-10,atol=1e-12): raise ValueError('reported predicted curves disagree with independent kinetic model')
    diagnostic=result.get('discriminating_observable')
    if not isinstance(diagnostic,dict) or not isinstance(diagnostic.get('predictions'),dict): raise ValueError('provide a machine-checkable discriminating_observable')
    predictions=diagnostic['predictions']
    if diagnostic.get('type')=='absolute_fluorescence_yield':
        if diagnostic.get('unit')!='dimensionless': raise ValueError('absolute fluorescence yield must be dimensionless')
        def fluorescence_yield(q):
            a=np.array([[-(q['f']+q['nrS']+q['isc']),q['risc']],[q['isc'],-(q['risc']+q['ph1']+q['nr1'])]])
            return float(q['f']*(np.linalg.solve(-a,np.array([1.,0.]))[0]))
        expected_a=fluorescence_yield(rates_a); expected_b=fluorescence_yield(distinct[0][0])
    elif diagnostic.get('type')=='direct_rate_measurement':
        parameter=diagnostic.get('parameter')
        if parameter not in keys or diagnostic.get('unit')!='s^-1': raise ValueError('direct rate observable must name a rate in s^-1')
        expected_a=rates_a[parameter]; expected_b=distinct[0][0][parameter]
    elif diagnostic.get('type')=='calibrated_fluorescence_flux':
        scenario=diagnostic.get('scenario'); time_s=float(diagnostic.get('time_s',math.nan))
        if scenario not in SCENARIOS or diagnostic.get('unit')!='s^-1 per initially excited molecule' or not math.isfinite(time_s) or time_s<0:
            raise ValueError('calibrated fluorescence flux requires a scenario, nonnegative time, and declared units')
        def fluorescence_flux(q):
            a=generator(q,scenario)
            return float(q['f']*(expm(a*time_s)@np.array([1.,0.]))[0])
        expected_a=fluorescence_flux(rates_a); expected_b=fluorescence_flux(distinct[0][0])
    else: raise ValueError('unsupported discriminating_observable type')
    if not math.isclose(float(predictions.get('fit_a',math.nan)),expected_a,rel_tol=1e-10,abs_tol=1e-12) or not math.isclose(float(predictions.get('fit_b',math.nan)),expected_b,rel_tol=1e-10,abs_tol=1e-12):
        raise ValueError('discriminating-observable predictions do not follow from the fitted parameter sets')
    minimum_separation=(YIELD_MIN_SEPARATION if diagnostic.get('type')=='absolute_fluorescence_yield' else RATE_MIN_RELATIVE_SEPARATION*max(abs(expected_a),abs(expected_b)))
    if abs(expected_a-expected_b)<=minimum_separation:
        raise ValueError('proposed observable does not numerically distinguish the reported fits')
    evidence=diagnosis_evidence(final/'diagnosis.md',result,rates_a,distinct[0][0],rows)
    structural=evidence.get('structural_identifiability')
    if not isinstance(structural,dict) or structural.get('status') not in {'witnessed_equivalent_generator','witnessed_equivalent_observations'}:
        raise ValueError('diagnosis evidence must describe a numerically witnessed structural ambiguity')
    def fit_ref(ref):
        if ref=='parameters_fit_a': return rates_a
        if ref=='parameters_fit_b_equivalent' and rates_b is not None: return validate_rates(rates_b,'fit_b')
        match=re.fullmatch(r'degeneracy_profile\[(\d+)\]',str(ref))
        if match and isinstance(profile,list) and int(match.group(1))<len(profile): return validate_rates(profile[int(match.group(1))]['parameters'],'profile witness')
        raise ValueError('diagnosis witness must reference a reported fitted parameter set')
    witness_a=fit_ref(structural.get('fit_a_ref')); witness_b=fit_ref(structural.get('fit_b_ref'))
    if structural.get('fit_a_ref')!='parameters_fit_a': raise ValueError('structural witness must include the selected fit')
    scenario_gen_delta=max(float(np.max(np.abs(generator(witness_a,s)-generator(witness_b,s)))) for s in SCENARIOS)
    witness_curves_a=predict(witness_a,rows); witness_curves_b=predict(witness_b,rows)
    scenario_curve_delta=max(float(np.max(np.abs(witness_curves_a[s]-witness_curves_b[s]))) for s in SCENARIOS)
    rate_scale=max(1.0,*[abs(witness_a[k]) for k in keys])
    if scenario_curve_delta>FIT_RMS_MAX:
        raise ValueError('diagnosis witness does not preserve observed curves within the calibrated numerical resolution')
    if structural['status']=='witnessed_equivalent_generator' and scenario_gen_delta>max(1e-8,1e-12*rate_scale):
        raise ValueError('claimed equivalent-generator witness changes the generator')
    if structural['status']=='witnessed_equivalent_observations':
        relative_parameter_delta=max(abs(witness_a[k]-witness_b[k])/max(abs(witness_a[k]),abs(witness_b[k])) for k in keys)
        if relative_parameter_delta<=1e-6 or not isinstance(structural.get('invariant_explanation'),str) or not structural['invariant_explanation'].strip():
            raise ValueError('observation-equivalence witness needs distinct rates and a stated invariant/mapping')
        if not math.isclose(float(structural.get('max_parameter_relative_delta',math.nan)),relative_parameter_delta,rel_tol=2e-5,abs_tol=1e-12):
            raise ValueError('diagnosis relative parameter separation is not independently reproducible')
    for field,value in [('max_generator_abs_delta_s-1',scenario_gen_delta),('max_curve_abs_delta',scenario_curve_delta)]:
        if not math.isclose(float(structural.get(field,math.nan)),value,rel_tol=2e-5,abs_tol=1e-12): raise ValueError(f'diagnosis evidence {field} is not independently reproducible')
    practical=evidence.get('practical_identifiability')
    if not isinstance(practical,dict) or practical.get('status') not in {'not_quantified_without_noise_model','profile_quantified'}:
        raise ValueError('diagnosis evidence must state whether practical uncertainty was quantified')
    if practical.get('fit_window_s')!=fit_window: raise ValueError('diagnosis finite-window statement must match fit_window_s')
    if practical['status']=='not_quantified_without_noise_model' and practical.get('noise_model') is not None:
        raise ValueError('unquantified practical uncertainty must not claim a noise model')
    if practical['status']=='profile_quantified':
        if profile is None or not isinstance(practical.get('profile_refs'),list) or not practical['profile_refs']:
            raise ValueError('profile-quantified diagnosis must cite independently checked profiles')
        for ref in practical['profile_refs']: fit_ref(ref)
    if evidence.get('discriminating_observable_ref')!='result.discriminating_observable':
        raise ValueError('diagnosis must cite the machine-checked discriminating observable in result.json')
    if (final/'observations.csv').exists():
        out=load_rows(final/'observations.csv')
        if len(out)!=len(rows) or any(a[1]!=b[1] or a[0]!=b[0] or a[2]!=b[2] or a[3]!=b[3] for a,b in zip(out,rows)):
            raise ValueError('a submitted observations.csv must preserve the public observations')
    return {'rms':residual_a,'curve_delta':max_delta}

def _replay_public_experiment(script, app, root, *, timeout=300):
    """Replay final/experiment.py inside an isolated copy of the public app layout."""
    scratch=Path(root)/'scratch'
    scratch.mkdir(parents=True,exist_ok=False)
    (scratch/'inputs').mkdir()
    (scratch/'final').mkdir()
    shutil.copy2(script,scratch/'final'/'experiment.py')
    for name in ('observations.csv','benchmark.json'):
        shutil.copy2(Path(app)/'inputs'/name,scratch/'inputs'/name)
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(scratch),'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MPLBACKEND':'Agg'}
    proc=subprocess.run([sys.executable,'final/experiment.py'],cwd=scratch,env=env,capture_output=True,text=True,timeout=timeout)
    final=scratch/'final'
    for path,label in ((scratch,'scratch root'),(scratch/'inputs','inputs directory'),(final,'final directory')):
        try: mode=path.lstat().st_mode
        except FileNotFoundError as exc: raise ValueError(f'missing replay {label}') from exc
        if not stat.S_ISDIR(mode): raise ValueError(f'unsafe replay {label}')
    if (scratch/'result.json').exists() or (scratch/'result.json').is_symlink():
        raise ValueError('unexpected root-level replay result')
    for name in ('result.json','observations.csv','diagnosis.md'):
        output=final/name
        if output.is_symlink(): raise ValueError(f'unsafe replay output symlink: {name}')
        if output.exists() and not output.is_file(): raise ValueError(f'unsafe replay output type: {name}')
    return proc, final

def grade(app, final):
    app,final=Path(app),Path(final)
    try:
        if SCORER_IMPORT_ERROR is not None: raise EnvironmentError(f'NumPy/SciPy scorer dependency unavailable: {SCORER_IMPORT_ERROR}')
        for name,digest in EXPECTED.items():
            p=app/'inputs'/name
            if p.is_symlink() or not p.is_file() or sha(p)!=digest: raise EnvironmentError(f'public evaluation asset missing/damaged: {name}')
        protocol=read_json(app/'inputs'/'benchmark.json')
        numerical=protocol.get('numerical_acceptance',{})
        if numerical.get('fit_rms_max')!=FIT_RMS_MAX or numerical.get('absolute_fluorescence_yield_minimum_separation')!=YIELD_MIN_SEPARATION or numerical.get('direct_rate_measurement_minimum_relative_separation')!=RATE_MIN_RELATIVE_SEPARATION:
            raise EnvironmentError('public numerical-acceptance protocol differs from scorer calibration')
        if protocol.get('experiments')!={'baseline':{'ph1_multiplier':1.0,'nr1_multiplier':1.0},'intervention_A':{'ph1_multiplier':3.0,'nr1_multiplier':1.0},'intervention_B':{'ph1_multiplier':1.0,'nr1_multiplier':3.0}}:
            raise EnvironmentError('public intervention protocol is inconsistent with scorer')
        rows=load_rows(app/'inputs'/'observations.csv')
        by={s:[r for r in rows if r[1]==s] for s in SCENARIOS}
        if any(len(v)<80 for v in by.values()): raise EnvironmentError('frozen public observation set is incomplete')
        t=np.array([r[0] for r in by['baseline']])
        if not np.allclose(t,np.geomspace(1e-9,1e-2,len(t)),rtol=2e-14,atol=0): raise EnvironmentError('public time grid does not match contract')
        for s in SCENARIOS:
            if [r[0] for r in by[s]]!=list(t): raise EnvironmentError('scenario time grids differ')
        observed=validate(final,rows)
        script=final/'experiment.py'
        if script.is_symlink() or not script.is_file(): raise ValueError('final/experiment.py required')
        with tempfile.TemporaryDirectory(prefix='identifiability-replay-') as td:
            proc,replay_final=_replay_public_experiment(script,app,td)
            if proc.returncode: raise ValueError(f'experiment.py replay failed rc={proc.returncode}: {proc.stderr[-1000:]}')
            replay=validate(replay_final,rows)
            if replay['rms']>1e-8: raise ValueError('replayed candidate fit did not reproduce observations')
        return {'status':'PASS','reward':1.0,'exit_code':0,'detail':f"Independent kinetic recomputation, frozen observations, source replay, declared intervention effects, and numerically distinct positive fits and discriminating observable passed (RMS {observed['rms']:.3g})."}
    except EnvironmentError as e: return {'status':'ENV_INVALID','reward':None,'exit_code':2,'detail':str(e)}
    except ImportError as e: return {'status':'ENV_INVALID','reward':None,'exit_code':2,'detail':f'scorer dependency unavailable: {e}'}
    except Exception as e: return {'status':'FAIL','reward':0.0,'exit_code':1,'detail':str(e)}

def check(package, candidate):
    return grade(Path(package), Path(candidate))

if __name__=='__main__':
    app=Path(os.environ.get('APP','/app')); final=app/'final'; logs=Path(os.environ.get('LOGS','/logs/verifier')); logs.mkdir(parents=True,exist_ok=True)
    outcome=grade(app,final); (logs/'verification.json').write_text(json.dumps(outcome,indent=2)+'\n')
    if outcome['reward'] is None: (logs/'reward.txt').unlink(missing_ok=True)
    else: (logs/'reward.txt').write_text(f"{outcome['reward']}\n")
    print(json.dumps(outcome,ensure_ascii=False)); raise SystemExit(outcome['exit_code'])
