#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
ASSETS="${CASE03_DATA_ROOT:-$APP/environment/assets}"
OUTPUT="${ANSWER_PATH:-$APP/final/answer.json}"
mkdir -p "$APP" "$(dirname "$OUTPUT")"
WORK="$(mktemp -d)"
cleanup() { status=$?; trap - EXIT; rm -rf "$WORK"; exit "$status"; }
trap cleanup EXIT
cat > "$WORK/implementation.py" <<'CCW_TASK51_IMPLEMENTATION_PY_EOF'
#!/usr/bin/env python3
"""Reference candidate API for the archived Case03 reconstruction task."""
from __future__ import annotations
import math, struct, zipfile, pickletools

SHAPES=((48,4),(48,), (24,48),(24,), (12,24),(12,), (1,12),(1,))
LAYER_NAMES=('fc1','fc2','fc3','out')


def _finite(value):
    try: return math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError): return False


def _shape(array,shape):
    if len(shape)==1:
        if not isinstance(array,(list,tuple)) or len(array)!=shape[0] or any(not _finite(x) for x in array):
            raise ValueError('checkpoint vector shape/value invalid')
    else:
        if not isinstance(array,(list,tuple)) or len(array)!=shape[0]: raise ValueError('checkpoint matrix shape invalid')
        for row in array:
            if not isinstance(row,(list,tuple)) or len(row)!=shape[1] or any(not _finite(x) for x in row):
                raise ValueError('checkpoint matrix shape/value invalid')


def _layers(checkpoint):
    if not isinstance(checkpoint,dict) or set(checkpoint)!={'layers'}: raise ValueError('checkpoint must contain layers')
    layers=checkpoint['layers']
    if not isinstance(layers,(list,tuple)) or len(layers)!=4: raise ValueError('checkpoint layer count invalid')
    result=[]
    for i,(entry,weight_shape,bias_shape) in enumerate(zip(layers,SHAPES[::2],SHAPES[1::2])):
        if not isinstance(entry,dict) or set(entry)!={'weight','bias'}: raise ValueError('checkpoint layer fields invalid')
        _shape(entry['weight'],weight_shape);_shape(entry['bias'],bias_shape)
        result.append((entry['weight'],entry['bias']))
    return result


def forward_and_grad(angles,checkpoint):
    if not isinstance(angles,(list,tuple)) or len(angles)!=2 or not all(_finite(x) for x in angles):
        raise ValueError('angles must be two finite radians [phi, psi]')
    phi,psi=map(float,angles);layers=_layers(checkpoint)
    values=[math.sin(phi),math.sin(psi),math.cos(phi),math.cos(psi)]
    pre=[];acts=[values]
    for weight,bias in layers[:-1]:
        z=[float(bias[i])+sum(float(weight[i][j])*acts[-1][j] for j in range(len(acts[-1]))) for i in range(len(bias))]
        pre.append(z);acts.append([max(0.0,x) for x in z])
    weight,bias=layers[-1]
    energy=float(bias[0])+sum(float(weight[0][j])*acts[-1][j] for j in range(len(acts[-1])))
    grad=[float(x) for x in weight[0]]
    for (weight,_),z in zip(reversed(layers[:-1]),reversed(pre)):
        grad=[sum(grad[i]*(1.0 if z[i]>0.0 else 0.0)*float(weight[i][j]) for i in range(len(z))) for j in range(len(weight[0]))]
    return {'bias_kj_mol':energy,
            'dV_dphi_kj_mol_rad':grad[0]*math.cos(phi)-grad[2]*math.sin(phi),
            'dV_dpsi_kj_mol_rad':grad[1]*math.cos(psi)-grad[3]*math.sin(psi)}


class _DualScalar:
    def __init__(self,value,gradient): self.v=float(value);self.g=gradient
class _DualVector:
    def __init__(self,value,gradient): self.v=value;self.g=gradient

def _dual_vector(value,atom):
    g=[[0.0]*66 for _ in range(3)]
    for j in range(3):g[j][3*atom+j]=1.0
    return _DualVector([float(v) for v in value],g)
