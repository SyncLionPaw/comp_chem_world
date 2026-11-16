#!/bin/bash
set -euo pipefail
# Oracle entrypoint: reference solve by real computation, no hardcoded answers.
export APP="${APP:-/app}" IR_PACKAGE_ROOT="${APP:-/app}"
mkdir -p "$APP/final"
python3 - "$APP/final" <<'PY'
from __future__ import annotations
import os, csv,hashlib,json,sys,time
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
ROOT=Path(os.environ.get('IR_REFERENCE_ROOT', str(Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents)>3 else Path(__file__).resolve().parent)));PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
def row_shuffle(te):
 ids=te['sample_id'].astype(str);forms=te['formula'].astype(str);x=te['spectra'].astype(np.float32)
 from collections import defaultdict
 by=defaultdict(list)
 for i,f in enumerate(forms):by[f].append(i)
 out=x.copy();eligible=[]
 for f in sorted(by):
  ix=sorted(by[f],key=lambda i:ids[i]);n=len(ix)
  if n<2:continue
  eligible.extend(ix)
  seed=int.from_bytes(hashlib.sha256(f'ir-local-formula-row-shuffle-v1|20261005|{f}'.encode()).digest()[:8],'little')
  offset=int(np.random.default_rng(seed).integers(1,n))
  for j,i in enumerate(ix):out[i]=x[ix[(j+offset)%n]]
 return out,np.asarray(sorted(eligible),dtype=int)
