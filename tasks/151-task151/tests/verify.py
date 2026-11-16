#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including design.json, partition.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare quantum-region partitions for 5HLS–62G with a fixed protein environment.
"""Independent deterministic verifier for Case02 task version 2.0."""
import hashlib, itertools, json, math, os, sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
REFS_PATH=Path(__file__).with_name('refs.json')

def positive_number(value):
 if type(value) is int:return value>0
 return type(value) is float and math.isfinite(value) and value>0

def positive_decimal_string(value):
 if not isinstance(value,str):return False
 try:d=Decimal(value)
 except InvalidOperation:return False
 return d.is_finite() and d>0

def validate_refs(refs):
 if not isinstance(refs,dict) or refs.get('schema_version')!='case02-test-references/v1':raise ValueError('unsupported reference schema')
 for table,keys in ((refs['public_asset_sha256'],{'5hls_a_flip_H.pqr','model_template.gjf','5hls_a_flip_ligH.pdb','62G_optRESP.mol2'}),(refs['reference_sidecar_sha256'],{'62G.top','62G.par'})):
  if not isinstance(table,dict) or set(table)!=keys or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in table.values()):raise ValueError('invalid reference hash table')
 p=refs['policy']
 if not positive_number(p['contact_cutoff_angstrom']):raise ValueError('invalid positive contact cutoff')
 if not positive_decimal_string(p['coordinate_tolerance_angstrom']) or not positive_decimal_string(p['partial_charge_tolerance']):raise ValueError('invalid positive decimal tolerance')
 for k in ('max_qm_atom_count','max_qm_electron_count','reported_distance_decimals'):
  if type(p[k]) is not int or p[k]<=0:raise ValueError('invalid positive integer policy')
 if p['rounding']!='Python round ties-to-even':raise ValueError('unsupported rounding policy')

try:
 REFS=json.loads(REFS_PATH.read_text(encoding='utf-8'))
 validate_refs(REFS)
 EXPECTED=REFS['public_asset_sha256']; REF=REFS['reference_sidecar_sha256']; POLICY=REFS['policy']
except (OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError,ValueError) as e:
 print('ENV_INVALID: task reference configuration unavailable: '+str(e)); raise SystemExit(2)
Z={'H':1,'C':6,'N':7,'O':8,'F':9,'P':15,'S':16,'Cl':17,'Zn':30}; CUT=POLICY['contact_cutoff_angstrom']
class Bad(ValueError): pass
class Env(ValueError): pass

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(cond,msg):
 if not cond:raise Bad(msg)
def same_json(a,b):
 if type(a) is not type(b):
  # JSON integers and finite JSON decimals are equivalent for continuous
  # quantities (e.g. 4 and 4.0); booleans remain distinct from both.
  if json_number(a) and json_number(b):
   return finite_number(a) and finite_number(b) and same_number(a,b)
  return False
 if isinstance(a,dict): return a.keys()==b.keys() and all(same_json(a[k],b[k]) for k in a)
 if isinstance(a,list): return len(a)==len(b) and all(same_json(x,y) for x,y in zip(a,b))
 return a==b
def same_schema(a,b):
 # Recursive equality with schema-directed JSON types. Integers remain strict
 # (and booleans are never integers); fields represented by a floating-point
 # schema value accept any finite mathematically equal JSON number.
 if type(b) is int: return type(a) is int and a==b
 if type(b) is float: return finite_number(a) and same_number(a,b)
 if type(b) is bool: return type(a) is bool and a==b
 if type(b) is dict: return isinstance(a,dict) and a.keys()==b.keys() and all(same_schema(a[k],b[k]) for k in b)
 if type(b) is list: return isinstance(a,list) and len(a)==len(b) and all(same_schema(x,y) for x,y in zip(a,b))
 return type(a) is type(b) and a==b
def int_json(x): return type(x) is int
def json_number(x): return type(x) in (int,float) or isinstance(x,Decimal)
def same_number(a,b):
 try:return Decimal(str(a))==Decimal(str(b))
 except (InvalidOperation,ValueError,TypeError):return False
def finite_number(x):
 if type(x) is float:return math.isfinite(x)
 if type(x) is int:
  try:return math.isfinite(x)
  except OverflowError:return False
 if isinstance(x,Decimal):return x.is_finite()
 return False
