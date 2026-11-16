#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Crack-tip hydrogen occupation and fracture free energy.
"""Independent case-05 thermodynamic reconstruction from public source parameters."""
import argparse,csv,hashlib,json,math
from decimal import Decimal, InvalidOperation
from pathlib import Path
import numpy as np
from numpy.polynomial.legendre import leggauss
KB=8.617333262145e-5; EV_A2=16.02176634; K=leggauss(512); X=8*K[0]; W=8*K[1]*np.exp(-X*X)/math.sqrt(math.pi)
WIDTHS={'printed_formula_scale':1.,'caption_standard_deviation':math.sqrt(2)}
CONDS=[('fig1b_ss304_2600appm_300K',('SS304',),.0026,300),('fig2b_reference_5800appm_300K_assumed','ALL',.0058,300),('fig3_ss304_4000appm_300K',('SS304',),.004,300),('fig3_ss304_4000appm_400K',('SS304',),.004,400)]
def read(p):
 with p.open(newline='',encoding='utf8') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def close(a,b,t=2e-7):return math.isfinite(float(a)) and abs(float(a)-float(b))<=t
def parse_exact_integral_csv(text,field):
 try:d=Decimal(text.strip())
 except (InvalidOperation,AttributeError):raise AssertionError(f'{field} must be a finite integer value') from None
 if not d.is_finite() or d!=d.to_integral_value():raise AssertionError(f'{field} must be a finite integer value')
 return int(d)
def occupancy_bounds_interval(value):
 if isinstance(value,dict):
  if not {'minimum','maximum'}.issubset(value):raise AssertionError('occupancy bound object needs minimum and maximum')
  bounds=[value['minimum'],value['maximum']]
 elif isinstance(value,list) and len(value)==2:bounds=value
 else:raise AssertionError('occupancy bounds must be [minimum,maximum] or a named bound object')
 if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in bounds):raise AssertionError('occupancy bounds must be finite numeric values')
 return bounds

def conditional_reference_valid(value):
 if isinstance(value,str):return all(token in value for token in ('conditional','assumed','±0.05'))
 if not isinstance(value,dict):return False
 return value.get('status')=='conditional' and value.get('reference_temperature_status')=='assumed' and close(value.get('reference_Cb_fraction',float('nan')),.0058,1e-12) and close(value.get('reference_temperature_K',float('nan')),300.,1e-12) and close(value.get('image_half_width_J_m2',float('nan')),.05,1e-12)

def preflight(app,tests):
 try:refs=json.loads((tests/'refs.json').read_text(encoding='utf8'))
 except Exception as exc:raise RuntimeError(f'integrity failure: refs.json: {type(exc).__name__}') from exc
 if not isinstance(refs,dict) or refs.get('case_id')!='case-05':raise RuntimeError('integrity failure: refs.json case/schema')
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
def check_calculation_evidence(final, app):
 import ast
 source=final/'calculation_source.py';record=final/'run_metadata.json'
 if not source.is_file() or not record.is_file():raise AssertionError('executable calculation source and run record are required')
 try:ast.parse(source.read_text(encoding='utf8'))
 except SyntaxError as exc:raise AssertionError('calculation source must be executable Python') from exc
 meta=json.loads(record.read_text(encoding='utf8'))
 if not isinstance(meta,dict) or meta.get('schema')!='compchemworld-calculation-run/v1':raise AssertionError('invalid calculation run record')
 sources=meta.get('calculation_sources')
 if not isinstance(sources,list) or not sources or any(not isinstance(x,dict) or not isinstance(x.get('name'),str) for x in sources):raise AssertionError('calculation source records are required')
 names=[x['name'] for x in sources]
 if 'calculation_source.py' not in names or len(set(names))!=len(names):raise AssertionError('calculation sources must uniquely include the main source')
 for item in sources:
  rel=Path(item['name']);p=final/rel
  if rel.is_absolute() or '..' in rel.parts or not p.resolve().is_relative_to(final.resolve()) or p.is_symlink() or not p.is_file() or str(item.get('sha256','')).removeprefix('sha256:')!=sha(p):raise AssertionError('calculation source binding mismatch')
 inputs=meta.get('inputs');outputs=meta.get('outputs')
 if not isinstance(inputs,dict) or not isinstance(outputs,dict):raise AssertionError('input/output records must be objects')
 expected_inputs={p.name:sha(p) for p in (app/'assets').iterdir() if p.is_file()}
 expected_outputs={p.relative_to(final).as_posix():sha(p) for p in final.rglob('*') if p.is_file() and p!=record}
 if {k:str(v).removeprefix('sha256:') for k,v in inputs.items()}!=expected_inputs:raise AssertionError('calculation input binding mismatch')
 if {k:str(v).removeprefix('sha256:') for k,v in outputs.items()}!=expected_outputs:raise AssertionError('calculation output binding mismatch')
 version=meta.get('python');context=meta.get('execution_context')
 if not ((isinstance(version,str) and version.strip()) or (isinstance(version,dict) and isinstance(version.get('version'),str) and version['version'].strip())):raise AssertionError('Python version is required')
 if not ((isinstance(context,str) and context.strip()) or (isinstance(context,dict) and context)):raise AssertionError('execution context is required')

