#!/usr/bin/env python3
"""Independent, single-pass validation of the existing Case01 trajectory.

No dynamics are integrated. Outputs are written to a new validation directory.
Uses SciPy FFT, a separate CIC implementation, per-mode normalization, direct
coordinate Fourier sums, and paired 256/384 mesh diagnostics.
"""
from __future__ import annotations

import csv, hashlib, json, os, subprocess
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from scipy import fft

ROOT = Path(os.environ.get("CASE01_DIR", Path(__file__).resolve().parents[1]))
OUT = Path(os.environ.get("OUTDIR", ROOT / "science-validation"))
PLAN_FILE = Path(os.environ.get("PLAN_FILE", OUT / "science-plan.md"))
TPR = ROOT / "production.tpr"
XTC = ROOT / "production.xtc"
N256, N384 = 256, 384
NFRAME = 2000
PAIR_FRAMES = set(range(0, NFRAME, 10))
FFT_WORKERS = max(1, int(os.environ.get("CASE01_FFT_WORKERS", os.environ.get("OMP_NUM_THREADS", "1"))))
E, EPS0, KB, T = 1.602176634e-19, 8.8541878128e-12, 1.380649e-23, 300.0
SEED = 20261006

def sampled_time_metadata(times):
    """Validate and summarize the timestamps actually selected for analysis."""
    values=np.asarray(times,dtype=float)
    if values.shape!=(NFRAME,) or not np.all(np.isfinite(values)):
      raise RuntimeError(f"sampled trajectory frame count invalid: {len(values)}")
    if abs(values[0])>.01 or abs(values[-1]-19990.0)>.01:
      raise RuntimeError(f"sampled trajectory time range invalid: {values[0]}..{values[-1]} ps")
    intervals=np.diff(values)
    expected=values[0]+10.0*np.arange(NFRAME,dtype=float)
    if (not np.all(np.isfinite(intervals)) or not np.all(np.abs(intervals-10.0)<=.01)
            or not np.all(np.abs(values-expected)<=.01)):
      raise RuntimeError("sampled trajectory timestamps are not uniformly spaced by 10 ps")
    period=float((values[-1]-values[0])/(len(values)-1))
    return {"sample_period_ps":period,"first_time_ps":float(values[0]),
            "last_time_ps":float(values[-1])}

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for c in iter(lambda:f.read(8*1024*1024),b""): h.update(c)
    return h.hexdigest()

def deposit(n, pos, q, box):
    # Independent periodic trilinear charge assignment; flattened bincounts.
    f=np.mod(pos,box)/box*n; base=np.floor(f).astype(np.int32); frac=f-base; base%=n
    grid=np.zeros(n**3,dtype=np.float64)
    for a in (0,1):
      wx=frac[:,0] if a else 1-frac[:,0]; ix=(base[:,0]+a)%n
      for b in (0,1):
        wy=frac[:,1] if b else 1-frac[:,1]; iy=(base[:,1]+b)%n
        for c in (0,1):
          wz=frac[:,2] if c else 1-frac[:,2]; iz=(base[:,2]+c)%n
          ids=ix.astype(np.int64)*n*n+iy.astype(np.int64)*n+iz
          grid += np.bincount(ids,weights=q*wx*wy*wz,minlength=n**3)
    return grid.reshape((n,n,n))

def reciprocal(n,L,kmax=6.0):
    v=np.rint(np.fft.fftfreq(n)*n).astype(np.int32)
    ix,iy,iz=np.meshgrid(v,v,v,indexing="ij",sparse=True)
    n2=(ix*ix+iy*iy+iz*iz).ravel()
    kval=2*np.pi/L*np.sqrt(n2.astype(np.float64))
    good=(n2>0)&(kval<=kmax)
    kv=kval[good]
    bid=np.floor(kv/0.05).astype(np.int32)
    k_A=kv
    sinc=np.sinc(v.astype(float)/n)**2
    win=(sinc[:,None,None]*sinc[None,:,None]*sinc[None,None,:])**2
    pwin=win.ravel()[good]
    return v,good,bid,k_A,pwin

