#!/usr/bin/env bash
# Oracle reference solution for task 151. Real execution against the public inputs;
# no precomputed answers. The solver is embedded so the task keeps a single
# solution entrypoint.
set -euo pipefail

exec python3 - "${1:-$PWD}" <<'PY'
#!/usr/bin/env python3
"""Build a source-mapped model and exhaustive finite static partition table."""
import hashlib, itertools, json, math, os, sys
from pathlib import Path
ASSET_DIR = Path(os.environ.get("SOLUTION_ASSETS", "/app/assets"))

# --- inlined solution/source_model.py helpers ---
"""Small standard-library parsers for the case02 public source files.

This module reads only the four public assets. It has no dependency on the
grader, package tests, cached answers, or external chemistry software.
"""
from pathlib import Path


def parse_pdb(path):
    atoms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        name = line[12:16].strip()
        element = line[76:78].strip().capitalize() or name.lstrip("0123456789")[:1].upper()
        atoms.append({"atom_name": name, "residue": line[17:20].strip(),
                      "chain": line[21:22].strip(), "resid": int(line[22:26]),
                      "element": element,
                      "xyz": tuple(float(line[a:b]) for a,b in ((30,38),(38,46),(46,54)))})
    return atoms


def parse_gjf(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    try:
        cursor = next(i for i,line in enumerate(lines) if line.strip() == "0 1 0 1 0 1") + 1
    except StopIteration as exc:
        raise ValueError("GJF charge/multiplicity header missing") from exc
    atoms = []
    for line in lines[cursor:]:
        f = line.split()
        if len(f) < 5:
            break
        try:
            xyz = tuple(float(x) for x in f[1:4])
        except ValueError:
            break
        atoms.append({"element": f[0].capitalize(), "xyz": xyz, "layer": f[4]})
    cursor += len(atoms)
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    edges = set()
    for line in lines[cursor:]:
        f = line.split()
        if not f:
            continue
        try:
            a = int(f[0])
            if len(f[1:]) % 2:
                raise ValueError("odd GJF connectivity row")
            for n in range(1, len(f), 2):
                b = int(f[n]); float(f[n+1])
                if a == b or a < 1 or b < 1 or a > len(atoms) or b > len(atoms):
                    raise ValueError("GJF connectivity index out of range")
                edges.add(tuple(sorted((a,b))))
        except ValueError as exc:
            raise ValueError("malformed GJF connectivity") from exc
    return atoms, edges


def parse_mol2(path):
    atoms, edges, mode = [], {}, ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line == "@<TRIPOS>ATOM":
            mode = "atoms"; continue
        if line == "@<TRIPOS>BOND":
            mode = "bonds"; continue
        if line.startswith("@<TRIPOS>"):
            mode = ""; continue
        f = line.split()
        if not f:
            continue
        if mode == "atoms":
            atype = f[5].lower()
            element = "Cl" if atype.startswith("cl") else atype.split(".")[0][:1].upper()
            atoms.append({"index": int(f[0]), "name": f[1],
                          "xyz": tuple(float(x) for x in f[2:5]), "element": element,
                          "type": f[5], "partial_charge": float(f[8])})
        elif mode == "bonds":
            pair = tuple(sorted((int(f[1]), int(f[2]))))
            if f[3] not in {"1", "2", "3", "ar"} or pair in edges:
                raise ValueError("unsupported or duplicate MOL2 bond")
            edges[pair] = f[3]
    return atoms, edges


def residue_formal_charge(residue, atom_names, is_n_terminus=False, is_c_terminus=False):
    """Canonical explicit residue charges; never sums PQR partial charges."""
    side = {"LYS": 1, "ARG": 1, "ASP": -1, "GLU": -1}.get(residue, 0)
    supported = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIE",
                 "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL", "WAT"}
    if residue not in supported:
        return None
    required = {
        "LYS": {"NZ", "HZ1", "HZ2", "HZ3"},
        "ARG": {"NE", "HE", "NH1", "NH2", "HH11", "HH12", "HH21", "HH22"},
        "ASP": {"OD1", "OD2"}, "GLU": {"OE1", "OE2"},
        "CYS": {"SG", "HG"}, "TYR": {"OH", "HH"},
    }.get(residue, set())
    if not required <= atom_names:
        return None
    if residue == "ASP" and ({"HD1", "HD2"} & atom_names): return None
    if residue == "GLU" and ({"HE1", "HE2"} & atom_names): return None
    if is_n_terminus:
        if not {"H1", "H2", "H3"} <= atom_names:
            return None
        side += 1
    if is_c_terminus:
        if not ({"OXT", "OT2"} & atom_names):
            return None
        side -= 1
    if residue == "HIE" and ("HE2" not in atom_names or "HD1" in atom_names):
        return None
    return side