def _vsub(a,b):return _DualVector([a.v[k]-b.v[k] for k in range(3)],[[a.g[k][j]-b.g[k][j] for j in range(66)] for k in range(3)])
def _vdot(a,b):
    v=sum(a.v[k]*b.v[k] for k in range(3))
    g=[sum(a.g[k][j]*b.v[k]+a.v[k]*b.g[k][j] for k in range(3)) for j in range(66)]
    return _DualScalar(v,g)
def _vcross(a,b):
    v=[a.v[1]*b.v[2]-a.v[2]*b.v[1],a.v[2]*b.v[0]-a.v[0]*b.v[2],a.v[0]*b.v[1]-a.v[1]*b.v[0]]
    g=[[0.0]*66 for _ in range(3)]
    for j in range(66):
        da=[a.g[k][j] for k in range(3)];db=[b.g[k][j] for k in range(3)]
        c=[da[1]*b.v[2]-da[2]*b.v[1]+a.v[1]*db[2]-a.v[2]*db[1],
           da[2]*b.v[0]-da[0]*b.v[2]+a.v[2]*db[0]-a.v[0]*db[2],
           da[0]*b.v[1]-da[1]*b.v[0]+a.v[0]*db[1]-a.v[1]*db[0]]
        for k in range(3):g[k][j]=c[k]
    return _DualVector(v,g)
def _vscale(s,a):return _DualVector([s.v*a.v[k] for k in range(3)],[[a.v[k]*s.g[j]+s.v*a.g[k][j] for j in range(66)] for k in range(3)])
def _vdiv(a,s):return _DualVector([a.v[k]/s.v for k in range(3)],[[a.g[k][j]/s.v-a.v[k]*s.g[j]/(s.v*s.v) for j in range(66)] for k in range(3)])
def _torsion(points,atoms):
    p=[_dual_vector(points[k],atom) for k,atom in enumerate(atoms)]
    b0=_vsub(p[0],p[1]);b1=_vsub(p[2],p[1]);b2=_vsub(p[3],p[2])
    q=_vdot(b1,b1);length=math.sqrt(q.v)
    if length<=1e-12: raise ValueError('degenerate torsion bond')
    length_dual=_DualScalar(length,[x/(2.0*length) for x in q.g])
    axis=_vdiv(b1,length_dual)
    v=_vsub(b0,_vscale(_vdot(b0,axis),axis));w=_vsub(b2,_vscale(_vdot(b2,axis),axis))
    xx=_vdot(v,w);yy=_vdot(_vcross(axis,v),w)
    denom=xx.v*xx.v+yy.v*yy.v
    if denom<=1e-24: raise ValueError('undefined torsion')
    angle=math.atan2(yy.v,xx.v)
    gradient=[(xx.v*yy.g[j]-yy.v*xx.g[j])/denom for j in range(66)]
    return angle,gradient

def _wrapped_points(coords,atoms,box):
    # Place successive bonds in the nearest orthorhombic image; each unwrapped
    # coordinate retains the identity Jacobian away from image boundaries.
    raw=[coords[i] for i in atoms]; placed=[list(raw[0])]
    for i in range(1,4):
        delta=[raw[i][k]-raw[i-1][k] for k in range(3)]
        delta=[delta[k]-round(delta[k]/box[k])*box[k] for k in range(3)]
        placed.append([placed[-1][k]+delta[k] for k in range(3)])
    return placed

