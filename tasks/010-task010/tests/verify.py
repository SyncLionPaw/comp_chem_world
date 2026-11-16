#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Low-energy hydrogen occupation and finite-spectrum sampling.
"""Independent SciPy-quad closure, tail, and finite-IID protocol checks."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from statistics import NormalDist
from functools import lru_cache
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.integrate import quad
from scipy.optimize import brentq
KB=8.617333262145e-5; CBL=(1e-6,1e-5,1e-4,1e-3,2.6e-3,5.8e-3); QL=(.001,.01,.05); NL=(25,50,100)
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
@lru_cache(maxsize=None)
def gl_nodes(order):return leggauss(order)
def preflight(app,tests):
 try: refs=json.loads((tests/'refs.json').read_text(encoding='utf8'))
 except Exception as exc: raise RuntimeError(f'integrity failure: refs.json: {type(exc).__name__}') from exc
 if not isinstance(refs,dict) or refs.get('case_id')!='case-04':raise RuntimeError('integrity failure: refs.json case/schema')
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
def logistic(z):
 if z>700:return 0.
 if z < -700:return 1.
 return 1/(1+math.exp(z))
def integ(f,lo=-9,hi=9):return quad(f,lo,hi,epsabs=2e-13,epsrel=2e-11,limit=300)[0]
def eta_for(cb,sigma,T):return brentq(lambda eta:integ(lambda x:math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x-eta)/(KB*T)))-cb,-3,3,xtol=2e-14)
def eta_gl(cb,sigma,T,order):
 z,w=gl_nodes(order);x=9*z;ww=9*w*np.exp(-x*x)/math.sqrt(math.pi);lo,hi=-3.,3.
 for _ in range(100):
  mid=(lo+hi)/2;v=float(np.dot(ww,1/(1+np.exp(np.clip((sigma*x-mid)/(KB*T),-700,700)))))
  if v<cb:lo=mid
  else:hi=mid
 return (lo+hi)/2
def finite_mc(seed,sigma,T,cb,N):
 rng=np.random.default_rng(seed);xs=rng.normal(0.,1/math.sqrt(2.),(512,N));lo=np.full(512,-3.);hi=np.full(512,3.)
 for _ in range(64):
  mid=(lo+hi)/2;occ=1/(1+np.exp(np.clip((sigma*xs-mid[:,None])/(KB*T),-700,700)));below=occ.mean(axis=1)<cb;lo=np.where(below,mid,lo);hi=np.where(below,hi,mid)
 return xs,(lo+hi)/2
def verify(app,tests,final):
 preflight(app,tests)
 check_calculation_evidence(final,app,"absorption_distribution_fig2a.csv")
 refs=json.loads((tests/'refs.json').read_text())
 for rel,h in refs['asset_hashes'].items():
  p=app/rel
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('public input invalid: '+rel)
 for rel,h in refs['grader_reference_hashes'].items():
  p=tests/rel.removeprefix('tests/')
  if not p.is_file() or 'sha256:'+sha(p)!=h:raise RuntimeError('grading reference invalid: '+rel)
 src=read(app/'assets/absorption_distribution_fig2a.csv'); closure=read(final/'concentration_closure.csv'); tails=read(final/'tail_enrichment.csv'); finite=read(final/'finite_sampling.csv'); inf=json.loads((final/'inference.json').read_text())
 if not isinstance(inf,dict):raise AssertionError('inference.json must be a JSON object')
 if len(src)!=6 or len(closure)!=72 or len(tails)!=216 or len(finite)!=648:raise AssertionError('expected 6 alloys, 72 closures, 216 tails and 648 finite-IID rows')
 ci={(r['alloy'],int(r['T_K']),float(r['Cb_fraction'])):r for r in closure}; ti={(r['alloy'],int(r['T_K']),float(r['Cb_fraction']),float(r['q'])):r for r in tails}; fi={(r['alloy'],int(r['T_K']),float(r['Cb_fraction']),int(r['N']),float(r['q'])):r for r in finite}
 if len(ci)!=72 or len(ti)!=216 or len(fi)!=648:raise AssertionError('duplicate output keys or incomplete domains')
 for p in src:
  alloy=p['alloy']; sigma=float(p['sigma_eV']); ebar=float(p['Ebar_eV'])
  for T in (300,400):
   for cb in CBL:
    eta=eta_for(cb,sigma,T); pred=integ(lambda x:math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x-eta)/(KB*T))); r=ci[(alloy,T,cb)]
    if abs(float(r['eta_eV_mu_minus_Ebar'])-eta)>2e-8 or abs(pred-cb)>3e-10 or abs(float(r['bulk_integral'])-pred)>3e-10:raise AssertionError('independent quadrature bulk closure mismatch')
    if abs(float(r['residual'])-abs(pred-cb))>3e-10:raise AssertionError('closure residual field mismatch')
    q512,q1024=eta_gl(cb,sigma,T,512),eta_gl(cb,sigma,T,1024)
    if abs(float(r['quadrature_error'])-abs(q1024-q512))>3e-9:raise AssertionError('closure quadrature refinement field mismatch')
    # A common energy-reference translation moves Ebar and mu together; eta must not move.
    shifted=brentq(lambda m:integ(lambda x:math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x+.731-m)/(KB*T)))-cb,-3,4,xtol=2e-14)
    if abs((shifted-.731)-eta)>2e-9:raise AssertionError('common reference translation changed eta')
    for q in QL:
     xq=NormalDist().inv_cdf(q)/math.sqrt(2); tail=integ(lambda x:math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x-eta)/(KB*T)),hi=xq); tr=ti[(alloy,T,cb,q)]
     meanx=integ(lambda x:x*math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x-eta)/(KB*T)))/cb
     if abs(float(tr['E_q_eV'])-(ebar+sigma*xq))>2e-8 or abs(float(tr['occupation_below_Eq'])-tail)>3e-10 or abs(float(tr['occupied_fraction_below_Eq'])-tail/cb)>3e-8 or abs(float(tr['enrichment_ratio'])-tail/(cb*q))>3e-7 or abs(float(tr['mean_occupied_energy_eV'])-(ebar+sigma*meanx))>3e-8:raise AssertionError('independent lower-tail quadrature mismatch')
     tail512=quad(lambda x:math.exp(-x*x)/math.sqrt(math.pi)*logistic((sigma*x-eta)/(KB*T)),-9,xq,epsabs=2e-13,epsrel=2e-11,limit=300)[0]
     # 512-point quadrature over [−9,xq] is calculated independently to check the advertised refinement diagnostic.
     z,w=leggauss(512);half=(xq+9)/2;mid=(xq-9)/2;xx=half*z+mid; ww=half*w*np.exp(-xx*xx)/math.sqrt(math.pi)
     low512=float(np.dot(ww,1/(1+np.exp(np.clip((sigma*xx-eta)/(KB*T),-700,700)))))
     if abs(float(tr['tail_integral_quadrature_delta_512_1024'])-abs(tail-low512))>3e-9:raise AssertionError('tail quadrature refinement field mismatch')
    for N in NL:
     last=None
     samples=None; sample_eta=None
     seed_payload=f"175501|{alloy}|{T}|{cb:.12g}|{N}".encode(); wanted_seed=int.from_bytes(hashlib.sha256(seed_payload).digest()[:4],'big')
     for q in QL:
      r=fi[(alloy,T,cb,N,q)]
      if abs(float(r['exact_P_no_tail_sample'])-(1-q)**N)>1e-10 or int(r['replicates'])!=512 or int(r['seed'])!=wanted_seed:raise AssertionError('finite-IID no-tail probability, seed, or replicate count mismatch')
      if not str(r['seed']).isdigit() or 'hypothetical IID' not in r['simulation_label']:raise AssertionError('seed or finite-IID interpretation absent')
      bias=json.loads(r['eta_bias_interval_eV']); frac=json.loads(r['tail_occupied_fraction_sampling_interval'])
      if len(bias)!=3 or len(frac)!=3 or any(not math.isfinite(float(x)) for x in bias+frac) or bias!=sorted(bias) or frac!=sorted(frac) or min(frac)<0 or max(frac)>1:raise AssertionError('invalid finite-IID quantile interval')
      if samples is None:samples,sample_eta=finite_mc(wanted_seed,sigma,T,cb,N)
      if not np.allclose(bias,np.quantile(sample_eta-eta,[.05,.5,.95]),atol=2e-8,rtol=0):raise AssertionError('seeded Monte Carlo eta quantile mismatch')
      xq=NormalDist().inv_cdf(q)/math.sqrt(2); occs=1/(1+np.exp(np.clip((sigma*samples-sample_eta[:,None])/(KB*T),-700,700))); fraction=(occs*(samples<=xq)).sum(axis=1)/occs.sum(axis=1)
      if not np.allclose(frac,np.quantile(fraction,[.05,.5,.95]),atol=2e-8,rtol=0):raise AssertionError('seeded Monte Carlo tail fraction mismatch')
      halves=[np.quantile(sample_eta[:256]-eta,[.05,.5,.95]),np.quantile(sample_eta[256:]-eta,[.05,.5,.95])]
      expected_eta=float(np.max(np.abs(halves[0]-halves[1])))
      half_fracs=[]
      for xbatch,ebatch in ((samples[:256],sample_eta[:256]),(samples[256:],sample_eta[256:])):
       ob=1/(1+np.exp(np.clip((sigma*xbatch-ebatch[:,None])/(KB*T),-700,700))); fb=(ob*(xbatch<=xq)).sum(axis=1)/ob.sum(axis=1); half_fracs.append(np.quantile(fb,[.05,.5,.95]))
      expected_fraction=float(np.max(np.abs(half_fracs[0]-half_fracs[1])))
      if abs(float(r['half_batch_interval_endpoint_difference_eta_eV'])-expected_eta)>2e-8 or abs(float(r['half_batch_interval_endpoint_difference_tail_fraction'])-expected_fraction)>2e-8:raise AssertionError('half-batch precision diagnostic mismatch')
      if last and any(frac[i]<last[i]-1e-12 for i in range(3)):raise AssertionError('sample tail quantiles are not monotone in q')
      last=frac
 if inf.get('MC_replicates')!=512 or inf.get('N')!=[25,50,100] or inf.get('q')!=[.001,.01,.05] or not inf.get('quadrature') or not inf.get('MC_interval_interpretation'):raise AssertionError('finite-IID protocol or quadrature declaration mismatch')
 return {'status':'PASS','reward':1,'closures':72,'tails':216,'finite_iid_rows':648,'independent_method':'scipy.integrate.quad + brentq'}
def main():
 p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--tests-dir',type=Path,required=True);p.add_argument('--final-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 try:r=verify(a.app_dir,a.tests_dir,a.final_dir);c=0
 except RuntimeError as e:r={'status':'ENV_INVALID','reward':None,'reason':str(e)};c=2
 except (AssertionError,KeyError,ValueError,TypeError,OSError,json.JSONDecodeError) as e:r={'status':'FAIL','reward':0,'reason':f'{type(e).__name__}: {e}'};c=1
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));raise SystemExit(c)
if __name__=='__main__':main()
