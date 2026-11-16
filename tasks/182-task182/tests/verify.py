#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Analyze oxygen structure in fixed nonblind water trajectories.
"""Independent Case04 v2 verifier; recomputes finite-N RDF from the public dumps."""
import argparse, hashlib, json, math, sys
from pathlib import Path
import numpy as np
class EvaluationError(Exception): pass

EXPECTED_REFS_SHA256 = "5dd30756649424f06181ff103574238100f32513cbf9d5e0bbc6895492c0090e"


def load_refs():
    path = Path(__file__).resolve().parent / "refs.json"
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_REFS_SHA256:
            raise EvaluationError("trusted grading reference integrity check failed")
        refs = json.loads(raw.decode("utf-8"))
    except EvaluationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"trusted grading references unavailable: {exc}") from exc
    if not isinstance(refs, dict) or refs.get("schema") != "water-case-contract/v2":
        raise EvaluationError("trusted grading references have an unexpected schema")
    return refs

REFS = load_refs()
GRADE = REFS["grading"]
METHOD = REFS["method"]
DR=float(METHOD["dr_A"]); RMAX=float(GRADE["rmax_A"]); BOX=GRADE["box_A"]
N=GRADE["oxygen_count"]; RCUT=GRADE["cutoff_A"]
EXPECTED_MANIFEST_SHA=GRADE["manifest_sha256"]
CONTRACT_VERSION=REFS["contract_version"]

def read(path):
    out=[]
    lines=Path(path).read_text().splitlines(); k=0
    while k<len(lines):
        if lines[k]!='ITEM: TIMESTEP': raise ValueError('dump marker')
        step=int(lines[k+1]); k+=2
        if lines[k]!='ITEM: NUMBER OF ATOMS' or int(lines[k+1])!=GRADE['atom_count']: raise ValueError('atom count')
        k+=2
        if lines[k]!='ITEM: BOX BOUNDS xy xz yz pp pp pp': raise ValueError('box header')
        box=[]
        for x in lines[k+1:k+4]:
            a=list(map(float,x.split()))
            if len(a)!=3 or abs(a[2])>GRADE["box_tilt_tolerance_A"] or abs((a[1]-a[0])-BOX)>GRADE["box_length_tolerance_A"]: raise ValueError('box geometry')
            box.append(a[1]-a[0])
        k+=4
        if not lines[k].startswith('ITEM: ATOMS id type x y z'): raise ValueError('atom columns')
        k+=1; atoms=[]
        for x in lines[k:k+GRADE["atom_count"]]:
            a=x.split(); atoms.append((int(a[0]),int(a[1]),tuple(map(float,a[2:5]))))
        k+=GRADE["atom_count"]; atoms.sort()
        if len({a[0] for a in atoms})!=GRADE["atom_count"]: raise ValueError('duplicate atom IDs')
        if sum(a[1]==1 for a in atoms)!=N or sum(a[1]==2 for a in atoms)!=GRADE["hydrogen_count"]: raise ValueError('atom type counts')
        if not np.all(np.isfinite(np.array([a[2] for a in atoms],dtype=float))): raise ValueError('nonfinite coordinates')
        out.append((step,np.array([a[1] for a in atoms]),np.array([a[2] for a in atoms]),np.array(box)))
    if len(out)!=GRADE["frames"] or [x[0] for x in out]!=list(range(GRADE["step_start"],GRADE["step_stop"]+1,GRADE["step_interval"])): raise ValueError('frame count/steps')
    return out

def hist(frames, edges):
    counts=np.zeros(len(edges)-1,dtype=np.int64); total=0
    for _,typ,pos,box in frames:
        oxy=pos[typ==1]; d=oxy[:,None,:]-oxy[None,:,:]; d-=box*np.rint(d/box)
        tri=np.triu_indices(N,1); r=np.sqrt((d*d).sum(2))[tri]; r=r[r<RMAX]
        counts+=np.histogram(r,edges)[0]; total+=N*(N-1)//2
    return counts,total

def curve(frames,edges,shell):
    h,pairs=hist(frames,edges); return h*np.prod(frames[0][3])/(pairs*shell)

def fields_equal(actual,expected,tol=GRADE["value_tolerance"]):
    a=np.asarray(actual,dtype=float); b=np.asarray(expected,dtype=float)
    return a.shape==b.shape and np.all(np.isfinite(a)) and np.max(np.abs(a-b),initial=0)<=tol

