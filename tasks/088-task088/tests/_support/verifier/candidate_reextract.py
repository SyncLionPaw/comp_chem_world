#!/usr/bin/env python3
"""Independent candidate-schedule re-extraction from audited native inputs.

This path is deliberately separate from the frozen author-reference kernel.
It reads only the audited TPR/XTC, uses evaluator-owned charge parsing and CIC
deposition, and records sufficient statistics on the candidate's declared
sample schedule, block duration, uniform reporting bins, and supported
256/384/512 primary mesh. It also runs independent 256/384 and direct-mode
numerical diagnostics. Unknown assignment or bin conventions fail closed.
"""
from __future__ import annotations

import hashlib, json, math, os, time
from pathlib import Path
import numpy as np

E=1.602176634e-19
EPS0=8.8541878128e-12
KB=1.380649e-23
TEMP=300.0
V6_CRITICAL_LABELS=frozenset({1,2,3,4,47,48,49,59,60,61,72,73,74,109,110,111,118,119,120})

def _v6_probe_pool(pool,sx,sy,sz,critical):
    """Preserve the V5 pair verbatim, then extend by deterministic geometry."""
    first=int(pool[0]); chosen=[first]
    if len(pool)>1:
        v0=np.array([sx[first],sy[first],sz[first]],float); v0/=np.linalg.norm(v0)
        vectors=np.column_stack((sx[pool],sy[pool],sz[pool])).astype(float)
        vectors/=np.linalg.norm(vectors,axis=1)[:,None]
        scores=np.abs(vectors@v0); scores[np.flatnonzero(pool==first)]=np.inf
        chosen.append(int(pool[int(np.argmin(scores))]))
    target=min(8,len(pool)) if critical else min(2,len(pool))
    while len(chosen)<target:
        chosen_rows=np.asarray([int(np.flatnonzero(pool==item)[0]) for item in chosen])
        remaining=np.asarray([i for i in range(len(pool)) if int(pool[i]) not in chosen],dtype=int)
        score=np.max(np.abs(vectors[remaining]@vectors[chosen_rows].T),axis=1)
        chosen.append(int(pool[int(remaining[int(np.argmin(score))])]))
    return chosen

def _v6_pair_positions(candidates):
    """Union V5's fixed 10 positions and the fixed 20-position schedule."""
    candidates=np.asarray(candidates,dtype=int)
    if not len(candidates): return np.asarray([],dtype=int)
    old=np.floor(np.linspace(0,len(candidates)-1,min(10,len(candidates)))).astype(int)
    dense=np.floor(np.linspace(0,len(candidates)-1,min(20,len(candidates)))).astype(int)
    return np.unique(np.concatenate((old,dense)))

def _per_mode_power_over_k2(power:np.ndarray,k_A_inverse:np.ndarray)->np.ndarray:
    """Convert each reciprocal mode to SI q²/k² units before shell binning."""
    power=np.asarray(power,dtype=float); k=np.asarray(k_A_inverse,dtype=float)
    if np.any(~np.isfinite(power)) or np.any(power<0) or np.any(~np.isfinite(k)) or np.any(k<=0):
        raise ValueError('mode power and reciprocal magnitudes must be finite and physical')
    return power/(k*1e10)**2

def _spce_molecular_dipole(pos_by_water:np.ndarray,charges_by_water:np.ndarray,box_A:np.ndarray)->np.ndarray:
    """Compute charge-neutral SPC/E dipole using O-relative minimum-image bonds."""
    pos=np.asarray(pos_by_water,dtype=float); q=np.asarray(charges_by_water,dtype=float); box=np.asarray(box_A,dtype=float)
    if pos.ndim!=3 or pos.shape[1:]!=(3,3) or q.shape!=pos.shape[:2] or box.shape!=(3,):
        raise ValueError('water positions, charges, or orthorhombic box have invalid shape')
    if np.any(~np.isfinite(pos)) or np.any(~np.isfinite(q)) or np.any(~np.isfinite(box)) or np.any(box<=0):
        raise ValueError('water positions, charges, and box must be finite')
    if not np.allclose(q.sum(axis=1),0.,atol=1e-10,rtol=0):
        raise ValueError('each water molecule must be charge neutral for the molecular dipole gauge')
    rel=pos[:,1:,:]-pos[:,:1,:]
    rel-=box[None,None,:]*np.rint(rel/box[None,None,:])
    dipole_pos=np.concatenate((np.zeros((len(pos),1,3)),rel),axis=1)
    return np.sum(dipole_pos*q[:,:,None],axis=(0,1))*E*1e-10

def _selected_probe_gate(direct_upper:np.ndarray,mesh_mean:np.ndarray,bins:np.ndarray,limit:float=.01)->tuple[bool,float]:
    """Check every probed vector; signed errors cannot cancel within a shell."""
    upper=np.asarray(direct_upper,dtype=float); mesh=np.asarray(mesh_mean,dtype=float); bins=np.asarray(bins,int)
    if upper.ndim!=1 or mesh.shape!=upper.shape or bins.shape!=upper.shape or not len(upper):
        raise ValueError('selected probe arrays must be nonempty matching vectors')
    if np.any(~np.isfinite(upper)) or np.any(upper<0) or np.any(~np.isfinite(mesh)) or np.any(~np.isfinite(bins)):
        raise ValueError('selected probe values must be finite and upper bounds nonnegative')
    rel=upper/np.maximum(np.abs(mesh),1e-12)
    return bool(np.all(rel<=limit+1e-12)),float(np.max(rel))