def frame_force(coords_nm,box_nm,checkpoint):
    if not isinstance(coords_nm,(list,tuple)) or len(coords_nm)!=22: raise ValueError('coords_nm must contain 22 atoms')
    if any(not isinstance(row,(list,tuple)) or len(row)!=3 or any(not _finite(x) for x in row) for row in coords_nm):
        raise ValueError('coords_nm must be finite 22x3')
    if not isinstance(box_nm,(list,tuple)) or len(box_nm)!=3 or any(not _finite(x) or float(x)<=0 for x in box_nm):
        raise ValueError('box_nm must be three positive orthorhombic lengths')
    box=list(map(float,box_nm));coords=[[float(x) for x in row] for row in coords_nm]
    phi_atoms=(4,6,8,14);psi_atoms=(6,8,14,16)
    pphi=_wrapped_points(coords,phi_atoms,box);ppsi=_wrapped_points(coords,psi_atoms,box)
    phi,gphi=_torsion(pphi,phi_atoms);psi,gpsi=_torsion(ppsi,psi_atoms)
    value=forward_and_grad([phi,psi],checkpoint)
    angle_grad=(value['dV_dphi_kj_mol_rad'],value['dV_dpsi_kj_mol_rad'])
    force=[[-(angle_grad[0]*gphi[3*i+j]+angle_grad[1]*gpsi[3*i+j]) for j in range(3)] for i in range(22)]
    return {'phi_rad':phi,'psi_rad':psi,'bias_kj_mol':value['bias_kj_mol'],'force_kj_mol_nm':force}


def _wrap_angle(a):return (a+math.pi)%(2.0*math.pi)-math.pi

def _core_of(phi,psi,contract):
    hits=[]
    for name,center in contract['cores_rad'].items():
        dx=_wrap_angle(phi-float(center[0]));dy=_wrap_angle(psi-float(center[1]))
        if math.hypot(dx,dy)<=float(contract['core_radius_rad']):hits.append(name)
    if len(hits)>1:raise ValueError('overlapping analysis cores')
    return hits[0] if hits else None

def _arm_summary(rows,contract):
    if not isinstance(rows,(list,tuple)) or not rows:raise ValueError('analysis arm must have rows')
    stride=int(contract['stride_steps']);counts={k:0 for k in contract['cores_rad']};trans=[]
    last=None;active=None;streak=0;prevstep=None
    for row in rows:
        if not isinstance(row,dict) or not {'step','time_ps','phi_rad','psi_rad'}<=set(row):raise ValueError('malformed analysis row')
        if type(row['step']) is not int:raise ValueError('analysis step must be an integer')
        step=row['step'];time=float(row['time_ps']);phi=float(row['phi_rad']);psi=float(row['psi_rad'])
        if not all(_finite(x) for x in (time,phi,psi)) or abs(time-step*float(contract['dt_ps']))>1e-8:
            raise ValueError('invalid row time or CV')
        if prevstep is not None and step-prevstep!=stride:raise ValueError('analysis rows have gap or bad ordering')
        core=_core_of(phi,psi,contract)
        if core is None:active=None;streak=0
        elif core==active:streak+=1
        else:active=core;streak=1
        if core is not None and streak==int(contract['minimum_consecutive_samples']):
            counts[core]+=1
            if last is not None and last!=core:trans.append({'from':last,'to':core,'step':step})
            last=core
        prevstep=step
    return {'rows':len(rows),'first_step':int(rows[0]['step']),'last_step':int(rows[-1]['step']),'core_visits':counts,'qualified_intercore_transitions':trans}

def _static_weights(rows,contract):
    beta=1.0/(float(contract['gas_constant_kj_mol_k_K'])*float(contract['temperature_K']))
    logs=[]
    for row in rows:
        if 'bias_kj_mol' not in row or not _finite(row['bias_kj_mol']):raise ValueError('static VES row requires finite bias_kj_mol')
        logs.append(beta*float(row['bias_kj_mol']))
    m=max(logs);weights=[math.exp(x-m) for x in logs];den=sum(weights)
    if not math.isfinite(den) or den<=0:raise ValueError('invalid stable reweight normalizer')
    core_w={k:0.0 for k in contract['cores_rad']};core_sum={k:0.0 for k in contract['cores_rad']};core_sq={k:0.0 for k in contract['cores_rad']}
    for row,w in zip(rows,weights):
        core=_core_of(float(row['phi_rad']),float(row['psi_rad']),contract)
        if core is not None:core_w[core]+=w/den;core_sum[core]+=w;core_sq[core]+=w*w
    ess_by={k:(core_sum[k]*core_sum[k]/core_sq[k] if core_sq[k] else 0.0) for k in core_w}
    return {'temperature_K':float(contract['temperature_K']),'gas_constant_kJ_mol_K':float(contract['gas_constant_kj_mol_k_K']),'beta_mol_per_kJ':beta,'log_weight_convention':'logw=+beta*V','log_normalizer':m+math.log(den),'normalized_weight_sum':sum(w/den for w in weights),'core_mass':core_w,'raw_kish_ess_by_core':ess_by,'raw_kish_ess_global':den*den/sum(w*w for w in weights),'qualification':'RAW_IMPORTANCE_SUPPORT_DIAGNOSTIC_ONLY','limitations':'Not time-corrected ESS, FES, or a scientific decision gate.'}

