#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including report.md, diagnosis.json).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Analyse occupancy refinement and its relation to an independent X-ray baseline.
"""Full binary verifier for the finite M7 multiobjective decision task."""
import csv,hashlib,json,math,os,sys
from pathlib import Path
REFS_PATH=Path(__file__).with_name('refs.json')

def positive_number(value):
 if type(value) is int:return value>0
 return type(value) is float and math.isfinite(value) and value>0

def validate_refs(refs):
 if not isinstance(refs,dict) or refs.get('schema_version')!='case04-test-references/v1':raise ValueError('unsupported reference schema')
 hashes=refs['public_asset_sha256']
 if not isinstance(hashes,dict) or set(hashes)!={'occupancy_sweep.csv'} or not isinstance(hashes['occupancy_sweep.csv'],str) or len(hashes['occupancy_sweep.csv'])!=64 or any(c not in '0123456789abcdef' for c in hashes['occupancy_sweep.csv']):raise ValueError('invalid public asset hash table')
 labels=refs['source_labels']
 if not isinstance(labels,list) or len(labels)!=3 or any(not isinstance(v,str) or not v for v in labels) or len(set(labels))!=len(labels):raise ValueError('invalid source label reference')
 p=refs['policy']
 if not positive_number(p['numeric_tolerance']) or not positive_number(p['component_half_width']):raise ValueError('invalid positive numerical policy')
 domain=p['weight_domain']
 if not isinstance(domain,list) or len(domain)!=2 or any(type(v) not in (int,float) or (type(v) is float and not math.isfinite(v)) for v in domain) or domain[0]<0 or domain[0]>=domain[1]:raise ValueError('invalid finite weight domain')
 if type(p['sum_is_derived_from_components']) is not bool:raise ValueError('invalid Sum derivation policy')

try:
 REFS=json.loads(REFS_PATH.read_text(encoding='utf-8'))
 validate_refs(REFS)
 SHA=REFS['public_asset_sha256']['occupancy_sweep.csv']
 LABELS=tuple(REFS['source_labels']); POLICY=REFS['policy']; TOL=POLICY['numeric_tolerance']
 EPS=POLICY['component_half_width']
 WEIGHT_DOMAIN=POLICY['weight_domain']
except (OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError,ValueError) as e:
 print('ENV_INVALID: task reference configuration unavailable: '+str(e)); raise SystemExit(2)

def exact_source_number(a,b):
 if not isinstance(a,(int,float)) or isinstance(a,bool): return False
 if not isinstance(b,(int,float)) or isinstance(b,bool): return False
 try: return math.isfinite(a) and math.isfinite(b) and a==b
 except (OverflowError,TypeError): return False

def fail(msg,env=False):
 print(('ENV_INVALID: ' if env else 'FAIL: ')+msg); return 2 if env else 1
def equal(a,b,path=()):
 if isinstance(b,dict):
  optional={'weight_definition'} if path==('scalarization',) else {'interpretation'} if path==('rounding_robustness',) else set()
  if not isinstance(a,dict) or not set(b).difference(optional).issubset(a): return False
  for k,v in b.items():
   field_path=path+(k,)
   if field_path in (("scalarization","weight_definition"),("rounding_robustness","interpretation")) and k not in a:
    continue
   if field_path in (("scalarization","weight_definition"),("rounding_robustness","interpretation")):
    if not isinstance(a[k],str) or not a[k].strip(): return False
   elif not equal(a[k],v,field_path): return False
  return True
 if isinstance(b,list):
  if path==('source','rows','values'):
   return isinstance(a,list) and len(a)==len(b) and all(exact_source_number(x,y) for x,y in zip(a,b))
  return isinstance(a,list) and len(a)==len(b) and all(equal(x,y,path) for x,y in zip(a,b))
 if isinstance(b,(int,float)) and not isinstance(b,bool):
  if not isinstance(a,(int,float)) or isinstance(a,bool): return False
  try: return math.isfinite(a) and abs(a-b)<=TOL
  except (OverflowError,TypeError): return False
 return type(a) is type(b) and a==b