def feature(y,k):
    # y contains k=0 then nonzero bins, both separated by 0.05 A^-1 bins.
    lo=np.flatnonzero((k>=0.05)&(k<=2.5)); hi=np.flatnonzero((k>=2.5)&(k<=6.0))
    imin=int(lo[np.argmin(y[lo])]); imax=int(hi[np.argmax(y[hi])])
    half=y[imax]/2
    left=np.flatnonzero(y[:imax]<=half); right=np.flatnonzero(y[imax+1:]<=half)
    width=None; kl=kr=None
    if len(left) and len(right):
      a=int(left[-1]); b=int(imax+1+right[0])
      kl=float(k[a]+(half-y[a])*(k[a+1]-k[a])/(y[a+1]-y[a]))
      kr=float(k[b-1]+(half-y[b-1])*(k[b]-k[b-1])/(y[b]-y[b-1]))
      width=kr-kl
    return {"k_min_A^-1":float(k[imin]),"chi_min":float(y[imin]),"k_max_A^-1":float(k[imax]),"chi_max":float(y[imax]),"half_height_k_minus_A^-1":kl,"half_height_k_plus_A^-1":kr,"delta_k_A^-1":width}

def boot_features(curves,k,seed):
    # Input rows are already bootstrap curves; do not bootstrap them again.
    draws=curves
    fs=[feature(row,k) for row in draws]
    result={}
    for name in ("k_min_A^-1","chi_min","k_max_A^-1","chi_max","delta_k_A^-1"):
      vals=np.array([x[name] for x in fs if x[name] is not None],float)
      result[name]={"ci95":[float(np.quantile(vals,.025)),float(np.quantile(vals,.975))],"se":float(vals.std(ddof=1))}
    lo=np.flatnonzero((k>=.05)&(k<=2.5)); support=0
    for y in draws:
      j=int(lo[np.argmin(y[lo])])
      if j not in (int(lo[0]),int(lo[-1])) and y[j]<y[j-1] and y[j]<y[j+1]: support+=1
    resolved=support/len(draws)
    result["strict_interior_minimum_support"]=float(resolved)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    gmx=os.environ.get("GMX",str(ROOT.parent/"gromacs-env/bin/gmx"))
    native_version=subprocess.run([gmx,"--version"],capture_output=True,text=True,check=True).stdout
    native_check=subprocess.run([gmx,"check","-s1",str(TPR),"-f",str(XTC)],capture_output=True,text=True,timeout=1800,check=True)
    edr_check=subprocess.run([gmx,"check","-e",str(ROOT/"production.edr")],capture_output=True,text=True,timeout=1800,check=True)
    tpr_dump=subprocess.run([gmx,"dump","-s",str(TPR)],capture_output=True,text=True,timeout=1800,check=True)
    (OUT/"native_audit.txt").write_text(native_version+"\n--- TPR/XTC check ---\n"+native_check.stdout+native_check.stderr+"\n--- EDR check ---\n"+edr_check.stdout+edr_check.stderr+"\n--- TPR settings ---\n"+tpr_dump.stdout)
    log=(ROOT/"production.log").read_text(errors="replace")
    if "Finished mdrun" not in log or "Performance:" not in log: raise RuntimeError("production log lacks normal-completion markers")
    u=mda.Universe(str(TPR),str(XTC)); nat=len(u.atoms); nw=nat//3
    names=np.asarray(u.atoms.names).reshape(nw,3)
    if nat!=27099 or not np.all(names==np.array(["OW","HW1","HW2"])): raise RuntimeError("TPR topology/atom order invalid")
    q=np.asarray(u.atoms.charges,float)
    qt=q.reshape(nw,3)
    if not np.allclose(qt,np.tile([-.8476,.4238,.4238],(nw,1)),atol=2e-4) or not np.allclose(qt.sum(axis=1),0,atol=2e-4): raise RuntimeError("SPC/E charge/order/neutrality check failed")
    ts0=u.trajectory[0]; box0=np.asarray(ts0.dimensions[:3],float); L=float(box0.mean()); V=L**3*1e-30
    if np.ptp(box0)>.02: raise RuntimeError("non-cubic production box")
    # Build per-mode normalization maps independently for each mesh.
    v256,mask256,bid256,k256,pw256=reciprocal(N256,L)
    bins=np.unique(bid256); nb=len(bins)
    deg=np.bincount(bid256,minlength=int(bins[-1])+1)[bins]
    kbin=np.bincount(bid256,weights=k256,minlength=int(bins[-1])+1)[bins]/deg
    norm=E**2/(V*EPS0*KB*T)
    p256strict=np.zeros((40,nb)); p256sum=np.zeros((40,nb))
    mdip=np.zeros((40,3)); mdip2=np.zeros(40); mframes=np.zeros(40,int)
    # Pair set from preregistration: 10 frames per 1-ns block.
    pair_modes=[]
    # Select reproducible nonconjugate integer modes, at least two per output bin.
    vv=np.rint(np.fft.fftfreq(N384)*N384).astype(int)
    v384=vv.astype(float)
    # bins from 256 grid define output bins. For each bin, find vectors on 384 mesh.
    ix,iy,iz=np.meshgrid(vv,vv,vv,indexing="ij",sparse=True)
    n2=(ix*ix+iy*iy+iz*iz).ravel(); kk=2*np.pi/L*np.sqrt(n2.astype(float))
    bd=np.floor(kk/.05).astype(int)
    rng=np.random.default_rng(SEED)
    kval384=kk
    mask384=(n2>0)&(kval384<=6.0)
    b384=np.floor(kval384[mask384]/.05).astype(int)
    vw384=np.sinc(v384/N384)**2
    w384=(vw384[:,None,None]*vw384[None,:,None]*vw384[None,None,:]).ravel()[mask384]**2
    deg384=np.bincount(b384,minlength=int(bins[-1])+1)[bins]
    candidate=np.flatnonzero((n2>0)&(kk<=6.0))
    cx=candidate//(N384*N384); cy=(candidate//N384)%N384; cz=candidate%N384
    sx=vv[cx]; sy=vv[cy]; sz=vv[cz]
    half=(sx>0)|((sx==0)&(sy>0))|((sx==0)&(sy==0)&(sz>0))
    candidate=candidate[half]; sx=sx[half]; sy=sy[half]; sz=sz[half]; cb=bd[candidate]
    for b in bins:
      inds=np.flatnonzero(cb==b)
      if len(inds):
        nselect=8 if int(b) in {1,2,3,4,47,48,49,59,60,61,72,73,74,109,110,111,118,119,120} else 2
        sel=rng.choice(inds,size=min(nselect,len(inds)),replace=False)
        for s in sel:
          j=int(candidate[s]); pair_modes.append((int(b),int(sx[s]),int(sy[s]),int(sz[s]),int(n2[j])))
    modes=np.asarray(pair_modes,int)
    mode_k=2*np.pi/L*np.sqrt(modes[:,4].astype(float))
    mode_b=modes[:,0]
    if not np.array_equal(deg384,deg): raise RuntimeError("256/384 reciprocal bin populations differ; paired comparison is invalid")
    # Selected mode statistics for exact direct sum versus 384 CIC.
    direct=np.zeros((40,len(modes))); mesh384=np.zeros_like(direct); mesh256=np.zeros_like(direct)
    # Full 384 and 256 paired curves on same 200 deterministic configurations.
    curve384=np.zeros((40,nb)); curve256pair=np.zeros((40,nb)); pair_count=np.zeros(40,int)
    trajectory_read=0; sampled=0; sampled_times=[]; frame_last=None; time_first=None; time_last=None; box_maxdev=0.0
    for ts in u.trajectory:
      trajectory_read+=1
      if time_first is None: time_first=float(ts.time)
      if time_last is not None and float(ts.time)<=time_last: raise RuntimeError("trajectory times are not strictly increasing")
      time_last=float(ts.time)
      if abs(float(ts.time)-(trajectory_read-1)*1.0)>.01: raise RuntimeError(f"unexpected native frame time at frame {ts.frame}: {ts.time} ps")
      thisbox=np.asarray(ts.dimensions[:3],float); angles=np.asarray(ts.dimensions[3:6],float)
      if np.ptp(thisbox)>.02 or not np.allclose(angles,90,atol=.02): raise RuntimeError(f"non-cubic or non-orthogonal cell at frame {ts.frame}")
      if box_maxdev==0.0: box_maxdev=float(np.max(np.abs(thisbox-box0)))
      else: box_maxdev=max(box_maxdev,float(np.max(np.abs(thisbox-box0))))
      if not np.allclose(thisbox,box0,atol=.02): raise RuntimeError(f"production box changed at frame {ts.frame}")
      if ts.frame%10 or ts.time>=20000: continue
      sampled_times.append(float(ts.time))
      f=int(ts.frame//10); block=f//50
      if f>=NFRAME: continue
      pos=np.asarray(u.atoms.positions,float); box=np.asarray(ts.dimensions[:3],float)
      # Independent molecular dipole from minimum-image intramolecular vectors.
      xyz=pos.reshape(nw,3,3); dr=xyz[:,1:]-xyz[:,:1]; dr-=box*np.rint(dr/box)
      mu=np.sum(dr*q.reshape(nw,3)[:,1:,None],axis=(0,1))*E*1e-10
      mdip[block]+=mu; mdip2[block]+=mu@mu; mframes[block]+=1
      g256=deposit(N256,pos,q,box); F256=fft.fftn(g256,workers=FFT_WORKERS).ravel()
      P256=(F256.real**2+F256.imag**2)[mask256]/pw256
      # Strict response applies each mode's own k^-2 before shell/bin averaging.
      p256sum[block]+=np.bincount(bid256,weights=P256,minlength=int(bins[-1])+1)[bins]
      p256strict[block]+=np.bincount(bid256,weights=P256/(k256*1e10)**2,minlength=int(bins[-1])+1)[bins]
      if f in PAIR_FRAMES:
        g384=deposit(N384,pos,q,box); F384=fft.fftn(g384,workers=FFT_WORKERS)
        flat=((modes[:,1]%N384)*N384+modes[:,2]%N384)*N384+(modes[:,3]%N384)
        # k-axis is reconstructed from a frame's actual fixed box.
        win384=np.prod(np.sinc(modes[:,1:4]/N384)**2,axis=1)**2
        win256=np.prod(np.sinc(modes[:,1:4]/N256)**2,axis=1)**2
        mesh384[block]+=np.abs(F384.ravel()[flat])**2/win384
        flat256=((modes[:,1]%N256)*N256+modes[:,2]%N256)*N256+(modes[:,3]%N256)
        mesh256[block]+=np.abs(F256[flat256])**2/win256
        # Exact coordinate sum, chunked to bound memory.
        wrapped=np.mod(pos,box)
        for start in range(0,len(modes),16):
          mm=modes[start:start+16,1:4].astype(float)
          phase=wrapped @ (2*np.pi/L*mm.T)
          rho=np.exp(-1j*phase).T @ q
          direct[block,start:start+len(mm)]+=np.abs(rho)**2
        # Paired all-bin full mesh curves, with per-mode k normalization.
        P384=(F384.real**2+F384.imag**2).ravel()[mask384]/w384
        strict384=np.bincount(b384,weights=P384/(kval384[mask384]*1e10)**2,minlength=int(bins[-1])+1)[bins]
        # Average mode-level susceptibilities with fixed bin counts.
        curve384[block]+=strict384/deg384*norm
        strict256=np.bincount(bid256,weights=P256/(k256*1e10)**2,minlength=int(bins[-1])+1)[bins]/deg*norm
        curve256pair[block]+=strict256
        pair_count[block]+=1
      sampled+=1
      if sampled%100==0:
        np.savez(OUT/"checkpoint.npz",p256strict=p256strict,p256sum=p256sum,mdip=mdip,mdip2=mdip2,mframes=mframes,direct=direct,mesh384=mesh384,mesh256=mesh256,curve384=curve384,curve256pair=curve256pair,pair_count=pair_count,modes=modes,bins=bins,deg=deg,kbin=kbin)
        print(f"processed {sampled}/2000 frames",flush=True)
    if sampled!=2000 or trajectory_read!=20001 or not np.all(mframes==50):
      raise RuntimeError(f"trajectory coverage failed: read={trajectory_read},sampled={sampled},blocks={mframes.tolist()}")
    sampling=sampled_time_metadata(sampled_times)
    if not np.all(pair_count==5): raise RuntimeError(f"paired frame selection failed: {pair_count}")
    # Convert per-block averages to observable curves; strict and legacy definitions remain separate.
    p256sum=p256sum.reshape(20,2,nb).sum(axis=1); p256strict=p256strict.reshape(20,2,nb).sum(axis=1)
    mdip=mdip.reshape(20,2,3).sum(axis=1); mdip2=mdip2.reshape(20,2).sum(axis=1)
    mframes=mframes.reshape(20,2).sum(axis=1)
    direct=direct.reshape(20,2,-1).sum(axis=1); mesh384=mesh384.reshape(20,2,-1).sum(axis=1); mesh256=mesh256.reshape(20,2,-1).sum(axis=1)
    curve384=curve384.reshape(20,2,nb).sum(axis=1); curve256pair=curve256pair.reshape(20,2,nb).sum(axis=1)
    pair_count=pair_count.reshape(20,2).sum(axis=1)
    legacy_curve=(p256sum/(mframes[:,None]*deg[None,:]))/((kbin*1e10)[None,:]**2)*norm
    strict_curve=p256strict/(mframes[:,None]*deg[None,:])*norm
    kfull=np.r_[0.0,kbin]
    # Independent 256 reproduction gate compares legacy-defined curve.
    legacy_mean=legacy_curve.mean(axis=0)
    # Recompute epsilon separately, pooled and per bootstrap selection.
    def epsilon(ids):
      sm=mdip[ids].sum(axis=0); s2=mdip2[ids].sum(); n=mframes[ids].sum()
      return 1+(s2/n-(sm/n)@(sm/n))/(3*EPS0*V*KB*T)
    eps=float(epsilon(np.arange(20))); chi0=1-1/eps
    full=np.r_[chi0,strict_curve.mean(axis=0)]
    full_legacy=np.r_[chi0,legacy_mean]
    # Block-bootstrap CIs and reblocking sensitivity.
    rngb=np.random.default_rng(SEED); draws=rngb.integers(0,20,size=(10000,20))
    epsb=np.array([epsilon(ix) for ix in draws]); eps_ci=np.quantile(epsb,[.025,.975])
    chi0b=1-1/epsb
    # strict curve bootstrap, plus 2 ns (10 blocks) sensitivity.
    cb=strict_curve[draws].mean(axis=1); featboot=boot_features(np.column_stack((chi0b,cb)),kfull,SEED)
    curve2=strict_curve.reshape(10,2,nb).mean(axis=1); mu2=mdip.reshape(10,2,3).mean(axis=1)
    # 2 ns pooled dipole epsilon from summed moment moments (compute exact groups).
    m2sum=mdip2.reshape(10,2).sum(axis=1); m2vec=mdip.reshape(10,2,3).sum(axis=1)
    def eps2(ids):
      sm=m2vec[ids].sum(axis=0); s2=m2sum[ids].sum(); n=200*len(ids)
      return 1+(s2/n-(sm/n)@(sm/n))/(3*EPS0*V*KB*T)
    draws2=np.random.default_rng(SEED).integers(0,10,size=(10000,10))
    epsb2=np.array([eps2(ix) for ix in draws2]); cb2=curve2[draws2].mean(axis=1)
    feat2=boot_features(np.column_stack((1-1/epsb2,cb2)),kfull,SEED)
    # Direct/mesh paired comparison, resampled by contiguous 1 ns block.
    direct_ratio=mesh384/np.maximum(direct,1e-30)
    selected_direct=[]
    for j,m in enumerate(modes):
      vals=direct_ratio[:,j]
      selected_direct.append({"bin_id":int(mode_b[j]),"nxyz":[int(x) for x in m[1:4]],"k_A^-1":float(mode_k[j]),"mean_mesh384_over_direct_power":float(vals.mean()),"paired_relative_bias_percent":float(100*(vals.mean()-1)),"frames":int(pair_count.sum())})
    # Per-output-bin paired full mesh comparisons; 20 blocks provide paired uncertainty.
    c256=curve256pair/10; c384=curve384/10
    diff=(c256-c384)/np.maximum(np.abs(c384),1e-12)
    bybin=[]
    for j,b in enumerate(bins):
      vals=diff[:,j]; mean=float(vals.mean()); se=float(vals.std(ddof=1)/np.sqrt(20))
      relse=float(strict_curve[:,j].std(ddof=1)/np.sqrt(20)/max(abs(strict_curve[:,j].mean()),1e-12))
      bybin.append({"bin_id":int(b),"k_A^-1":float(kbin[j]),"256_over_384_relative_bias":mean,"paired_95_upper_abs":float(abs(mean)+1.96*se),"full2000_relative_statistical_SE":relse,"allowed":float(max(.01,3*relse))})
    # Strict-vs-legacy binning and mesh numerical envelope per bin.
    strictmean=strict_curve.mean(axis=0); legacymean=legacy_curve.mean(axis=0)
    binning_delta=(strictmean-legacymean)/np.maximum(np.abs(strictmean),1e-12)
    out={"plan_sha256":sha(PLAN_FILE),"source_sha256":{"tpr":sha(TPR),"xtc":sha(XTC),"production.log":sha(ROOT/"production.log"),"production.edr":sha(ROOT/"production.edr")},
      "method":{"independent_implementation":"SciPy FFT + separate periodic CIC deposition + direct coordinate Fourier sums","frame_count":sampled,"sample_period_ps":sampling["sample_period_ps"],"sampled_time_range_ps":[sampling["first_time_ps"],sampling["last_time_ps"]],"pair_frames":200,"paired_per_ns_block":10,"bins":nb,"modes_direct_per_bin_min":int(min(np.bincount(mode_b,minlength=int(bins[-1])+1)[bins])),"seed":SEED,"N256":N256,"N384":N384,"bootstrap_resamples":10000},
      "native":{"atoms":nat,"waters":nw,"trajectory_frames":trajectory_read,"first_time_ps":time_first,"last_time_ps":time_last,"strictly_increasing_times":True,"every_frame_time_grid_1ps_pass":bool(trajectory_read==20001 and time_first==0.0 and time_last==20000.0),"box_A":box0.tolist(),"max_box_deviation_A":box_maxdev,"fixed_cubic_orthogonal_box_all_frames_pass":box_maxdev<=.02,"frame_dt_ps":float(u.trajectory[1].time-u.trajectory[0].time),"sampled_blocks":mframes.tolist(),"all_water_charges_and_order_pass":True,"gmx_check_pass":native_check.returncode==0,"edr_check_pass":edr_check.returncode==0,"production_completion_log_markers":True},
      "independent_reproduction":{"status":"INDEPENDENT_RECOMPUTATION_OF_CORRECTED_NATIVE_TRAJECTORY","same_trajectory_author_curve_comparison":"NOT_APPLICABLE; prior native TPR failed SPC/E intramolecular-exclusion audit","epsilon_w":eps,"epsilon_w_ci95":eps_ci.tolist()},
      "bin_definition":{"strict_modewise_k2_vs_legacy_bin_mean_power_over_mean_k2_max_relative_difference":float(np.max(np.abs(binning_delta))),"bins_over_1pct":int(np.sum(np.abs(binning_delta)>.01)),"strict_curve":strictmean.tolist(),"legacy_curve":legacymean.tolist()},
      "features_1ns":{"point":feature(full,kfull),"bootstrap":featboot,"epsilon_w_ci95":eps_ci.tolist()},"features_2ns":{"point":feature(np.r_[1-eps2(np.arange(10))**-1,curve2.mean(axis=0)],kfull),"bootstrap":feat2,"epsilon_w_ci95":np.quantile(epsb2,[.025,.975]).tolist()},
      "mesh_comparison":{"per_bin":bybin,"max_256_vs_384_paired_95_upper_abs":max(x["paired_95_upper_abs"] for x in bybin),"bins_exceeding_allowed":sum(x["paired_95_upper_abs"]>x["allowed"] for x in bybin),"selected_mode_direct_checks":selected_direct,"direct_vs_384_mean_absolute_relative_bias":float(np.mean(np.abs(direct_ratio.mean(axis=0)-1))),"direct_vs_384_max_absolute_relative_bias":float(np.max(np.abs(direct_ratio.mean(axis=0)-1)))},
      "criteria":{"legacy_reference_comparison":"NOT_APPLICABLE_INVALID_OLD_NATIVE_PROTOCOL","strict_per_mode_averaging_reported":True,"mesh_256_384_all_bins":True,"direct_sum_two_or_more_modes_per_bin":bool(np.all(np.bincount(mode_b,minlength=int(bins[-1])+1)[bins]>=2)),"numerical_tolerance_gates_not_adjusted":True}}
    (OUT/"independent_validation.json").write_text(json.dumps(out,indent=2)+"\n")
    with open(OUT/"mesh_per_bin.csv","w",newline="") as fh:
      w=csv.DictWriter(fh,fieldnames=list(bybin[0])); w.writeheader(); w.writerows(bybin)
    with open(OUT/"direct_modes.csv","w",newline="") as fh:
      w=csv.DictWriter(fh,fieldnames=list(selected_direct[0])); w.writeheader(); w.writerows(selected_direct)
    np.savetxt(OUT/"strict_response.csv",np.column_stack([kbin,strictmean,legacymean,binning_delta]),delimiter=",",header="k_A^-1,chi_strict,chi_legacy,relative_strict_minus_legacy",comments="")
    print(json.dumps({"epsilon_w":eps,"features":feature(full,kfull),"mesh_bins_over_gate":out["mesh_comparison"]["bins_exceeding_allowed"],"direct_modes":len(modes),"output":str(OUT)},indent=2))

if __name__=="__main__": main()
