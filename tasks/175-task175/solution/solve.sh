#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
ASSETS="$APP_DIR/environment/assets"
mkdir -p "$APP_DIR/final"
PYTHON=${PYTHON:-python3}
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$ASSETS" "$APP_DIR/final/topology.json" <<'PY'
import json, re, sys
from pathlib import Path
import numpy as np
assets, output = map(Path, sys.argv[1:])
LI_CUT, O_CUT = 3.0, 2.6

def load(name):
    lines=(assets/name).read_text().splitlines()
    n=int(lines[0].strip())
    match=re.search(r"cubic\s+box\s+([0-9.eE+-]+)",lines[1],re.I)
    if not match: raise ValueError(f"box length missing in {name}")
    box=float(match.group(1)); elems=[]; coords=[]
    for line in lines[2:]:
        p=line.split()
        if len(p)<4: continue
        elems.append(p[0]); coords.append([float(v) for v in p[1:4]])
    if len(elems)!=n: raise ValueError(f"atom count mismatch in {name}")
    return np.asarray(elems),np.asarray(coords,dtype=float),box

def analyze(elems, xyz, box):
    li=np.flatnonzero(elems=="Li"); oi=np.flatnonzero(elems=="O"); hi=np.flatnonzero(elems=="H")
    def dist(a,b):
        d=a-b; d-=box*np.round(d/box); return np.linalg.norm(d,axis=-1)
    water=set()
    for o in oi:
        if len(hi) and np.any(dist(xyz[hi],xyz[o])<1.25): water.add(int(o))
    oxygen_neighbors=[]
    for i in li:
        oxygen_neighbors.append(set(map(int,oi[dist(xyz[oi],xyz[i])<=O_CUT])))
    parent=list(range(len(li))); sizes=[]
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    pairs=bridged=0; share_water=False; cobridge=False
    for a in range(len(li)):
        for b in range(a+1,len(li)):
            if float(dist(xyz[li[a]],xyz[li[b]]))>LI_CUT: continue
            pairs+=1
            shared=oxygen_neighbors[a]&oxygen_neighbors[b]
            if shared: bridged+=1
            if shared & water: share_water=True
            if (shared & water) and (shared-water): cobridge=True
            ra,rb=find(a),find(b)
            if ra!=rb: parent[rb]=ra
    for i in range(len(li)):
        root=find(i)
        while len(sizes)<=root: sizes.append(0)
        sizes[root]+=1
    components=[x for x in sizes if x]
    return {"n_contact_pairs":pairs,"fraction_oxygen_bridged":bridged/pairs if pairs else 0.0,"max_component_size":max(components,default=0),"fraction_Li_in_components_ge_3":sum(x for x in components if x>=3)/len(li) if len(li) else 0.0,"contacts_share_water":share_water,"anion_can_co_bridge":cobridge}

elem_e,xyz_e,box_e=load("frame_early.xyz")
elem_l,xyz_l,box_l=load("frame_late.xyz")
if not np.array_equal(elem_e,elem_l) or box_e!=box_l: raise ValueError("frames do not describe the same cell")
early=analyze(elem_e,xyz_e,box_e); late=analyze(elem_l,xyz_l,box_l)
# Evidence requires parseable numeric time/population samples and explicit numeric
# uncertainty or sampling-statistics data in the same record; labels alone do not count.
series=list(assets.glob("*population*"))+list(assets.glob("*ensemble*"))
ensemble_established=False
for evidence in series:
    if not evidence.is_file() or evidence.stat().st_size == 0: continue
    rows=[]
    for line in evidence.read_text(errors="ignore").splitlines():
        vals=re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",line)
        if len(vals)>=3: rows.append([float(v) for v in vals])
    if rows and any(any(term in line.lower() for term in ("uncertainty", "stderr", "std", "error", "block")) and re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",line) for line in evidence.read_text(errors="ignore").splitlines()):
        ensemble_established=True
        break
result={"li_li_cutoff_A":LI_CUT,"li_o_cutoff_A":O_CUT,"late":{k:late[k] for k in ("n_contact_pairs","fraction_oxygen_bridged","max_component_size","fraction_Li_in_components_ge_3")},"early":{k:early[k] for k in ("n_contact_pairs","fraction_oxygen_bridged","max_component_size","fraction_Li_in_components_ge_3")},"contacts_share_water":late["contacts_share_water"],"anion_can_co_bridge":late["anion_can_co_bridge"],"chains_present_in_late_frame":late["max_component_size"]>=3,"extended_chains_present_at_classical_start":early["max_component_size"]>=4,"ensemble_population_established":ensemble_established}
output.write_text(json.dumps(result,indent=2)+"\n")
PY