def expected(src):
 with src.open(newline='',encoding='utf8') as f: rows=list(csv.reader(f))
 if len(rows)!=5 or len(rows[1])!=13: raise ValueError('source CSV shape changed')
 cols=rows[1][1:]; data={r[0]:[float(v) for v in r[1:]] for r in rows[2:]}
 if tuple(data)!=LABELS or len(cols)!=12 or not all(math.isfinite(v) for vs in data.values() for v in vs): raise ValueError('source rows/columns invalid')
 if POLICY['sum_is_derived_from_components'] and any(abs(data[LABELS[0]][i]+data[LABELS[1]][i]-data['Sum'][i])>TOL for i in range(12)): raise ValueError('Sum no longer derives from component rows')
 rs=cols[:-1]; v={r:(data[LABELS[0]][i],data[LABELS[1]][i]) for i,r in enumerate(rs)}
 def mins(vals):
  m=min(vals.values()); return {'value':m,'ratios':[r for r in rs if vals[r]==m]}
 ce={k:mins({r:data[k][i] for i,r in enumerate(rs)}) for k in LABELS[:2]}; je=mins({r:data['Sum'][i] for i,r in enumerate(rs)})
 pareto=[r for r in rs if not any(q!=r and all(v[q][j]<=v[r][j] for j in range(2)) and any(v[q][j]<v[r][j] for j in range(2)) for q in rs)]
 # Generate all pairwise line intersections, including non-winning crossings; filtered output is the full lower envelope.
 points=set(WEIGHT_DOMAIN)
 for r in rs:
  for q in rs:
   da=v[r][0]-v[q][0]; db=v[r][1]-v[q][1]; den=da-db
   if den:
    x=-db/den
    if WEIGHT_DOMAIN[0]<x<WEIGHT_DOMAIN[1]: points.add(round(x,12))
 pts=sorted(points); raw=[]
 for lo,hi in zip(pts,pts[1:]):
  w=(lo+hi)/2; scores={r:w*v[r][0]+(1-w)*v[r][1] for r in rs}; m=min(scores.values()); raw.append((lo,hi,[r for r in rs if abs(scores[r]-m)<=TOL]))
 intervals=[]
 for lo,hi,winners in raw:
  if intervals and intervals[-1]['ratios']==winners: intervals[-1]['weight_interval'][1]=hi
  else: intervals.append({'weight_interval':[lo,hi],'ratios':winners})
 switches=[]
 for w in sorted({*WEIGHT_DOMAIN,*[item['weight_interval'][1] for item in intervals[:-1]]}):
  score={r:w*v[r][0]+(1-w)*v[r][1] for r in rs}; m=min(score.values()); ties=[r for r in rs if abs(score[r]-m)<=TOL]
  if len(ties)>1: switches.append({'weight':w,'ratios':ties,'score':m})
 eps=EPS; robust=[]; possible=[]
 for r in rs:
  for q in rs:
   if r==q: continue
   ur=[v[r][j]+eps for j in range(2)]; lq=[v[q][j]-eps for j in range(2)]
   if all(ur[j]<=lq[j]+TOL for j in range(2)) and any(ur[j]<lq[j]-TOL for j in range(2)): robust.append([r,q])
   lr=[v[r][j]-eps for j in range(2)]; uq=[v[q][j]+eps for j in range(2)]
   if all(lr[j]<=uq[j]+TOL for j in range(2)) and any(lr[j]<uq[j]-TOL for j in range(2)): possible.append([r,q])
 return {'schema_version':'case04-m7-sweep/v2','task_version':'2.0','evaluation_scope':'m7_finite_data_robust_multiobjective_diagnosis','source':{'columns':cols,'rows':[{'label':k,'values':data[k]} for k in LABELS]},'component_extrema':ce,'joint_extrema':je,'pareto_ratios':pareto,'scalarization':{'weight_definition':'w in [0,1] multiplies CYS A 145; (1-w) multiplies 4WI A 401','switch_points':switches,'open_intervals':intervals},'rounding_robustness':{'component_half_width':eps,'sum_is_derived_from_components':True,'robust_dominance_pairs':robust,'possible_dominance_pairs':possible,'interpretation':'component perturbations are shared through Sum; Sum is not an independent observation'}}
def _main(root):
 root=Path(root); src=root/'assets/occupancy_sweep.csv'
 try:
  if hashlib.sha256(src.read_bytes()).hexdigest()!=SHA: raise ValueError('pinned source hash mismatch')
  exp=expected(src)
 except (OSError,ValueError,csv.Error,UnicodeError) as e: return fail(str(e),True)
 try: got=json.loads((root/'diagnosis.json').read_text()); report=(root/'report.md').read_text()
 except (OSError,UnicodeError,json.JSONDecodeError) as e: return fail('missing/malformed submission: '+str(e))
 if isinstance(got,dict):
  got.setdefault('schema_version','case04-m7-sweep/v2')
  got.setdefault('task_version','2.0')
  got.setdefault('evaluation_scope','m7_finite_data_robust_multiobjective_diagnosis')
 policy=got.get('rounding_robustness') if isinstance(got,dict) else None
 half=policy.get('component_half_width') if isinstance(policy,dict) else None
 try: half_is_public=(not isinstance(half,bool) and isinstance(half,(int,float)) and math.isfinite(half) and float(half)==EPS)
 except (OverflowError,TypeError): half_is_public=False
 if not half_is_public:
  return fail(f'component_half_width must equal the public {EPS} policy constant')
 if not equal(got,exp): return fail('structured output must contain exact source values and complete extrema/Pareto/weight/rounding results')
 if not report.strip(): return fail('report is empty')
 logs=Path(os.environ.get('LOGS',root)); logs.mkdir(parents=True,exist_ok=True)
 result={'status':'PASS','earned':1,'maximum':1,'reward':1,'scope':'m7_finite_data_robust_multiobjective_diagnosis_v2'}
 (logs/'verification.json').write_text(json.dumps(result,indent=2)+'\n'); (logs/'reward.txt').write_text('1\n'); print('PASS: all finite-data decision claims verified'); return 0

def main(root):
 root=Path(root); logs=Path(os.environ.get('LOGS',root)); logs.mkdir(parents=True,exist_ok=True)
 try: code=_main(root)
 except Exception as e:
  print('ENV_INVALID: verifier exception: '+type(e).__name__+': '+str(e)); code=2
 if code==0:
  try:
   receipt=json.loads((logs/'verification.json').read_text(encoding='utf8'))
   if not isinstance(receipt,dict) or receipt.get('status')!='PASS': raise ValueError('missing PASS receipt')
  except Exception as e: print('ENV_INVALID: invalid PASS receipt: '+str(e)); code=2
 if code==1:
  (logs/'verification.json').write_text(json.dumps({'status':'FAIL','earned':0,'maximum':1,'reward':0,'reason':'candidate submission did not satisfy the public structured contract'},indent=2)+'\n')
  (logs/'reward.txt').write_text('0\n')
 elif code==2:
  (logs/'verification.json').write_text(json.dumps({'status':'ENV_INVALID','reason':'pinned evidence or verifier execution is unavailable'},indent=2)+'\n')
  (logs/'reward.txt').unlink(missing_ok=True)
 return code
if __name__=='__main__': raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else '.'))
