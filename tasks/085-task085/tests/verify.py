#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including submission.csv, model.npz).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Prediction Stability Under Controlled Simulated Spectrum Perturbations.
"""Terminal-state verification for task 86.

Single-file verifier: it checks the declared inputs and the hidden reference,
recomputes the published metrics from the submission and writes
verification.json. The task contract is unchanged.
"""
import hashlib, json, os, sys
from pathlib import Path

app = Path(os.environ['APP']); tests = Path(os.environ['TESTS']); logs = Path(os.environ['LOGS'])
# Resolve the scorer's roots before its module constants are evaluated.
os.environ['IR_PACKAGE_ROOT'] = str(app)
os.environ['IR_REFERENCE_ROOT'] = str(tests)

INPUT_HASHES = {'SOURCES.yaml': 'b757de684147c56efe1aa0b9fe4239afff37730881c6a2f0efc6d153be2396a5', 'axis-cm-1.npy': '772e01ff5c4e632c725c3e70220c865246f42f7576febfd360e4f63242bfcfcd', 'cohort-blind-test.npz': '97d8efce7e2cba35ee9ca2d67a6a2c3fe50c8a0bd7745c3bed01905de6874c96', 'cohort-train.npz': '1d6c93b082427d6895da6f1cd72ecfe0a04b775b05550ab1495926f03e0ef77a', 'cohort-validation.npz': 'a454592acac8be98e74142e353e6fb70498fcf858faafd0a234ae07d1d7ca2e7'}
REFERENCE_SHA256 = "b4877db2dd4670686a0398420c684d3923b53e4b0fe2676b09a5ec369404671f"

import os, csv, hashlib, json, math
from pathlib import Path
import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from sklearn.metrics import average_precision_score
GROUP_SMARTS={
 'alcohol':'[OX2H][CX4;!$(C([OX2H])[O,S,#7,#15])]',
 'carboxylic_acid':'[CX3](=O)[OX2H1]',
 'ester':'[#6][CX3](=O)[OX2H0][#6]',
 'ketone':'[#6][CX3](=O)[#6]',
 'alkene':'[CX3]=[CX3]',
 'alkyne':'[$([CX2]#C)]',
 'benzene':'c1ccccc1',
 'cyano':'[NX1]#[CX2]'}
PATTERNS={k:Chem.MolFromSmarts(v) for k,v in GROUP_SMARTS.items()}
class InfrastructureError(Exception): pass
class SubmissionError(Exception): pass
def file_sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def load_npz(path:Path)->dict:
 if not path.is_file() or path.stat().st_size==0:raise InfrastructureError(f'missing or empty input: {path.name}')
 try:
  with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in z.files}
 except Exception as e:raise InfrastructureError(f'cannot load {path.name}: {e}')
def load_hidden(root:Path)->dict:
 p=root/'refs.json'
 if not p.is_file() or p.stat().st_size==0:raise InfrastructureError('evaluator reference is missing: refs.json')
 try:
  doc=json.loads(p.read_text(encoding='utf-8'))
 except Exception as e:raise InfrastructureError(f'cannot parse hidden references: {e}')
 rows=doc.get('samples')
 if not isinstance(rows,dict) or not rows:raise InfrastructureError('refs.json must carry a non-empty samples object')
 return rows
def labels_from_smiles(smiles):
 mol=Chem.MolFromSmiles(str(smiles))
 if mol is None:raise InfrastructureError('invalid hidden canonical SMILES')
 return np.asarray([int(mol.HasSubstructMatch(PATTERNS[k])) for k in GROUP_SMARTS],dtype=np.uint8)
def validate_public_schema(npz, blind=False):
 required={'sample_id','formula','spectra'}
 if not required.issubset(npz):raise InfrastructureError('NPZ is missing base fields')
 if blind:
  if set(npz)!={'sample_id','formula','spectra'}:raise InfrastructureError('blind NPZ contains forbidden labels/structures')
 else:
  if not {'smiles','group_labels','group_names'}.issubset(npz):raise InfrastructureError('train/validation NPZ missing labels/SMILES')
 ids=npz['sample_id'];forms=npz['formula'];x=npz['spectra']
 if ids.ndim!=1 or forms.shape!=ids.shape or x.shape!=(len(ids),1791):raise InfrastructureError('NPZ array dimensions differ from frozen schema')
 if len(set(map(str,ids)))!=len(ids):raise InfrastructureError('duplicate sample IDs')
 if not np.isfinite(x).all():raise InfrastructureError('non-finite spectrum values')
 if blind is False:
  y=npz['group_labels'];names=list(map(str,npz['group_names']))
  if y.shape!=(len(ids),8) or y.dtype.kind not in 'ui' or names!=list(GROUP_SMARTS):raise InfrastructureError('label dimensions/order mismatch')
  if not np.isin(y,[0,1]).all():raise InfrastructureError('invalid group labels')
 return ids,forms,x
