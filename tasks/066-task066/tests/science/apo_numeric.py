#!/usr/bin/env python3
"""Independent, source-driven numeric checks for case-05-apo-cavity-hydration apo hydration evidence.

Candidate region definitions and graph thresholds are parsed from the submitted
artifacts. Unsupported geometry encodings stay JUDGE_REQUIRED; candidate value
mismatches are FAIL and trusted input failures are INFRA.
"""
from __future__ import annotations
import csv, hashlib, json, math, re
from pathlib import Path

class CandidateError(ValueError): pass
class UnsupportedCandidate(ValueError): pass

def _sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _json(path): return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
def _number(v,label):
    if isinstance(v,bool): raise CandidateError(f'{label} must be numeric')
    try: x=float(v)
    except (TypeError,ValueError): raise CandidateError(f'{label} is not numeric')
    if not math.isfinite(x): raise CandidateError(f'{label} is nonfinite')
    return x
def _close(a,b,tol=1e-6): return math.isclose(_number(a,'candidate value'),float(b),rel_tol=0,abs_tol=tol)
def _rounded_value_matches(reported, expected):
    """Compare an analytic value at the decimal precision actually reported."""
    text=str(reported).strip()
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',text):
        raise CandidateError('reported volume must be a finite decimal number')
    mantissa, _, exponent=text.lower().partition('e')
    places=len(mantissa.partition('.')[2]) - (int(exponent) if exponent else 0)
    tolerance=10.0 ** (-places)
    return abs(_number(reported,'reported volume')-float(expected)) <= tolerance
def _int(v,label):
    if isinstance(v,bool): raise CandidateError(f'{label} must be an integer')
    try: x=int(v)
    except (TypeError,ValueError): raise CandidateError(f'{label} must be an integer')
    if str(v).strip() not in (str(x),str(x)+'.0'): raise CandidateError(f'{label} must be an integer')
    return x
def _parse_pair(raw):
    parts=re.split(r'[;,\s-]+',str(raw).strip())
    parts=[x for x in parts if x]
    if len(parts)!=2: raise CandidateError('each reported graph edge must identify exactly two water oxygen atom IDs')
    return tuple(sorted(_int(x,'water oxygen atom ID') for x in parts))
def _judge(summary, checked=None, hashes=None): return {'status':'JUDGE_REQUIRED','summary':summary,'checked_values':checked or {},'source_hashes':hashes or {}}
def _pass(summary,checked=None,hashes=None): return {'status':'PASS','summary':summary,'checked_values':checked or {},'source_hashes':hashes or {}}
def _fail(summary,checked=None,hashes=None): return {'status':'FAIL','summary':summary,'checked_values':checked or {},'source_hashes':hashes or {}}
def _pbc(delta,box):
    import numpy as np
    frac=np.asarray(delta,dtype=float)@np.linalg.inv(np.asarray(box,dtype=float))
    return (frac-np.round(frac))@box

def _normalize_region_definition(definition):
    """Normalize the public axis interval form without changing its geometry."""
    import numpy as np
    d=dict(definition)
    shape=str(d.get('region_shape','')).lower()
    if shape=='cyl': d['region_shape']='cylinder'
    elif shape not in ('sphere','cylinder'): raise UnsupportedCandidate(f'unsupported candidate region shape: {shape}')
    if 'center_nm' in d and 'center_or_axis_nm' not in d:
        d['center_or_axis_nm']=d['center_nm']
    top_radius=d.get('radius_nm',d.get('radius'))
    dims=d.get('dimensions_nm')
    if top_radius is not None:
        top_radius=_number(top_radius,'region radius')
        if top_radius<=0: raise CandidateError('region radius must be positive')
        if isinstance(dims,dict):
            dimension_radius=dims.get('radius_nm',dims.get('radius'))
            if dimension_radius is not None and not math.isclose(_number(dimension_radius,'region dimension radius'),top_radius,rel_tol=0,abs_tol=1e-12):
                raise CandidateError('top-level radius contradicts dimensions_nm radius')
            dims=dict(dims); dims['radius_nm']=top_radius; d['dimensions_nm']=dims
    if shape=='cyl' and 'axis_xy_nm' in d and 'z_range_nm' in d:
        axis=d['axis_xy_nm']; bounds=d['z_range_nm']
        if not isinstance(axis,(list,tuple)) or len(axis)!=2: raise CandidateError('cylinder axis_xy_nm must contain x and y')
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=2: raise CandidateError('cylinder z_range_nm must contain lower and upper bounds')
        zlo,zhi=(_number(v,'cylinder z bound') for v in bounds)
        if zhi<=zlo: raise CandidateError('cylinder z_range_nm must have positive length')
        center=[_number(axis[0],'cylinder axis x'),_number(axis[1],'cylinder axis y'),(zlo+zhi)/2]
        if d.get('center_or_axis_nm') is not None:
            declared=np.asarray(d['center_or_axis_nm'],dtype=float)
            if declared.shape!=(3,) or not np.allclose(declared,center,rtol=0,atol=1e-12):
                raise CandidateError('cylinder axis bounds contradict center_or_axis_nm')
        d['center_or_axis_nm']=center
        dims=dict(d.get('dimensions_nm',{}))
        declared_length=dims.get('length_nm',dims.get('height_nm',dims.get('length')))
        if declared_length is not None and not math.isclose(_number(declared_length,'cylinder length'),zhi-zlo,rel_tol=0,abs_tol=1e-12):
            raise CandidateError('cylinder z_range_nm contradicts dimensions_nm length')
        dims.update({'radius_nm':d.get('radius_nm',d.get('radius')),'length_nm':zhi-zlo})
        d['dimensions_nm']=dims
    dims=d.get('dimensions_nm')
    if isinstance(dims,dict) and 'radius_nm' not in dims and 'radius' not in dims and d.get('radius_nm',d.get('radius')) is not None:
        dims=dict(dims); dims['radius_nm']=d.get('radius_nm',d.get('radius')); d['dimensions_nm']=dims
    center=d.get('center_or_axis_nm',d.get('axis_center_nm'))
    if isinstance(center,dict):
        try:
            x=_number(center.get('x_nm', center.get('x', center.get('X_nm'))),'axis x coordinate')
            y=_number(center.get('y_nm', center.get('y', center.get('Y_nm'))),'axis y coordinate')
            interval=center.get('z_interval_nm', center.get('z_nm', center.get('z_range_nm', center.get('z'))))
            if not isinstance(interval,(list,tuple)) or len(interval)!=2: raise CandidateError('z_interval_nm must contain lower and upper coordinates')
            zlo=_number(interval[0],'axis lower z'); zhi=_number(interval[1],'axis upper z')
        except CandidateError: raise
        if not zhi>zlo: raise CandidateError('axis z interval must have positive length')
        dims=d.get('dimensions_nm')
        if isinstance(dims,dict):
            length=dims.get('length_nm',dims.get('height_nm',dims.get('length')))
            if length is not None and not _close(length,zhi-zlo,1e-8): raise CandidateError('axis z interval length contradicts declared region length')
        d['center_or_axis_nm']=[x,y,(zlo+zhi)/2]
        d['_axis_interval_nm']=[zlo,zhi]
    return d