def analyze(train,ves,control,contract):
    if not isinstance(contract,dict):raise ValueError('contract must be a mapping')
    if type(contract.get('native_science_pass')) is not bool:raise ValueError('native_science_pass must be Boolean')
    arms={name:_arm_summary(rows,contract) for name,rows in [('train',train),('ves',ves),('control',control)]}
    start=int(contract['static_window_start_step']);end=int(contract['static_window_end_step'])
    if start>end:raise ValueError('static window start exceeds end')
    static_rows=[row for row in ves if start<=int(row['step'])<=end]
    if not static_rows:raise ValueError('static window contains no VES frames')
    static=_static_weights(static_rows,contract)
    common=sorted(k for k,m in static['core_mass'].items() if m>0 and arms['control']['core_visits'][k]>0)
    return {'freeze':{'checkpoint_iteration':int(contract['checkpoint_iteration']),'forced_freeze_step':int(contract['forced_freeze_step']),'forced_freeze_time_ps':float(contract['forced_freeze_time_ps']),'convergence_claim':False},
            'static_window':{'arm':'ves','first_step':int(static_rows[0]['step']),'last_step':int(static_rows[-1]['step']),'rows':len(static_rows),'checkpoint_iteration':int(contract['checkpoint_iteration'])},
            'arms':arms,
            'static_ves_reweighting':static,
            'common_support':{'cores_with_positive_weighted_ves_mass_and_control_visits':common,'qualification':'EMPIRICAL_CORE_OVERLAP_ONLY'},
            'evidence_limits':{'native_terminal_status':contract['native_terminal_status'],'native_science_pass':contract['native_science_pass'],'fes_status':'NOT_ASSESSED_NO_APPROVED_REFERENCE','time_corrected_ess_status':'NOT_ASSESSED_NO_APPROVED_METHOD','scope':'historical archived finite instance only; no fresh MD, convergence, FES accuracy, or general-method claim'}}


def checkpoint_from_file(path):
    """Decode this pinned Torch ZIP without pickle execution or Torch import."""
    prefix='model.iter-1500/'
    with zipfile.ZipFile(path) as z:
        meta=z.read(prefix+'data.pkl');ops=list(pickletools.genops(meta))
        globals_={arg for op,arg,_ in ops if op.name=='GLOBAL'}
        allowed={'__torch__ Module',*(f'__torch__.___torch_mangle_{i} Module' for i in range(4)),'torch._utils _rebuild_tensor_v2','torch FloatStorage','collections OrderedDict'}
        if not globals_<=allowed:raise ValueError('unexpected checkpoint pickle globals')
        arrays=[]
        for i,shape in enumerate(SHAPES):
            raw=z.read(prefix+f'data/{i}');n=math.prod(shape)
            if len(raw)!=4*n:raise ValueError('checkpoint storage shape mismatch')
            flat=struct.unpack('<'+'f'*n,raw)
            if len(shape)==1:arr=list(flat)
            else:arr=[list(flat[r*shape[1]:(r+1)*shape[1]]) for r in range(shape[0])]
            arrays.append(arr)
    return {'layers':[{'weight':arrays[i],'bias':arrays[i+1]} for i in (0,2,4,6)]}
CCW_TASK51_IMPLEMENTATION_PY_EOF
cat > "$WORK/solve.py" <<'CCW_TASK51_SOLVE_PY_EOF'
#!/usr/bin/env python3
"""Reference solution driver; candidate numerical logic lives in implementation.py."""
from __future__ import annotations
import argparse,csv,json,math,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import implementation