def within_decimal_tolerance(a,b,tolerance):
 try:
  da=a if isinstance(a,Decimal) else Decimal(str(a)); db=b if isinstance(b,Decimal) else Decimal(str(b))
  delta=abs(da-db)
  return delta.is_finite() and delta<=Decimal(tolerance)
 except (InvalidOperation,ValueError,TypeError):return False
def atoms_pdb(path):
 out=[]
 for no,l in enumerate(Path(path).read_text().splitlines(),1):
  if l.startswith(('ATOM  ','HETATM')):
   try:
    e=l[76:78].strip().capitalize(); name=l[12:16].strip(); e=e or name.lstrip('0123456789')[:1].upper()
    slices=((30,38),(38,46),(46,54)); xyz_text=tuple(l[a:b].strip() for a,b in slices)
    out.append({'index':len(out)+1,'serial':int(l[6:11]),'name':name,'res':l[17:20].strip(),'chain':l[21:22].strip(),'resid':int(l[22:26]),'element':e,'xyz':tuple(float(x) for x in xyz_text),'xyz_decimal':tuple(Decimal(x) for x in xyz_text)})
   except Exception as e:raise Bad(f'{path}:{no} malformed atom record: {e}')
 return out
def gjf(path):
 ls=Path(path).read_text().splitlines()
 try:i=next(i for i,l in enumerate(ls) if l.strip()=='0 1 0 1 0 1')+1
 except StopIteration:raise Env('GJF charge header absent')
 aa=[]
 for l in ls[i:]:
  f=l.split()
  if len(f)<5:break
  try: xyz=tuple(float(x) for x in f[1:4]); xyz_decimal=tuple(Decimal(x) for x in f[1:4])
  except ValueError:break
  aa.append({'element':f[0].capitalize(),'xyz':xyz,'xyz_decimal':xyz_decimal,'layer':f[4]})
 i+=len(aa)
 while i<len(ls) and not ls[i].strip():i+=1
 edges={}
 for l in ls[i:]:
  f=l.split()
  if not f:continue
  try:
   a=int(f[0])
   for j in range(1,len(f),2):
    b=int(f[j]); order=float(f[j+1]); pair=tuple(sorted((a,b)))
    if a==b or a<1 or b<1 or a>len(aa) or b>len(aa):raise ValueError()
    edges[pair]=order
  except Exception:raise Env('malformed GJF connectivity')
 return aa,edges
def mol2(path):
 aa=[]; ee={}; mode=''
 for line in Path(path).read_text().splitlines():
  if line=='@<TRIPOS>ATOM':mode='a';continue
  if line=='@<TRIPOS>BOND':mode='b';continue
  if line.startswith('@<TRIPOS>'):mode='';continue
  f=line.split()
  if not f:continue
  if mode=='a':
   typ=f[5].lower(); el='Cl' if typ.startswith('cl') else typ.split('.')[0][:1].upper()
   aa.append({'idx':int(f[0]),'element':el,'xyz':tuple(float(x) for x in f[2:5]),'type':f[5]})
  if mode=='b':
   pair=tuple(sorted((int(f[1]),int(f[2]))));
   if pair in ee or f[3] not in {'1','2','3','ar'}:raise Env('invalid independent MOL2 bond')
   ee[pair]=f[3]
 return aa,ee
def charge(res,names,nterm=False,cterm=False):
 side={'LYS':1,'ARG':1,'ASP':-1,'GLU':-1}.get(res,0)
 supported={'ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIE','ILE','LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL','WAT'}
 if res not in supported:return None
 req={'LYS':{'NZ','HZ1','HZ2','HZ3'},'ARG':{'NE','HE','NH1','NH2','HH11','HH12','HH21','HH22'},'ASP':{'OD1','OD2'},'GLU':{'OE1','OE2'},'CYS':{'SG','HG'},'TYR':{'OH','HH'}}.get(res,set())
 if not req<=names:return None
 if res=='ASP' and {'HD1','HD2'}&names:return None
 if res=='GLU' and {'HE1','HE2'}&names:return None
 if nterm:
  if not {'H1','H2','H3'}<=names:return None
  side+=1
 if cterm:
  if not {'OXT','OT2'}&names:return None
  side-=1
 if res=='HIE' and ('HE2' not in names or 'HD1' in names):return None
 return side