def _definition_volume(definition):
    import numpy as np
    mask,volume=_region_membership(definition,np.zeros((1,3)),np.eye(3))
    return volume

def _expand_public_regions(document, public_hosts):
    """Read the public top-level host + region_shape grouping without guessing."""
    hosts=document.get('host')
    groups=document.get('region_shape')
    if not isinstance(hosts,list) or not hosts or any(not isinstance(h,str) or not h.strip() for h in hosts):
        raise CandidateError('cavity host must be a nonempty list of host names')
    hosts=[h.strip().upper() for h in hosts]
    if len(hosts)!=len(set(hosts)) or not set(hosts)<=public_hosts:
        raise CandidateError('cavity host list contains duplicate or unknown hosts')
    if not isinstance(groups,dict) or set(groups)-{'primary_choices','sensitivity_variants','rationale'}:
        raise CandidateError('region_shape contains unsupported fields')
    entries=[]
    for key in ('primary_choices','sensitivity_variants'):
        values=groups.get(key,[])
        if not isinstance(values,list): raise CandidateError(f'{key} must be a list')
        for item in values:
            if not isinstance(item,dict): raise CandidateError('each region choice must be an object')
            if not isinstance(item.get('region_id'),str) or not item['region_id'].strip():
                raise CandidateError('region_id must be a nonempty string')
            region=_normalize_region_definition(item)
            region['region_id']=item['region_id'].strip()
            for host in hosts:
                entries.append({**region,'host':host})
    if not entries: raise CandidateError('cavity definition contains no region choices')
    unique={}
    def canonical(value):
        if isinstance(value,bool) or value is None or isinstance(value,str): return value
        if isinstance(value,(int,float)): return round(float(value),12)
        if isinstance(value,(list,tuple)): return tuple(canonical(v) for v in value)
        if isinstance(value,dict): return tuple(sorted((k,canonical(v)) for k,v in value.items()))
        return value
    for region in entries:
        key=(region['host'],region['region_id'])
        # Ignore prose labels when determining whether repeated primary/variant
        # declarations identify the same physical region.
        signature=(region['region_shape'],canonical(region['center_or_axis_nm']),
                   canonical(region['dimensions_nm']),round(_number(region.get('volume_nm3'),'region volume'),12))
        if key in unique and unique[key][0]!=signature:
            raise CandidateError(f'inconsistent duplicate region definition for {key[0]}/{key[1]}')
        unique.setdefault(key,(signature,region))
    return [value[1] for value in unique.values()]

def _region_membership(definition, oxygen, box):
    import numpy as np
    definition=_normalize_region_definition(definition)
    shape=str(definition.get('region_shape','')).lower()
    if shape not in ('cylinder','sphere'): raise UnsupportedCandidate(f'unsupported candidate region shape: {shape}')
    center_raw=definition.get('center_or_axis_nm',definition.get('axis_center_nm'))
    try: center=np.asarray(center_raw,dtype=float)
    except (TypeError,ValueError): raise CandidateError('region center must be a 3-vector in nm')
    if center.shape!=(3,) or not np.isfinite(center).all(): raise CandidateError('region center must be a finite 3-vector in nm')
    delta=np.asarray([_pbc(w-center,box) for w in oxygen]); dims=definition.get('dimensions_nm',{})
    if isinstance(dims,(list,tuple)):
        try: size=[_number(v,'region dimension') for v in dims]
        except CandidateError: raise
        if len(size)!=3 or min(size)<=0: raise CandidateError('list dimensions must be three positive nm lengths')
        if 'cylinder' in shape:
            if not math.isclose(size[0],size[1],rel_tol=0,abs_tol=1e-8): raise UnsupportedCandidate('elliptical cylinder dimensions are not yet supported')
            radius=size[0]/2; length=size[2]
        else:
            if not (math.isclose(size[0],size[1],rel_tol=0,abs_tol=1e-8) and math.isclose(size[1],size[2],rel_tol=0,abs_tol=1e-8)):
                raise UnsupportedCandidate('ellipsoid dimensions are not yet supported as a sphere')
            radius=size[0]/2
    elif isinstance(dims,dict):
        radius_raw=dims.get('radius_nm',dims.get('radius'))
        if radius_raw is None and dims.get('diameter_nm') is not None: radius_raw=_number(dims['diameter_nm'],'region diameter')/2
        radius=_number(radius_raw,'region radius')
        if 'cylinder' in shape:
            length=_number(dims.get('length_nm',dims.get('height_nm',dims.get('length'))),'cylinder length')
    else: raise CandidateError('dimensions_nm must be a mapping or three-value list')
    if radius<=0: raise CandidateError('region radius must be positive')
    if 'cylinder' in shape:
        if length<=0: raise CandidateError('cylinder length must be positive')
        mask=(np.linalg.norm(delta[:,:2],axis=1)<=radius)&(np.abs(delta[:,2])<=length/2); volume=math.pi*radius**2*length
    else:
        mask=np.linalg.norm(delta,axis=1)<=radius; volume=4*math.pi*radius**3/3
    return mask,volume

def _angle(donor_o, donor_h, acceptor_o, box):
    import numpy as np
    vd=_pbc(donor_o-donor_h,box); va=_pbc(acceptor_o-donor_h,box)
    den=float(np.linalg.norm(vd)*np.linalg.norm(va))
    if den==0: return float('nan')
    return math.degrees(math.acos(float(np.clip(np.dot(vd,va)/den,-1,1))))