# --- end inlined helpers ---
EXPECTED={
 '5hls_a_flip_H.pqr':'e00776fd63b0c8049fe7387b18f4c74a7dd5beb7f06ef1222ee32a1ad989ca85',
 'model_template.gjf':'dbbd3487e50ae5bf7be6673754bdd1fb72ac92f6d9f05f98b1a636ab56a9c28b',
 '5hls_a_flip_ligH.pdb':'aa7b0a0e101c83e3d04458a27c1753d5d80cb9648594e189624a8c71076cd405',
 '62G_optRESP.mol2':'4285423e2bb924a56ac4971da95a5502eca159ebf826cd72db8a48a0bbf2f715'}
Z={'H':1,'C':6,'N':7,'O':8,'F':9,'P':15,'S':16,'Cl':17,'Zn':30}
CUTOFF=4.0
def pdb_xyz(xyz): return tuple(float(f'{v:.3f}') for v in xyz)

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def gjf_qm_charge_spin(path):
 headers=[]
 for line in Path(path).read_text(encoding='utf-8').splitlines():
  fields=line.split()
  if len(fields)==6 and all(x.lstrip('+-').isdigit() for x in fields):
   values=[int(x) for x in fields]
   headers.append(tuple(zip(values[::2],values[1::2])))
 if len(headers)!=1: raise SystemExit('public GJF must contain exactly one six-integer charge/multiplicity header')
 pairs=headers[0]
 if any(mult<1 for _,mult in pairs): raise SystemExit('public GJF multiplicities must be positive')
 # This registered source declares the same state for all three model pairs.
 if any(pair != pairs[0] for pair in pairs[1:]):
  raise SystemExit('registered GJF charge/multiplicity pairs disagree')
 return pairs[0]
def pqr_charges(path):
 out={}
 for i,line in enumerate(Path(path).read_text().splitlines(),1):
  if line.startswith(('ATOM  ','HETATM')): out[i]=float(line.split()[-2])
 return out

