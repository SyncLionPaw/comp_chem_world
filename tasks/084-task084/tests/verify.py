#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Ranking of Constitutional Isomers with Identical Molecular Formula.
"""Terminal-state verification for task 85.

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

INPUT_HASHES = {'SOURCES.yaml': 'c4c556e486508f50ddf736965406ae542825ebd096f2da88f9abb989350e43d1', 'cohort-train.npz': '1d6c93b082427d6895da6f1cd72ecfe0a04b775b05550ab1495926f03e0ef77a', 'cohort-validation.npz': 'a454592acac8be98e74142e353e6fb70498fcf858faafd0a234ae07d1d7ca2e7', 'isomer-candidates-public.json': '0948d0a82e6c4faedcf0113e3c8542b42f477181f6de6e4b9a421c3a38a5df41', 'isomer-query-public.npz': 'de60ccbe1ee9cf854f7e6d1efedcc0eddc9ef8ba0122f5f589d466ad20400f0b'}
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
def sha_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def id_hash(ids)->str:return sha_bytes(('\n'.join(map(str,ids))+'\n').encode())
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

import os, csv, hashlib, json, math, sys
from pathlib import Path
import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

ROOT=Path(os.environ.get('IR_REFERENCE_ROOT', str(Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents)>3 else Path(__file__).resolve().parent))); PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
CONDS={'full_spectrum','candidate_only','frequency_scrambled_query'}
def fail(s): raise SubmissionError(s)
def formula(m): return rdMolDescriptors.CalcMolFormula(m)
def metrics(rows):
 n=len(rows); top=sum(r['rank']==1 for r in rows)/n; mrr=sum(1/r['rank'] for r in rows)/n
 # Formula-cluster bootstrap; this cohort deliberately has one query per formula.
 rng=np.random.default_rng(20261112); vals=[]
 for _ in range(2000):
  ix=rng.integers(0,n,n); vals.append((np.mean([rows[i]['rank']==1 for i in ix]),np.mean([1/rows[i]['rank'] for i in ix])))
 a=np.asarray(vals)
 return {'top1':top,'mrr':mrr,'top1_ci95':np.quantile(a[:,0],[.025,.975]).tolist(),'mrr_ci95':np.quantile(a[:,1],[.025,.975]).tolist()}
def random_top1_pvalue(ranks,ks):
 # Exact upper-tail Poisson-binomial probability under independently randomized candidate order.
 probs=[1.0/k for k in ks]; obs=sum(r==1 for r in ranks); dp=np.zeros(len(probs)+1);dp[0]=1
 for p in probs:
  dp[1:]=dp[1:]*(1-p)+dp[:-1]*p;dp[0]*=(1-p)
 return float(dp[obs:].sum())
def run(outdir):
 out=Path(outdir)
 for f in ('cohort-train.npz','cohort-validation.npz','isomer-query-public.npz','isomer-candidates-public.json'):
  if not (PKG/'assets'/f).is_file(): raise InfrastructureError('missing package input: '+f)
 validate_sources(PKG)
 tr=np.load(PKG/'assets/cohort-train.npz',allow_pickle=False); va=np.load(PKG/'assets/cohort-validation.npz',allow_pickle=False)
 q=np.load(PKG/'assets/isomer-query-public.npz',allow_pickle=False)
 if set(q.files)!={'sample_id','formula','spectra'}: raise InfrastructureError('query NPZ must contain only sample_id/formula/spectra')
 ids=q['sample_id'].astype(str); forms=q['formula'].astype(str); x=q['spectra']
 if x.shape!=(len(ids),1791) or len(set(ids))!=len(ids): raise InfrastructureError('invalid query spectrum matrix/IDs')
 try: doc=json.loads((PKG/'assets/isomer-candidates-public.json').read_text(encoding='utf-8'))
 except Exception as e: raise InfrastructureError('invalid candidate JSON: '+str(e))
 if doc.get('schema')!='ir-local-isomer-questions/v1' or not isinstance(doc.get('questions'),list): raise InfrastructureError('candidate schema mismatch')
 qs={z['query_id']:z for z in doc['questions']}
 if set(qs)!=set(ids) or len(qs)!=len(ids): raise InfrastructureError('question/query IDs mismatch')
 hidden=load_hidden(ROOT); rows=[]; allowed={}
 for i,sid in enumerate(ids):
  h=hidden.get(sid)
  if not h or h['split']!='blind-test' or str(h['formula'])!=forms[i]: raise InfrastructureError('hidden identity/formula mismatch')
  z=qs[sid]; cs=z.get('candidates')
  if z.get('formula')!=forms[i] or not isinstance(cs,list) or len(cs)!=z.get('candidate_count') or len(cs)<2: raise InfrastructureError('invalid candidate set')
  cids=[]; can=[]
  for c in cs:
   m=Chem.MolFromSmiles(c.get('smiles',''))
   if m is None or formula(m)!=forms[i]: raise InfrastructureError('candidate structure/formula mismatch')
   s=Chem.MolToSmiles(m,canonical=True,isomericSmiles=False)
   if s in can: raise InfrastructureError('duplicate constitutional candidate')
   can.append(s);cids.append(c.get('candidate_id'))
  if len(set(cids))!=len(cids) or h.get('correct_candidate_id') not in cids: raise InfrastructureError('candidate IDs or hidden target inconsistent')
  allowed[sid]=set(cids)
 # Verify query-only split and candidate-source disjointness from the exposed training labels.
 train_can=set()
 for ds in (tr,va):
  for s in ds['smiles']:
   m=Chem.MolFromSmiles(str(s)); train_can.add(Chem.MolToSmiles(m,canonical=True,isomericSmiles=False))
 for s in ids:
  for c in qs[s]['candidates']:
   can=Chem.MolToSmiles(Chem.MolFromSmiles(c['smiles']),canonical=True,isomericSmiles=False)
   if can in train_can: raise InfrastructureError('candidate graph overlaps public train/validation structures')
 target={s:hidden[s]['correct_candidate_id'] for s in ids}
 path=out/'submission.jsonl'
 if not path.is_file() or not path.stat().st_size: fail('missing/empty submission.jsonl')
 got={}
 try:
  for line in path.read_text(encoding='utf-8').splitlines():
   r=json.loads(line); sid=r['query_id']; cond=r['condition_id']; ranked=r['ranked_candidates']
   if sid not in allowed or cond not in CONDS: fail('unknown query or condition')
   key=(sid,cond)
   if key in got: fail('duplicate query/condition')
   if not isinstance(ranked,list) or [a['candidate_id'] for a in ranked].__len__()!=len(allowed[sid]) or set(a['candidate_id'] for a in ranked)!=allowed[sid]: fail('ranking must include each candidate exactly once')
   scores=[float(a['score']) for a in ranked]
   if not np.isfinite(scores).all() or any(scores[j]<scores[j+1] for j in range(len(scores)-1)): fail('finite ranking scores must be non-increasing')
   try: unc=float(r['uncertainty'])
   except (KeyError,TypeError,ValueError): fail('each ranking needs a numeric uncertainty in [0,1]')
   if not np.isfinite(unc) or not -1e-9<=unc<=1+1e-9: fail('uncertainty must be finite and in [0,1]')
   got[key]=ranked
 except SubmissionError: raise
 except Exception as e: fail('malformed JSONL: '+str(e))
 if set(got)!={(s,c) for s in ids for c in CONDS}: fail('submission must cover all query/condition pairs')
 result={}
 for cond in CONDS:
  rr=[]
  for s in ids:
   rank=next(i+1 for i,c in enumerate(got[(s,cond)]) if c['candidate_id']==target[s]);rr.append({'rank':rank})
  result[cond]=metrics(rr)
 ks=[len(allowed[s]) for s in ids]; full_ranks=[next(i+1 for i,c in enumerate(got[(s,'full_spectrum')]) if c['candidate_id']==target[s]) for s in ids]
 random_top=float(np.mean([1/k for k in ks])); pnull=random_top1_pvalue(full_ranks,ks)
 scientific='SUPPORTED_OVER_RANDOM' if pnull<0.05 and result['full_spectrum']['top1']>random_top else 'NOT_ESTABLISHED'
 return {'status':'PASS' if scientific=='SUPPORTED_OVER_RANDOM' else 'FAIL','reward':1.0 if scientific=='SUPPORTED_OVER_RANDOM' else 0.0,'scientific_status':scientific,'random_null_one_sided_exact_p':pnull,'questions':len(ids),'candidate_count_histogram':{str(k):sum(len(allowed[s])==k for s in ids) for k in sorted(set(ks))},'random_choice_top1':random_top,'metrics':result,'full_minus_candidate_only_top1':result['full_spectrum']['top1']-result['candidate_only']['top1'],'full_minus_frequency_scrambled_top1':result['full_spectrum']['top1']-result['frequency_scrambled_query']['top1'],'interpretation':'random-choice is the independent primary null; submitted candidate-only/frequency controls are diagnostics and cannot alone establish spectral value'}


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