def validate_hidden_rows(npz, hidden):
 ids,forms,x=validate_public_schema(npz,blind=True)
 test=[]
 for i,(sid,formula) in enumerate(zip(ids,forms)):
  sid=str(sid);formula=str(formula)
  if sid not in hidden:raise InfrastructureError('blind ID is missing from the hidden evaluation map')
  r=hidden[sid]
  if r.get('split')!='blind-test' or r.get('formula')!=formula:raise InfrastructureError('blind ID/split/formula mismatch')
  y=labels_from_smiles(r.get('canonical_smiles',''))
  try:recorded=json.loads(r.get('group_labels_json','{}'))
  except Exception as e:raise InfrastructureError('cannot parse hidden label record') from e
  if isinstance(recorded,dict):recorded=np.asarray([int(recorded[k]) for k in GROUP_SMARTS],dtype=np.uint8)
  else:recorded=np.asarray(recorded,dtype=np.uint8)
  if not np.array_equal(y,recorded):raise InfrastructureError('hidden group labels disagree with independent SMARTS recalculation')
  test.append((i,sid,formula,y))
 return test

def validate_sources(package:Path):
 manifest=package/'assets/SOURCES.yaml'
 if not manifest.is_file():raise InfrastructureError('missing inputs/SOURCES.yaml')
 try:
  import yaml
  doc=yaml.safe_load(manifest.read_text(encoding='utf-8'))
  entries=doc['files']
 except Exception as e:raise InfrastructureError(f'invalid SOURCES.yaml: {e}') from e
 for ent in entries:
  p=package/ent['path']
  if not p.is_file():raise InfrastructureError(f'missing package input: {ent["path"]}')
  if file_sha(p)!=ent['sha256']:raise InfrastructureError(f'package input hash mismatch: {ent["path"]}')

def macro_ap(y,p):
 values=[]
 for j in range(y.shape[1]):
  if len(np.unique(y[:,j]))<2:continue
  values.append(float(average_precision_score(y[:,j],p[:,j])))
 return float(np.mean(values)) if values else float('nan')
def cluster_bootstrap_delta(y,a,b,clusters,seed=20261101,n_boot=1000):
 # Resample independent clusters with replacement and retain all rows within each selected cluster.
 groups={}
 for i,g in enumerate(clusters):groups.setdefault(str(g),[]).append(i)
 names=np.asarray(list(groups));rng=np.random.default_rng(seed);d=[]
 if len(names)<2:return {'estimate':macro_ap(y,a)-macro_ap(y,b),'ci95':[None,None],'clusters':len(names),'bootstraps':0}
 for _ in range(n_boot):
  sampled=rng.choice(names,size=len(names),replace=True)
  ix=np.concatenate([np.asarray(groups[g]) for g in sampled])
  if len(np.unique(y[ix],axis=0))==0:continue
  d.append(macro_ap(y[ix],a[ix])-macro_ap(y[ix],b[ix]))
 est=macro_ap(y,a)-macro_ap(y,b)
 ci=np.quantile(d,[0.025,0.975]).tolist() if d else [None,None]
 return {'estimate':float(est),'ci95':[float(ci[0]),float(ci[1])],'clusters':len(names),'bootstraps':len(d)}
def canonical_json(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

import os, csv,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.interpolate import interp1d
from scipy.special import expit
ROOT=Path(os.environ.get('IR_REFERENCE_ROOT', str(Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents)>3 else Path(__file__).resolve().parent)));PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
CONDS=('clean','formula_only','phase400','phase402','smooth075','smooth125','frequency_scrambled')
def fail(s):raise SubmissionError(s)
def norm(x):return np.clip((x/np.maximum(np.max(x,axis=1,keepdims=True),1e-12)*99).astype(np.int16),0,99).astype(np.float32)
def scramble(x,ids):
 o=np.empty_like(x)
 for i,s in enumerate(ids):
  seed=int.from_bytes(hashlib.sha256(f'ir-local-frequency-scramble-v1|20261006|{s}'.encode()).digest()[:8],'little');o[i]=x[i,np.random.default_rng(seed).permutation(x.shape[1])]
 return o