def _audit_nsblock_index(time_ps:float,n_full_blocks:int)->int|None:
    """Return the full-nanosecond paired-audit bucket, excluding any tail."""
    if not math.isfinite(time_ps) or time_ps<0 or n_full_blocks<1: return None
    if time_ps>=n_full_blocks*1000.-1e-9: return None
    return int(math.floor(time_ps/1000.))

def _paired_simultaneous_upper(delta:np.ndarray,seed:int,confidence:float=.975,draws:int=10000)->tuple[np.ndarray,dict]:
    """Paired block max-stat upper for a family of reciprocal-mode errors."""
    delta=np.asarray(delta,dtype=float)
    if delta.ndim!=2 or delta.shape[0]<2 or delta.shape[1]<1 or np.any(~np.isfinite(delta)):
        raise ValueError('paired differences must be a finite block-by-mode matrix')
    if not 0<confidence<1 or draws<100: raise ValueError('invalid simultaneous-bootstrap settings')
    se=delta.std(axis=0,ddof=1)/math.sqrt(len(delta)); avg=delta.mean(axis=0)
    rng=np.random.default_rng(seed); maxima=[]
    for begin in range(0,draws,128):
        size=min(128,draws-begin); pick=rng.integers(0,len(delta),(size,len(delta)))
        boot=delta[pick].mean(axis=1)
        maxima.extend(np.max(np.abs(boot-avg)/np.maximum(se,1e-15),axis=1).tolist())
    crit=float(np.quantile(maxima,confidence))
    return np.abs(avg)+crit*se,{'critical_value':crit,'confidence_level':confidence,'standard_error':se.tolist(),
      'mean_paired_difference':avg.tolist(),'max_stat_bootstrap_draws':draws,'bootstrap_seed':seed}

def _deposit(n:int,pos:np.ndarray,q:np.ndarray,box:float)->np.ndarray:
    frac=np.mod(pos,box)/box*n
    base=np.floor(frac).astype(np.int32); delta=frac-base; base%=n
    grid=np.zeros(n**3,dtype=np.float64)
    for ax in (0,1):
      wx=delta[:,0] if ax else 1-delta[:,0]; ix=(base[:,0]+ax)%n
      for ay in (0,1):
        wy=delta[:,1] if ay else 1-delta[:,1]; iy=(base[:,1]+ay)%n
        for az in (0,1):
          wz=delta[:,2] if az else 1-delta[:,2]; iz=(base[:,2]+az)%n
          flat=ix.astype(np.int64)*n*n+iy.astype(np.int64)*n+iz
          grid+=np.bincount(flat,weights=q*wx*wy*wz,minlength=n**3)
    return grid.reshape((n,n,n))

def _grid(n:int,box:float,width:float,kmax:float,center_convention:str):
    iv=np.rint(np.fft.fftfreq(n)*n).astype(np.int32)
    x,y,z=np.meshgrid(iv,iv,iv,indexing='ij',sparse=True)
    n2=(x*x+y*y+z*z).ravel()
    kmag=(2*np.pi/box)*np.sqrt(n2.astype(float))
    reciprocal_cut=math.ceil(kmax/width-1e-12)*width
    use=(n2>0)&(kmag<=reciprocal_cut+1e-12)
    labels=np.unique(np.floor(kmag[use]/width).astype(np.int32))
    bids=np.searchsorted(labels,np.floor(kmag[use]/width).astype(np.int32))
    modecount=np.bincount(bids,minlength=len(labels))
    if np.any(modecount==0):
        raise NotImplementedError('declared reporting grid contains an empty reciprocal bin')
    sinc=np.sinc(iv.astype(float)/n)**2
    window=(sinc[:,None,None]*sinc[None,:,None]*sinc[None,None,:]).ravel()[use]**2
    if np.any(window<=0): raise ValueError('invalid CIC deconvolution window')
    centers=(np.bincount(bids,weights=kmag[use],minlength=len(labels))/modecount if center_convention=='mode_mean'
             else (labels+(.5 if center_convention=='center' else 1.0))*width)
    return use,kmag[use],bids,window,modecount,centers,labels