def finite_scalar(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False

def numeric_tree(value):
    if finite_scalar(value):
        return True
    if isinstance(value, list):
        return all(numeric_tree(item) for item in value)
    return False

def number_vector(value, length):
    return isinstance(value,list) and len(value)==length and all(finite_scalar(x) for x in value)

def validate_candidate_types(got):
    """Reject non-schema JSON types before numeric comparisons can coerce them."""
    if not isinstance(got, dict): return False
    if type(got.get('schema')) is not str or type(got.get('contract_version')) is not str: return False
    source=got.get('source_sha256')
    if not isinstance(source,dict) or set(source)!={'0','1'} or any(type(x) is not str for x in source.values()): return False
    method=got.get('method')
    if not isinstance(method,dict): return False
    for key in ('dr_A','rmax_A','cutoff_bin_edge_A'):
        if not finite_scalar(method.get(key)): return False
    for key in ('first_peak_window_A','first_minimum_window_A'):
        value=method.get(key)
        if not isinstance(value,list) or len(value)!=2 or not all(finite_scalar(x) for x in value): return False
    for key in ('normalization','minimum_smoothing','coordination_density'):
        if type(method.get(key)) is not str: return False
    if not number_vector(got.get('bin_edges_A'),125): return False
    for key in ('pooled_first_peak_A','pooled_first_smoothed_minimum_A'):
        if not finite_scalar(got.get(key)): return False
    replicas=got.get('replicas')
    if not isinstance(replicas,list) or len(replicas)!=GRADE["replica_count"]: return False
    for rep in replicas:
        if not isinstance(rep,dict) or type(rep.get('replica')) is not str: return False
        if not number_vector(rep.get('bin_edges_A'),125) or not number_vector(rep.get('bin_centers_A'),124): return False
        for key in ('first_peak_A','first_smoothed_minimum_A','first_shell_cutoff_A'):
            if not finite_scalar(rep.get(key)): return False
        segments=rep.get('segments')
        if not isinstance(segments,list) or len(segments)!=3: return False
        for seg in segments:
            if not isinstance(seg,dict) or type(seg.get('segment')) is not str: return False
            if type(seg.get('frame_count')) is not int: return False
            if not number_vector(seg.get('time_ps'),2) or not number_vector(seg.get('g_r'),124) or not finite_scalar(seg.get('cn_first_shell')): return False
    limits=got.get('interpretation_limits')
    return isinstance(limits,list) and all(type(x) is str for x in limits)

def check(app,assets):
    try:
        manifest_path=assets/'trajectory-manifest.json'
        manifest_bytes=manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest()!=EXPECTED_MANIFEST_SHA: raise EvaluationError('reference manifest SHA mismatch')
        man=json.loads(manifest_bytes)
        groups=[]
        for row in man['trajectory_files']:
            f=assets/row['path']; sha=hashlib.sha256(f.read_bytes()).hexdigest()
            if sha!=row['sha256']: raise ValueError('reference asset mismatch')
            groups.append(read(f))
        edges=np.arange(0,RMAX+DR/2,DR); shell=4*math.pi/3*(edges[1:]**3-edges[:-1]**3); centers=(edges[:-1]+edges[1:])/2
        pool=[fr for group in groups for fr in group]; gp=curve(pool,edges,shell)
        peak_i=np.where((centers>=2.4)&(centers<=3.1))[0][np.argmax(gp[(centers>=2.4)&(centers<=3.1)])]
        sm=np.convolve(gp,np.ones(3)/3,'valid'); sc=centers[1:-1]
        mins=[i for i in range(1,len(sm)-1) if sc[i]>=3 and sc[i]<=4 and i>peak_i-1 and sm[i]<=sm[i-1] and sm[i]<sm[i+1]]
        if not mins: raise ValueError('locked minimum unavailable')
        min_i=mins[0]; cutoff_edge=edges[round((sc[min_i]+DR/2)/DR)]
        if abs(cutoff_edge-RCUT)>GRADE["cutoff_tolerance_A"]: raise ValueError('locked source result does not reproduce contract cutoff')
    except Exception as e:
        raise EvaluationError(f'reference inputs/criteria invalid: {e}')
    try: got=json.loads((app/'final/exploration/rdf-analysis.json').read_text())
    except Exception: return False,'candidate JSON missing or malformed'
    if not isinstance(got,dict): return False,'candidate JSON must be an object'
    if not validate_candidate_types(got): return False,'candidate JSON field types or shapes do not match the public schema'
    if got.get('schema')!='case04-rdf-analysis/v2' or got.get('contract_version')!=CONTRACT_VERSION: return False,'schema/version mismatch'
    if got.get('source_sha256')!={str(i):hashlib.sha256((assets/row['path']).read_bytes()).hexdigest() for i,row in enumerate(man['trajectory_files'])}: return False,'source identity mismatch'
    method=got.get('method')
    required_method={
        'dr_A':DR,
        'rmax_A':RMAX,
        'normalization':'finite_N_unordered_OO_pairs',
        'first_peak_window_A':[2.4,3.1],
        'minimum_smoothing':'centered_3_bin_arithmetic_mean',
        'first_minimum_window_A':[3.0,4.0],
        'cutoff_bin_edge_A':RCUT,
        'coordination_density':'(N_O-1)/V',
    }
    if not isinstance(method,dict) or any(method.get(k)!=v for k,v in required_method.items() if k!='cutoff_bin_edge_A') or not finite_scalar(method.get('cutoff_bin_edge_A')) or abs(method['cutoff_bin_edge_A']-RCUT)>GRADE["cutoff_tolerance_A"]: return False,'method/cutoff mismatch'
    if not fields_equal(got.get('bin_edges_A',[]),edges): return False,'missing or incorrect bins'
    if (not finite_scalar(got.get('pooled_first_peak_A'))
            or not finite_scalar(got.get('pooled_first_smoothed_minimum_A'))
            or abs(got['pooled_first_peak_A']-centers[peak_i])>GRADE["value_tolerance"]
            or abs(got['pooled_first_smoothed_minimum_A']-sc[min_i])>GRADE["value_tolerance"]): return False,'peak/minimum mismatch'
    if len(got.get('replicas',[]))!=2: return False,'replica count mismatch'
    for i,(frames,rep) in enumerate(zip(groups,got['replicas'])):
        if rep.get('replica')!=f'replica-{i:02d}' or not fields_equal(rep.get('bin_edges_A',[]),edges) or not fields_equal(rep.get('bin_centers_A',[]),centers): return False,'replica identity/bin mismatch'
        if (any(not finite_scalar(rep.get(k)) or abs(rep[k]-v)>GRADE["value_tolerance"] for k,v in [('first_peak_A',centers[peak_i]),('first_smoothed_minimum_A',sc[min_i])])
                or not finite_scalar(rep.get('first_shell_cutoff_A')) or abs(rep['first_shell_cutoff_A']-RCUT)>GRADE["cutoff_tolerance_A"]): return False,'replica peak/minimum/cutoff mismatch'
        segs=rep.get('segments',[])
        expected=[]
        for segment in GRADE["segments"]:
            tag,lo,hi=segment["segment"],segment["start_step"],segment["end_step"]
            fs=[fr for fr in frames if lo<=fr[0]<=hi]; expected.append((tag,fs,curve(fs,edges,shell)))
        if len(segs)!=len(GRADE["segments"]): return False,'segment count mismatch'
        for gotseg,(tag,fs,g) in zip(segs,expected):
            cn=(N-1)/np.prod(fs[0][3])*float(np.sum(g[:round(RCUT/DR)]*shell[:round(RCUT/DR)]))
            expected_time=[fs[0][0]*GRADE["time_ps_per_step"],fs[-1][0]*GRADE["time_ps_per_step"]]
            if gotseg.get('segment')!=tag or gotseg.get('frame_count')!=len(fs) or gotseg.get('time_ps')!=expected_time or not fields_equal(gotseg.get('g_r',[]),g): return False,'RDF/segment mismatch'
            if not finite_scalar(gotseg.get('cn_first_shell')) or abs(gotseg['cn_first_shell']-cn)>GRADE["value_tolerance"]: return False,'finite-N first-shell CN mismatch'
    limits=got.get('interpretation_limits',[])
    if not isinstance(limits,list) or not limits or any(type(x) is not str or not x.strip() for x in limits): return False,'nonempty interpretation limits are required'
    return True,'all source-derived RDF curves, fixed cutoff and finite-N CN verified'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--app-dir',type=Path,required=True); p.add_argument('--assets-dir',type=Path,required=True); a=p.parse_args()
    try: ok,msg=check(a.app_dir,a.assets_dir)
    except (ValueError,TypeError,KeyError,OverflowError) as e: ok,msg=False,f'candidate field invalid: {e}'
    except EvaluationError as e: print(json.dumps({'status':'ERROR','task_status':'NOT_EVALUATED','science_status':'INCONCLUSIVE','reward':None,'message':str(e)})); return 2
    except Exception as e: ok,msg=False,f'candidate submission invalid: {e}'
    result={'status':'PASS' if ok else 'FAIL','task_status':'COMPLETED_VALIDATION' if ok else 'FAILED_REQUIREMENTS','science_status':'PASS' if ok else 'FAIL','reward':1 if ok else 0,'message':msg}
    print(json.dumps(result)); return 0 if ok else 1
if __name__=='__main__': sys.exit(main())