TASK_PROTOCOL = {'network': {'checkpoint_iteration': 1500},
 'analysis': {'dt_ps': 0.002,
              'sample_interval_ps': 0.04,
              'stride_steps': 20,
              'steps': 750000,
              'required_rows_per_arm': 37501,
              'core_radius_rad': 0.35,
              'minimum_consecutive_samples': 25,
              'cores_rad': {'b1': [-1.3823, 1.0053],
                            'b2': [-2.5133, 2.7646],
                            'b3': [-1.508, 2.2619],
                            'b4': [1.131, -0.754]},
              'forced_freeze_step': 750000,
              'forced_freeze_time_ps': 1500.0,
              'static_window_start_step': 0,
              'static_window_end_step': 750000,
              'temperature_K': 300.0,
              'gas_constant_kj_mol_k_K': 0.00831446261815324,
              'reweighting': 'static VES evaluation arm only; logw=+beta*V; global stable '
                             'normalization',
              'freeze_policy': 'forced policy at 1.5 ns; not intrinsic convergence'}}


def parse_colvar(path,dt_ps,stride,required_rows):
    fields=None;rows=[];previous=None
    for line in path.read_text().splitlines():
        if line.startswith('#! FIELDS'):
            fields=line.split()[2:];continue
        if not line.strip() or line.startswith('#'):continue
        values=line.split()
        if fields is None or len(values)!=len(fields):raise ValueError('bad COLVAR fields/row width')
        row=dict(zip(fields,values));time=float(row['time']);step=round(time/dt_ps)
        if not math.isfinite(time) or abs(step*dt_ps-time)>1e-8 or step%stride:
            raise ValueError('invalid COLVAR cadence')
        if previous is not None and step-previous!=stride:raise ValueError('COLVAR has missing/out-of-order rows')
        rec={'step':step,'time_ps':time,'phi_rad':float(row['phi']),'psi_rad':float(row['psi'])}
        if 'nn.bias' in row:rec['bias_kj_mol']=float(row['nn.bias'])
        if not all(math.isfinite(v) for v in rec.values()):raise ValueError('nonfinite COLVAR data')
        rows.append(rec);previous=step
    if len(rows)!=required_rows:raise ValueError('wrong COLVAR row count')
    return rows

def build_contract(assets,task_contract):
    data=assets/'native-unit-output-complete'
    cfg=dict(task_contract['analysis'])
    cfg['gas_constant_kj_mol_k_K']=cfg.pop('gas_constant_kj_mol_k_K')
    cfg['checkpoint_iteration']=task_contract['network']['checkpoint_iteration']
    terminal=json.loads((data/'terminal-check.json').read_text())
    cfg['native_terminal_status']=terminal['status']
    if type(terminal.get('science_pass')) is not bool:raise ValueError('terminal science_pass must be Boolean')
    cfg['native_science_pass']=terminal['science_pass']
    cfg['forced_freeze_step']=task_contract['analysis']['forced_freeze_step']
    cfg['forced_freeze_time_ps']=task_contract['analysis']['forced_freeze_time_ps']
    return cfg

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--assets',type=Path,default=Path('/app/environment/assets'));ap.add_argument('--output',type=Path,default=Path('/app/final/answer.json'));a=ap.parse_args()
    assets=a.assets.resolve();tc=TASK_PROTOCOL;cfg=build_contract(assets,tc);data=assets/'native-unit-output-complete'
    dt=float(cfg['dt_ps']);stride=int(cfg['stride_steps']);n=int(cfg['required_rows_per_arm'])
    arms=[parse_colvar(data/'train/COLVAR',dt,stride,n),parse_colvar(data/'eval/ves/COLVAR',dt,stride,n),parse_colvar(data/'eval/control/COLVAR',dt,stride,n)]
    record=implementation.analyze(*arms,cfg)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print(json.dumps(record,sort_keys=True))
if __name__=='__main__':main()
CCW_TASK51_SOLVE_PY_EOF
cp "$WORK/implementation.py" "$APP/submission.py"
python3 "$WORK/solve.py" --assets "$ASSETS" --output "$OUTPUT"
