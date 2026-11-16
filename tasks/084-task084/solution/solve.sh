#!/bin/bash
set -euo pipefail
# Oracle entrypoint: reference solve by real computation, no hardcoded answers.
export APP="${APP:-/app}" IR_PACKAGE_ROOT="${APP:-/app}"
mkdir -p "$APP/final"
python3 - "$APP/final" <<'PY'
import numpy as np
from rdkit import Chem
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

def labels_from_smiles(smiles):
 mol=Chem.MolFromSmiles(str(smiles))
 if mol is None:
  raise ValueError("invalid public candidate SMILES")
 return np.asarray([int(mol.HasSubstructMatch(PATTERNS[k])) for k in GROUP_SMARTS],dtype=np.uint8)

import os, csv,hashlib,json,sys
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from rdkit import Chem
PKG=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
def scramble(x,ids):
 out=np.empty_like(x)
 for i,s in enumerate(ids):
  seed=int.from_bytes(hashlib.sha256(f'ir-local-frequency-scramble-v1|20261006|{s}'.encode()).digest()[:8],'little')
  out[i]=x[i,np.random.default_rng(seed).permutation(x.shape[1])]
 return out
def sha(x):return hashlib.sha256(np.asarray(x).astype(np.float32).tobytes()).hexdigest()
def idsha(x):return hashlib.sha256(('\n'.join(map(str,x))+'\n').encode()).hexdigest()
def main(outdir):
 out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
 tr=np.load(PKG/'assets/cohort-train.npz',allow_pickle=False);va=np.load(PKG/'assets/cohort-validation.npz',allow_pickle=False)
 q=np.load(PKG/'assets/isomer-query-public.npz',allow_pickle=False);doc=json.loads((PKG/'assets/isomer-candidates-public.json').read_text())
 ids=q['sample_id'].astype(str);x=q['spectra'].astype(np.float32);x=x/np.maximum(np.max(np.abs(x),axis=1,keepdims=True),1e-12)
 y=tr['group_labels'].astype(np.uint8);sc=StandardScaler();xt=sc.fit_transform(tr['spectra'].astype(np.float32)/np.maximum(np.max(np.abs(tr['spectra']),axis=1,keepdims=True),1e-12)).astype(np.float32);xq=sc.transform(x).astype(np.float32)
 models=[]
 for j in range(y.shape[1]):
  m=LogisticRegression(solver='liblinear',C=.1,max_iter=100,tol=1e-3,random_state=20261008+j);m.fit(xt,y[:,j]);models.append(m)
 def prob(z):return np.column_stack([m.predict_proba(z)[:,1] for m in models])
 full=prob(xq);scr=prob(sc.transform(scramble(x,ids)).astype(np.float32))
 globalp=(y.sum(axis=0)+1)/(len(y)+2);pri={}
 for f in np.unique(tr['formula']):
  ix=tr['formula']==f;pri[str(f)]=(y[ix].sum(axis=0)+1)/(ix.sum()+2)
 byid={z['query_id']:z for z in doc['questions']};conditions={'full_spectrum':full,'frequency_scrambled_query':scr}
 with (out/'submission.jsonl').open('w',encoding='utf8') as f:
  for i,sid in enumerate(ids):
   qrow=byid[sid];cand=qrow['candidates']; formula=qrow['formula']; cp=pri.get(formula,globalp)
   # Query likelihood under simple supervised functional-group indicator surrogate.
   vals={}
   for cond,ps in conditions.items():
    p=np.clip(ps[i],1e-5,1-1e-5)
    for c in cand:
     z=np.asarray(labels_from_smiles(c['smiles']),dtype=float)
     score=float(np.sum(z*np.log(p)+(1-z)*np.log(1-p)))
     vals[(cond,c['candidate_id'])]=score
   for cond in ('full_spectrum','candidate_only','frequency_scrambled_query'):
    if cond=='candidate_only':
     rankings=[]
     for c in cand:
      z=np.asarray(labels_from_smiles(c['smiles']),dtype=float);score=float(np.sum(z*np.log(cp)+(1-z)*np.log(1-cp)))
      rankings.append({'candidate_id':c['candidate_id'],'score':score})
    else: rankings=[{'candidate_id':c['candidate_id'],'score':vals[(cond,c['candidate_id'])]} for c in cand]
    rankings.sort(key=lambda r:(-r['score'],r['candidate_id']))
    sv=np.asarray([r['score'] for r in rankings],dtype=float)
    if len(sv)>1:
     w=np.exp(sv-sv.max());w/=w.sum();unc=float(min(1.0,max(0.0,-(w*np.log(w)).sum()/np.log(len(sv)))))
    else: unc=0.0
    f.write(json.dumps({'query_id':sid,'condition_id':cond,'uncertainty':unc,'ranked_candidates':rankings},separators=(',',':'))+'\n')
 cands='\n'.join(s+'\t'+','.join(sorted(c['candidate_id'] for c in byid[s]['candidates'])) for s in ids)+'\n'
 p={'model':'8 OVR logistic group-presence surrogate trained on public train only; candidate rank by Bernoulli log-likelihood of RDKit SMARTS profile','train_ids_sha256':idsha(tr['sample_id']),'validation_ids_sha256':idsha(va['sample_id']),'query_ids_sha256':idsha(ids),'query_spectrum_sha256':sha(q['spectra']),'candidate_sets_sha256':hashlib.sha256(cands.encode()).hexdigest(),'frequency_scramble_seed':20261006,'normalization':'per-row max-absolute normalization then train-only StandardScaler'}
 (out/'protocol.json').write_text(json.dumps(p,indent=2)+'\n')
 print(json.dumps({'status':'reference-generated','queries':len(ids),'output':str(out)}))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '/tmp/case-02-reference')
PY