def _graph(z, frame_row, region_definition, cutoff, angle_cut):
    import numpy as np
    box=z['box_vectors_nm'][frame_row]; waters=z['water_OHH_xyz_nm'][frame_row]; ids=z['water_atom_ids_OHH_1based']; oxy=waters[:,0,:]
    region_mask,_=_region_membership(region_definition,oxy,box); local=np.where(region_mask)[0]
    nodes={int(ids[i,0]):i for i in local}; edges=[]
    for q,ia in enumerate(local):
        for ib in local[q+1:]:
            d=_pbc(oxy[ib]-oxy[ia],box); dist=float(np.linalg.norm(d))
            if not (1e-8<dist<=cutoff): continue
            best=-1.; donor=-1
            for donor_idx,accept_idx,direction in ((ia,ib,d),(ib,ia,-d)):
                for hi in (1,2):
                    dh=_pbc(waters[donor_idx,hi]-oxy[donor_idx],box); vd=-dh; va=direction-dh
                    denom=float(np.linalg.norm(vd)*np.linalg.norm(va))
                    ang=math.degrees(math.acos(float(np.clip(np.dot(vd,va)/denom,-1,1)))) if denom else float('nan')
                    if ang>best: best=ang; donor=int(ids[donor_idx,hi])
            if best>=angle_cut: edges.append((int(ids[ia,0]),int(ids[ib,0]),dist,donor,best))
    adj={x:set() for x in nodes}
    for a,b,*_ in edges: adj[a].add(b); adj[b].add(a)
    components=[]; seen=set()
    for node in nodes:
        if node in seen: continue
        stack=[node]; seen.add(node); comp=[]
        while stack:
            v=stack.pop(); comp.append(v)
            for n in adj[v]:
                if n not in seen: seen.add(n); stack.append(n)
        components.append(sorted(comp))
    cyc=sum(max(0,sum(1 for a,b,*_ in edges if a in c and b in c)-len(c)+1) for c in components)
    return {'nodes':nodes,'edges':edges,'components':components,'isolated':sum(len(c)==1 for c in components),'largest':max(map(len,components),default=0),'cycle_rank':cyc}

