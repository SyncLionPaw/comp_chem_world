#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Hydrogen-induced stacking-fault response and finite-area uncertainty.
"""Independent case-03 statistics and finite-area transport verifier."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from statistics import NormalDist
N=9; AREAS=(30.,50.,70.,108.)

def check_calculation_evidence(final, app, expected_input_name):
 import ast
 src=final/"calculation_source.py"; mp=final/"run_metadata.json"
 if not src.is_file() or not mp.is_file(): raise AssertionError("executable calculation source and run metadata are required")
 try: ast.parse(src.read_text(encoding="utf8")); meta=json.loads(mp.read_text(encoding="utf8"))
 except Exception as exc: raise AssertionError("calculation evidence is not parseable") from exc
 if not isinstance(meta,dict): raise AssertionError("run metadata must be a JSON object")
 if meta.get("schema")!="compchemworld-calculation-run/v1" or meta.get("calculation_source_sha256")!=sha(src): raise AssertionError("calculation source provenance hash mismatch")
 candidates=list((app/"assets").glob(expected_input_name)); item=meta.get("input")
 if not isinstance(item,dict): raise AssertionError("run metadata input must be a JSON object")
 if len(candidates)!=1 or item.get("logical_name")!=expected_input_name or item.get("sha256")!=sha(candidates[0]): raise AssertionError("run metadata public input hash mismatch")
 outputs={p.name:sha(p) for p in final.iterdir() if p.is_file() and p.name not in {"calculation_source.py","run_metadata.json"}}
 if not isinstance(meta.get("output_sha256"),dict): raise AssertionError("run metadata output_sha256 must be a JSON object")
 if meta.get("output_sha256")!=outputs: raise AssertionError("run metadata output hashes mismatch")
 python_meta=meta.get("python")
 python_valid=(isinstance(python_meta,str) and bool(python_meta.strip())) or (isinstance(python_meta,dict) and isinstance(python_meta.get("version"),str) and bool(python_meta["version"].strip()))
 if not python_valid or not meta.get("execution_context"): raise AssertionError("run environment metadata missing")

def read(p):
 with p.open(newline='',encoding='utf8') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ck(a,b,t=2e-8):return abs(float(a)-float(b))<=t
def canonical_contrast_name(value):
 names=('delta_0_to_05','delta_05_to_1','delta_0_to_1','curvature_mu1_minus2mu05_plusmu0')
 return {name.replace('_',''):name for name in names}.get(value.replace('_',''),value)

def response_rounding_mode(rows, source_precision):
 expected_coefficients={
  'delta_0_to_05':[-1,1,0],
  'delta_05_to_1':[0,-1,1],
  'delta_0_to_1':[-1,0,1],
  'curvature_mu1_minus2mu05_plusmu0':[1,-2,1],
 }
 propagated={}
 per_anchor_values=[]
 propagated_values=[]
 for row in rows:
  contrast=canonical_contrast_name(row['contrast'])
  coefficients=expected_coefficients.get(contrast)
  if coefficients is None:raise AssertionError('unknown response contrast')
  try:reported_coefficients=json.loads(row['coverage_coefficients'])
  except (TypeError,ValueError) as exc:raise AssertionError('invalid response contrast coefficients') from exc
  if reported_coefficients!=coefficients:raise AssertionError('contrast coefficient mismatch')
  key=(row['alloy'],contrast,row['spread_convention'])
  if key in propagated:raise AssertionError('duplicate response rounding key')
  bound=source_precision*sum(abs(value) for value in coefficients)
  propagated[key]=bound
  reported=float(row['source_anchor_rounding_bound_mJ_m2'])
  per_anchor_values.append(reported)
  propagated_values.append((reported,bound))
 if len(rows)!=48:raise AssertionError('expected all 48 response rows before rounding-mode detection')
 per_anchor=all(ck(value,source_precision) for value in per_anchor_values)
 contrast_level=all(ck(value,bound) for value,bound in propagated_values)
 if per_anchor==contrast_level:
  raise AssertionError('response rounding column must use one consistent per-anchor or propagated-contrast convention')
 return ('per_anchor' if per_anchor else 'contrast'),propagated

def normal95_protocol(rows, propagated_rounding):
 for z in (NormalDist().inv_cdf(.975),1.96):
  for include_rounding in (True,False):
   valid=True
   for row in rows:
    center=float(row['mean_contrast_mJ_m2']);se=float(row['SE_independent_mJ_m2'])
    if not math.isfinite(center) or not math.isfinite(se) or se<=0:
     raise AssertionError('invalid normal interval calibration row')
    bounds=json.loads(row['normal95_independent_interval_mJ_m2'])
    if len(bounds)!=2:raise AssertionError('invalid normal interval calibration row')
    key=(row['alloy'],canonical_contrast_name(row['contrast']),row['spread_convention'])
    if key not in propagated_rounding:raise AssertionError('normal interval has no validated contrast rounding bound')
    extra=propagated_rounding[key] if include_rounding else 0.
    if not (ck(bounds[0],center-z*se-extra) and ck(bounds[1],center+z*se+extra)):
     valid=False
     break
   if valid:return z,include_rounding
 raise AssertionError('normal95 intervals must use one exact normal quantile or 1.96 throughout, with propagated source rounding either included or reported separately')

def preflight(app,tests):
 try: refs=json.loads((tests/'refs.json').read_text(encoding='utf8'))
 except Exception as exc: raise RuntimeError(f'integrity failure: refs.json: {type(exc).__name__}') from exc
 if not isinstance(refs,dict) or refs.get('case_id')!='case-03':raise RuntimeError('integrity failure: refs.json case/schema')
 for key,base,subdir in (('asset_hashes',app,'assets'),('grader_reference_hashes',tests,'references')):
  entries=refs.get(key)
  if not isinstance(entries,dict) or (key=='asset_hashes' and not entries):raise RuntimeError('integrity failure: missing '+key)
  expected={str(p.relative_to(base)) for p in (base/subdir).rglob('*') if p.is_file()}
  actual={name.removeprefix('tests/') for name in entries} if key=='grader_reference_hashes' else set(entries)
  if actual!=expected:raise RuntimeError('integrity failure: incomplete or extra '+key)
  for rel,h in entries.items():
   p=base/rel.removeprefix('tests/') if key=='grader_reference_hashes' else base/rel
   try:valid=p.is_file() and 'sha256:'+sha(p)==h
   except Exception:valid=False
   if not valid:raise RuntimeError('integrity failure: '+rel)
 return refs
def verify(app,tests,final):
 preflight(app,tests)
 check_calculation_evidence(final,app,"gamma_usf_fig2c_parameters.csv")
 refs=json.loads((tests/'refs.json').read_text())
 for rel,h in refs['asset_hashes'].items():
  p=app/rel
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('public input invalid: '+rel)
 for rel,h in refs['grader_reference_hashes'].items():
  p=tests/rel.removeprefix('tests/')
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('grading reference invalid: '+rel)
 src=read(app/'assets/gamma_usf_fig2c_parameters.csv')
 if len(src)!=18:raise AssertionError('expected 18 published anchors')
 data={}
 for r in src:data.setdefault(r['alloy'],[]).append(r)
 if len(data)!=6 or any(len(v)!=3 for v in data.values()):raise AssertionError('expected six alloys × three anchors')
 response=read(final/'response.csv'); area=read(final/'area_transport.csv'); ranks=read(final/'ranking.csv')
 z95=None;normal_includes_rounding=False
 if (len(response),len(area),len(ranks))!=(48,72,30):raise AssertionError('required output cardinality mismatch')
 ridx={(r['alloy'],canonical_contrast_name(r['contrast']),r['spread_convention']):r for r in response}
 aidx={(r['alloy'],float(r['coverage']),float(r['area_A2'])):r for r in area}
 rkidx={(float(r['coverage']),int(r['adjacent_rank_edge']),r['source_ddof_interpretation']):r for r in ranks}
 if len(ridx)!=48 or len(aidx)!=72 or len(rkidx)!=30:raise AssertionError('duplicate output keys')
 spread_columns_at_source = None
 for candidate in area:
  if float(candidate['area_A2']) == 108.:continue
  anchors=[r for r in data.get(candidate['alloy'],[]) if float(r['coverage_Cusf'])==float(candidate['coverage'])]
  if len(anchors)!=1:raise AssertionError('area row has unknown source anchor')
  source_sigma=float(anchors[0]['gamma_usf_std_DFT_mJ_m2']);scale=math.sqrt(108/float(candidate['area_A2']))
  reported=float(candidate['spread_if_reported_ddof1_sample_mJ_m2'])
  if ck(reported,source_sigma):spread_columns_at_source=True
  elif ck(reported,source_sigma*scale):spread_columns_at_source=False
  else:raise AssertionError('spread columns must consistently report source or transported physical spread')
  break
 if spread_columns_at_source is None:raise AssertionError('finite-area grid missing non-source areas')
 required_response={'coverage_coefficients','mean_contrast_mJ_m2','SE_independent_mJ_m2','SE_unknown_covariance_min_mJ_m2','SE_unknown_covariance_max_mJ_m2','normal95_independent_interval_mJ_m2','normal95_unknown_covariance_envelope_mJ_m2','source_anchor_rounding_bound_mJ_m2','sign_robust_under_worst_covariance_and_rounding','source_n'}
 required_area={'mean_mJ_m2','mean_estimation_SE_if_reported_ddof0_mJ_m2','mean_estimation_SE_if_reported_ddof1_mJ_m2','spread_if_reported_ddof0_sample_corrected_mJ_m2','spread_if_reported_ddof1_sample_mJ_m2','scale_factor_from_108A2','source_precision_mJ_m2','Gaussian_model_domain_flag'}
 if any(not required_response.issubset(r) for r in response) or any(not required_area.issubset(r) for r in area):raise AssertionError('required uncertainty/provenance columns missing')
 spec=json.loads((app/'assets/task09_task_spec.json').read_text(encoding='utf8'))
 source_precision=float(spec['frozen_grid']['source_precision_mJ_m2'])
 if not math.isfinite(source_precision) or source_precision<=0:raise AssertionError('invalid public source precision')
 rounding_column_mode,propagated_rounding=response_rounding_mode(response,source_precision)
 z95,normal_includes_rounding=normal95_protocol(response,propagated_rounding)
 input_order={a:i for i,a in enumerate(sorted(data))}
 for alloy,items in data.items():
  items.sort(key=lambda r:float(r['coverage_Cusf']))
  means=[float(r['gamma_usf_mean_mJ_m2']) for r in items]; sig=[float(r['gamma_usf_std_DFT_mJ_m2']) for r in items]
  if any(float(r['area_A2'])!=108 for r in items):raise AssertionError('source area must be 108 A2')
  contrasts={'delta_0_to_05':([-1,1,0],means[1]-means[0]),'delta_05_to_1':([0,-1,1],means[2]-means[1]),'delta_0_to_1':([-1,0,1],means[2]-means[0]),'curvature_mu1_minus2mu05_plusmu0':([1,-2,1],means[0]-2*means[1]+means[2])}
  for name,(coef,val) in contrasts.items():
   for convention,factor in [('reported_ddof0_population',math.sqrt(N/(N-1))),('reported_ddof1_sample',1.)]:
    s=[x*factor for x in sig]; terms=[abs(c)*v for c,v in zip(coef,s)]; mx=sum(terms); mn=max(0,2*max(terms)-mx)
    se=math.sqrt(sum((c*v)**2 for c,v in zip(coef,s)))/math.sqrt(N); worst=mx/math.sqrt(N)
    out=ridx.get((alloy,name,convention))
    if not out or not ck(out['mean_contrast_mJ_m2'],val):raise AssertionError('published mean contrast mismatch')
    if not ck(out['SE_independent_mJ_m2'],se) or not ck(out['SE_unknown_covariance_min_mJ_m2'],mn/math.sqrt(N)) or not ck(out['SE_unknown_covariance_max_mJ_m2'],worst):raise AssertionError('SE/covariance bound mismatch')
    if json.loads(out['coverage_coefficients'])!=coef or int(out['source_n'])!=N:raise AssertionError('contrast coefficient or sample count mismatch')
    rounding=source_precision*sum(abs(x) for x in coef)
    for field,err in [('normal95_independent_interval_mJ_m2',se),('normal95_unknown_covariance_envelope_mJ_m2',worst)]:
     got=json.loads(out[field]);extra=rounding if normal_includes_rounding else 0.;want=[val-z95*err-extra,val+z95*err+extra]
     if len(got)!=2 or not ck(got[0],want[0]) or not ck(got[1],want[1]):raise AssertionError('conditional interval mismatch')
    robust=(val-z95*worst-rounding>0 or val+z95*worst+rounding<0)
    if out['sign_robust_under_worst_covariance_and_rounding']!=str(robust).lower():raise AssertionError('contrast robustness label mismatch')
  for r in items:
   cov=float(r['coverage_Cusf']); m=float(r['gamma_usf_mean_mJ_m2']); sd=float(r['gamma_usf_std_DFT_mJ_m2'])
   for A in AREAS:
    z=aidx.get((alloy,cov,A))
    if not z:raise AssertionError('missing area transport row')
    scale=math.sqrt(108/A); pop=sd*scale; sample=sd*math.sqrt(N/(N-1))*scale
    reported_scale=1. if spread_columns_at_source else scale
    if not ck(z['scale_factor_from_108A2'],scale) or not ck(z['spread_if_reported_ddof1_sample_mJ_m2'],sd*reported_scale) or not ck(z['spread_if_reported_ddof0_sample_corrected_mJ_m2'],sd*math.sqrt(N/(N-1))*reported_scale):raise AssertionError('area transport formula mismatch')
    if not ck(z['mean_mJ_m2'],m) or not ck(z['mean_estimation_SE_if_reported_ddof0_mJ_m2'],sd/math.sqrt(N-1)) or not ck(z['mean_estimation_SE_if_reported_ddof1_mJ_m2'],sd/math.sqrt(N)):raise AssertionError('mean/mean-SE separation mismatch')
    if not ck(z['source_precision_mJ_m2'],source_precision) or 'conditional extrapolation' not in z['Gaussian_model_domain_flag']:raise AssertionError('area-source precision/domain declaration mismatch')
    for mode,sigma in [('ddof0',sample),('ddof1',pop)]:
     q=float(z[f'quantile_05_{mode}_mJ_m2']); med=float(z[f'quantile_50_{mode}_mJ_m2']); hi=float(z[f'quantile_95_{mode}_mJ_m2'])
     if not ck(q,m+NormalDist().inv_cdf(.05)*sigma) or not ck(med,m) or not ck(hi,m+NormalDist().inv_cdf(.95)*sigma):raise AssertionError('area quantiles mismatch')
     tail=.5*math.erfc(m/(sigma*math.sqrt(2)))
     if not ck(z[f'P_gamma_nonpositive_{mode}'],tail):raise AssertionError('Gaussian negative-tail probability mismatch')
 # Verify every adjacent published ranking and its ddof-dependent, unknown-covariance envelope.
 expected_rank_rows=[]
 for cov in (0.,.5,1.):
  ordered=sorted(((a,next(r for r in items if float(r['coverage_Cusf'])==cov)) for a,items in data.items()),key=lambda v:float(v[1]['gamma_usf_mean_mJ_m2']))
  for edge,((low,lr),(high,hr)) in enumerate(zip(ordered,ordered[1:]),1):
   diff=float(hr['gamma_usf_mean_mJ_m2'])-float(lr['gamma_usf_mean_mJ_m2'])
   for conv,factor in [('reported_ddof0_population',math.sqrt(N/(N-1))),('reported_ddof1_sample',1.)]:
    ls=float(lr['gamma_usf_std_DFT_mJ_m2']);hs=float(hr['gamma_usf_std_DFT_mJ_m2']);se_ind=math.hypot(ls*factor,hs*factor)/math.sqrt(N);se_worst=(ls+hs)*factor/math.sqrt(N);rounding=1.;lo=diff-z95*se_worst-rounding;hi=diff+z95*se_worst+rounding
    rr=rkidx.get((cov,edge,conv))
    if not rr or rr['alloy_low']!=low or rr['alloy_high']!=high:raise AssertionError('adjacent ranking order mismatch')
    if not ck(rr['mean_difference_high_minus_low_mJ_m2'],diff) or not ck(rr['SE_independent_mJ_m2'],se_ind) or not ck(rr['SE_worst_covariance_mJ_m2'],se_worst) or not ck(rr['source_rounding_bound_mJ_m2'],rounding):raise AssertionError('adjacent rank uncertainty mismatch')
    got=json.loads(rr['conditional_interval_low_high_mJ_m2'])
    if not ck(got[0],lo) or not ck(got[1],hi):raise AssertionError('adjacent rank interval mismatch')
    label='robust_under_worst_covariance_plugin95' if lo>0 else 'unresolved'
    if rr['rank_robust_or_unresolved']!=label or 'not an exact 95% confidence' not in rr['interpretation']:raise AssertionError('adjacent rank label or interval interpretation mismatch')
 inf=json.loads((final/'inference.json').read_text())
 if not isinstance(inf,dict) or not isinstance(inf.get('scientific_inference'),dict) or not isinstance(inf.get('scientific_inference',{}).get('pairwise_rank_comparisons'),list):raise AssertionError('inference.json must contain scientific_inference object and pairwise_rank_comparisons array')
 if inf['n_independent_sqs_per_anchor']!=9 or inf['source_area_A2']!=108 or inf['rows']!={'response':48,'area_transport':72,'ranking':30}:raise AssertionError('inference declaration mismatch')
 if inf['scientific_inference']['published_means_monotonically_harden_all_six']!=all(float(v[2]['gamma_usf_mean_mJ_m2'])>float(v[0]['gamma_usf_mean_mJ_m2']) for v in [sorted(r,key=lambda x:float(x['coverage_Cusf'])) for r in data.values()]):raise AssertionError('mean hardening claim mismatch')
 if len(inf['scientific_inference']['pairwise_rank_comparisons'])!=90:raise AssertionError('full 15 pairwise comparisons × 3 coverages × 2 ddof conventions missing')
 for cov in ('0.0','0.5','1.0'):
  order=sorted(data,key=lambda a:next(float(r['gamma_usf_mean_mJ_m2']) for r in data[a] if float(r['coverage_Cusf'])==float(cov)))
  if inf['scientific_inference']['published_mean_rankings_by_coverage'][cov] not in (order,list(reversed(order))):raise AssertionError('published mean ranking summary mismatch')
 # Each all-pairs entry is derived from the same anchor means and spread declarations.
 pidx={(float(r['coverage']),r['alloy_a'],r['alloy_b'],r['spread_convention']):r for r in inf['scientific_inference']['pairwise_rank_comparisons']}
 for cov in (0.,.5,1.):
  alloys=sorted(data)
  for i,a1 in enumerate(alloys):
   for a2 in alloys[i+1:]:
    x=next(r for r in data[a1] if float(r['coverage_Cusf'])==cov);y=next(r for r in data[a2] if float(r['coverage_Cusf'])==cov);diff=float(x['gamma_usf_mean_mJ_m2'])-float(y['gamma_usf_mean_mJ_m2'])
    for conv,factor in [('reported_ddof0_population',math.sqrt(N/(N-1))),('reported_ddof1_sample',1.)]:
     row=pidx.get((cov,a1,a2,conv));semax=(float(x['gamma_usf_std_DFT_mJ_m2'])+float(y['gamma_usf_std_DFT_mJ_m2']))*factor/math.sqrt(N);lo=diff-z95*semax-1.;hi=diff+z95*semax+1.
     if not row or not ck(row['mean_difference_a_minus_b_mJ_m2'],diff) or not ck(row['unknown_cross_alloy_covariance_plugin95_envelope_mJ_m2'][0],lo) or not ck(row['unknown_cross_alloy_covariance_plugin95_envelope_mJ_m2'][1],hi) or row['conditional_rank_resolved']!=(lo>0 or hi<0):raise AssertionError('full pairwise ranking interval mismatch')
 return {'status':'PASS','reward':1,'source_anchors':18,'response_rows':48,'area_rows':72,'rank_rows':30,'source_rounding_column_mode':rounding_column_mode}
def main():
 p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--tests-dir',type=Path,required=True);p.add_argument('--final-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 try:r=verify(a.app_dir,a.tests_dir,a.final_dir);c=0
 except RuntimeError as e:r={'status':'ENV_INVALID','reward':None,'reason':str(e)};c=2
 except (AssertionError,KeyError,ValueError,TypeError,OSError,json.JSONDecodeError) as e:r={'status':'FAIL','reward':0,'reason':f'{type(e).__name__}: {e}'};c=1
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));raise SystemExit(c)
if __name__=='__main__':main()