def build(out):
 out=Path(out); out.mkdir(parents=True,exist_ok=True)
 paths={n:ASSET_DIR/n for n in EXPECTED}
 for n,h in EXPECTED.items():
  if not paths[n].is_file() or sha(paths[n])!=h: raise SystemExit('public source missing or changed: '+n)
 pqr=parse_pdb(paths['5hls_a_flip_H.pqr']); full=parse_pdb(paths['5hls_a_flip_ligH.pdb'])
 lig,edges=parse_gjf(paths['model_template.gjf']); ligand_formal_charge,ligand_multiplicity=gjf_qm_charge_spin(paths['model_template.gjf']); mol,mol_edges=parse_mol2(paths['62G_optRESP.mol2'])
 if (len(pqr),len(full),len(lig),len(edges),len(mol),len(mol_edges))!=(2577,2619,42,45,42,45) or set(edges)!=set(mol_edges): raise SystemExit('public source has unexpected structure')
 waters={}; residues={}
 for idx,a in enumerate(pqr,1): residues.setdefault((a['chain'] or 'A',a['resid'],a['residue']),[]).append((idx,a))
 for key,atoms in residues.items():
  if key[2]=='WAT':
   names=[a['atom_name'] for _,a in atoms]
   if sorted(names)!=['HW','HW','OW']: raise SystemExit('unsupported water atom inventory '+str(key))
   waters[key]=atoms
 eligible=[]
 for key,atoms in waters.items():
  d=min(math.dist(pdb_xyz(la['xyz']),pdb_xyz(ea['xyz'])) for la in lig if la['element'] not in {'H','D'} for _,ea in atoms if ea['element'] not in {'H','D'})
  if d<=CUTOFF: eligible.append((key,atoms))
 eligible.sort(key=lambda x:x[0])
 # Full map. All input PQR atoms are represented, and all ligand atoms use GJF coordinates.
 rows=[]; pdb=[]; serial=0; counts={}
 for idx,a in enumerate(pqr,1):
  serial+=1; key=(a['chain'] or 'A',a['resid'],a['residue']); counts[key]=counts.get(key,0)+1
  name=a['atom_name']
  if a['residue']=='WAT' and name=='HW': name='H'+str(sum(1 for _,x in residues[key][:counts[key]] if x['atom_name']=='HW'))
  pdb.append((serial,name,a['residue'],a['chain'] or 'A',a['resid'],a['xyz'],a['element']))
  rows.append({'model_serial':serial,'element':a['element'],'atom_name':name,'region':'real','source_asset':'5hls_a_flip_H.pqr','source_atom_index':idx,'source_identity':{k:a[k] for k in ('atom_name','residue','chain','resid')},'coordinate_policy':'preserve'})
 env_serial={i:i for i in range(1,len(pqr)+1)}; ligserial={}
 for idx,a in enumerate(lig,1):
  serial+=1; ligserial[idx]=serial; name=f'L{idx:03d}'
  pdb.append((serial,name,'LIG','L',1,a['xyz'],a['element']))
  rows.append({'model_serial':serial,'element':a['element'],'atom_name':name,'region':'qm','source_asset':'model_template.gjf','source_atom_index':idx,'source_identity':{'source_index':idx,'element':a['element'],'source_layer':a['layer']},'coordinate_policy':'preserve'})
 def unit_id(key): return f'{key[0]}:{key[1]}:{key[2]}'
 # Candidate domain: ligand plus zero or one eligible complete water.
 candidate_selections=[()]+[(w,) for w in eligible]
 env_heavy=[(i,a) for i,a in enumerate(pqr,1) if a['element'] not in {'H','D'}]
 lig_heavy=[(i,a) for i,a in enumerate(lig,1) if a['element'] not in {'H','D'}]
 candidates=[]; exact_nearest={}
 for selection in candidate_selections:
  keys=tuple(item[0] for item in selection); promoted={i for _,atoms in selection for i,_ in atoms}
  waterids=[unit_id(k) for k in keys]; qm_atoms=42+3*len(keys)
  # Selected source waters are complete neutral OW/HW/HW units.
  qm_electrons=sum(Z[a['element']] for a in lig)+sum(Z[a['element']] for _,atoms in selection for _,a in atoms)-ligand_formal_charge
  covered=0; remaining=[]
  for _,la in lig_heavy:
   for si,ea in env_heavy:
    dist=math.dist(pdb_xyz(la['xyz']),pdb_xyz(ea['xyz']))
    if dist<=CUTOFF and si in promoted: covered+=1
    if si not in promoted: remaining.append(dist)
  nearest=min(remaining)
  cid='ligand-only' if not keys else '+'.join('water:'+unit_id(k) for k in keys)
  exact_nearest[cid]=nearest
  # The only supported covalent edges are complete ligand topology and complete-water O-H bonds.
  crossing=0
  expected_sites=len(pqr)-len(promoted)
  c={'candidate_id':cid,
     'selected_water_units':waterids,'qm_atom_count':qm_atoms,'qm_electron_count':qm_electrons,
     'covered_contact_pair_count':covered,'nearest_omitted_contact_angstrom':round(nearest,3),
     'cross_region_covalent_edge_count':crossing,'expected_embedding_site_count':expected_sites,
     'embedding_missing_site_count':0,'embedding_duplicate_site_count':0,'embedding_extra_site_count':0,
     'within_proxy_limits':qm_atoms<=50 and qm_electrons<=210,'pareto':False}
  candidates.append(c)
 feasible=[c for c in candidates if c['within_proxy_limits']]
 def dominates(a,b):
  da=exact_nearest[a['candidate_id']]; db=exact_nearest[b['candidate_id']]
  return (a['qm_atom_count']<=b['qm_atom_count'] and a['covered_contact_pair_count']>=b['covered_contact_pair_count'] and da>=db and (a['qm_atom_count']<b['qm_atom_count'] or a['covered_contact_pair_count']>b['covered_contact_pair_count'] or da>db))
 pareto=[c['candidate_id'] for c in feasible if not any(dominates(other,c) for other in feasible if other is not c)]
 for c in candidates: c['pareto']=c['candidate_id'] in pareto
 # A generic resource-conservative choice: the least-QM-atom member of the computed Pareto set.
 selected=min((c for c in candidates if c['candidate_id'] in pareto),key=lambda c:(c['qm_atom_count'],-c['covered_contact_pair_count'],-c['nearest_omitted_contact_angstrom'],c['candidate_id']))
 chosen={x for x in selected['selected_water_units']}
 # Regions, ledger and embedding follow the selected complete units exactly.
 selected_src={i for key,atoms in waters.items() if unit_id(key) in chosen for i,_ in atoms}
 for r in rows:
  if r['source_asset']=='5hls_a_flip_H.pqr' and r['source_atom_index'] in selected_src: r['region']='qm'
 # Fix PDB atom names are source-normalized above; write records.
 lines=[]
 for s,n,res,ch,rid,xyz,el in pdb:
  lines.append(f'ATOM  {s:5d} {n:>4s} {res:3s} {ch}{rid:4d}    {xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{1.:6.2f}{20.:6.2f}          {el:>2s}  \n')
 model=out/'model.pdb'; model.write_text(''.join(lines)+'END\n')
 pqr_groups={}
 for i,a in enumerate(pqr,1):pqr_groups.setdefault((a['chain'] or 'A',a['resid'],a['residue']),[]).append(i)
 protein=[k for k in pqr_groups if k[2]!='WAT']; groups=[]
 for key,indices in pqr_groups.items():
  q=residue_formal_charge(key[2],{pqr[i-1]['atom_name'] for i in indices},key==protein[0],key==protein[-1])
  if q is None:raise SystemExit('unsupported formal-state atom inventory '+str(key))
  groups.append({'chemical_unit':unit_id(key),'formal_charge':q,'region':'qm' if set(indices)<=selected_src else 'real','model_serials':indices})
 groups.append({'chemical_unit':'ligand:62G','formal_charge':ligand_formal_charge,'region':'qm','model_serials':list(ligserial.values())})
 formal_total_charge=sum(g['formal_charge'] for g in groups)
 qm_formal_charge=sum(g['formal_charge'] for g in groups if g['region']=='qm')
 qm_multiplicity=ligand_multiplicity
 qm_nuclear_charge=sum(Z[a['element']] for a in lig)+sum(Z[a['element']] for key,atoms in waters.items() if unit_id(key) in chosen for _,a in atoms)
 if qm_nuclear_charge-qm_formal_charge!=selected['qm_electron_count']:
  raise SystemExit('selected QM electron count differs from source-derived QM formal charge')
 moltype={'1':'single','2':'double','3':'triple','ar':'aromatic'}
 connectivity=[{'atoms':[ligserial[a],ligserial[b]],'bond_type':moltype[o]} for (a,b),o in sorted(mol_edges.items())]
 for key,atoms in waters.items():
  if unit_id(key) in chosen:
   serial_by_name={}
   for idx,_ in atoms:
    row=next(r for r in rows if r['source_asset']=='5hls_a_flip_H.pqr' and r['source_atom_index']==idx)
    src=row['source_identity']['atom_name']; serial_by_name.setdefault(src,[]).append(row['model_serial'])
   ow=serial_by_name['OW'][0]
   connectivity.extend({'atoms':[ow,h],'bond_type':'single'} for h in serial_by_name['HW'])
 # Contact table includes every <=cutoff heavy pair, including selected and omitted sites.
 contacts={}
 for li,la in lig_heavy:
  ls=ligserial[li]; hits=[]
  for si,ea in env_heavy:
   d=math.dist(pdb_xyz(la['xyz']),pdb_xyz(ea['xyz']))
   if d<=CUTOFF:hits.append({'model_serial':si,'distance_angstrom':round(d,3)})
  contacts[str(ls)]=sorted(hits,key=lambda x:(x['distance_angstrom'],x['model_serial']))
 phash=sha(model); design={
  'schema_version':'case02-static-model/v2','task_version':'2.0','evaluation_scope':'finite_static_partition_decision','system_id':'5HLS',
  'model':{'path':'model.pdb','sha256':phash,'atom_count':len(pdb)},'source_assets':EXPECTED,'atoms':rows,
  'partition':{'selected_candidate_id':selected['candidate_id'],'candidate_domain':{'base_unit':'ligand:62G','unit_kind':'WAT_OW_HW_HW','maximum_selected_waters':1,'proxy_limits':{'qm_atom_count_max':50,'qm_electron_count_max':210},'cutoff_angstrom':4.0},'candidates':candidates,'pareto_candidate_ids':pareto},
  'formal_charge_ledger':{'schema_version':'case02-formal-charge-ledger/v2','groups':groups},
  # Outer total multiplicity is an interface convention for the classical environment.
  'charge_spin':{'formal_total_charge':formal_total_charge,'total_multiplicity':1,'qm_formal_charge':qm_formal_charge,'qm_multiplicity':qm_multiplicity},
  'embedding':{'source_atoms':[{'source_atom_index':i,'model_serial':i,'partial_charge':q} for i,q in pqr_charges(paths['5hls_a_flip_H.pqr']).items() if i not in selected_src]},
  'connectivity':connectivity,'interfaces':[],
  'contacts':{'cutoff_angstrom':CUTOFF,'coordinate_sources':['model_template.gjf','5hls_a_flip_H.pqr'],'pairs':contacts}}
 dp=out/'design.json'; dp.write_text(json.dumps(design,sort_keys=True,indent=2)+'\n')
 (out/'partition.json').write_text(json.dumps(design['partition'],sort_keys=True,indent=2)+'\n')
 inp={'schema_version':'case02-engine-neutral-input/v2','task_version':'2.0','evaluation_scope':'finite_static_partition_decision','engine_native':False,'execution_claim':'not_executed','system_id':'5HLS','model_sha256':phash,'design_sha256':sha(dp),'selected_candidate_id':selected['candidate_id'],'qm_atom_count':selected['qm_atom_count'],'qm_electron_count':selected['qm_electron_count'],'qm_formal_charge':qm_formal_charge,'qm_multiplicity':qm_multiplicity}
 (out/'input.inp').write_text(json.dumps(inp,sort_keys=True,indent=2)+'\n')
 (out/'report.md').write_text(f"""# Case02 static partition decision (task 2.0)\n\nThe selected member is `{selected['candidate_id']}`. It uses {selected['qm_atom_count']} QM atoms and {selected['qm_electron_count']} QM electrons, captures {selected['covered_contact_pair_count']} declared 4.0 Å heavy-atom contact pairs in complete QM units, and leaves a nearest omitted contact of {selected['nearest_omitted_contact_angstrom']:.3f} Å. The table contains all {len(candidates)} candidates from the declared finite domain; {len(pareto)} are non-dominated under the three published proxies.\n\nThe 4.0 Å contact count, nearest omitted distance, atom/electron caps and Pareto comparison are reproducible static descriptors. They do not estimate QM error or establish physical boundary sufficiency. No QM calculation was run. Protein residues remain whole in the fixed-charge environment because the registered PQR does not supply a protein covalent graph. Water promotions use complete OW/HW/HW source units only.\n""")

def main():build(sys.argv[1] if len(sys.argv)>1 else '.')
if __name__=='__main__':main()

PY