def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def _declaration(root:Path,curve_path:Path):
    obs=json.loads((root/'final/observables.json').read_text())
    method=obs.get('method')
    if not isinstance(method,dict): raise NotImplementedError('method metadata is required for native re-extraction')
    required={
      'assignment':method.get('charge_assignment',method.get('assignment',method.get('estimator'))),
      'estimator':method.get('reciprocal_estimator',method.get('power_deconvolution',method.get('averaging'))),
      'bin_width':method.get('reporting_bin_width_A^-1',method.get('bin_width_A^-1')),
      'center':method.get('bin_center_convention','mode_mean'),
      'mesh':method.get('mesh',method.get('mesh_pair')),
      'period':obs.get('source',{}).get('sampling_interval_ps'),
      'start':obs.get('source',{}).get('sampling_start_ps',0.0),
      'endpoint':obs.get('source',{}).get('sampling_endpoint_rule','end_exclusive'),
      'block':obs.get('source',{}).get('block_length_ns'),
    }
    # The declaration determines which uncertainty reconstruction is
    # currently supported. The evaluator independently applies its own
    # periodic-CIC estimator to native coordinates; bin geometry, schedule,
    # and claimed feature definitions remain candidate-declared inputs.
    if required['center'] not in ('center','right_edge','mode_mean'): raise NotImplementedError('bin_center_convention must be center, right_edge, or mode_mean')
    assignment=str(required['assignment'] or '').lower()
    estimator=str(required['estimator'] or '').lower()
    mesh=required['mesh']
    rawdims=[mesh]*3 if isinstance(mesh,(int,float)) and not isinstance(mesh,bool) else list(mesh) if isinstance(mesh,(list,tuple)) and len(mesh)==3 else None
    if rawdims is None or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(float(x)) or not float(x).is_integer() for x in rawdims):
        raise NotImplementedError('primary mesh must contain three finite integer dimensions')
    dims=[int(x) for x in rawdims]
    if not ('cic' in assignment and 'periodic' in assignment):
        raise NotImplementedError('candidate uncertainty currently supports only a declared periodic CIC charge assignment; alternative or missing assignments are unsupported, not candidate failures')
    if not any(token in estimator for token in ('power/k^2','power_over_k2','mean_power_over_k2')):
        raise NotImplementedError('candidate uncertainty currently supports only per-mode power/k^2 averaging; alternative or missing estimators are unsupported, not candidate failures')
    if dims not in ([256,256,256],[384,384,384],[512,512,512]):
        raise NotImplementedError('candidate uncertainty currently supports declared periodic-CIC primary meshes 256^3, 384^3, or 512^3; other meshes are unsupported, not candidate failures')
    width=float(required['bin_width']); period=float(required['period']); block=float(required['block']); start=float(required['start'])
    if not all(math.isfinite(x) and x>0 for x in (width,period,block)) or not math.isfinite(start) or start<0: raise ValueError('sampling, block, and bin widths must be finite and positive')
    if required['endpoint'] not in ('end_exclusive','end_inclusive'): raise NotImplementedError('sampling_endpoint_rule must be end_exclusive or end_inclusive')
    rows=list(__import__('csv').DictReader(curve_path.open(newline='')))
    kval=np.asarray([float(x['k_A^-1']) for x in rows],float)
    if len(kval)<3 or np.any(~np.isfinite(kval)) or np.any(np.diff(kval)<=0): raise ValueError('candidate k grid must be finite and strictly increasing')
    if abs(kval[0])>1e-10: raise ValueError('candidate curve must include its explicit k=0 limit')
    kmax=float(kval[-1]); nb=len(kval)-1
    if required['center']!='mode_mean':
        first_label=(int(round(kval[1]/width-.5)) if required['center']=='center'
                     else int(round(kval[1]/width))-1)
        expected=(np.arange(nb)+first_label+(.5 if required['center']=='center' else 1.0))*width
        if not np.allclose(kval[1:],expected,rtol=0,atol=max(1e-8,width*1e-6)):
            raise NotImplementedError('candidate k values do not match the declared uniform-bin edges/centers')
    # A half-ns sufficient-statistic block schedule needs integral frame
    # selection in each block; arbitrary block duration is supported here by
    # assigning each selected native frame to a contiguous declared interval.
    return obs,method,kval,width,kmax,period,block,required['center'],start,required['endpoint'],dims[0]

