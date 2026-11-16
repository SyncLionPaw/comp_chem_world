#!/bin/bash
set -euo pipefail
# Oracle entrypoint: reference solve by real computation, no hardcoded answers.
export APP="${APP:-/app}" IR_PACKAGE_ROOT="${APP:-/app}"
mkdir -p "$APP/final"
python3 - "$APP/final" <<'PY'
import os, csv,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.interpolate import interp1d
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
def norm(s):return np.clip((s/np.maximum(np.max(s,axis=1,keepdims=True),1e-12)*99).astype(np.int16),0,99).astype(np.float32)
def transforms(x,ids,axis):
 x=np.asarray(x,dtype=np.float32);out={'clean':norm(x)}; orig=np.arange(400,3982,2);short=np.arange(400,3982,4); phase1=x[:,::2];phase2=np.concatenate([x[:,1::2],x[:,-1:][:,0:1]],axis=1)
 def interp(a,ox):return norm(np.stack([interp1d(ox,row)(axis) for row in a]))
 out['phase400']=interp(phase1,short);out['phase402']=interp(phase2,short)
 out['smooth075']=interp(np.stack([gaussian_filter1d(r,.75) for r in x]),orig);out['smooth125']=interp(np.stack([gaussian_filter1d(r,1.25) for r in x]),orig)
 sh=np.empty_like(x)
 for i,s in enumerate(ids):
  seed=int.from_bytes(hashlib.sha256(f'ir-local-frequency-scramble-v1|20261006|{s}'.encode()).digest()[:8],'little');sh[i]=x[i,np.random.default_rng(seed).permutation(x.shape[1])]
 out['frequency_scrambled']=norm(sh)
 return out
def main(outdir):
 out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
 tr=np.load(PKG/'assets/cohort-train.npz',allow_pickle=False);va=np.load(PKG/'assets/cohort-validation.npz',allow_pickle=False);te=np.load(PKG/'assets/cohort-blind-test.npz',allow_pickle=False);axis=np.load(PKG/'assets/axis-cm-1.npy',allow_pickle=False)
 names=list(map(str,tr['group_names']));xtr=norm(tr['spectra'].astype(np.float32));y=tr['group_labels'].astype(np.uint8);xt=norm(te['spectra'].astype(np.float32));tx=transforms(te['spectra'],te['sample_id'].astype(str),axis)
 sc=StandardScaler();a=sc.fit_transform(xtr).astype(np.float32);models=[]
 for j in range(len(names)):
  m=LogisticRegression(solver='liblinear',C=.1,max_iter=100,tol=1e-3,random_state=20261008+j);m.fit(a,y[:,j]);models.append(m)
 coef=np.stack([m.coef_[0] for m in models]).astype(np.float32);inter=np.array([m.intercept_[0] for m in models],dtype=np.float32)
 def pred(z):
  z=sc.transform(z).astype(np.float32);return np.column_stack([m.predict_proba(z)[:,1] for m in models]).astype(np.float32)
 probs={k:pred(v) for k,v in tx.items()};globalp=(y.sum(0)+1)/(len(y)+2);by={}
 for f in np.unique(tr['formula']):
  ix=tr['formula']==f;by[str(f)]=(y[ix].sum(0),int(ix.sum()))
 fp=np.stack([globalp if str(f) not in by else (by[str(f)][0]+1)/(by[str(f)][1]+2) for f in te['formula'].astype(str)])
 namesconds=['clean','formula_only','phase400','phase402','smooth075','smooth125','frequency_scrambled']; fields=['sample_id','condition_id',*names]
 with (out/'submission.csv').open('w',newline='',encoding='utf8') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for i,sid in enumerate(te['sample_id'].astype(str)):
   for cond in namesconds:
    p=fp[i] if cond=='formula_only' else probs[cond][i];w.writerow({'sample_id':sid,'condition_id':cond,**dict(zip(names,map(float,p)))})
 np.savez_compressed(out/'model.npz',coef=coef,intercept=inter,scaler_mean=sc.mean_.astype(np.float32),scaler_scale=sc.scale_.astype(np.float32))
 def ids_sha(a):return hashlib.sha256(('\n'.join(map(str,a))+'\n').encode()).hexdigest()
 input_hash={k:hashlib.sha256(v.astype(np.float32).tobytes()).hexdigest() for k,v in tx.items()};input_hash['formula_only']=hashlib.sha256(('\n'.join(f'{i}\t{f}' for i,f in zip(te['sample_id'].astype(str),te['formula'].astype(str)))+'\n').encode()).hexdigest()
 protocol={'model_family':'linear_ovr_logistic_v1','model_file':'model.npz','model_sha256':hashlib.sha256((out/'model.npz').read_bytes()).hexdigest(),'train_ids_sha256':ids_sha(tr['sample_id']),'validation_ids_sha256':ids_sha(va['sample_id']),'condition_input_sha256':input_hash,'normalization':'author norm_spectrum per row: intensity/max*99, truncate int, clip[0,99]; clean uses interpolate_spectrum onto frozen source axis; StandardScaler fit train only','training':'8 LogisticRegression(liblinear,C=.1,max_iter=100,tol=.001), seeds 20261008..20261015'}
 (out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
 print(json.dumps({'status':'reference-generated','conditions':namesconds,'rows':len(te['sample_id'])}))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '/tmp/case-03-reference')
PY