def emit(root,status,reason=None):
 logs=Path(os.environ.get('LOGS',root)); logs.mkdir(parents=True,exist_ok=True)
 report={'status':status}
 if status=='PASS':report.update(reward=1,score=1,task_version='2.0',evaluation_scope='finite_static_partition_decision')
 elif status=='FAIL':report.update(reward=0,reason=reason)
 else:report.update(reason=reason)
 (logs/'verification.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
 rp=logs/'reward.txt'
 if status in {'PASS','FAIL'}:rp.write_text(str(report['reward'])+'\n')
 else:rp.unlink(missing_ok=True)
 return {'PASS':0,'FAIL':1,'ENV_INVALID':2}[status]

def main(root):
 root=Path(root)
 try:
  for n,h in EXPECTED.items():
   p=root/'assets'/n
   if not p.is_file() or sha(p)!=h:raise Env('missing or hash-mismatched public source '+n)
  pqr=atoms_pdb(root/'assets/5hls_a_flip_H.pqr'); full=atoms_pdb(root/'assets/5hls_a_flip_ligH.pdb')
  lig,gedges=gjf(root/'assets/model_template.gjf'); mol,medges=mol2(root/'assets/62G_optRESP.mol2')
  if (len(pqr),len(full),len(lig),len(gedges),len(mol),len(medges))!=(2577,2619,42,45,42,45) or set(gedges)!=set(medges):raise Env('registered source structures have unexpected counts')
  if any(lig[i]['element']!=mol[i]['element'] for i in range(42)):raise Env('independent ligand element order differs')
  # Validate the independent MOL2 closed-shell neutral valence adapter.
  val={a['idx']:0. for a in mol}; ov={'1':1.,'2':2.,'3':3.,'ar':1.5}
  for (a,b),o in medges.items():val[a]+=ov[o];val[b]+=ov[o]
  target={'H':1.,'C':4.,'N':3.,'O':2.,'Cl':1.}
  if not all(a['element'] in target and abs(val[a['idx']]-target[a['element']])<1e-8 for a in mol):raise Env('independent ligand valence check failed')
  required=('model.pdb','design.json','input.inp','partition.json','report.md')
  if any(not (root/n).is_file() for n in required):raise Bad('missing required deliverable')
  if not (root/'report.md').read_text().strip():raise Bad('report.md must be non-empty')
  model=atoms_pdb(root/'model.pdb'); design=json.loads((root/'design.json').read_text(),parse_float=Decimal); inp=json.loads((root/'input.inp').read_text()); part=json.loads((root/'partition.json').read_text(),parse_float=Decimal)
  # Permit omitted transport/version metadata only. All supplied values still
  # pass the same fixed-value and hash comparisons below.
  if isinstance(design,dict):
   design.setdefault('schema_version','case02-static-model/v2');design.setdefault('task_version','2.0');design.setdefault('evaluation_scope','finite_static_partition_decision')
   design.setdefault('source_assets',EXPECTED)
   if isinstance(design.get('model'),dict):design['model'].setdefault('sha256',sha(root/'model.pdb'))
   if isinstance(design.get('formal_charge_ledger'),dict):design['formal_charge_ledger'].setdefault('schema_version','case02-formal-charge-ledger/v2')
  if isinstance(inp,dict):
   inp.setdefault('schema_version','case02-engine-neutral-input/v2');inp.setdefault('task_version','2.0');inp.setdefault('evaluation_scope','finite_static_partition_decision')
   inp.setdefault('model_sha256',sha(root/'model.pdb'));inp.setdefault('design_sha256',sha(root/'design.json'))
  need(isinstance(design,dict) and set(design)=={'schema_version','task_version','evaluation_scope','system_id','model','source_assets','atoms','partition','formal_charge_ledger','charge_spin','embedding','connectivity','interfaces','contacts'} and design.get('schema_version')=='case02-static-model/v2' and design.get('task_version')=='2.0' and design.get('evaluation_scope')=='finite_static_partition_decision' and design.get('system_id')=='5HLS','unsupported design version/scope/system')
  need(isinstance(inp,dict) and set(inp)=={'schema_version','task_version','evaluation_scope','engine_native','execution_claim','system_id','model_sha256','design_sha256','selected_candidate_id','qm_atom_count','qm_electron_count','qm_formal_charge','qm_multiplicity'} and inp.get('schema_version')=='case02-engine-neutral-input/v2' and inp.get('task_version')=='2.0' and inp.get('evaluation_scope')=='finite_static_partition_decision' and inp.get('engine_native') is False and inp.get('execution_claim')=='not_executed','input.inp has unsupported version or execution claim')
  serials=[a['serial'] for a in model]; ids=[(a['chain'],a['resid'],a['res'],a['name']) for a in model]
  need(len(set(serials))==len(serials) and len(set(ids))==len(ids),'model atom identities/serials are not unique')
  need(same_schema(design.get('model'),{'path':'model.pdb','sha256':sha(root/'model.pdb'),'atom_count':len(model)}),'model hash/count mismatch')
  need(same_json(design.get('source_assets'),EXPECTED),'source asset declaration mismatch')
  need(inp.get('model_sha256')==sha(root/'model.pdb') and inp.get('design_sha256')==sha(root/'design.json'),'input hashes mismatch')
  need(same_json(part,design.get('partition')),'partition.json differs from design partition')
  rows=design.get('atoms'); need(isinstance(rows,list) and len(rows)==len(model),'atom mapping count mismatch')
  byserial={a['serial']:a for a in model}; mapped=set(); rowserial={}; gm={}; reg={}
  sourcep={(a['chain'],a['resid'],a['res']):[] for a in pqr}
  for i,a in enumerate(pqr,1):sourcep[(a['chain'],a['resid'],a['res'])].append(i)
  for r in rows:
   # The four following values duplicate information fixed by the submitted
   # model serial and source-row reference. Fill only absent copies, and only
   # after those references are independently range-checked.
   if not isinstance(r,dict):continue
   s=r.get('model_serial');asset=r.get('source_asset');idx=r.get('source_atom_index')
   if not int_json(s) or s not in byserial or asset not in {'5hls_a_flip_H.pqr','model_template.gjf'} or type(idx)is not int:continue
   src=pqr if asset=='5hls_a_flip_H.pqr' else lig
   if not 1<=idx<=len(src):continue
   source_row=src[idx-1];model_atom=byserial[s]
   r.setdefault('element',source_row['element'])
   r.setdefault('atom_name',model_atom['name'])
   r.setdefault('source_identity',({'atom_name':source_row['name'],'residue':source_row['res'],'chain':source_row['chain'],'resid':source_row['resid']} if asset=='5hls_a_flip_H.pqr' else {'source_index':idx,'element':source_row['element'],'source_layer':source_row['layer']}))
   r.setdefault('coordinate_policy','preserve')
  for r in rows:
   need(isinstance(r,dict) and set(r)=={'model_serial','element','atom_name','region','source_asset','source_atom_index','source_identity','coordinate_policy'},'malformed atom mapping/schema'); s=r.get('model_serial'); need(int_json(s) and s in byserial and s not in rowserial,'duplicate/unknown/non-integer model serial mapping')
   rowserial[s]=r; a=byserial[s]
   need(r.get('element')==a['element'] and r.get('atom_name')==a['name'],'model/mapping identity mismatch')
   asset=r.get('source_asset'); idx=r.get('source_atom_index'); need(asset in {'5hls_a_flip_H.pqr','model_template.gjf'},'unsupported atom source')
   src=pqr if asset=='5hls_a_flip_H.pqr' else lig
   need(type(idx)is int and 1<=idx<=len(src),'invalid source row')
   key=(asset,idx); need(key not in mapped,'source row duplicated');mapped.add(key)
   sa=src[idx-1]
   ident=({'atom_name':sa['name'],'residue':sa['res'],'chain':sa['chain'],'resid':sa['resid']} if asset=='5hls_a_flip_H.pqr' else {'source_index':idx,'element':sa['element'],'source_layer':sa['layer']})
   need(same_schema(r.get('source_identity'),ident) and r['element']==sa['element'],'source identity or element mismatch')
   need(r.get('coordinate_policy')=='preserve','task 2.0 permits source-preserved coordinates only')
   need(all(within_decimal_tolerance(x,y,POLICY['coordinate_tolerance_angstrom']) for x,y in zip(a['xyz_decimal'],sa['xyz_decimal'])),'preserved coordinates differ from source')
   reg[s]=r.get('region')
   if asset=='model_template.gjf':gm[idx]=s
  need(mapped=={('5hls_a_flip_H.pqr',i) for i in range(1,len(pqr)+1)}|{('model_template.gjf',i) for i in range(1,len(lig)+1)},'source atoms are omitted or extra')
  need(set(gm)==set(range(1,43)),'ligand atoms are not mapped exactly once')
  source_to_model={r['source_atom_index']:r['model_serial'] for r in rows if r['source_asset']=='5hls_a_flip_H.pqr'}
  # Registered mixed PDB row map confirms PQR and ligand provenance.
  for i,a in enumerate(pqr,1):
   fi=i if i<=2118 else i+42
   b=full[fi-1]
   if a['element']!=b['element'] or a['xyz']!=b['xyz']:raise Env(f'mixed-source PQR row mismatch {i}')
  for i,a in enumerate(lig,1):
   b=full[2117+i]
   if a['xyz']!=b['xyz']:raise Env(f'mixed-source ligand coordinates mismatch {i}')
  units={};
  for i,a in enumerate(pqr,1):units.setdefault((a['chain'] or 'A',a['resid'],a['res']),[]).append((i,a))
  waters={k:v for k,v in units.items() if k[2]=='WAT'}
  for k,v in waters.items():need(sorted(a['name'] for _,a in v)==['HW','HW','OW'],'unsupported source water inventory '+str(k))
  lig_model_xyz={i:byserial[gm[i]]['xyz'] for i in gm}
  env_model_xyz={i:byserial[source_to_model[i]]['xyz'] for i in source_to_model}
  waterdist={k:min(math.dist(lig_model_xyz[i],env_model_xyz[si]) for i,x in enumerate(lig,1) if x['element'] not in {'H','D'} for si,y in v if y['element'] not in {'H','D'}) for k,v in waters.items()}
  eligible=sorted(k for k,d in waterdist.items() if d<=CUT)
  expected_sel=[()]+[(k,) for k in eligible]
  # Canonical charge evidence table is independent of force-field partial charges.
  prot=[k for k in units if k[2]!='WAT']; expected_groups=[]
  for k,v in units.items():
   q=charge(k[2],{a['name'] for _,a in v},k==prot[0],k==prot[-1])
   if q is None:raise Env(f'unsupported source canonical-state inventory {k}')
   expected_groups.append((f'{k[0]}:{k[1]}:{k[2]}',q,{source_to_model[i] for i,_ in v}))
  # Independent domain and all candidate metrics.
  envheavy=[(i,a) for i,a in enumerate(pqr,1) if a['element'] not in {'H','D'}]
  ligheavy=[(i,a) for i,a in enumerate(lig,1) if a['element'] not in {'H','D'}]
  candidates=[]; exact_nearest={}
  def uid(k):return f'{k[0]}:{k[1]}:{k[2]}'
  for sel in expected_sel:
   promoted={i for k in sel for i,_ in waters[k]}; qm_atoms=42+3*len(sel)
   qm_e=sum(Z[a['element']] for a in lig)+sum(Z[a['element']] for k in sel for _,a in waters[k]); covered=0; rem=[]
   for _,la in ligheavy:
    for si,ea in envheavy:
     d=math.dist(lig_model_xyz[_],env_model_xyz[si])
     if d<=CUT and si in promoted:covered+=1
     if si not in promoted:rem.append(d)
   candidate_id='ligand-only' if not sel else 'water:'+uid(sel[0])
   exact_nearest[candidate_id]=min(rem)
   candidate={'candidate_id':candidate_id,'selected_water_units':[] if not sel else [uid(sel[0])],
    'qm_atom_count':qm_atoms,'qm_electron_count':qm_e,'covered_contact_pair_count':covered,'nearest_omitted_contact_angstrom':round(min(rem),POLICY['reported_distance_decimals']),
    'cross_region_covalent_edge_count':0,'expected_embedding_site_count':len(pqr)-len(promoted),'embedding_missing_site_count':0,'embedding_duplicate_site_count':0,'embedding_extra_site_count':0,
    'within_proxy_limits':qm_atoms<=POLICY['max_qm_atom_count'] and qm_e<=POLICY['max_qm_electron_count'],'pareto':False}
   candidates.append(candidate)
  feasible=[c for c in candidates if c['within_proxy_limits']]
  def dom(a,b):
   da=exact_nearest[a['candidate_id']]; db=exact_nearest[b['candidate_id']]
   return (a['qm_atom_count']<=b['qm_atom_count'] and a['covered_contact_pair_count']>=b['covered_contact_pair_count'] and da>=db and (a['qm_atom_count']<b['qm_atom_count'] or a['covered_contact_pair_count']>b['covered_contact_pair_count'] or da>db))
  pareto=[c['candidate_id'] for c in feasible if not any(dom(o,c) for o in feasible if o is not c)]
  for c in candidates:c['pareto']=c['candidate_id'] in pareto
  partition=design.get('partition');need(isinstance(partition,dict) and set(partition)=={'selected_candidate_id','candidate_domain','candidates','pareto_candidate_ids'},'partition decision/schema missing')
  need(same_schema(partition.get('candidate_domain'),{'base_unit':'ligand:62G','unit_kind':'WAT_OW_HW_HW','maximum_selected_waters':1,'proxy_limits':{'qm_atom_count_max':POLICY['max_qm_atom_count'],'qm_electron_count_max':POLICY['max_qm_electron_count']},'cutoff_angstrom':CUT}),'candidate domain declaration mismatch')
  candidate_keys={'candidate_id','selected_water_units','qm_atom_count','qm_electron_count','covered_contact_pair_count','nearest_omitted_contact_angstrom','cross_region_covalent_edge_count','expected_embedding_site_count','embedding_missing_site_count','embedding_duplicate_site_count','embedding_extra_site_count','within_proxy_limits','pareto'}
  submitted_candidates=partition.get('candidates')
  need(isinstance(submitted_candidates,list) and all(isinstance(c,dict) and set(c)==candidate_keys for c in submitted_candidates),'candidate row schema is incomplete or contains undeclared fields')
  need(same_schema(submitted_candidates,candidates),'candidate table incomplete, omitted, or metrics/Pareto are incorrect')
  need(partition.get('pareto_candidate_ids')==pareto,'declared Pareto set is incomplete or incorrect')
  chosen=partition.get('selected_candidate_id');need(chosen in pareto,'selected candidate is not Pareto')
  selected=next(c for c in candidates if c['candidate_id']==chosen); promote=expected_sel[candidates.index(selected)];promoted={i for k in promote for i,_ in waters[k]}
  for r in rows:
   if r['source_asset']=='model_template.gjf':need(r['region']=='qm','ligand must remain a complete QM unit')
   else:need(r['region']==('qm' if r['source_atom_index'] in promoted else 'real'),'PQR unit region differs from selected complete water set')
  ledger_obj=design.get('formal_charge_ledger');need(isinstance(ledger_obj,dict) and set(ledger_obj)=={'schema_version','groups'} and ledger_obj.get('schema_version')=='case02-formal-charge-ledger/v2','formal charge ledger schema missing/invalid')
  ledger=ledger_obj.get('groups'); need(isinstance(ledger,list),'formal charge ledger groups missing')
  observed={}
  for g in ledger:
   need(isinstance(g,dict) and set(g)=={'chemical_unit','formal_charge','region','model_serials'} and type(g.get('formal_charge'))is int and isinstance(g.get('model_serials'),list),'malformed charge ledger group')
   serial_list=g['model_serials'];need(all(int_json(x) for x in serial_list),'ledger model_serials must be strict integers')
   need(len(serial_list)==len(set(serial_list)),'ledger group repeats a model serial')
   need(g.get('chemical_unit') not in observed,'duplicate formal charge unit');observed[g['chemical_unit']]=(g['formal_charge'],set(serial_list),g.get('region'))
  expected={name:(q,ss,'qm' if ss & {source_to_model[i] for i in promoted} else 'real') for name,q,ss in expected_groups}
  expected['ligand:62G']=(0,set(gm.values()),'qm')
  need(set(observed)==set(expected),'formal charge ledger unit inventory incomplete')
  for name,val in expected.items():need(observed[name]==val,f'formal charge ledger mismatch: {name}')
  cs=design.get('charge_spin');need(isinstance(cs,dict) and set(cs)=={'formal_total_charge','total_multiplicity','qm_formal_charge','qm_multiplicity'} and all(int_json(cs.get(k)) for k in ('formal_total_charge','total_multiplicity','qm_formal_charge','qm_multiplicity')) and same_json(cs,{'formal_total_charge':1,'total_multiplicity':1,'qm_formal_charge':0,'qm_multiplicity':1}),'formal charge/spin ledger mismatch')
  qme=selected['qm_electron_count'];need((qme-(cs['qm_multiplicity']-1))%2==0,'QM electron/spin parity invalid')
  qsum=sum(q for _,q,_ in expected_groups);need(qsum==cs['formal_total_charge'],'total charge does not match canonical source ledger')
  conn=design.get('connectivity');need(isinstance(conn,list),'connectivity missing')
  expected_bonds={}
  conv={'1':'single','2':'double','3':'triple','ar':'aromatic'}
  for (a,b),o in medges.items():expected_bonds[tuple(sorted((gm[a],gm[b])))]=conv[o]
  for k in promote:
   v=waters[k]; byname={}
   for i,a in v:byname.setdefault(a['name'],[]).append(source_to_model[i])
   for h in byname['HW']:expected_bonds[tuple(sorted((byname['OW'][0],h)))]='single'
  got={}
  for b in conn:
   need(isinstance(b,dict) and set(b)=={'atoms','bond_type'} and isinstance(b.get('atoms'),list) and len(b['atoms'])==2 and all(int_json(x) for x in b['atoms']),'malformed connectivity edge/schema');pair=tuple(sorted(b['atoms']));need(pair not in got,'duplicate connectivity edge');got[pair]=b.get('bond_type')
  need(got==expected_bonds,'connectivity differs from source ligand graph or selected complete-water graph')
  need(design.get('interfaces')==[],'unsupported covalent cuts/interfaces are not allowed')
  charges={}
  for i,l in enumerate((root/'assets/5hls_a_flip_H.pqr').read_text().splitlines(),1):
   if l.startswith(('ATOM  ','HETATM')):charges[i]=Decimal(l.split()[-2])
  embedding=design.get('embedding');need(isinstance(embedding,dict) and set(embedding)=={'source_atoms'},'embedding object/schema missing')
  sites=embedding.get('source_atoms');need(isinstance(sites,list),'embedding map missing')
  seen={};
  for x in sites:
   need(isinstance(x,dict) and set(x)=={'source_atom_index','model_serial','partial_charge'} and int_json(x.get('source_atom_index')) and int_json(x.get('model_serial')) and finite_number(x.get('partial_charge')),'malformed embedding site/schema'); i=x['source_atom_index'];need(i not in seen and i in charges,'duplicated/unknown embedding row');seen[i]=x
   need(x['model_serial']==source_to_model[i] and i not in promoted,'embedding source mapping/region mismatch')
   need(within_decimal_tolerance(x['partial_charge'],charges[i],POLICY['partial_charge_tolerance']),'embedding partial charge differs from source')
  need(set(seen)==set(charges)-promoted,'embedding has missing or extra fixed source sites')
  # Every measured contact pair is recomputed directly from the submitted coordinates.
  contacts=design.get('contacts');need(isinstance(contacts,dict) and set(contacts)=={'cutoff_angstrom','coordinate_sources','pairs'} and finite_number(contacts.get('cutoff_angstrom')) and contacts.get('cutoff_angstrom')==CUT and same_json(contacts.get('coordinate_sources'),['model_template.gjf','5hls_a_flip_H.pqr']),'contact definition/schema mismatch')
  expected_contacts={}
  for li,la in ligheavy:
   ls=gm[li]; hits=[]
   for si,ea in envheavy:
    d=math.dist(byserial[ls]['xyz'],byserial[source_to_model[si]]['xyz'])
    if d<=CUT:hits.append({'model_serial':source_to_model[si],'distance_angstrom':round(d,POLICY['reported_distance_decimals'])})
   expected_contacts[str(ls)]=sorted(hits,key=lambda x:(x['distance_angstrom'],x['model_serial']))
  need(same_json(contacts.get('pairs'),expected_contacts),'contact pair table is incomplete or incorrect')
  need(inp.get('system_id')=='5HLS' and inp.get('selected_candidate_id')==chosen and all(int_json(inp.get(k)) for k in ('qm_atom_count','qm_electron_count','qm_formal_charge','qm_multiplicity')) and inp.get('qm_atom_count')==selected['qm_atom_count'] and inp.get('qm_electron_count')==selected['qm_electron_count'] and inp.get('qm_formal_charge')==0 and inp.get('qm_multiplicity')==1,'input.inp selected decision differs from design')
 except Env as e:return emit(root,'ENV_INVALID',str(e))
 except (OSError,UnicodeError,json.JSONDecodeError,TypeError,KeyError,ValueError,IndexError,StopIteration) as e:return emit(root,'FAIL',str(e))
 return emit(root,'PASS')
if __name__=='__main__':raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else '.'))