def make_inputs(raw,ids,axis):
 raw=np.asarray(raw,dtype=np.float32);orig=np.arange(400,3982,2);short=np.arange(400,3982,4)
 def itp(a,ox):return norm(np.stack([interp1d(ox,r)(axis) for r in a]))
 set1=raw[:,::2];set2=np.concatenate([raw[:,1::2],raw[:,-1:]],axis=1)
 return {'clean':norm(raw),'phase400':itp(set1,short),'phase402':itp(set2,short),'smooth075':itp(np.stack([gaussian_filter1d(r,.75) for r in raw]),orig),'smooth125':itp(np.stack([gaussian_filter1d(r,1.25) for r in raw]),orig),'frequency_scrambled':norm(scramble(raw,ids))}
def read_csv(path,names,ids):
 if not path.is_file() or not path.stat().st_size:fail('missing submission.csv')
 out={}
 try:
  with path.open(newline='',encoding='utf8') as f:
   for r in csv.DictReader(f):
    k=(r['sample_id'],r['condition_id'])
    if k in out or k[0] not in set(ids) or k[1] not in CONDS:fail('duplicate/unknown prediction key')
    p=np.asarray([float(r[g]) for g in names])
    if not np.isfinite(p).all() or np.any((p<0)|(p>1)):fail('probabilities must be finite in [0,1]')
    out[k]=p
 except SubmissionError:raise
 except Exception as e:fail('malformed submission.csv: '+str(e))
 if set(out)!={(str(s),c) for s in ids for c in CONDS}:fail('predictions must cover all samples and conditions')
 return out