def occ(E,eta,T):return 1/(1+np.exp(np.clip((E-eta)/(KB*T),-700,700)))
def solve_eta(cb,sigma,T,offset=0):
 lo,hi=-5.,5.
 for _ in range(100):
  mid=(lo+hi)/2
  if float(np.dot(W,occ(sigma*X+offset,mid,T)))<cb:lo=mid
  else:hi=mid
 return (lo+hi)/2
def gamma_s(cs,cb,T,a0):
 v=0.
 if cs>0:v+=-cs*math.log(cb)+cs*math.log(cs)
 if cs<1:v+=(1-cs)*math.log(1-cs)
 return KB*T/(math.sqrt(3)*a0*a0/4)*v*EV_A2
def interp(x,pts):
 pts=sorted(pts)
 if x<pts[0][0]-1e-10 or x>pts[-1][0]+1e-10:raise AssertionError('C_S outside source anchor range')
 for (x0,y0),(x1,y1) in zip(pts,pts[1:]):
  if x0<=x<=x1:return y0+(y1-y0)*(x-x0)/(x1-x0)
 return pts[-1][1]
def hill(c11,c12,c44):
 gv=(c11-c12+3*c44)/5;gr=5*(c11-c12)*c44/(4*c44+3*(c11-c12));g=(gv+gr)/2;b=(c11+2*c12)/3
 return (3*b-2*g)/(2*(3*b+g))
def covers(alloy,Kapp,width,nu,dv,origin,origin_sign,assets,density,coords):
 p=density[alloy]; sig=float(p['sigma_eV'])*WIDTHS[width]; cb=.0026; eta=solve_eta(cb,sig,300)
 A0={r['alloy']:float(r['A0_A2']) for r in read(assets/'lattice_parameters_A0.csv')}[alloy]; a0=math.sqrt(A0*4/math.sqrt(3)); dx=a0*math.sqrt(6)/4
 vals=[]
 for r in coords[alloy]:
  xx=float(r['x_A'])+origin_sign*origin*dx; yy=float(r['y_A']); radius=math.hypot(xx,yy); th=math.atan2(yy,xx)
  if radius<1e-12:raise AssertionError('singular registered origin')
  pressure=2*(1+nu)/3*Kapp/math.sqrt(2*math.pi*radius*1e-10)*math.cos(th/2)
  shift=pressure*dv*6.241509074e-6
  vals.append(float(np.dot(W,occ(sig*X-shift,eta,300))))
 cc=sum(vals[:9])/9;ce=sum(vals[9:])/3;return vals,cc,ce,min(1,1.5*cc)
