#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including submission.csv, model.npz, band_evidence.json).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Functional Group Signals in Simulated Infrared Spectra.
"""Terminal-state verification for the simulated IR functional-group case.

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

import os, csv,json,sys
from pathlib import Path
import numpy as np
from scipy.special import expit
ROOT=Path(os.environ.get('IR_REFERENCE_ROOT', str(Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents)>3 else Path(__file__).resolve().parent)))
PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
def fail(msg):raise SubmissionError(msg)
def row_shuffle(test):
 ids=np.asarray(test['sample_id']).astype(str); formulas=np.asarray(test['formula']).astype(str); x=np.asarray(test['spectra'],dtype=np.float32)
 by={}
 for i,f in enumerate(formulas):by.setdefault(f,[]).append(i)
 out=x.copy();eligible=[]
 for formula in sorted(by):
  ix=sorted(by[formula],key=lambda i:ids[i]);n=len(ix)
  if n<2:continue
  eligible.extend(ix)
  import hashlib
  seed=int.from_bytes(hashlib.sha256(f'ir-local-formula-row-shuffle-v1|20261005|{formula}'.encode()).digest()[:8],'little')
  offset=int(np.random.default_rng(seed).integers(1,n))
  for j,i in enumerate(ix):out[i]=x[ix[(j+offset)%n]]
 return out,np.asarray(sorted(eligible),dtype=int),by
def read_predictions(path,names,valid_conditions):
 if not path.is_file() or path.stat().st_size==0:fail('missing/empty submission.csv')
 need={'sample_id','condition_id',*names}
 results={}
 try:
  with path.open(newline='',encoding='utf-8') as f:
   for r in csv.DictReader(f):
    if not need.issubset(r):fail('prediction CSV missing required columns')
    sid=r['sample_id'];condition=r['condition_id']
    if condition not in valid_conditions:fail('unknown condition_id')
    key=(sid,condition)
    if key in results:fail('duplicate sample_id/condition_id prediction')
    try:p=np.asarray([float(r[k]) for k in names],dtype=float)
    except Exception:fail('invalid probability field')
    if not np.isfinite(p).all() or np.any(p<0) or np.any(p>1):fail('probabilities must be finite in [0,1]')
    results[key]=p
 except SubmissionError:raise
 except Exception as e:fail(f'cannot parse predictions: {e}')
 return results
def run(outdir):
 outdir=Path(outdir)
 for name in ('cohort-train.npz','cohort-validation.npz','cohort-blind-test.npz','axis-cm-1.npy'):
  if not (PKG/'assets'/name).is_file():raise InfrastructureError(f'missing package input: {name}')
 validate_sources(PKG)
 tr=load_npz(PKG/'assets/cohort-train.npz');va=load_npz(PKG/'assets/cohort-validation.npz');te=load_npz(PKG/'assets/cohort-blind-test.npz')
 tri,trf,trX=validate_public_schema(tr);vai,vaf,vaX=validate_public_schema(va);tei,tef,teX=validate_public_schema(te,blind=True)
 names=list(map(str,tr['group_names']))
 if names!=list(GROUP_SMARTS) or list(map(str,va['group_names']))!=names:raise InfrastructureError('frozen class order mismatch')
 axis=np.load(PKG/'assets/axis-cm-1.npy',allow_pickle=False)
 if not np.array_equal(axis,np.arange(400,3982,2,dtype=axis.dtype)):raise InfrastructureError('frequency axis must be exactly 400..3980 by 2 cm-1')
 hidden=load_hidden(ROOT);test_records=validate_hidden_rows(te,hidden)
 ys=np.stack([r[3] for r in test_records]);formulas=np.asarray([r[2] for r in test_records]);ids=np.asarray([r[1] for r in test_records])
 if not np.array_equal(ids,tei.astype(str)) or len(test_records)!=len(tei):raise InfrastructureError('hidden references do not exactly align with blind IDs')
 # Validate public train/validation labels independently from their public structures.
 for split,data,smiles in [('train',tr,tr['smiles']),('validation',va,va['smiles'])]:
  y=np.stack([labels_from_smiles(s) for s in smiles])
  if not np.array_equal(y,data['group_labels']):raise InfrastructureError(f'{split} public labels mismatch RDKit SMARTS')
 # Ensure exact canonical graph disjointness across all three splits.
 from rdkit import Chem
 canon=lambda arr:{Chem.MolToSmiles(Chem.MolFromSmiles(str(s)),canonical=True,isomericSmiles=False) for s in arr}
 a,b,c=canon(tr['smiles']),canon(va['smiles']),{str(hidden[s]['canonical_smiles']) for s in ids}
 if (a&b) or (a&c) or (b&c):raise InfrastructureError('canonical molecule identity crosses data splits')
 shuffled,eligible,byformula=row_shuffle(te)
 full_ids=set(ids);eligible_ids=set(ids[eligible])
 # Package ID order is frozen; verifier parses all submitted conditions.
 conditions={'full_spectrum':full_ids,'within_formula_spectrum_shuffle':eligible_ids}
 pred=read_predictions(outdir/'submission.csv',names,set(conditions))
 if set(pred)!={(sid,cond) for cond,sids in conditions.items() for sid in sids}:fail('prediction rows do not exactly cover required ID/condition pairs')
 raw=np.asarray(te['spectra'],dtype=np.float32)
 model_path=outdir/'model.npz'
 if not model_path.is_file() or model_path.stat().st_size==0:fail('missing safe model.npz')
 try:
  model=np.load(model_path,allow_pickle=False);coef=model['coef'];inter=model['intercept'];mean=model['scaler_mean'];scale=model['scaler_scale']
 except Exception as e:fail(f'invalid safe model.npz: {e}')
 if coef.shape!=(len(names),raw.shape[1]) or inter.shape!=(len(names),) or mean.shape!=(raw.shape[1],) or scale.shape!=(raw.shape[1],) or not all(np.isfinite(z).all() for z in (coef,inter,mean,scale)) or np.any(scale<=0):fail('model array shape/value invalid')
 from scipy.special import expit
 model_probs={}
 for cond,x in [('full_spectrum',raw),('within_formula_spectrum_shuffle',shuffled)]:model_probs[cond]=expit(((x/np.maximum(np.max(np.abs(x),axis=1,keepdims=True),1e-12)-mean)/scale)@coef.T+inter)
 for cond,sids in conditions.items():
  got=np.stack([pred[(sid,cond)] for sid in ids if sid in sids])
  want=model_probs[cond] if cond=='full_spectrum' else model_probs[cond][eligible]
  if got.shape!=want.shape or not np.allclose(got,want,rtol=1e-4,atol=2e-5):fail(f'{cond} predictions do not come from the same safe model on frozen inputs')
 bands_path=outdir/'band_evidence.json'
 if not bands_path.is_file() or bands_path.stat().st_size==0:fail('missing band_evidence.json')
 try:bands=json.loads(bands_path.read_text(encoding='utf-8'))
 except Exception as e:fail(f'invalid band_evidence.json: {e}')
 if not isinstance(bands,dict) or not isinstance(bands.get('classes'),dict):fail('band evidence must carry a classes object')
 if set(bands['classes'])!=set(names):fail('band evidence must report every frozen class')
 for group,items in bands['classes'].items():
  if not isinstance(items,list) or not 1<=len(items)<=5:fail(f'band evidence for {group} must contain 1–5 train-selected intervals')
  seen_ranges=set()
  for item in items:
   if not isinstance(item,dict) or not isinstance(item.get('range_cm1'),list) or len(item['range_cm1'])!=2:fail(f'invalid band evidence for {group}')
   lo,hi=item['range_cm1']
   if not np.isfinite([lo,hi]).all() or lo<400 or hi>3980 or lo>=hi or hi-lo>4.0 or item.get('direction') not in {'higher_in_positive','lower_in_positive'}:fail(f'invalid band interval/direction for {group}')
   if (lo,hi) in seen_ranges:fail(f'duplicate band interval for {group}')
   seen_ranges.add((lo,hi))
 # Independent validation confirmation of train-selected narrow bands.
 val_x=np.asarray(va['spectra'],dtype=np.float32);val_x=val_x/np.maximum(np.max(np.abs(val_x),axis=1,keepdims=True),1e-12)
 val_y=va['group_labels'].astype(np.uint8);val_forms=va['formula'].astype(str)
 band_results={}
 for group,items in bands['classes'].items():
  j=names.index(group);band_results[group]=[]
  for item in items:
   lo,hi=map(float,item['range_cm1']);mask=(axis>=lo)&(axis<=hi)
   if not mask.any():fail('band interval contains no frequency bins')
   feat=val_x[:,mask].mean(axis=1);pos=val_y[:,j].astype(bool);obs=float(feat[pos].mean()-feat[~pos].mean())
   directional=obs if item['direction']=='higher_in_positive' else -obs
   groups={}
   for k,f in enumerate(val_forms):groups.setdefault(str(f),[]).append(k)
   gn=list(groups);delta=[]
   seed=int.from_bytes(__import__('hashlib').sha256(f"ir-local01-band-bootstrap-v1|20261104|{group}|{lo:.1f}|{hi:.1f}".encode()).digest()[:8],'little');rng=np.random.default_rng(seed)
   for _ in range(500):
    sampled=rng.choice(gn,size=len(gn),replace=True);ix=np.concatenate([np.asarray(groups[g]) for g in sampled]);yy=pos[ix];ff=feat[ix]
    if yy.any() and (~yy).any():
     delta.append(float(ff[yy].mean()-ff[~yy].mean()))
   ci=np.quantile(delta,[.025,.975]).tolist() if delta else [None,None]
   if not isinstance(item.get('validation_mean_difference'),(int,float)) or not np.isclose(float(item['validation_mean_difference']),obs,atol=1e-7):fail('band validation effect does not match public validation data')
   if not isinstance(item.get('validation_ci95'),list) or len(item['validation_ci95'])!=2 or not np.allclose(item['validation_ci95'],ci,atol=1e-7,rtol=0):fail('band validation CI does not match molecule/formula bootstrap')
   band_results[group].append({'range_cm1':[lo,hi],'direction':item['direction'],'validation_mean_difference':obs,'validation_ci95':ci,'directional_effect':directional,'positive_support':int(pos.sum()),'negative_support':int((~pos).sum()),'supported':bool(ci[0]>0 if item['direction']=='higher_in_positive' and ci[0] is not None else ci[1]<0 if ci[1] is not None else False)})
 # Compute every metric from per-sample rows and hidden RDKit labels.
 P={'full_spectrum':model_probs['full_spectrum']}
 # Scorer-owned Beta(1,1)-smoothed formula-only baseline from public train labels.
 global_p=(tr['group_labels'].sum(axis=0)+1)/(len(tr['group_labels'])+2); prior={}
 for f in np.unique(tr['formula']):
  ix=tr['formula']==f;prior[str(f)]=(tr['group_labels'][ix].sum(axis=0)+1)/(int(ix.sum())+2)
 P['formula_only']=np.stack([global_p if str(f) not in prior else prior[str(f)] for f in formulas])
 macro={k:macro_ap(ys,v) for k,v in P.items()}
 from sklearn.metrics import average_precision_score
 class_ap={k:{name:float(average_precision_score(ys[:,j],v[:,j])) for j,name in enumerate(names)} for k,v in P.items()}
 dformula=cluster_bootstrap_delta(ys,P['full_spectrum'],P['formula_only'],formulas,seed=20261101)
 ix=eligible;shp=np.stack([pred[(str(ids[i]),'within_formula_spectrum_shuffle')] for i in ix])
 dshuffle=cluster_bootstrap_delta(ys[ix],P['full_spectrum'][ix],model_probs['within_formula_spectrum_shuffle'][eligible],formulas[ix],seed=20261102)
 signal='SUPPORTED' if dformula['ci95'][0] is not None and dformula['ci95'][0]>0 and dshuffle['ci95'][0] is not None and dshuffle['ci95'][0]>0 else 'NOT_ESTABLISHED_BY_THIS_SPLIT'
 metrics={'status':'PASS' if signal=='SUPPORTED' else 'FAIL','reward':1.0 if signal=='SUPPORTED' else 0.0,'blind_rows':len(ids),'same_formula_shuffle_rows':len(ix),'same_formula_shuffle_groups':len(set(formulas[ix])),'class_average_precision':class_ap,'macro_average_precision':macro,'full_minus_formula_only':dformula,'full_minus_within_formula_shuffle_on_eligible_subset':dshuffle,'validation_band_audit':band_results,'signal_status':signal}
 return metrics

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
    except SubmissionError as exc:
        result = {'status': 'FAIL', 'reward': 0.0, 'reason': str(exc)}
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        return 1
    except InfrastructureError as exc:
        result = {'status': 'ERROR', 'reward': None, 'reason': str(exc)}
    except Exception as exc:
        result = {'status': 'ERROR', 'reward': None, 'reason': str(exc)}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