def evaluate_apo(package_dir,candidate_root,protocol,refs):
    """Evaluate D05 numeric evidence using public source archives and candidate definitions."""
    import numpy as np
    package_dir=Path(package_dir); candidate_root=Path(candidate_root)
    if candidate_root.name=='submission' and (candidate_root.parent/'cavity-definition.json').is_file(): candidate_root=candidate_root.parent
    criteria=[x['criterion'] for x in protocol.get('criteria',[]) if isinstance(x,dict) and x.get('necessary') is True]
    result={c:_judge('Scientific interpretation remains for trusted review.') for c in criteria}
    source_refs=refs.get('source_hashes',{}) if isinstance(refs,dict) else {}
    try:
        for rel,want in source_refs.items():
            if not str(rel).startswith('environment/'): continue
            p=package_dir/rel
            if p.is_symlink() or not p.is_file() or _sha(p)!=want:
                return {'status':'INFRA','criteria':{c:{'status':'INFRA','summary':f'trusted asset hash failed: {rel}','checked_values':{},'source_hashes':{}} for c in criteria}}
        assets=package_dir/'environment/assets'; out=candidate_root
        required=('cavity-definition.json','occupancy-region-sensitivity.csv','bias-validity-audit.json','wire-geometry.csv')
        missing=[name for name in required if not (out/name).is_file()]
        if missing: raise CandidateError('candidate missing D05 numeric artifact(s): '+', '.join(missing))
        try: definitions=_json(out/'cavity-definition.json')
        except (OSError,ValueError,TypeError) as exc: raise CandidateError(f'candidate cavity-definition.json is invalid: {exc}')
        if not isinstance(definitions,dict): raise CandidateError('cavity-definition must be a JSON object')
        public_hosts={p.stem.split('-coordinate-samples')[0].upper() for p in assets.glob('*-coordinate-samples.npz')}
        regions=(_expand_public_regions(definitions,public_hosts) if 'regions' not in definitions
                 else definitions.get('regions'))
        if not isinstance(regions,list) or not regions: raise CandidateError('cavity definition has no regions')
        if any(not isinstance(x,dict) for x in regions): raise CandidateError('each candidate region definition must be an object')
        regions=[_normalize_region_definition(x) for x in regions]
        occupancy=list(csv.DictReader((out/'occupancy-region-sensitivity.csv').open(newline='',encoding='utf-8')))
        if not occupancy or not {'host','region_id','source_frame_index','time_ps','N_water','region_volume_nm3'}<=set(occupancy[0]): raise CandidateError('occupancy CSV does not expose the required numeric columns')
        # region_id is an occupancy-table key, not a required cavity-definition
        # field in the public schema. When omitted, associate a definition only
        # with a unique host + independently derived analytic volume match.
        row_ids_by_host={}
        for row in occupancy: row_ids_by_host.setdefault(str(row.get('host','')).upper(),set()).add(str(row.get('region_id','')))
        for definition in regions:
            host=str(definition.get('host','')).upper()
            if not host: raise CandidateError('region host is required')
            volume=_definition_volume(definition)
            if not _rounded_value_matches(definition.get('volume_nm3'),volume): raise CandidateError(f'declared volume contradicts region geometry for {host}')
            if not definition.get('region_id'):
                matches=[]
                for region_id in row_ids_by_host.get(host,set()):
                    rows_for_id=[r for r in occupancy if str(r.get('host','')).upper()==host and str(r.get('region_id',''))==region_id]
                    if rows_for_id and all(_rounded_value_matches(r.get('region_volume_nm3'),volume) for r in rows_for_id): matches.append(region_id)
                if len(matches)!=1: raise UnsupportedCandidate(f'{host} region geometry/volume maps to {len(matches)} occupancy region_ids; unique match required')
                definition['region_id']=matches[0]
        declared_region_keys={(str(x.get('host','')).upper(),str(x.get('region_id',''))) for x in regions}
        if len(declared_region_keys)!=len(regions): raise UnsupportedCandidate('multiple cavity definitions map to the same host/region_id; numeric attribution is ambiguous')
        if any((str(r.get('host','')).upper(),str(r.get('region_id',''))) not in declared_region_keys for r in occupancy): raise CandidateError('occupancy row names an undeclared region or unknown host')
        occ_checked={}; unsupported=[]; partial_coverage=False
        z_by_host={}
        claimed_hosts={str(x.get('host','')).upper() for x in regions}
        if not claimed_hosts or not claimed_hosts<=public_hosts: raise CandidateError('candidate region names an unknown host')
        for host in sorted(public_hosts):
            key=host.lower(); src=assets/f'{key}-coordinate-samples.npz'
            with np.load(src,allow_pickle=False) as z:
                z_by_host[host]={k:np.asarray(z[k]) for k in z.files}
        for definition in regions:
            host=str(definition.get('host','')).upper(); region_id=str(definition.get('region_id','')); z=z_by_host[host]
            rows=[r for r in occupancy if r.get('host','').upper()==host and r.get('region_id')==region_id]
            if not rows: raise CandidateError(f'no occupancy rows for candidate region {host}/{region_id}')
            if str(definition.get('atom_selection','')).lower() and 'water oxygen' not in str(definition['atom_selection']).lower():
                unsupported.append(f'{host}/{region_id} atom selection not recognized'); continue
            volume_decl=_number(definition.get('volume_nm3'),'declared region volume')
            total=0; seen=set(); frame_map={int(v):i for i,v in enumerate(z['frame_index'])}
            for row in rows:
                frame=_int(row['source_frame_index'],'occupancy source_frame_index'); i=frame_map.get(frame)
                if i is None: raise CandidateError(f'occupancy row references absent source frame {frame}')
                if (host,region_id,frame) in seen: raise CandidateError('duplicate host/region/frame occupancy row')
                seen.add((host,region_id,frame)); mask,volume=_region_membership(definition,z['water_OHH_xyz_nm'][i,:,0,:],z['box_vectors_nm'][i])
                n=int(mask.sum()); total+=1
                if not _close(row['time_ps'],z['time_ps'][i],1e-6) or _int(row['N_water'],'reported water count')!=n or not _rounded_value_matches(row['region_volume_nm3'],volume) or not _rounded_value_matches(volume_decl,volume):
                    raise CandidateError(f'occupancy/volume mismatch for {host}/{region_id} frame {frame}')
            if not seen: raise CandidateError(f'candidate region {host}/{region_id} has no reported frames')
            occ_checked[f'{host}/{region_id}']={'rows_recomputed':total,'public_frame_count':len(z['frame_index']),'coverage_fraction':total/len(z['frame_index']),'declared_volume_nm3':volume_decl}
            partial_coverage |= total<len(z['frame_index'])
        c0=criteria[0]
        if unsupported: result[c0]=_judge('Reported cavity rows were replayed where possible; one or more region representations need scientific review.',occ_checked)
        elif partial_coverage: result[c0]=_judge('Recomputed every reported PBC cavity occupancy and analytic volume; sparse frame coverage is reported for scientific review.',occ_checked,{str(p.relative_to(package_dir)): _sha(p) for p in package_dir.glob('environment/assets/*coordinate-samples.npz')})
        else: result[c0]=_pass('Recomputed every integer PBC occupancy exactly; analytic volumes were checked at each reported decimal resolution.',occ_checked,{str(p.relative_to(package_dir)): _sha(p) for p in package_dir.glob('environment/assets/*coordinate-samples.npz')})

        try: audit=_json(out/'bias-validity-audit.json')
        except (OSError,ValueError,TypeError) as exc: raise CandidateError(f'candidate bias-validity-audit.json is not valid JSON: {exc}')
        join_checked={}; join_hashes={}; join_ok=True; join_schema_unknown=False
        audit_hosts=audit.get('hosts',audit.get('host_records')) if isinstance(audit,dict) else None
        if audit_hosts is None and isinstance(audit,dict) and isinstance(audit.get('host'),list):
            audit_hosts=[]
            for host in audit['host']:
                if not isinstance(host,str) or not host.strip(): raise CandidateError('bias audit host names must be nonempty strings')
                key=host.strip().upper()
                item={'host':key}
                for field in ('xtc_source_hash','colvar_source_hash','cadences_ps','offset_ps','matched_or_unmatched_pairs','bias_diagnostic','history_scope','weight_validity_decision','exported_npz_sha256'):
                    section=audit.get(field)
                    if isinstance(section,dict):
                        source_key=next((k for k in section if str(k).upper()==key),None)
                        if source_key is not None: item[field]=section[source_key]
                cadence=item.get('cadences_ps')
                if isinstance(cadence,dict) and {'xtc','colvar'}<=set(cadence):
                    item['cadences_ps']={'XTC':cadence['xtc'],'COLVAR_excerpt_median':cadence['colvar']}
                offset=item.get('offset_ps')
                if isinstance(offset,dict) and 'offset_ps' in offset: item['offset_ps']=offset['offset_ps']
                audit_hosts.append(item)
        if not isinstance(audit_hosts,list) or any(not isinstance(x,dict) for x in audit_hosts): raise CandidateError('bias audit must contain a hosts/host_records list of objects')
        expected_hosts={p.stem.split('-coordinate-samples')[0].upper() for p in assets.glob('*-coordinate-samples.npz')}
        if {str(x.get('host','')).upper() for x in audit_hosts}!=expected_hosts: raise CandidateError('bias audit host coverage differs from public coordinate hosts')
        for item in audit_hosts:
            host=str(item.get('host','')).upper(); key=host.lower(); src=assets/f'{key}-coordinate-samples.npz'; bias=assets/f'{key}-bias-audit.csv'; meta=_json(assets/f'{key}-coordinate-provenance.json'); bmeta=_json(assets/f'{key}-bias-audit-provenance.json')
            with np.load(src,allow_pickle=False) as z: times=np.asarray(z['time_ps'],dtype=float); indices=np.asarray(z.get('frame_index',np.arange(len(times))))
            csvrows=list(csv.DictReader(bias.open(newline='',encoding='utf-8'))); tcol='time' if csvrows and 'time' in csvrows[0] else 'time_ps'; btimes=np.asarray([_number(r[tcol],'bias time') for r in csvrows])
            if len(btimes)<2: raise CandidateError(f'{host} bias excerpt lacks enough timestamps')
            unique=np.unique(np.sort(btimes)); dif=np.diff(unique); cadence=float(np.median(dif[dif>0])) if np.any(dif>0) else 0.
            native_idx=np.asarray(meta.get('frame_indices',[]),dtype=float); native_t=np.asarray(meta.get('times_ps',[]),dtype=float)
            native_cad=float(np.median(np.diff(native_t)/np.diff(native_idx))) if len(native_t)>1 and np.all(np.diff(native_idx)>0) else None
            nearest=np.min(np.abs(times[:,None]-btimes[None,:]),axis=1)
            j=item.get('matched_or_unmatched_pairs',{})
            if not isinstance(j,dict): j={}
            tol=float(j.get('join_tolerance_ps',max((native_cad or 0)/2,cadence/2)))
            cad=item.get('cadences_ps',{})
            if not isinstance(cad,dict): join_schema_unknown=True; cad={}
            native_value=cad.get('XTC',cad.get('xtc')); bias_value=cad.get('COLVAR_excerpt_median',cad.get('colvar'))
            if native_value is None or bias_value is None: join_schema_unknown=True; reported_native=native_cad; reported_bias=cadence
            else: reported_native=_number(native_value,'reported XTC cadence'); reported_bias=_number(bias_value,'reported bias cadence')
            max_near=float(nearest.max()); med_near=float(np.median(nearest)); matched=nearest<=tol; actual_offset=float(btimes.min())
            if {'coordinate_sample_count','excerpt_rows','matched_count','unmatched_count','nearest_abs_dt_median_ps','nearest_abs_dt_max_ps','join_tolerance_ps'}<=set(j):
                match=(_int(j.get('coordinate_sample_count'),'coordinate_sample_count')==len(times) and _int(j.get('excerpt_rows'),'excerpt_rows')==len(csvrows) and _int(j.get('matched_count'),'matched_count')==int(matched.sum()) and _int(j.get('unmatched_count'),'unmatched_count')==int((~matched).sum()) and _close(j.get('nearest_abs_dt_median_ps'),med_near,1e-6) and _close(j.get('nearest_abs_dt_max_ps'),max_near,1e-6) and _close(j.get('join_tolerance_ps'),tol,1e-8) and ((matched.any() and _close(j.get('accepted_abs_dt_max_ps'),float(nearest[matched].max()),1e-6)) or (not matched.any() and j.get('accepted_abs_dt_max_ps') is None)))
            elif {'exact_time_in_supplied_excerpt','nearest_time_pairs_within_1.0_ps','unavailable_historical_pairs'}<=set(j):
                exact_count=int(np.count_nonzero(nearest<=1e-6)); within_one=int(np.count_nonzero(nearest<=1.0+1e-12))
                match=(_int(j.get('exact_time_in_supplied_excerpt'),'exact-time count')==exact_count and _int(j.get('nearest_time_pairs_within_1.0_ps'),'nearest-time count')==within_one and _int(j.get('unavailable_historical_pairs'),'unavailable historical count')==len(times)-exact_count)
            elif {'n_exported_frames','frames_on_full_colvar_grid','frames_with_exact_colvar_row_in_supplied_excerpts','unmatched_within_supplied_excerpts','nearest_supplied_excerpt_time_offset_ps'}<=set(j):
                exact_count=int(np.count_nonzero(nearest<=1e-6)); cadence=float(cad.get('COLVAR_excerpt_median',cad.get('colvar',0)))
                first_colvar=float(item.get('offset_ps',actual_offset))
                phase=(times-first_colvar)/cadence if cadence>0 else np.full(len(times),np.nan)
                full_grid=int(np.count_nonzero(np.abs(phase-np.round(phase))<=1e-6))
                near=j.get('nearest_supplied_excerpt_time_offset_ps',{})
                match=(cadence>0 and _int(j['n_exported_frames'],'exported frame count')==len(times)
                    and _int(j['frames_on_full_colvar_grid'],'full-grid frame count')==full_grid
                    and _int(j['frames_with_exact_colvar_row_in_supplied_excerpts'],'exact excerpt frame count')==exact_count
                    and _int(j['unmatched_within_supplied_excerpts'],'unmatched excerpt frame count')==len(times)-exact_count
                    and isinstance(near,dict)
                    and _rounded_value_matches(near.get('min'),float(nearest.min()))
                    and _rounded_value_matches(near.get('median'),float(np.median(nearest)))
                    and _int(near.get('n_within_0.25_ps'),'nearest within 0.25 ps')==int(np.count_nonzero(nearest<=.25+1e-12))
                    and _int(near.get('n_within_0.50_ps'),'nearest within 0.50 ps')==int(np.count_nonzero(nearest<=.50+1e-12)))
                if match: join_schema_unknown=True
            else:
                match=False; join_schema_unknown=True
            cadence_match=(native_cad is None or (reported_native is not None and _close(reported_native,native_cad,0.02))) and (reported_bias is not None and _close(reported_bias,cadence,1e-6))
            offset_match=_close(item.get('offset_ps'),actual_offset,1e-6) if 'offset_ps' in item else True
            match=match and cadence_match and offset_match
            join_ok &= match
            join_checked[host]={'coordinate_samples':len(times),'excerpt_rows':len(csvrows),'exact_count':int(np.count_nonzero(nearest<=1e-6)),'within_1ps':int(np.count_nonzero(nearest<=1.0+1e-12)),'matched':int(matched.sum()),'unmatched':int((~matched).sum()),'nearest_abs_dt_median_ps':med_near,'nearest_abs_dt_max_ps':max_near,'join_tolerance_ps':tol,'native_cadence_ps':native_cad,'excerpt_cadence_ps':cadence,'cadence_match':cadence_match,'match':match}
            # Hashes are machine-checkable facts, distinct from raw-source reconstruction.
            coordsha=_sha(src); biassha=_sha(bias); rawxtc=next((v for k,v in meta.get('sha256',{}).items() if k.endswith('.xtc')),None)
            hash_checks={}
            for field,actual in (('coordinate_public_input_sha256',coordsha),('exported_npz_sha256',coordsha),('bias_excerpt_public_input_sha256',biassha),('colvar_source_hash',bmeta.get('sha256')),('xtc_source_hash',rawxtc)):
                if field in item:
                    ok=item[field]==actual
                    hash_checks[field]={'reported':item[field],'source_value':actual,'matches':ok}
                    if not ok: join_ok=False
            join_checked[host]['source_hash_checks']=hash_checks
            join_hashes[str(src.relative_to(package_dir))]=coordsha; join_hashes[str(bias.relative_to(package_dir))]=biassha
        c1=criteria[1]
        if join_schema_unknown and join_ok: result[c1]=_judge('Recomputed available source joins/cadences; candidate uses an unrecognized summary encoding requiring review.',join_checked,join_hashes)
        else: result[c1]=_pass('Recomputed each coordinate-to-bias excerpt nearest-time join and cadence; candidate-reported provenance hashes were checked when present.',join_checked,join_hashes) if join_ok else _fail('Reported bias-time join, cadence or provenance hash differs from source data.',join_checked,join_hashes)

        # Replay graph evidence when the candidate explicitly labels complete local-region summaries.
        wire=list(csv.DictReader((out/'wire-geometry.csv').open(newline='',encoding='utf-8')))
        graph_def=definitions.get('wire_graph_region',{}); graph_id=definitions.get('wire_graph_region_id')
        if not isinstance(graph_def,dict): raise CandidateError('wire_graph_region must be an object')
        graph_regions={}
        for host in sorted(public_hosts):
            choices=[x for x in regions if str(x.get('region_id'))==str(graph_id) and str(x.get('host','')).upper()==host]
            if not choices:
                choices=[x for x in regions if str(x.get('host','')).upper()==host]
            if not choices: continue
            graph_region=dict(choices[0]); graph_region.update(graph_def)
            if 'region_shape' not in graph_region: raise UnsupportedCandidate('graph region shape is not declared')
            graph_region['center_or_axis_nm']=graph_def.get('axis_center_nm',graph_def.get('center_or_axis_nm',graph_region.get('center_or_axis_nm')))
            dim_keys=('radius_nm','length_nm','height_nm','radius','length','diameter_nm')
            graph_dims={k:v for k,v in graph_def.items() if k in dim_keys}
            graph_region['dimensions_nm']=graph_def.get('dimensions_nm',graph_dims or graph_region.get('dimensions_nm'))
            graph_regions[host]=graph_region
        is_summary=lambda row: str(row.get('component_or_ring','')).startswith(('graph-summary','summary;'))
        summaries=[r for r in wire if is_summary(r)]
        edge_rows=[r for r in wire if str(r.get('water_O_ids','')).strip() not in ('','-','none','null') and not is_summary(r)]
        thresholds=set()
        for row in summaries:
            m=re.search(r'cutoff=([0-9.]+)nm\s+angle=([0-9.]+)',row.get('component_or_ring',''))
            if not m: continue
            thresholds.add((float(m.group(1)),float(m.group(2))))
        for row in edge_rows:
            m=re.search(r'cutoff=([0-9.]+)nm(?:\s+|_)angle=([0-9.]+)',row.get('component_or_ring',''))
            if not m: m=re.search(r'O-O\s*<=\s*([0-9.]+)\s*nm.*?angle\s*>=\s*([0-9.]+)\s*deg',row.get('definition',''),re.I)
            if not m: m=re.search(r'O-O\s*<=\s*([0-9.]+)\s*nm.*?DHA\s*>=\s*([0-9.]+)\s*deg',row.get('definition',''),re.I)
            if m: thresholds.add((float(m.group(1)),float(m.group(2))))
        for row in summaries:
            definition=row.get('definition','')
            m=re.search(r'O-O\s*<=\s*([0-9.]+)\s*nm.*?DHA\s*>=\s*([0-9.]+)\s*deg',definition,re.I)
            if m: thresholds.add((float(m.group(1)),float(m.group(2))))
        # Some public-permitted bounded graph rows carry the graph definition
        # beside each edge rather than in cavity-definition.wire_graph_region.
        # Normalize only a unique, explicit cylinder definition from that text.
        if not graph_def and edge_rows:
            for host in sorted(public_hosts):
                host_rows=[r for r in edge_rows if str(r.get('host','')).upper()==host]
                if not host_rows: continue
                specs=[]
                for row in host_rows:
                    text=row.get('definition','')
                    ball=re.search(r'probe\s*=\s*ball\s+R\s*=\s*([0-9.]+)\s*nm\s+about\s+axis\s+active\s+point\s*\(([^,]+),([^,]+),([^\)]+)\)',text,re.I)
                    if ball:
                        specs.append(('sphere',float(ball.group(1)),tuple(float(ball.group(i)) for i in (2,3,4))))
                        continue
                    rm=re.search(r'r\s*<=\s*([0-9.]+)\s*nm',text,re.I)
                    zm=re.search(r'\|z\s*-\s*([0-9.]+)\|\s*<=\s*([0-9.]+)\s*nm',text,re.I)
                    if not rm or not zm: continue
                    specs.append((float(rm.group(1)),float(zm.group(1)),float(zm.group(2))))
                if not specs: continue
                if len(set(specs))!=1: raise UnsupportedCandidate(f'{host} wire rows contain ambiguous region definitions')
                if specs[0][0]=='sphere':
                    _,radius,center=specs[0]
                    graph_regions[host]={'host':host,'region_shape':'sphere','center_or_axis_nm':list(center),
                        'dimensions_nm':{'radius_nm':radius},'volume_nm3':4*math.pi*radius**3/3,
                        'atom_selection':'water oxygen only'}
                    continue
                radius,zc,half_length=specs[0]
                axis=next((r for r in regions if str(r.get('host','')).upper()==host),None)
                if axis is None: continue
                center=axis.get('center_or_axis_nm')
                if not isinstance(center,(list,tuple)) or len(center)!=3: raise UnsupportedCandidate(f'{host} wire region has no explicit host-aligned x/y axis')
                graph_regions[host]={'host':host,'region_shape':'cylinder','center_or_axis_nm':[center[0],center[1],zc],
                    'dimensions_nm':{'radius_nm':radius,'length_nm':2*half_length},'volume_nm3':math.pi*radius*radius*2*half_length,
                    'atom_selection':'water oxygen only'}
        complete_claim=graph_def.get('complete_graph') is True
        complete=complete_claim
        if complete_claim and (not summaries or not thresholds):
            result[criteria[2]]=_fail('Candidate declares a complete graph but omits parseable component summaries or graph thresholds.')
        elif not thresholds or not (summaries or edge_rows):
            result[criteria[2]]=_judge('No parseable candidate-declared graph thresholds or reported edges were supplied.')
        else:
            graph_check=True; counters={'summary_mismatch':0,'edge_mismatch':0,'edge_missing':0,'edge_distance_mismatch':0,'edge_donor_missing':0,'edge_angle_mismatch':0,'complete_key_mismatch':0,'complete_edge_set_mismatch':0,'subgraph_topology_mismatch':0}; mismatch_samples=[]; details={'thresholds':sorted([list(x) for x in thresholds]),'summary_rows':len(summaries),'edge_rows':len(edge_rows),'complete_graph_claim':complete}; expected_keys=set(); seen_edge=set(); graph_cache={}; frame_maps={h:{int(v):i for i,v in enumerate(z_by_host[h]['frame_index'])} for h in z_by_host}; topology_claims={}; checked_edge_count=0
            def get_graph(host,frame,cutoff,ang):
                key=(host,int(frame),float(cutoff),float(ang))
                if key not in graph_cache:
                    if host not in graph_regions: raise CandidateError(f'candidate graph region does not declare host {host}')
                    i=frame_maps[host][int(frame)]; graph_cache[key]=_graph(z_by_host[host],i,graph_regions[host],float(cutoff),float(ang))
                return graph_cache[key]
            for row in summaries:
                m=re.search(r'cutoff=([0-9.]+)nm\s+angle=([0-9.]+);components=(\d+);isolated_nodes=(\d+);largest_component=(\d+);edges=(\d+);total_cycle_rank=(\d+)',row.get('component_or_ring',''))
                if not m:
                    compact=re.fullmatch(r'summary;waters=(\d+);edges=(\d+);components=(\d+);cycle_rank_total=(\d+)(?:;.*)?',row.get('component_or_ring',''))
                    if not compact: graph_check=False; continue
                    cutoff_angle=next(iter(thresholds),None)
                    host=row['host'].upper(); frame=_int(row['frame_index'],'wire graph frame_index')
                    if cutoff_angle is None or frame not in frame_maps.get(host,{}): graph_check=False; continue
                    g=get_graph(host,frame,*cutoff_angle)
                    actual=(len(g['nodes']),len(g['edges']),len(g['components']),g['cycle_rank'])
                    declared=tuple(map(int,compact.groups()))
                    ids_text=str(row.get('water_O_ids','')).strip()
                    reported_ids=tuple(sorted(_int(x,'summary water oxygen ID') for x in re.split(r'[;,\s]+',ids_text) if x))
                    actual_ids=tuple(sorted(g['nodes']))
                    claimed_components=[tuple(map(int,x)) for x in re.findall(r'comp\d+\[V(\d+),E(\d+),cyc(\d+)\]',row.get('component_or_ring',''))]
                    actual_components=[]
                    for comp in g['components']:
                        edge_count=sum(1 for a,b,*_ in g['edges'] if a in comp and b in comp)
                        actual_components.append((len(comp),edge_count,max(0,edge_count-len(comp)+1)))
                    if (actual!=declared or (reported_ids and reported_ids!=actual_ids)
                            or (not reported_ids and declared[0]!=0)
                            or sorted(claimed_components)!=sorted(actual_components)):
                        graph_check=False; counters['summary_mismatch']+=1
                    key=(host,frame,*cutoff_angle); expected_keys.add(key)
                    continue
                cutoff,ang,comps,isol,largest,edges_n,cycles=m.groups(); host=row['host'].upper(); frame=_int(row['frame_index'],'wire graph frame_index');
                if frame not in frame_maps.get(host,{}): graph_check=False; continue
                g=get_graph(host,frame,float(cutoff),float(ang)); actual=(len(g['components']),g['isolated'],g['largest'],len(g['edges']),g['cycle_rank']); declared=tuple(map(int,(comps,isol,largest,edges_n,cycles)))
                if complete and actual!=declared: graph_check=False; counters['summary_mismatch']+=1
                key=(host,frame,float(cutoff),float(ang)); expected_keys.add(key)
            for row in edge_rows:
                try:
                    host=row['host'].upper(); frame=_int(row['frame_index'],'wire graph frame_index'); pair=_parse_pair(row['water_O_ids']); m=re.search(r'cutoff=([0-9.]+)nm(?:\s+|_)angle=([0-9.]+)',row.get('component_or_ring',''))
                    if not m: m=re.search(r'O-O\s*<=\s*([0-9.]+)\s*nm.*?angle\s*>=\s*([0-9.]+)\s*deg',row.get('definition',''),re.I)
                    if not m: m=re.search(r'O-O\s*<=\s*([0-9.]+)\s*nm.*?DHA\s*>=\s*([0-9.]+)\s*deg',row.get('definition',''),re.I)
                    if not m: graph_check=False; continue
                    cutoff=float(m.group(1)); ang=float(m.group(2)); g=get_graph(host,frame,cutoff,ang)
                    actual=next((e for e in g['edges'] if tuple(sorted(e[:2]))==pair),None)
                    if actual is None or not _close(row['edge_distance_nm'],actual[2],1e-6):
                        graph_check=False; counters['edge_mismatch']+=1; counters['edge_missing' if actual is None else 'edge_distance_mismatch']+=1
                    else:
                        checked_edge_count+=1
                        z=z_by_host[host]; donor_h=_int(row['donor_H_id'],'donor_H_id'); ids=z['water_atom_ids_OHH_1based']; z_index=frame_maps[host][frame]; waters=z['water_OHH_xyz_nm'][z_index]; box=z['box_vectors_nm'][z_index]
                        donor_idx=None; accept_id=None
                        for node_id,other_id in ((pair[0],pair[1]),(pair[1],pair[0])):
                            wi=next((q for q in g['nodes'].values() if int(ids[q,0])==node_id),None)
                            if wi is not None and donor_h in set(map(int,ids[wi,1:])): donor_idx=wi; accept_id=other_id; break
                        if donor_idx is None:
                            graph_check=False; counters['edge_mismatch']+=1; counters['edge_donor_missing']+=1
                        else:
                            hi=int(np.where(ids[donor_idx]==donor_h)[0][0]); accept_idx=next(q for q in g['nodes'].values() if int(ids[q,0])==accept_id)
                            vec=_pbc(waters[accept_idx,0]-waters[donor_idx,0],box); dh=_pbc(waters[donor_idx,hi]-waters[donor_idx,0],box); vd=-dh; va=vec-dh
                            den=float(np.linalg.norm(vd)*np.linalg.norm(va)); candidate_angle=math.degrees(math.acos(float(np.clip(np.dot(vd,va)/den,-1,1)))) if den else float('nan')
                            definition=row.get('definition','')
                            ha_match=re.search(r'H-A\s*<=\s*([0-9.]+)\s*nm',definition,re.I)
                            h_a_distance=float(np.linalg.norm(_pbc(waters[accept_idx,0]-waters[donor_idx,hi],box)))
                            ha_valid=(ha_match is None or h_a_distance<=float(ha_match.group(1))+1e-6)
                            if not math.isfinite(candidate_angle) or candidate_angle<float(ang) or not ha_valid or not _close(row['DHA_angle_deg'],candidate_angle,5e-3):
                                graph_check=False; counters['edge_mismatch']+=1; counters['edge_angle_mismatch']+=1
                                if len(mismatch_samples)<3: mismatch_samples.append({'row':row['water_O_ids'],'frame':frame,'reported_angle':row['DHA_angle_deg'],'recomputed_angle':candidate_angle,'donor_H_id':donor_h})
                    # Legacy human-readable edge rows may also state component
                    # sizes/counts. Validate those claims against the source-
                    # recomputed graph without relying on arbitrary component IDs.
                    description=row.get('component_or_ring','')
                    legacy={key:re.search(rf'(?:^|;){key}=(\d+)(?:;|$)',description) for key in ('nodes','edges','cycle_rank')}
                    node_match=re.search(r'node_O_ids=\[([^\]]*)\]',description)
                    if any(legacy.values()) or node_match:
                        component=next((set(c) for c in g['components'] if pair[0] in c and pair[1] in c),None)
                        if component is None:
                            graph_check=False; counters['subgraph_topology_mismatch']+=1
                        else:
                            component_edges=[e for e in g['edges'] if e[0] in component and e[1] in component]
                            component_cycle=max(0,len(component_edges)-len(component)+1)
                            actual_claims={'nodes':len(component),'edges':len(component_edges),'cycle_rank':component_cycle}
                            for key,match in legacy.items():
                                if match and int(match.group(1))!=actual_claims[key]:
                                    graph_check=False; counters['subgraph_topology_mismatch']+=1
                            if node_match:
                                try: claimed_nodes={int(x.strip()) for x in node_match.group(1).split(',') if x.strip()}
                                except ValueError: claimed_nodes=set(); graph_check=False
                                if claimed_nodes!=component:
                                    graph_check=False; counters['subgraph_topology_mismatch']+=1
                    if (host,frame,cutoff,ang,pair) in seen_edge: graph_check=False
                    seen_edge.add((host,frame,cutoff,ang,pair))
                    claims=re.search(r'subgraph_components=(\d+);subgraph_cycle_rank=(\d+)',row.get('component_or_ring',''))
                    if claims:
                        topology_claims.setdefault((host,frame,cutoff,ang),[]).append(tuple(map(int,claims.groups())))
                except (KeyError,ValueError,TypeError,IndexError): graph_check=False
            if complete:
                hosts=sorted(z_by_host); frames_by_host={h:set(map(int,z_by_host[h]['frame_index'])) for h in hosts}; expected=set((h,f,c,a) for h in hosts for f in frames_by_host[h] for c,a in thresholds)
                if expected_keys!=expected: graph_check=False; counters['complete_key_mismatch']=len(expected.symmetric_difference(expected_keys))
                for host,frame,cutoff,ang in expected:
                    g=get_graph(host,frame,cutoff,ang)
                    actualpairs={tuple(sorted(e[:2])) for e in g['edges']}; reported={pair for h,f,c,a,pair in seen_edge if (h,f,c,a)==(host,frame,cutoff,ang)}
                    if actualpairs!=reported: graph_check=False; counters['complete_edge_set_mismatch']+=len(actualpairs.symmetric_difference(reported))
            details['complete_claim_verified']=bool(complete and graph_check); details['mismatch_counts']=counters; details['mismatch_samples']=mismatch_samples
            details['checked_edge_rows']=checked_edge_count
            # Recompute the topology of each explicitly reported edge subset; this is
            # distinct from claiming that the subset is the complete water graph.
            subgraph_checks={}
            for key in {(h,f,c,a) for h,f,c,a,_ in seen_edge}:
                pairs={pair for h,f,c,a,pair in seen_edge if (h,f,c,a)==key}
                nodes={v for pair in pairs for v in pair}; adjacency={v:set() for v in nodes}
                for a,b in pairs: adjacency[a].add(b); adjacency[b].add(a)
                comps=[]; visited=set()
                for node in nodes:
                    if node in visited: continue
                    stack=[node]; visited.add(node); comp=[]
                    while stack:
                        value=stack.pop(); comp.append(value)
                        for nxt in adjacency[value]:
                            if nxt not in visited: visited.add(nxt); stack.append(nxt)
                    comps.append(comp)
                cycle_rank=sum(max(0,sum(1 for a,b in pairs if a in comp and b in comp)-len(comp)+1) for comp in comps)
                actual_topology=(len(comps),cycle_rank); declared=topology_claims.get(key,[])
                if declared and any(claim!=actual_topology for claim in declared):
                    graph_check=False; counters['subgraph_topology_mismatch']+=1
                subgraph_checks[str(key)]={'nodes':len(nodes),'edges':len(pairs),'components':len(comps),'cycle_rank':cycle_rank,'declared_topology_claims':declared}
            details['reported_subgraph_topology']=subgraph_checks
            if graph_check and complete: result[criteria[2]]=_pass('Recomputed every declared complete per-frame water graph, PBC O-O/D-H-A edge, connected-component summary and cycle rank.',details,{str(p.relative_to(package_dir)):_sha(p) for p in package_dir.glob('environment/assets/*coordinate-samples.npz')})
            elif graph_check and edge_rows: result[criteria[2]]=_judge('Recomputed every reported bounded-subgraph edge and its declared subgraph components/cycle rank; unreported edges and global completeness remain open.',details)
            elif graph_check: result[criteria[2]]=_judge('Graph evidence is incomplete and requires scientific review.',details)
            else: result[criteria[2]]=_fail('Candidate-reported water graph edge geometry, per-frame topology or cycle rank differs from source-coordinate recomputation.',details)
        result[criteria[3]]=_judge('Unbiased occupancy identifiability is a scientific interpretation; verified input excerpts lack full same-configuration historical bias.')
        statuses=[x['status'] for x in result.values()]
        overall='FAIL' if 'FAIL' in statuses else ('INFRA' if 'INFRA' in statuses else ('NEEDS_JUDGE' if 'JUDGE_REQUIRED' in statuses else 'PASS'))
        return {'status':overall,'criteria':result}
    except UnsupportedCandidate as exc:
        # Candidate chose a legal but not yet implemented representation: defer to judge.
        failed=any(x['status']=='FAIL' for x in result.values())
        for c in criteria:
            if result[c]['status']=='JUDGE_REQUIRED': result[c]=_judge(str(exc))
        return {'status':'FAIL' if failed else 'NEEDS_JUDGE','criteria':result}
    except CandidateError as exc:
        return {'status':'FAIL','criteria':{c:_fail(str(exc)) for c in criteria}}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        return {'status':'INFRA','criteria':{c:{'status':'INFRA','summary':str(exc),'checked_values':{},'source_hashes':{}} for c in criteria}}