def verify(app,tests,final):
 refs=preflight(app,tests)
 check_calculation_evidence(final,app)
 for rel,h in refs['asset_hashes'].items():
  p=app/rel
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('public asset invalid: '+rel)
 for rel,h in refs['grader_reference_hashes'].items():
  p=tests/rel.removeprefix('tests/')
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('grading reference invalid: '+rel)
 density={r['alloy']:r for r in read(app/'assets/absorption_distribution_fig2a.csv')}; elastic={r['alloy']:r for r in read(app/'assets/elastic_constants_fig2a.csv')}; A0={r['alloy']:float(r['A0_A2']) for r in read(app/'assets/lattice_parameters_A0.csv')}
 gamma={}
 for r in read(app/'assets/gamma_f_fig2b_digitized.csv'):gamma.setdefault(r['alloy'],[]).append(r)
 coords={}
 for r in read(app/'assets/task11_crack_site_coordinates.csv'):coords.setdefault(r['alloy'],[]).append(r)
 for a in coords:coords[a].sort(key=lambda r:parse_exact_integral_csv(r['site_column'],'site_column'))
 if len(density)!=6 or set(density)!=set(A0) or any(len(coords.get(a,[]))!=12 for a in density):raise RuntimeError('public model sources incomplete')
 occrows=read(final/'occupation.csv'); therm=read(final/'fracture_free_energy.csv'); model=json.loads((final/'thermodynamic_model.json').read_text()); checks=json.loads((final/'limiting_checks.json').read_text()); mechanism=(final/'mechanism.md').read_text()
 if not isinstance(model,dict) or not isinstance(checks,dict):raise AssertionError('thermodynamic_model.json and limiting_checks.json must be JSON objects')
 if not isinstance(model.get('sensitivity_summary'),dict) or not isinstance(model['sensitivity_summary'].get('one_at_a_time_model_sensitivity'),list):raise AssertionError('sensitivity_summary must contain one_at_a_time_model_sensitivity array')
 if not isinstance(checks.get('gamma_S_endpoint_checks'),dict):raise AssertionError('limiting_checks endpoint map must be a JSON object')
 bounds=occupancy_bounds_interval(checks.get('site_occupancy_bounds'))
 if len(occrows)!=2808 or len(therm)!=234:raise AssertionError('expected exactly 2808 site rows and 234 thermodynamic rows')
 oidx={(r['alloy'],parse_exact_integral_csv(r['T_K'],'T_K'),float(r['Cb_fraction']),float(r['Kapp_MPa_sqrt_m']),r['width_interpretation'],parse_exact_integral_csv(r['site_column'],'site_column')):r for r in occrows}
 fidx={(r['alloy'],parse_exact_integral_csv(r['T_K'],'T_K'),float(r['Cb_fraction']),float(r['Kapp_MPa_sqrt_m']),r['width_interpretation']):r for r in therm}
 if len(oidx)!=2808 or len(fidx)!=234:raise AssertionError('duplicate output keys')
 condition_labels={}
 for row in occrows+therm:
  label=row['condition'];physical=(parse_exact_integral_csv(row['T_K'],'T_K'),float(row['Cb_fraction']))
  if not isinstance(label,str) or not label.strip() or label in condition_labels and condition_labels[label]!=physical:raise AssertionError('condition labels must consistently identify a physical concentration/temperature pair')
  condition_labels[label]=physical
 if len(condition_labels)!=4 or set(condition_labels.values())!={(300,.0026),(300,.0058),(300,.004),(400,.004)}:raise AssertionError('condition labels do not cover the four specified physical conditions')
 maxres=0.; maxshift=0.
 for cond,selected,cb,T in CONDS:
  for alloy in sorted(density) if selected=='ALL' else selected:
   p=density[alloy]; er=elastic[alloy]; nu=hill(float(er['C11_GPa']),float(er['C12_GPa']),float(er['C44_GPa'])); gamma_refs=sorted(gamma[alloy],key=lambda r:float(r['C_surface']))
   if len(gamma_refs)!=3:raise RuntimeError('source gammaF anchor set incomplete')
   ge={}; gl={}; gh={}
   a0=math.sqrt(A0[alloy]*4/math.sqrt(3))
   for x in gamma_refs:
    cs=float(x['C_surface']); gs=gamma_s(cs,.0058,300,a0)
    ge[cs]=float(x['gamma_F_mean_J_m2'])-gs;gl[cs]=float(x['gamma_F_low_J_m2'])-gs;gh[cs]=float(x['gamma_F_high_J_m2'])-gs
   for width,factor in WIDTHS.items():
    sw=float(p['sigma_eV'])*factor; eta=solve_eta(cb,sw,T); bulk=float(np.dot(W,occ(sw*X,eta,T)));maxres=max(maxres,abs(bulk-cb))
    shifted=solve_eta(cb,sw,T,.731);maxshift=max(maxshift,abs((shifted-.731)-eta))
    for k in range(13):
     Kapp=k/10; cis=[]
     for cr in coords[alloy]:
      x=float(cr['x_A']);y=float(cr['y_A']);rad=math.hypot(x,y);th=math.atan2(y,x);pressure=2*(1+nu)/3*Kapp/math.sqrt(2*math.pi*rad*1e-10)*math.cos(th/2);shift=pressure*2.8*6.241509074e-6
      cis.append(float(np.dot(W,occ(sw*X-shift,eta,T))))
     cc=sum(cis[:9])/9;ce=sum(cis[9:])/3;cs=min(1,1.5*cc);gs=gamma_s(cs,cb,T,a0)
     vals={'gamma_E_J_m2':interp(cs,[(x,ge[x]) for x in ge]),'gamma_E_low_J_m2':interp(cs,[(x,gl[x]) for x in gl]),'gamma_E_high_J_m2':interp(cs,[(x,gh[x]) for x in gh])}
     f=fidx[(alloy,T,cb,Kapp,width)]
     for key,value in [('eta_eV_mu_minus_Ebar_minus_EZP',eta),('Cb_recomputed',bulk),('C_cleave',cc),('C_emit',ce),('C_S',cs),('nu_hill',nu),('DeltaV_A3',2.8),('A0_A2',A0[alloy]),('gamma_S_J_m2',gs),('gamma_F_J_m2',vals['gamma_E_J_m2']+gs),('gamma_F_low_J_m2',vals['gamma_E_low_J_m2']+gs),('gamma_F_high_J_m2',vals['gamma_E_high_J_m2']+gs),*vals.items()]:
      if not close(f[key],value):raise AssertionError(f'{key} independent mismatch: {cond}/{alloy}/{Kapp}/{width}')
     for i,ci in enumerate(cis,1):
      o=oidx[(alloy,T,cb,Kapp,width,i)]
      if not close(o['c_i'],ci) or not close(o['C_cleave'],cc) or not close(o['C_emit'],ce) or not close(o['C_S'],cs) or not close(o['eta_eV_mu_minus_Ebar_minus_EZP'],eta):raise AssertionError('column occupation/weight formula mismatch')
 # The CSV domain/cardinality, physical pressure/elastic model and actual source
 # bytes are already independently checked. Do not require duplicate prose strings.
 if model.get('width_interpretations')!=WIDTHS or not close(model.get('DeltaV_A3',float('nan')),2.8,1e-12):raise AssertionError('density widths or relaxation volume declaration mismatch')
 if not conditional_reference_valid(model.get('gamma_E_condition')):raise AssertionError('conditional gammaE reference or image interval not declared')
 sensitivity=model.get('sensitivity_summary',{}).get('one_at_a_time_model_sensitivity',[])
 if any(not isinstance(x,dict) for x in sensitivity):raise AssertionError('sensitivity entries must be JSON objects')
 skeys={(x.get('width'),float(x.get('Kapp')),x.get('variant')):x for x in sensitivity}
 if len(skeys)!=28 or len(sensitivity)!=28:raise AssertionError('sensitivity key domain incomplete or duplicated')
 origin_sign_matches={-1:True,1:True}
 for width in WIDTHS:
  for k in (.6,.8):
   for variant in ('baseline','nu_Voigt','nu_Reuss','DeltaV_2.7','DeltaV_2.9','origin_-0.1','origin_0.1'):
    row=skeys.get((width,k,variant))
    if row is None:raise AssertionError('missing sensitivity '+str((width,k,variant)))
    params=row['parameters']; nu=hill(float(elastic['SS304']['C11_GPa']),float(elastic['SS304']['C12_GPa']),float(elastic['SS304']['C44_GPa']))
    if variant.startswith('nu_'):
     c11=float(elastic['SS304']['C11_GPa']);c12=float(elastic['SS304']['C12_GPa']);c44=float(elastic['SS304']['C44_GPa']);bulk=(c11+2*c12)/3;g=((c11-c12+3*c44)/5 if variant.endswith('Voigt') else 5*(c11-c12)*c44/(4*c44+3*(c11-c12)));nu=(3*bulk-2*g)/(2*(3*bulk+g))
    dv=float(params['DeltaV_A3']);origin=float(params['origin_delta_over_dx'])
    expected_dv={'DeltaV_2.7':2.7,'DeltaV_2.9':2.9}.get(variant,2.8)
    expected_origin={'origin_-0.1':-.1,'origin_0.1':.1}.get(variant,0.)
    if not close(dv,expected_dv,1e-12) or not close(origin,expected_origin,1e-12):raise AssertionError('sensitivity parameters do not match the declared perturbation: '+variant)
    row_origin_sign_matches={}
    for sign in origin_sign_matches:
     _,cc,ce,cs=covers('SS304',k,width,nu,dv,origin,sign,app/'assets',density,coords)
     row_origin_sign_matches[sign]=close(row['coverages']['C_cleave'],cc) and close(row['coverages']['C_emit'],ce) and close(row['coverages']['C_S'],cs)
    if not any(row_origin_sign_matches.values()):raise AssertionError('numeric sensitivity recomputation mismatch')
    for sign in origin_sign_matches:
     if not row_origin_sign_matches[sign]:origin_sign_matches[sign]=False
 matching_origin_signs=[sign for sign,matches in origin_sign_matches.items() if matches]
 if len(matching_origin_signs)!=1:raise AssertionError('all sensitivity rows must use one globally consistent origin sign convention')
 origin_sign_mode='coordinate_shift' if matching_origin_signs[0]==1 else 'origin_displacement'
 if maxres>2e-10 or not math.isfinite(float(checks['maximum_bulk_concentration_residual'])) or abs(float(checks['maximum_bulk_concentration_residual'])-maxres)>2e-10 or maxshift>1e-9 or not math.isfinite(float(checks['maximum_common_reference_shift_eta_residual_eV'])) or abs(float(checks['maximum_common_reference_shift_eta_residual_eV'])-maxshift)>1e-9:raise AssertionError('bulk/reference-shift closure exceeds numerical bound')
 if not(0<=float(bounds[0])<=float(bounds[1])<=1):raise AssertionError('site occupancy outside [0,1]')
 if isinstance(checks['site_occupancy_bounds'],dict):
  declaration=checks['site_occupancy_bounds'];actual_values=[float(r['c_i']) for r in occrows]
  if not close(bounds[0],min(actual_values)) or not close(bounds[1],max(actual_values)):raise AssertionError('declared occupancy extrema disagree with the computed site rows')
  if 'all_within_unit_interval' in declaration and declaration['all_within_unit_interval'] is not True:raise AssertionError('occupancy-bound declaration contradicts the site rows')
  if 'values_checked' in declaration and declaration['values_checked']!=len(occrows):raise AssertionError('occupancy count declaration mismatch')
  if 'values_out_of_bounds' in declaration and declaration['values_out_of_bounds']!=0:raise AssertionError('occupancy bound violation declaration mismatch')
 for alloy in density:
  area=A0[alloy]; a0=math.sqrt(area*4/math.sqrt(3)); want=KB*300/(math.sqrt(3)*a0*a0/4)*(-math.log(.0058))*EV_A2
  ends=checks['gamma_S_endpoint_checks'][alloy]
  if abs(float(ends['gamma_S_cs0_J_m2']))>1e-12 or not close(ends['gamma_S_cs1_J_m2'],want):raise AssertionError('entropy 0ln0 endpoint formula mismatch')
 if not mechanism.strip() or not model.get('conditional_assumptions') or len(model['conditional_assumptions'])<3:raise AssertionError('conditional scientific boundary documentation missing')
 return {'status':'PASS','reward':1,'occupation_rows':len(occrows),'thermodynamic_rows':len(therm),'independent_quadrature_order':512,'max_bulk_residual':maxres,'max_shift_residual':maxshift,'origin_sign_mode':origin_sign_mode}
def main():
 p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--tests-dir',type=Path,required=True);p.add_argument('--final-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 try:r=verify(a.app_dir,a.tests_dir,a.final_dir);c=0
 except RuntimeError as e:r={'status':'ENV_INVALID','reward':None,'reason':str(e)};c=2
 except (AssertionError,KeyError,ValueError,TypeError,OSError,json.JSONDecodeError) as e:
  msg=str(e).strip(); r={'status':'FAIL','reward':0,'reason':(f'{type(e).__name__}: {msg}' if msg else f'{type(e).__name__}: candidate output failed a typed scientific/format check')};c=1
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));raise SystemExit(c)
if __name__=='__main__':main()