def run(outdir):
 out=Path(outdir)
 for f in ('cohort-train.npz','cohort-validation.npz','cohort-blind-test.npz','axis-cm-1.npy'):
  if not (PKG/'assets'/f).is_file():raise InfrastructureError('missing package input: '+f)
 validate_sources(PKG);tr=load_npz(PKG/'assets/cohort-train.npz');va=load_npz(PKG/'assets/cohort-validation.npz');te=load_npz(PKG/'assets/cohort-blind-test.npz')
 tri,_,_=validate_public_schema(tr);vai,_,_=validate_public_schema(va);ids,forms,raw=validate_public_schema(te,blind=True);names=list(map(str,tr['group_names']))
 axis=np.load(PKG/'assets/axis-cm-1.npy',allow_pickle=False)
 if not np.array_equal(axis,np.arange(400,3982,2,dtype=axis.dtype)):raise InfrastructureError('axis mismatch')
 hidden=load_hidden(ROOT);records=validate_hidden_rows(te,hidden);ys=np.stack([z[3] for z in records]);formulas=np.asarray([z[2] for z in records])
 if not np.array_equal(np.asarray([z[1] for z in records]),ids.astype(str)):raise InfrastructureError('hidden/public IDs mismatch')
 model=out/'model.npz'
 if not model.is_file() or model.stat().st_size==0:fail('missing safe model.npz')
 try:m=np.load(model,allow_pickle=False);coef=m['coef'];inter=m['intercept'];mean=m['scaler_mean'];scale=m['scaler_scale']
 except Exception as e:fail('invalid safe model archive: '+str(e))
 if coef.shape!=(len(names),len(axis)) or inter.shape!=(len(names),) or mean.shape!=(len(axis),) or scale.shape!=(len(axis),) or not all(np.isfinite(z).all() for z in (coef,inter,mean,scale)) or np.any(scale<=0):fail('linear model arrays have invalid shape/value')
 arrays=make_inputs(raw,ids.astype(str),axis)
 # Formula-only is a scorer-owned fixed training baseline; it cannot be degraded in submission.
 yt=tr['group_labels'].astype(np.float64);glob=(yt.sum(0)+1)/(len(yt)+2);by={}
 for f in np.unique(tr['formula']):
  ix=tr['formula']==f;by[str(f)]=(yt[ix].sum(0),int(ix.sum()))
 fp=np.stack([glob if str(f) not in by else (by[str(f)][0]+1)/(by[str(f)][1]+2) for f in forms])
 rawpred={k:expit(((v-mean)/scale)@coef.T+inter).astype(np.float32) for k,v in arrays.items()}
 rawpred['formula_only']=fp.astype(np.float32)
 got=read_csv(out/'submission.csv',names,ids.astype(str))
 for cond in ('clean','phase400','phase402','smooth075','smooth125','frequency_scrambled'):
  actual=np.stack([got[(str(s),cond)] for s in ids])
  if not np.allclose(actual,rawpred[cond],rtol=1e-4,atol=2e-5):fail(f'{cond} probabilities do not come from the single submitted model on frozen transformed input')
 formula_sub=np.stack([got[(str(s),'formula_only')] for s in ids])
 if not np.allclose(formula_sub,fp,rtol=1e-5,atol=1e-6):fail('formula_only must equal scorer-owned train-only formula prevalence baseline')
 ap={k:macro_ap(ys,v) for k,v in rawpred.items()};ap['formula_only']=macro_ap(ys,fp)
 # Paired group bootstrap: condition-level AP is recomputed after sampling whole molecule rows.
 rng=np.random.default_rng(20261113);boot={k:[] for k in rawpred};paired={k:[] for k in rawpred if k!='clean'};flipboot={k:[] for k in rawpred if k!='clean'}
 for _ in range(300):
  ix=rng.integers(0,len(ys),len(ys))
  apclean=macro_ap(ys[ix],rawpred['clean'][ix])
  for k,v in rawpred.items():boot[k].append(macro_ap(ys[ix],v[ix]))
  for k,v in rawpred.items():
   if k!='clean':
    paired[k].append(macro_ap(ys[ix],v[ix])-apclean)
    flipboot[k].append(float((((rawpred['clean'][ix]>=.5)!=(v[ix]>=.5)).mean(axis=1)).mean()))
 ci={k:np.quantile(v,[.025,.975]).tolist() for k,v in boot.items()};delta_ci={k:np.quantile(v,[.025,.975]).tolist() for k,v in paired.items()};flip_ci={k:np.quantile(v,[.025,.975]).tolist() for k,v in flipboot.items()}
 stability={}
 base=rawpred['clean']
 for k,v in rawpred.items():
  if k=='clean':continue
  flips=((base>=.5)!=(v>=.5)).mean(axis=1)
  stability[k]={'mean_absolute_probability_change':float(np.abs(base-v).mean()),'mean_class_flip_fraction':float(flips.mean()),'sample_flip_distribution_quantiles':np.quantile(flips,[.025,.975]).tolist(),'bootstrap_mean_flip_fraction_ci95':flip_ci[k],'macro_AP_delta_from_clean':float(ap[k]-ap['clean']),'paired_macro_AP_delta_ci95':delta_ci[k]}
 established=delta_ci['formula_only'][1]<0 and delta_ci['frequency_scrambled'][1]<0
 scientific='QUALIFIED_FOR_ROBUSTNESS_INTERPRETATION' if established else 'NOT_ESTABLISHED; perturbation metrics descriptive only'
 return {'status':'PASS' if established else 'FAIL','reward':1.0 if established else 0.0,'scientific_status':scientific,'blind_rows':len(ids),'macro_average_precision':ap,'bootstrap_ci95':ci,'paired_macro_AP_delta_ci95':delta_ci,'stability':stability,'clean_signal_gate':'MET' if established else 'NOT_MET','bootstrap_unit':'opaque molecule IDs; each sample is one unique molecule; 300 paired resamples','model_condition_consistency':'independently rerun and matched for every spectral condition','warning':'simulated source-domain perturbations do not establish experimental/NIST generalization'}


def main():
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / 'verification.json'; report.unlink(missing_ok=True)
    try:
        for name, digest in INPUT_HASHES.items():
            f = app / 'assets' / name
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
                raise RuntimeError('missing/corrupt evaluation input: ' + name)
        f = tests / 'refs.json'
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != REFERENCE_SHA256:
            raise RuntimeError('missing/corrupt hidden reference')
        result = run(str(app / 'final'))
        status = result.get('status'); value = result.get('reward')
        if status not in ('PASS', 'FAIL') or value != (1 if status == 'PASS' else 0):
            raise RuntimeError(result.get('reason', 'scorer returned an unsupported result'))
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if status == 'PASS' else 1
    except Exception as exc:
        kind = 'ERROR' if isinstance(exc, InfrastructureError) else 'FAIL'
        result = {'status': kind, 'reward': None if kind == 'ERROR' else 0.0, 'reason': str(exc)}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result['status'] == 'ERROR' else 1


if __name__ == '__main__':
    raise SystemExit(main())