def id_hash(ids):return hashlib.sha256(('\n'.join(map(str,ids))+'\n').encode()).hexdigest()
def fsha(x):return hashlib.sha256(np.asarray(x).tobytes(order='C')).hexdigest()
def main(outdir):
 out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
 train=np.load(PKG/'assets/cohort-train.npz',allow_pickle=False);val=np.load(PKG/'assets/cohort-validation.npz',allow_pickle=False);test=np.load(PKG/'assets/cohort-blind-test.npz',allow_pickle=False);axis=np.load(PKG/'assets/axis-cm-1.npy',allow_pickle=False)
 names=list(map(str,train['group_names']));y=train['group_labels'].astype(np.uint8)
 xtr=train['spectra'].astype(np.float32);xte=test['spectra'].astype(np.float32)
 # Simple declared per-row max-absolute normalization; scaler learns only on train.
 xtr=xtr/np.maximum(np.max(np.abs(xtr),axis=1,keepdims=True),1e-12)
 xte=xte/np.maximum(np.max(np.abs(xte),axis=1,keepdims=True),1e-12)
 scaler=StandardScaler();a=scaler.fit_transform(xtr).astype(np.float32);b=scaler.transform(xte).astype(np.float32)
 p=np.empty((len(xte),len(names)),dtype=np.float32);models=[]
 for j in range(len(names)):
  m=LogisticRegression(solver='liblinear',C=.1,max_iter=100,tol=1e-3,random_state=20261008+j)
  m.fit(a,y[:,j]);p[:,j]=m.predict_proba(b)[:,1];models.append(m)
 # Smoothed exact-formula prevalence; unseen formulas fall back to global train prevalence.
 global_p=(y.sum(axis=0)+1)/(len(y)+2);by={}
 for f in np.unique(train['formula']):
  ix=np.asarray(train['formula']==f);by[str(f)]=(y[ix].sum(axis=0),int(ix.sum()))
 fp=np.empty_like(p)
 for i,f in enumerate(test['formula'].astype(str)):
  z=by.get(f)
  fp[i]=global_p if z is None else (z[0]+1)/(z[1]+2)
 shuffled,eligible=row_shuffle(test);sp=scaler.transform(shuffled/np.maximum(np.max(np.abs(shuffled),axis=1,keepdims=True),1e-12)).astype(np.float32)
 ps=np.empty((len(shuffled),len(names)),dtype=np.float32)
 for j,m in enumerate(models):ps[:,j]=m.predict_proba(sp)[:,1]
 fields=['sample_id','condition_id',*names]
 with (out/'submission.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  ids=test['sample_id'].astype(str)
  for i,sid in enumerate(ids):
   w.writerow({'sample_id':sid,'condition_id':'full_spectrum',**dict(zip(names,map(float,p[i])))})
  for i in eligible:w.writerow({'sample_id':ids[i],'condition_id':'within_formula_spectrum_shuffle',**dict(zip(names,map(float,ps[i])))})
 row_matrix,eligible=row_shuffle(test)
 np.savez_compressed(out/'model.npz',coef=np.stack([m.coef_[0] for m in models]).astype(np.float32),intercept=np.array([m.intercept_[0] for m in models],dtype=np.float32),scaler_mean=scaler.mean_.astype(np.float32),scaler_scale=scaler.scale_.astype(np.float32))
 formula_payload=('\n'.join(f'{i}\t{f}' for i,f in zip(ids,test['formula'].astype(str)))+'\n').encode()
 prot={'model':'8 one-vs-rest LogisticRegression(solver=liblinear,C=0.1,max_iter=100,tol=1e-3)','model_file':'model.npz','model_sha256':hashlib.sha256((out/'model.npz').read_bytes()).hexdigest(),'seed_start':20261008,'normalization':'per-sample divide by max absolute intensity; StandardScaler fit on train only','train_ids_sha256':id_hash(train['sample_id']),'validation_ids_sha256':id_hash(val['sample_id']),'condition_input_sha256':{'full_spectrum':fsha(test['spectra'].astype(np.float32)),'within_formula_spectrum_shuffle':fsha(row_matrix)},'row_shuffle_seed':20261005,'row_shuffle_eligible_rows':len(eligible),'threshold':'0.5 only for optional label summaries; main AP metrics threshold-free'}
 (out/'protocol.json').write_text(json.dumps(prot,indent=2)+'\n',encoding='utf-8')
 bands={'selection_source':'train_only; independent validation confirmation','selection_method':'top five absolute train-only standardized logistic coefficients; each is reported as a narrow +/-2 cm-1 local interval; direction follows coefficient sign','classes':{}}
 val_norm=val['spectra'].astype(np.float32);val_norm=val_norm/np.maximum(np.max(np.abs(val_norm),axis=1,keepdims=True),1e-12);vy=val['group_labels'].astype(np.uint8);vforms=val['formula'].astype(str)
 for j,name in enumerate(names):
  coef=models[j].coef_[0];inds=np.argsort(np.abs(coef))[::-1]
  chosen=[]
  for k in inds:
   if k<1 or k>=len(axis)-1:continue
   bandmask=(axis>=axis[k-1])&(axis<=axis[k+1]);feat=val_norm[:,bandmask].mean(axis=1);pos=vy[:,j].astype(bool);obs=float(feat[pos].mean()-feat[~pos].mean())
   byf={}
   for ii,ff in enumerate(vforms):byf.setdefault(str(ff),[]).append(ii)
   gnames=list(byf);ds=[];lo=float(axis[k-1]);hi=float(axis[k+1]);seed=int.from_bytes(hashlib.sha256(f'ir-local01-band-bootstrap-v1|20261104|{name}|{lo:.1f}|{hi:.1f}'.encode()).digest()[:8],'little');vrng=np.random.default_rng(seed)
   for _ in range(500):
    sampled=vrng.choice(gnames,size=len(gnames),replace=True);ix=np.concatenate([np.asarray(byf[g]) for g in sampled]);yy=pos[ix];vv=feat[ix]
    if yy.any() and (~yy).any():ds.append(float(vv[yy].mean()-vv[~yy].mean()))
   ci=np.quantile(ds,[.025,.975]).tolist() if ds else [None,None]
   chosen.append({'range_cm1':[lo,hi],'direction':'higher_in_positive' if coef[k]>0 else 'lower_in_positive','coefficient_abs':float(abs(coef[k])),'validation_mean_difference':obs,'validation_ci95':ci})
   if len(chosen)==5:break
  bands['classes'][name]=chosen
 (out/'band_evidence.json').write_text(json.dumps(bands,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'status':'reference-generated','rows':len(test['sample_id']),'eligible_shuffle_rows':len(eligible),'output':str(out)}))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '/tmp/case-01-reference')
PY