def reextract_candidate_method(root:Path,native_artifacts:dict,output:Path,*,_mesh_pair=(256,384),_primary_mesh:int|None=None)->dict:
    """Recompute candidate-method estimates and block statistics from TPR/XTC.

    `native_artifacts` must be the resolved paths returned by native_audit;
    candidate provenance/checkpoints are never opened as trusted evidence.
    """
    root=Path(root).resolve(); output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    try:
        tpr=Path(native_artifacts['tpr']).resolve(); xtc=Path(native_artifacts['xtc']).resolve()
        if not tpr.is_file() or not xtc.is_file(): raise ValueError('audited native TPR/XTC are unavailable')
        obs,method,kall,width,kmax,period,block_ns,center,start_ps,endpoint_rule,declared_primary_mesh=_declaration(root,root/'final/chi_k.csv')
        primary_n=int(_primary_mesh if _primary_mesh is not None else declared_primary_mesh)
        if primary_n not in (256,384,512):
            if _primary_mesh is None: raise NotImplementedError('candidate primary mesh is not supported')
            if primary_n<8: raise ValueError('test-only primary mesh override is invalid')
        if max(primary_n,*map(int,_mesh_pair))**3*64 > 16*1024**3:
            raise RuntimeError('estimated reciprocal-grid workspace exceeds the evaluator memory budget')
        analysis_started=time.monotonic()
        try:
            import MDAnalysis as mda
            from scipy import fft
        except Exception as e: raise RuntimeError(f'native re-extraction runtime unavailable: {e}') from e
        u=mda.Universe(str(tpr),str(xtc)); nat=len(u.atoms); nw=len(u.residues)
        if nw<2 or any(len(r.atoms)!=3 for r in u.residues): raise ValueError('native trajectory is not a three-site water system')
        water_ids=[]; charges=[]
        for wi,res in enumerate(u.residues):
            ids=np.asarray(res.atoms.indices,int); q=np.asarray(res.atoms.charges,float)
            oi=np.flatnonzero(q<-.5); hi=np.flatnonzero(q>.2)
            if len(oi)!=1 or len(hi)!=2: raise ValueError(f'residue {wi} lacks one oxygen and two hydrogen charges')
            qr=q[np.r_[oi,hi]]
            if not np.allclose(qr,[-.8476,.4238,.4238],rtol=0,atol=2e-4): raise ValueError(f'residue {wi} is not SPC/E charged')
            water_ids.extend(ids[np.r_[oi,hi]].tolist()); charges.extend(qr.tolist())
        atom_ids=np.asarray(water_ids,int); q=np.asarray(charges,float)
        if q.size%3: raise ValueError('audited SPC/E charge vector is not grouped by water molecule')
        nominal_q=np.tile(np.asarray([-.8476,.4238,.4238],float),q.size//3)
        f32_q=nominal_q.astype(np.float32).astype(float)
        if np.array_equal(q,nominal_q): nominal_charge_scale=1.0; charge_encoding='nominal_decimal'
        elif np.array_equal(q,f32_q):
            ratios=nominal_q/q
            if not np.all(np.isfinite(ratios)) or not np.allclose(ratios,ratios[0],rtol=0,atol=1e-12):
                raise NotImplementedError('native SPC/E charge precision is not one uniform nominal-to-float32 representation')
            nominal_charge_scale=float(ratios[0]); charge_encoding='native_float32'
        else: raise NotImplementedError('native SPC/E charges are not the exact nominal or float32 representation supported by the uncertainty audit')
        box0=np.asarray(u.trajectory[0].dimensions[:3],float); L=float(np.mean(box0))
        if np.max(np.abs(box0-L))>.02: raise ValueError('native reference box is not cubic')
        dt=float(u.trajectory[1].time-u.trajectory[0].time)
        if dt<=0 or not math.isfinite(dt): raise ValueError('native trajectory cadence is invalid')
        end_ps=float(u.trajectory[-1].time)
        ntarget=(int(math.floor((end_ps-start_ps)/period+1e-12))+1 if endpoint_rule=='end_inclusive'
                 else int(math.ceil((end_ps-start_ps)/period-1e-12)))
        if ntarget<1: raise ValueError('candidate sampling interval produces no targets inside production duration')
        if period<dt-1e-9: raise NotImplementedError('candidate sampling interval is finer than the native saved-frame cadence')
        if ntarget>5000: raise NotImplementedError('candidate schedule exceeds the evaluator two-hour frame-analysis budget')
        if len(kall)-1>250 or kmax/width>250.5:
            raise NotImplementedError('candidate reporting grid exceeds the evaluator 250-bin memory/runtime limit')
        target=start_ps+np.arange(ntarget,dtype=float)*period
        # Nearest native frame, ties earlier; dedup when candidate cadence is
        # finer than saved XTC cadence. Actual selected times are recorded.
        ids=np.unique(np.clip(np.ceil(target/dt-.5-1e-12).astype(int),0,len(u.trajectory)-1))
        if len(ids)<100: raise NotImplementedError('candidate sampling yields fewer than 100 distinct configurations')
        if len(ids)>5000: raise NotImplementedError(f'candidate sampling requires more than 5000 full {primary_n}-mesh FFT evaluations; evaluator two-hour budget exceeded')
        block_ps=block_ns*1000.
        target_block_id=np.floor(ids.astype(float)*dt/block_ps).astype(int)
        nblock=int(np.max(target_block_id))+1
        if nblock<10: raise NotImplementedError('candidate block duration leaves fewer than ten independent blocks for uncertainty reconstruction')
        if nblock>200: raise NotImplementedError('candidate schedule creates more than 200 independent blocks; evaluator bootstrap budget exceeded')
        nlo,nhi=map(int,_mesh_pair)
        if nlo<8 or nhi<=nlo: raise ValueError('invalid evaluator mesh pair')
        use256,km256,b256,w256,d256,k256,labels256=_grid(nlo,L,width,kmax,center)
        missing_critical_labels=sorted(V6_CRITICAL_LABELS-set(map(int,labels256)))
        use384,km384,b384,w384,d384,k384,labels384=_grid(nhi,L,width,kmax,center)
        if not np.array_equal(d256,d384) or not np.allclose(k256,k384,atol=1e-12):
            raise NotImplementedError('256/384 reciprocal grids do not contain matching declared bins')
        if not np.array_equal(labels256,labels384): raise NotImplementedError('256/384 meshes do not share the candidate reporting bins')
        usep,kmp,bp,wp,dp,kp,labelsp=_grid(primary_n,L,width,kmax,center)
        if not np.array_equal(labels256,labelsp) or not np.array_equal(d256,dp) or not np.allclose(k256,kp,atol=1e-12):
            raise NotImplementedError('candidate primary mesh does not share the evaluator reporting bins')
        if len(kall)!=len(k256)+1 or not np.allclose(kall[1:],k256,rtol=0,atol=max(1e-8,width*1e-6)):
            raise NotImplementedError('candidate finite-k values do not match independently reconstructed reporting-bin centers')
        nb=len(d256); boxA=box0
        if nb>250: raise NotImplementedError('candidate reciprocal reporting grid exceeds 250 nonzero bins; evaluator budget exceeded')
        p256=np.zeros((nblock,nb)); pprimary=np.zeros((nblock,nb)); dip=np.zeros((nblock,3)); dip2=np.zeros(nblock); counts=np.zeros(nblock,int)
        # Precision blocks cover complete nanoseconds only. An end-exclusive
        # 20 ns trajectory has 20 nonempty blocks; an included 20000 ps final
        # frame remains in primary candidate statistics but not in the full-1ns
        # numerical precision blocks.
        n_audit=max(1,int(math.floor((end_ps+1e-9)/1000.)))
        p256_1ns=np.zeros((n_audit,nb)); count_1ns=np.zeros(n_audit,int)
        n_pair_blocks=max(1,int(math.floor(end_ps/1000.))); p256pair=np.zeros((n_pair_blocks,nb)); p384pair=np.zeros((n_pair_blocks,nb))
        pprimarypair=np.zeros((n_pair_blocks,nb)); pair_counts=np.zeros(n_pair_blocks,int)
        selected_times=[]; selected_ids=[]; selected_blocks=[]
        # Fixed deterministic nonconjugate direct probes (up to 2/bin) are
        # evaluated on paired frames. The candidate's declared primary mesh
        # and 256-mesh reference curve use every selected native frame.
        iv=np.rint(np.fft.fftfreq(nhi)*nhi).astype(int)
        x,y,z=np.meshgrid(iv,iv,iv,indexing='ij',sparse=True); n2=(x*x+y*y+z*z).ravel()
        reciprocal_cut=math.ceil(kmax/width-1e-12)*width
        kval=(2*np.pi/L)*np.sqrt(n2.astype(float)); mask=(n2>0)&(kval<=reciprocal_cut+1e-12)
        ids_all=np.flatnonzero(mask)
        ax=ids_all//(nhi*nhi); ay=(ids_all//nhi)%nhi; az=ids_all%nhi
        sx,sy,sz=iv[ax],iv[ay],iv[az]
        nonconjugate=(sx>0)|((sx==0)&(sy>0))|((sx==0)&(sy==0)&(sz>0))
        ids_all=ids_all[nonconjugate]; ax,ay,az=ax[nonconjugate],ay[nonconjugate],az[nonconjugate]
        sx,sy,sz=sx[nonconjugate],sy[nonconjugate],sz[nonconjugate]
        direct_labels=np.floor(kval[mask][nonconjugate]/width).astype(int)
        bids=np.searchsorted(labels256,direct_labels)
        probe_modes=[]
        for bi in range(nb):
            pool=np.flatnonzero(bids==bi)
            if not len(pool): raise NotImplementedError(f'no reciprocal modes for candidate bin {bi}')
            label=int(labels256[bi])
            chosen=_v6_probe_pool(pool,sx,sy,sz,label in V6_CRITICAL_LABELS)
            probe_modes.extend(ids_all[chosen].tolist())
        probe_modes=np.unique(probe_modes)
        px=probe_modes//(nhi*nhi); py=(probe_modes//nhi)%nhi; pz=probe_modes%nhi
        ix=iv[px]; iy=iv[py]; iz=iv[pz]; pk=(2*np.pi/L)*np.sqrt(ix*ix+iy*iy+iz*iz)
        pb=np.searchsorted(labels256,np.floor(pk/width).astype(int)); pdir=np.zeros((n_pair_blocks,len(pk)))
        pmesh=np.zeros_like(pdir)
        pair_positions=[]
        for nsblock in range(n_pair_blocks):
            candidates=np.flatnonzero((ids.astype(float)*dt>=nsblock*1000.)&(ids.astype(float)*dt<(nsblock+1)*1000.))
            if not len(candidates): raise NotImplementedError('candidate cadence leaves an unpaired 1 ns reference block')
            choose=_v6_pair_positions(candidates)
            pair_positions.extend(candidates[choose].tolist())
        pair_positions=np.asarray(pair_positions,int)
        pair_frame_ids=set(int(ids[j]) for j in pair_positions)
        sinc384=np.sinc(iv.astype(float)/nhi)**2
        win_probe=(sinc384[px]*sinc384[py]*sinc384[pz])**2
        iv_primary=np.rint(np.fft.fftfreq(primary_n)*primary_n).astype(int)
        if primary_n==nhi:
            usep_from384=True; usep=use384; bp=b384; kmp=km384; winp=w384
        else:
            usep_from384=False
            sinc_primary=np.sinc(iv_primary.astype(float)/primary_n)**2
            winp=(sinc_primary[:,None,None]*sinc_primary[None,:,None]*sinc_primary[None,None,:]).ravel()[usep]**2
        last=-1; first_time=None; last_time=None; box_deviation=0.
        fft_workers=int(os.environ.get('CASE01_FFT_WORKERS','8'))
        if not 1<=fft_workers<=8: raise ValueError('CASE01_FFT_WORKERS must be an integer from 1 through 8')
        for fid in ids:
            if time.monotonic()-analysis_started>2*60*60:
                raise RuntimeError('independent candidate-method re-extraction exceeded its two-hour evaluator budget')
            ts=u.trajectory[int(fid)]; t=float(ts.time)
            if t<=last: raise ValueError('native trajectory times are not strictly increasing')
            last=t; first_time=t if first_time is None else first_time; last_time=t
            dims=np.asarray(ts.dimensions[:3],float); box_deviation=max(box_deviation,float(np.max(np.abs(dims-box0))))
            if box_deviation>.02: raise ValueError('native production box changes beyond evaluator tolerance')
            b=int(math.floor(t/block_ps)); pos=np.asarray(ts.positions[atom_ids],float)
            molpos=pos.reshape(nw,3,3); rel=molpos[:,1:,:]-molpos[:,:1,:]
            rel-=dims[None,None,:]*np.rint(rel/dims[None,None,:])
            dipole_pos=np.concatenate((np.zeros((nw,1,3)),rel),axis=1)
            mu=_spce_molecular_dipole(molpos,q.reshape(nw,3),dims)
            dip[b]+=mu; dip2[b]+=float(mu@mu); counts[b]+=1
            F256=fft.fftn(_deposit(nlo,pos,q,float(np.mean(dims))),workers=fft_workers)
            pw256=_per_mode_power_over_k2(np.abs(F256.ravel()[use256])**2/w256,km256)
            p256[b]+=np.bincount(b256,weights=pw256,minlength=nb)
            if primary_n==nlo:
                Fprimary=F256; pwprimary=pw256
            elif primary_n==nhi:
                Fprimary=fft.fftn(_deposit(primary_n,pos,q,float(np.mean(dims))),workers=fft_workers)
                pwprimary=_per_mode_power_over_k2(np.abs(Fprimary.ravel()[usep])**2/winp,kmp)
            else:
                Fprimary=fft.fftn(_deposit(primary_n,pos,q,float(np.mean(dims))),workers=fft_workers)
                pwprimary=_per_mode_power_over_k2(np.abs(Fprimary.ravel()[usep])**2/winp,kmp)
            pprimary[b]+=np.bincount(bp,weights=pwprimary,minlength=nb)
            audit_block=_audit_nsblock_index(t,n_audit)
            if audit_block is not None:
                p256_1ns[audit_block]+=np.bincount(b256,weights=pw256,minlength=nb)
                count_1ns[audit_block]+=1
            if int(fid) in pair_frame_ids:
                pblock=min(n_pair_blocks-1,int(math.floor(t/1000.)))
                F384=Fprimary if primary_n==nhi else fft.fftn(_deposit(nhi,pos,q,float(np.mean(dims))),workers=fft_workers)
                pw384=_per_mode_power_over_k2(np.abs(F384.ravel()[use384])**2/w384,km384)
                p256pair[pblock]+=np.bincount(b256,weights=pw256,minlength=nb)
                p384pair[pblock]+=np.bincount(b384,weights=pw384,minlength=nb)
                pprimarypair[pblock]+=np.bincount(bp,weights=pwprimary,minlength=nb)
                pair_counts[pblock]+=1
                pmesh[pblock]+=_per_mode_power_over_k2(np.abs(F384.ravel()[probe_modes])**2/win_probe,pk)
                # Exact direct sums on this paired subset only.
                wrapped=np.mod(pos,dims[0])
                for start in range(0,len(pk),16):
                    sl=slice(start,start+16); vec=np.column_stack((ix[sl],iy[sl],iz[sl])).astype(float)
                    if not (np.all(np.isfinite(wrapped)) and np.all(np.isfinite(vec)) and np.all(np.isfinite(pk[sl])) and np.all(pk[sl]>0)):
                        raise ValueError('non-finite positions or reciprocal direct-probe vectors')
                    if np.max(np.abs(wrapped))>1e4 or np.max(np.abs(vec))>1e4 or not math.isfinite(float(np.mean(dims))) or float(np.mean(dims))<=0:
                        raise ValueError('native box or coordinates are outside the supported physical range')
                    phase=wrapped@(2*np.pi/float(np.mean(dims))*vec.T)
                    rho=np.exp(-1j*phase).T@q
                    pdir[pblock,sl]+=_per_mode_power_over_k2(np.abs(rho)**2,pk[sl])
            selected_ids.append(int(fid)); selected_times.append(t); selected_blocks.append(b)
        block_id=np.asarray(selected_blocks,int)
        if np.any(counts==0): raise NotImplementedError('candidate block schedule contains an empty block')
        norm=E**2/(float(np.prod(box0))*1e-30*EPS0*KB*TEMP)
        c256=p256/(counts[:,None]*d256[None,:])*norm
        cprimary=pprimary/(counts[:,None]*dp[None,:])*norm
        if np.any(count_1ns==0): raise NotImplementedError('native sampling leaves an empty independent 1 ns precision block')
        c256_1ns=p256_1ns/(count_1ns[:,None]*d256[None,:])*norm
        if np.any(pair_counts==0): raise NotImplementedError('paired mesh/direct audit lacks frames in one or more 1 ns audit blocks')
        if not np.all(pair_counts==pair_counts[0]): raise NotImplementedError('paired mesh/direct audit has unequal per-block sample counts; weighted paired bootstrap is not available')
        c256pair=p256pair/(pair_counts[:,None]*d256[None,:])*norm
        c384pair=p384pair/(pair_counts[:,None]*d384[None,:])*norm
        cprimarypair=pprimarypair/(pair_counts[:,None]*dp[None,:])*norm
        direct=np.zeros((n_pair_blocks,nb))
        mesh_direct=np.zeros((n_pair_blocks,nb))
        for bi in range(nb):
            m=(pb==bi)
            if not np.any(m): raise NotImplementedError(f'no direct probes for candidate bin {bi}')
            direct[:,bi]=pdir[:,m].mean(axis=1)/(pair_counts)*norm
            mesh_direct[:,bi]=pmesh[:,m].mean(axis=1)/(pair_counts)*norm
        # Save evaluator-generated sufficient statistics, schedule binding and
        # three estimator curves. No candidate-provided summaries are inputs.
        volume=float(np.prod(box0))*1e-30
        eps_blocks=1.+(dip2/counts-np.sum((dip/counts[:,None])**2,axis=1))/(3*EPS0*volume*KB*TEMP)
        chi0_blocks=1.-1./eps_blocks
        checkpoint=output/'trusted_candidate_method.npz'
        np.savez_compressed(checkpoint,curve256_blocks=c256,p256strict=p256,primary_power_sums=pprimary,primary_mesh=np.asarray(primary_n),curve_primary_blocks=cprimary,
          curve256_paired_blocks=c256pair,curve384_paired_blocks=c384pair,curve_primary_paired_blocks=cprimarypair,direct_probe_blocks=direct,
          direct_probe_raw_sums=pdir,mesh_probe_raw_sums=pmesh,paired_frame_counts=pair_counts,
          probe_vectors_integer=np.column_stack((ix,iy,iz)),probe_k_A_inverse=pk,paired_frame_ids=np.asarray(sorted(pair_frame_ids),dtype=np.int64),
          dipole_sum_blocks=dip,dipole_sq_sum_blocks=dip2,mdip=dip,mdip2=dip2,eps_w_blocks=eps_blocks,chi0_blocks=chi0_blocks,frame_count_blocks=counts,mframes=counts,bin_centers_A_inverse=k256,kbin=k256,
          mode_degeneracy=d256,deg=d256,primary_mode_degeneracy=dp,primary_reciprocal_bin_labels=labelsp,native_charges=q,nominal_charges=nominal_q,nominal_charge_scale=np.asarray(nominal_charge_scale),sampled_frame_ids=np.asarray(selected_ids),sampled_times_ps=np.asarray(selected_times),
          block_ids=block_id,block_length_ns=np.asarray(block_ns),sample_period_ps=np.asarray(period),scheduled_target_count=np.asarray(ntarget),box_A=box0,
          bin_width_A_inverse=np.asarray(width),kmax_A_inverse=np.asarray(kmax))
        means={'256_all_frames':p256.sum(axis=0)/(counts.sum()*d256)*norm,'384_paired_frames':p384pair.sum(axis=0)/(pair_counts.sum()*d384)*norm,f'{primary_n}_all_frames':pprimary.sum(axis=0)/(counts.sum()*dp)*norm,'direct_probe_paired_frames':np.asarray([pdir[:,pb==bi].sum()/pair_counts.sum()/int(np.sum(pb==bi))*norm for bi in range(nb)]),'mesh384_direct_probe':np.asarray([pmesh[:,pb==bi].sum()/pair_counts.sum()/int(np.sum(pb==bi))*norm for bi in range(nb)])}
        # Triangle sum keeps full-curve mesh bias and paired direct-transform
        # numerical error separate from trajectory sampling uncertainty.
        grid_upper,grid_ci=_paired_simultaneous_upper(c256pair-c384pair,20261008)
        if primary_n==nlo:
            primary_grid_upper,primary_grid_ci=grid_upper,grid_ci
        elif primary_n==nhi:
            primary_grid_upper=np.zeros(nb)
            primary_grid_ci={'critical_value':0.0,'upper_absolute_per_bin':primary_grid_upper.tolist(),'scope':'candidate primary mesh equals paired 384 mesh'}
        else:
            primary_grid_upper,primary_grid_ci=_paired_simultaneous_upper(cprimarypair-c384pair,20261011)
        direct_mode=pdir/pair_counts[:,None]*norm; mesh_mode=pmesh/pair_counts[:,None]*norm
        direct_mode_upper,direct_ci=_paired_simultaneous_upper(direct_mode-mesh_mode,20261009)
        mode_relative=direct_mode_upper/np.maximum(np.abs(mesh_mode.mean(axis=0)),1e-12)
        direct_upper=np.zeros(nb); max_mode_relative=np.zeros(nb)
        for bi in range(nb):
            selected=pb==bi
            direct_upper[bi]=float(np.max(direct_mode_upper[selected]))
            max_mode_relative[bi]=float(np.max(mode_relative[selected]))
        err=primary_grid_upper+direct_upper
        maxrelative=float(np.max(err/np.maximum(np.abs(means[f'{primary_n}_all_frames']),1e-12)))
        # The preregistered limits apply to the two numerical checks separately:
        # direct-vs-mesh probe bias is bounded at 1%; mesh bias is bounded per
        # bin by max(1%, 3 full-curve block SE). The triangle-summed envelope is
        # retained for candidate comparison and is not itself a new 1% gate.
        grid_se=c256_1ns.std(axis=0,ddof=1)/math.sqrt(len(c256_1ns)) if len(c256_1ns)>1 else np.full(nb,np.inf)
        grid_limit=np.maximum(.01*np.abs(means['384_paired_frames']),3*grid_se)
        grid_pass=bool(np.all(grid_upper<=grid_limit+1e-15))
        # The paper's direct-Fourier method is validated in its low-k regime
        # (k < 2.5 A^-1). High-k direct probes remain in the full-range
        # empirical envelope above, but are diagnostics rather than a gate.
        low_probe=pk<2.5
        if not np.any(low_probe): raise NotImplementedError('selected probes do not cover the paper-supported low-k direct regime')
        direct_pass,max_direct_rel=_selected_probe_gate(direct_mode_upper[low_probe],mesh_mode.mean(axis=0)[low_probe],pb[low_probe],.01)
        _,max_all_direct_rel=_selected_probe_gate(direct_mode_upper,mesh_mode.mean(axis=0),pb,.01)
        high_direct_rel=float(np.max(mode_relative[~low_probe])) if np.any(~low_probe) else None
        numeric_pass=grid_pass and direct_pass
        max_grid_rel=float(np.max(grid_upper/np.maximum(np.abs(means['384_paired_frames']),1e-12)))
        max_direct_rel=float(max_direct_rel)
        result={'status':'REEXTRACTED' if numeric_pass else 'ERROR','errors':[] if numeric_pass else ['independent reference did not establish the preregistered mesh/direct numerical limits'],
          'unsupported_evidence':[],
          'trusted_checkpoint':str(checkpoint),'trusted_checkpoint_sha256':_sha(checkpoint),
          'native_sources':{'tpr_sha256':_sha(tpr),'xtc_sha256':_sha(xtc)},
          'sampling':{'native_frames':len(u.trajectory),'selected_frames':len(ids),'sample_period_ps_declared':period,'sampling_start_ps':start_ps,'sampling_endpoint_rule':endpoint_rule,'actual_times_ps':selected_times,'first_time_ps':first_time,'last_time_ps':last_time,'block_length_ns':block_ns,'block_count':nblock,'counts_per_block':counts.tolist(),'paired_frame_count':len(pair_frame_ids),'paired_frames_per_full_ns_block':int(pair_counts[0]),'paired_schedule':'V6 union of original fixed 10 positions and fixed 20 positions per complete 1 ns block','paired_numeric_block_length_ns':1.0,'paired_counts_per_block':pair_counts.tolist(),'partial_final_block':bool(np.any(counts!=counts[0]))},
          'reporting':{'bin_width_A^-1':width,'center_convention':center,'bin_centers_A^-1':kp.tolist(),'mode_degeneracy':dp.tolist(),'range_A^-1':[0.,kmax],'primary_mesh':primary_n},
          'independent_estimators':{key:value.tolist() for key,value in means.items()},
          'numerical_systematic_absolute_per_bin':err.tolist(),'mesh256_vs384_simultaneous_upper':grid_ci,'candidate_primary_vs384_simultaneous_upper':primary_grid_ci,'direct_vs384_paired_simultaneous_upper':direct_ci,'max_relative_systematic':maxrelative,
          'numerical_gate':{'mesh_per_bin_pass':grid_pass,'mesh_limit_rule':'max(1% of |384 curve|, 3 x full-curve 1 ns block SE)','max_mesh_relative_upper':max_grid_rel,'selected_direct_probe_pass':direct_pass,'selected_probe_limit_rule':'per-vector paired simultaneous 95% upper <=1% of the same 384-mesh vector estimate for k < 2.5 A^-1 (paper A6 direct regime)','max_selected_probe_relative_upper':max_direct_rel,'max_all_selected_probe_relative_upper':max_all_direct_rel,'max_high_k_direct_relative_upper':high_direct_rel,'high_k_direct_precision_unresolved':bool(high_direct_rel is not None and high_direct_rel>.01),'high_k_direct_accuracy_claimed':False,'high_k_direct_gate_applied':False,'passed':numeric_pass},
          'numerical_coverage_limit':'selected direct probes check two vectors per occupied shell ordinarily and up to eight for fixed V6 critical reciprocal labels; this finite direction set does not bound every angular direction. The unchanged 1% direct accuracy gate applies only below 2.5 A^-1, where paper A6 validates direct Fourier evaluation. High-k per-vector bounds are retained in the full-k empirical numerical envelope but are not claimed to pass a direct-method accuracy criterion; full-shell estimator stability is assessed separately by paired 256/384 meshes.',
           'direct_probe_vectors_integer':np.column_stack((ix,iy,iz)).tolist(),'direct_probe_reciprocal_labels':np.asarray(labels256)[pb].astype(int).tolist(),'direct_probe_represents_all_angular_modes':False,
          'precision_audit_plan':{'version':'V6_POST_V5_REFERENCE_PRECISION_REVIEW','critical_reciprocal_labels_requested':sorted(V6_CRITICAL_LABELS),'critical_reciprocal_labels_present':sorted(V6_CRITICAL_LABELS-set(missing_critical_labels)),'critical_reciprocal_labels_absent':missing_critical_labels,'critical_label_mode_target':'min(8, available nonconjugate modes)','ordinary_label_mode_target':'min(2, available nonconjugate modes)','fft_workers':fft_workers,'mesh_gate_limit_unchanged':True,'direct_gate_limit_unchanged':True,'bootstrap_seed_mesh':20261008,'bootstrap_seed_direct':20261009,'bootstrap_draws':10000,'confidence_level':0.975},
          'native_box_A':box0.tolist(),'box_deviation_max_A':box_deviation,'selected_frame_ids':selected_ids,'primary_mesh':primary_n,
          'charge_representation':charge_encoding,'nominal_charge_scale':nominal_charge_scale}
        (output/'trusted_candidate_method.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    except NotImplementedError as e:
        result={'status':'UNSUPPORTED_EVIDENCE','errors':[],'unsupported_evidence':[str(e)]}
    except Exception as e:
        result={'status':'ERROR','errors':[f'{type(e).__name__}: {e}'],'unsupported_evidence':[]}
    (output/'trusted_candidate_method.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
