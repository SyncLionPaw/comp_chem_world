#!/usr/bin/env python3
"""Summarize saved Case01 independent-validation checkpoints; no trajectory read."""
import csv, json, os, re, hashlib
from pathlib import Path
import numpy as np

ROOT=Path(os.environ.get("CASE01_DIR",Path(__file__).resolve().parents[1]))
OUT=Path(os.environ.get("OUTDIR",ROOT/"science-validation"))
SEED=20261006; NBOOT=10000
E=1.602176634e-19; EPS0=8.8541878128e-12; KB=1.380649e-23; T=300.0

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
      for c in iter(lambda:f.read(8*1024*1024),b""): h.update(c)
    return h.hexdigest()

def gro_density_g_cm3(path, waters=9033):
    lines=Path(path).read_text(errors="replace").splitlines()
    cell=np.asarray([float(x) for x in lines[-1].split()],float)
    if len(cell)<3: raise RuntimeError("GRO box line lacks three cell lengths")
    volume_nm3=float(np.prod(cell[:3]))
    if len(cell)>=9 and np.max(np.abs(cell[3:]))>1e-8: raise RuntimeError("NPT final GRO cell is not orthogonal; density helper expects the preregistered cubic cell")
    return waters*18.01528/6.02214076e23/(volume_nm3*1e-21)

def feature(y,k):
    lo=np.flatnonzero((k>=.05)&(k<=2.5)); hi=np.flatnonzero((k>=2.5)&(k<=6.0))
    i=int(lo[np.argmin(y[lo])]); j=int(hi[np.argmax(y[hi])]); half=y[j]/2
    a=np.flatnonzero(y[:j]<=half); b=np.flatnonzero(y[j+1:]<=half)
    kl=kr=width=None
    if len(a) and len(b):
      x=int(a[-1]); z=int(j+1+b[0])
      kl=float(k[x]+(half-y[x])*(k[x+1]-k[x])/(y[x+1]-y[x]))
      kr=float(k[z-1]+(half-y[z-1])*(k[z]-k[z-1])/(y[z]-y[z-1]))
      width=kr-kl
    strict=bool(i not in (int(lo[0]),int(lo[-1])) and y[i]<y[i-1] and y[i]<y[i+1])
    return {"k_min_A^-1":float(k[i]),"chi_min":float(y[i]),"k_min_strict_interior":strict,
      "k_max_A^-1":float(k[j]),"chi_max":float(y[j]),"half_height_k_minus_A^-1":kl,
      "half_height_k_plus_A^-1":kr,"delta_k_A^-1":width}

def parse_production_log(path):
    lines=Path(path).read_text(errors="replace").splitlines(); rows=[]
    num=re.compile(r"^\s*(\d+)\s+([-+0-9.eE]+)\s*$")
    value=re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
    for i,line in enumerate(lines):
      if not re.match(r"^\s*Step\s+Time\s*$",line): continue
      tm=num.match(lines[i+1]) if i+1<len(lines) else None
      if not tm: continue
      j=i+2
      while j<len(lines) and "Energies (kJ/mol)" not in lines[j] and not re.match(r"^\s*Step\s+Time\s*$",lines[j]): j+=1
      if j+5>=len(lines) or "Energies (kJ/mol)" not in lines[j]: continue
      e=[float(x) for x in value.findall(lines[j+2])]; t=[float(x) for x in value.findall(lines[j+4])]
      if len(e)>=5 and len(t)>=4: rows.append([float(tm.group(2)),e[3],e[4],t[2],t[3],t[1]])
    a=np.asarray(rows,float)
    if len(a)!=2001 or a[0,0]!=0 or a[-1,0]!=20000: raise RuntimeError(f"production log energy records incomplete: {len(a)}")
    result={"records":len(a),"time_ps":[float(a[0,0]),float(a[-1,0])],"columns":{}}
    for j,name in ((1,"Potential_kJ_mol"),(2,"Kinetic_kJ_mol"),(3,"Temperature_K"),(4,"Pressure_bar"),(5,"ConservedEnergy_kJ_mol")):
      x=a[:,j]; result["columns"][name]={"mean":float(x.mean()),"sd":float(x.std(ddof=1)),"min":float(x.min()),"max":float(x.max()),"first10ns_mean":float(x[a[:,0]<10000].mean()),"last10ns_mean":float(x[a[:,0]>=10000].mean())}
    return result

def numerical_width_bounds(curve,env,k):
    low=curve-env; high=curve+env; hi=np.flatnonzero((k>=2.5)&(k<=6.0))
    hlow=float(np.max(low[hi])); hhigh=float(np.max(high[hi]))
    candidates=hi[high[hi]>=hlow]
    if not len(candidates): return {"resolved":False,"reason":"no possible high-window peak"}
    anchor=int(candidates[np.argmax(low[candidates])])
    guaranteed=low>=hhigh/2
    if not guaranteed[anchor]: return {"resolved":False,"reason":"no guaranteed above-half anchor"}
    left=right=anchor
    while left>0 and guaranteed[left-1]: left-=1
    while right+1<len(k) and guaranteed[right+1]: right+=1
    if np.any((candidates<left)|(candidates>right)):
      return {"resolved":False,"reason":"possible peak candidates do not all lie in one guaranteed above-half component"}
    def crossings(curve0,threshold,peak):
      il=np.flatnonzero(curve0[:peak]<threshold); ir=np.flatnonzero(curve0[peak+1:]<threshold)
      if not len(il) or not len(ir): return None
      a=int(il[-1]); b=int(peak+1+ir[0])
      kl=float(k[a]+(threshold-curve0[a])*(k[a+1]-k[a])/(curve0[a+1]-curve0[a]))
      kr=float(k[b-1]+(threshold-curve0[b-1])*(k[b]-k[b-1])/(curve0[b]-curve0[b-1]))
      return kl,kr
    # Lower/upper envelope curves at worst-case half-height thresholds bound width.
    ca=crossings(low,hhigh/2,anchor); cb=crossings(high,hlow/2,anchor)
    if ca is None or cb is None: return {"resolved":False,"reason":"envelope does not bracket both interpolated crossings"}
    return {"resolved":True,"possible_peak_bin_ids":candidates.tolist(),"delta_k_A^-1_bounds":[float(ca[1]-ca[0]),float(cb[1]-cb[0])],"peak_height_bounds":[hlow,hhigh],"crossings_interpolated_between_reciprocal_bin_centers":True,"bin_resolution_half_width_A^-1":.025}

def joint_critical(a,quantile=.975,seed=SEED):
    rng=np.random.default_rng(seed); n,p=a.shape; mean=a.mean(axis=0); se=a.std(axis=0,ddof=1)/np.sqrt(n)
    maxima=[]
    for start in range(0,NBOOT,250):
      m=min(250,NBOOT-start); ix=rng.integers(0,n,(m,n)); boot=a[ix].mean(axis=1)
      maxima.extend(np.max(np.abs((boot-mean)/np.maximum(se,1e-15)),axis=1))
    return float(np.quantile(maxima,quantile))

def main():
  z=np.load(OUT/"checkpoint.npz")
  if z["mframes"].shape!=(40,) or not np.all(z["mframes"]==50) or z["pair_count"].shape!=(40,) or not np.all(z["pair_count"]==5):
    raise RuntimeError("checkpoint is incomplete; all 40 half-ns blocks and paired counts are required")
  nat=OUT/"independent_validation.json"
  if nat.exists():
    box=np.asarray(json.loads(nat.read_text())["native"]["box_A"],float)
  elif os.environ.get("BOX_A"):
    box=np.asarray([float(x) for x in os.environ["BOX_A"].split(",")],float)
  else: raise RuntimeError("need native box from independent_validation.json or BOX_A")
  L=float(box.mean()); V=L**3*1e-30; norm=E**2/(V*EPS0*KB*T)
  pstrict=z["p256strict"]; psum=z["p256sum"]; mu=z["mdip"]; mu2=z["mdip2"]; count=z["mframes"]
  bins=z["bins"]; deg=z["deg"]; kbin=z["kbin"]; k=np.r_[0.,kbin]
  direct=z["direct"]; mesh384=z["mesh384"]; curve384=z["curve384"]; curve256=z["curve256pair"]; pairs=z["pair_count"]
  modes=z["modes"]; modebin=modes[:,0]
  def groups(x,g): return x.reshape((x.shape[0]//g,g)+x.shape[1:]).sum(axis=1)
  def eps_from(a,b,c,idx):
    sm=a[idx].sum(axis=0); s2=b[idx].sum(); n=c[idx].sum()
    return 1+(s2/n-(sm/n)@(sm/n))/(3*EPS0*V*KB*T)
  def scale_report(g):
    a=groups(mu,g); b=groups(mu2,g); c=groups(count,g)
    ps=groups(pstrict,g); nblock=len(c)
    curves=ps/(c[:,None]*deg[None,:])*norm
    ep=eps_from(a,b,c,np.arange(nblock)); point=np.r_[1-1/ep,curves.mean(axis=0)]
    rng=np.random.default_rng(SEED); ix=rng.integers(0,nblock,(NBOOT,nblock))
    sm=a[ix].sum(axis=1); s2=b[ix].sum(axis=1); nn=c[ix].sum(axis=1)
    eb=1+(s2/nn-np.sum((sm/nn[:,None])**2,axis=1))/(3*EPS0*V*KB*T)
    cb=curves[ix].mean(axis=1); curvesb=np.column_stack((1-1/eb,cb))
    fs=[feature(row,k) for row in curvesb]; f0=feature(point,k)
    stats={}
    for key in ("k_min_A^-1","chi_min","k_max_A^-1","chi_max","delta_k_A^-1"):
      vv=np.asarray([f[key] for f in fs if f[key] is not None],float)
      stats[key]={"ci95":[float(np.quantile(vv,.025)),float(np.quantile(vv,.975))] if len(vv) else None,"se":float(vv.std(ddof=1)) if len(vv)>1 else None,"valid_fraction":float(len(vv)/len(fs))}
    stats["strict_interior_minimum_support"]=float(np.mean([f["k_min_strict_interior"] for f in fs]))
    stats["epsilon_w"]={"estimate":float(ep),"ci95":[float(np.quantile(eb,.025)),float(np.quantile(eb,.975))],"se":float(eb.std(ddof=1))}
    fixed={}
    for target in (.23,3.02,5.5):
      j=int(np.argmin(abs(kbin-target)))
      vv=curves[:,j]
      fixed[str(target)]={"k_A^-1":float(kbin[j]),"estimate":float(vv.mean()),"se":float(cb[:,j].std(ddof=1))}
    stats["fixed_bin_chi"]=fixed
    return {"block_length_ns":.5*g,"blocks":nblock,"point":f0,"statistics":stats,"_curves":curves,"_curve_boot":cb,"_eps_boot":eb,"_eps_blocks":np.asarray([eps_from(a,b,c,np.array([i])) for i in range(nblock)]),"_bootstrap_features":fs}
  scales={"0.5ns":scale_report(1),"1ns":scale_report(2),"2ns":scale_report(4)}
  # Full-grid paired 256/384 comparison at 1 ns grouping; summarize only measured paired frames.
  m256=groups(curve256,2); m384=groups(curve384,2); npair=groups(pairs,2)
  q256=m256/npair[:,None]; q384=m384/npair[:,None]
  rel=(q256-q384)/np.maximum(abs(q384),1e-15)
  mesh_rows=[]; env=np.zeros(len(bins)); mesh_relative_blocks=rel
  for j,bid in enumerate(bins):
    vals=rel[:,j]; mean=float(vals.mean()); se=float(vals.std(ddof=1)/np.sqrt(len(vals)))
    upper=abs(mean)+1.96*se
    relse=float(scales["1ns"]["_curves"][:,j].std(ddof=1)/np.sqrt(20)/max(abs(scales["1ns"]["_curves"][:,j].mean()),1e-15))
    allow=max(.01,3*relse)
    env[j]=upper*abs(float(q384[:,j].mean()))
    mesh_rows.append({"bin_id":int(bid),"k_A^-1":float(kbin[j],),"relative_bias_256_vs384":mean,"paired_95_abs_upper":upper,"full_curve_relative_SE":relse,"allowed":allow,"pass":bool(upper<=allow)})
  # Direct coordinate sums versus 384 CIC by mode, then paired block and output bin.
  d=groups(direct,2); m=groups(mesh384,2); dbias=np.zeros(len(bins)); direct_rows=[]; direct_relative_blocks=np.zeros((20,len(bins)))
  for j,bid in enumerate(bins):
    sel=np.where(modebin==bid)[0]
    rr=m[:,sel]/np.maximum(d[:,sel],1e-30)
    rr=rr.mean(axis=1)
    direct_relative_blocks[:,j]=rr-1
    vals=rr-1; mean=float(vals.mean()); se=float(vals.std(ddof=1)/np.sqrt(len(vals)))
    upper=abs(mean)+1.96*se; dbias[j]=upper
    direct_rows.append({"bin_id":int(bid),"k_A^-1":float(kbin[j]),"modes":int(len(sel)),"relative_bias_384_vs_direct":mean,"paired_95_abs_upper":upper,"pass_1pct":bool(upper<=.01)})
  # Propagate an explicit per-bin numerical envelope through each reported feature.
  curve=scales["1ns"]["_curves"].mean(axis=0); y=np.r_[1-1/scales["1ns"]["statistics"]["epsilon_w"]["estimate"],curve]
  # Joint, bootstrap-estimated 95% envelopes use two 97.5% max-stat bounds (Bonferroni).
  cmesh=joint_critical(mesh_relative_blocks,.975,SEED)
  cdirect=joint_critical(direct_relative_blocks,.975,SEED+1)
  env_mesh=(np.abs(mesh_relative_blocks.mean(axis=0))+cmesh*mesh_relative_blocks.std(axis=0,ddof=1)/np.sqrt(20))*np.abs(q384.mean(axis=0))
  env_direct=(np.abs(direct_relative_blocks.mean(axis=0))+cdirect*direct_relative_blocks.std(axis=0,ddof=1)/np.sqrt(20))*np.abs(curve)
  env=env_mesh+env_direct; envfull=np.r_[0.,env]
  numlo=feature(y-envfull,k); numhi=feature(y+envfull,k)
  # First/last 10 ns stability from 0.5 ns blocks; standard errors use the 20-block split.
  half={}
  a=groups(mu,1); b=groups(mu2,1); c=groups(count,1); rawcurve=pstrict/(count[:,None]*deg[None,:])*norm
  def eps_boot_se(ids):
    aa=a[ids]; bb=b[ids]; cc=c[ids]; rng=np.random.default_rng(SEED)
    ix=rng.integers(0,len(ids),(NBOOT,len(ids))); sm=aa[ix].sum(axis=1); s2=bb[ix].sum(axis=1); nn=cc[ix].sum(axis=1)
    vals=1+(s2/nn-np.sum((sm/nn[:,None])**2,axis=1))/(3*EPS0*V*KB*T)
    return float(vals.std(ddof=1))
  for label,ix in (("first10ns",np.arange(20)),("last10ns",np.arange(20,40))):
    half[label]={"epsilon_w":float(eps_from(a,b,c,ix)),"epsilon_w_se_block_bootstrap":eps_boot_se(ix),"chi_fixed_bins":{}}
    for target in (.23,3.02,5.5):
      j=int(np.argmin(abs(kbin-target))); vals=rawcurve[ix,j]
      half[label]["chi_fixed_bins"][str(target)]={"k_A^-1":float(kbin[j]),"estimate":float(vals.mean()),"se":float(vals[np.random.default_rng(SEED).integers(0,len(vals),(NBOOT,len(vals)))].mean(axis=1).std(ddof=1))}
  stability={}
  for key in ("epsilon_w","delta_k_A^-1"):
    se=[scales[x]["statistics"][key]["se"] for x in ("0.5ns","1ns","2ns")]
    ratios=[se[0]/se[1] if se[0] is not None and se[1] is not None and se[1]>0 else None,se[1]/se[2] if se[1] is not None and se[2] is not None and se[2]>0 else None]
    stability[key]={"se_by_blocking_ns":se,"adjacent_ratios":ratios,"pass_0.65_to_1.5":all(r is not None and np.isfinite(r) and .65<=r<=1.5 for r in ratios)}
  for target in (.23,3.02,5.5):
    key=str(target); se=[scales[x]["statistics"]["fixed_bin_chi"][key]["se"] for x in ("0.5ns","1ns","2ns")]
    ratios=[se[0]/se[1] if se[0] is not None and se[1] is not None and se[1]>0 else None,se[1]/se[2] if se[1] is not None and se[2] is not None and se[2]>0 else None]
    stability[f"chi_{key}"]={"se_by_blocking_ns":se,"adjacent_ratios":ratios,"pass_0.65_to_1.5":all(r is not None and np.isfinite(r) and .65<=r<=1.5 for r in ratios)}
  first=half["first10ns"]; last=half["last10ns"]
  differences={"epsilon_w":{"abs_difference":abs(first["epsilon_w"]-last["epsilon_w"]),"three_combined_SE":3*np.hypot(first["epsilon_w_se_block_bootstrap"],last["epsilon_w_se_block_bootstrap"])}}
  for target in (.23,3.02,5.5):
    key=str(target); aa=first["chi_fixed_bins"][key]; bb=last["chi_fixed_bins"][key]
    differences[f"chi_{key}"]={"abs_difference":abs(aa["estimate"]-bb["estimate"]),"three_combined_SE":3*np.hypot(aa["se"],bb["se"])}
  differences["all_within_gate"]=all(x["abs_difference"]<=x["three_combined_SE"] for k,x in differences.items() if k!="all_within_gate")
  fmesh256=feature(np.r_[1-1/scales["1ns"]["statistics"]["epsilon_w"]["estimate"],q256.mean(axis=0)],k)
  fmesh384=feature(np.r_[1-1/scales["1ns"]["statistics"]["epsilon_w"]["estimate"],q384.mean(axis=0)],k)
  mesh_feature={"256":fmesh256,"384":fmesh384,"abs_kmax_change":abs(fmesh256["k_max_A^-1"]-fmesh384["k_max_A^-1"]),"abs_width_change":abs(fmesh256["delta_k_A^-1"]-fmesh384["delta_k_A^-1"]) if fmesh256["delta_k_A^-1"] is not None and fmesh384["delta_k_A^-1"] is not None else None}
  low=curve-env; high=curve+env
  lowdomain=(kbin>=.05)&(kbin<=2.5); highdomain=(kbin>=2.5)&(kbin<=6.0)
  imin=low<=np.min(high[lowdomain]); imin &= lowdomain
  imax=high>=np.max(low[highdomain]); imax &= highdomain
  feature_bounds={"possible_minimum_bins":np.flatnonzero(imin).tolist(),"possible_minimum_k_A^-1":[float(kbin[imin].min()-.025),float(kbin[imin].max()+.025)],"possible_minimum_chi_range":[float(np.min(low[imin])),float(np.min(high[imin]))],"possible_maximum_bins":np.flatnonzero(imax).tolist(),"possible_maximum_k_A^-1":[float(kbin[imax].min()-.025),float(kbin[imax].max()+.025)],"possible_maximum_chi_range":[float(np.max(low[imax])),float(np.max(high[imax]))],"delta_k_low_vs_high_curve_sensitivity_only":[numlo["delta_k_A^-1"],numhi["delta_k_A^-1"]]}
  feature_bounds["delta_k_robust_bound"]=numerical_width_bounds(y,envfull,k)
  thermodynamics=parse_production_log(ROOT/"final/md_production.log")
  thermodynamics["density_g_cm3"]={"production_cell":9033*18.01528/6.02214076e23/(float(np.prod(box))*1e-24),"npt_final_gro":gro_density_g_cm3(ROOT/"final/npt.gro")}
  result={"source_checkpoint":str(OUT/"checkpoint.npz"),"box_A":box.tolist(),"production_thermodynamics_from_native_log":thermodynamics,"scales":{x:{k:v for k,v in q.items() if not k.startswith("_")} for x,q in scales.items()},"first_last_half_run":half,"first_last_gates":differences,"mesh_256_vs384":{"per_bin":mesh_rows,"bins_over_gate":sum(not x["pass"] for x in mesh_rows),"max_abs_upper":float(max(x["paired_95_abs_upper"] for x in mesh_rows)),"feature_comparison":mesh_feature,"feature_gate":bool(mesh_feature["abs_kmax_change"]<=.05 and mesh_feature["abs_width_change"] is not None and mesh_feature["abs_width_change"]<=.05)},"direct_vs384":{"per_bin":direct_rows,"bins_over_1pct":sum(not x["pass_1pct"] for x in direct_rows),"max_abs_upper":float(max(x["paired_95_abs_upper"] for x in direct_rows))},"numerical_envelope":{"definition":"per-bin max-stat bootstrap upper bands at 97.5% for each paired 20-block grid and direct probe; Bonferroni union gives bootstrap-estimated simultaneous at least 95% envelope, triangle-summed for feature propagation","grid_maxstat_critical_97_5":cmesh,"direct_maxstat_critical_97_5":cdirect,"per_bin_chi_absolute":env.tolist(),"features_low_curve":numlo,"features_high_curve":numhi,"extremum_position_and_height_bounds":feature_bounds},"reblocking_SE_stability":stability}
  (OUT/"science_summary.json").write_text(json.dumps(result,indent=2)+"\n")
  for name,rows in (("mesh_256_384_summary.csv",mesh_rows),("direct_384_summary.csv",direct_rows)):
    with open(OUT/name,"w",newline="") as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
  # Contract-facing outputs are derived directly from the saved block arrays.
  # Statistical intervals are block-bootstrap intervals; numerical bounds stay separate.
  final=ROOT/"final"; final.mkdir(parents=True,exist_ok=True)
  s1=scales["1ns"]; curve_boot=s1["_curve_boot"]; eps_boot=s1["_eps_boot"]
  chi0_boot=1-1/eps_boot
  with open(final/"chi_k.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["k_A^-1","mode_degeneracy","chi_parallel","chi_bootstrap_SE","chi_95_low","chi_95_high","epsilon_L"])
    eps=float(s1["statistics"]["epsilon_w"]["estimate"])
    w.writerow([0.0,0,1-1/eps,float(chi0_boot.std(ddof=1)),*np.quantile(chi0_boot,[.025,.975]).tolist(),eps])
    for j,bid in enumerate(bins):
      v=curve_boot[:,j]
      chi=float(s1["_curves"][:,j].mean()); el=(1/(1-chi)) if abs(1-chi)>1e-12 else None
      w.writerow([float(kbin[j]),int(deg[j]),chi,float(v.std(ddof=1)),*np.quantile(v,[.025,.975]).tolist(),el])
  summary_public={k:v for k,v in result.items() if k not in ("source_checkpoint",)}
  iv=json.loads((OUT/"independent_validation.json").read_text())
  def native_json_pass(relpath):
    p=ROOT/relpath
    return p.exists() and json.loads(p.read_text()).get("status")=="PASS"
  native=iv["native"]
  st=s1["statistics"]; boot=st
  gates={
    "complete_native_and_curve_audit": bool(result["production_thermodynamics_from_native_log"]["records"]==2001 and native["trajectory_frames"]==20001 and native["strictly_increasing_times"] and native["every_frame_time_grid_1ps_pass"] and native["fixed_cubic_orthogonal_box_all_frames_pass"] and native["all_water_charges_and_order_pass"] and native["gmx_check_pass"] and native["edr_check_pass"] and native_json_pass("logs/production-tpr-exclusions.json") and native_json_pass("logs/production-tpr-settings.json")),
    "all_256_vs384_bins_within_preregistered_gate": result["mesh_256_vs384"]["bins_over_gate"]==0,
    "all_direct_mode_bins_within_1pct": result["direct_vs384"]["bins_over_1pct"]==0,
    "mesh_peak_width_feature_gate": result["mesh_256_vs384"]["feature_gate"],
    "all_reblocking_SE_ratios_stable": all(v["pass_0.65_to_1.5"] for v in stability.values()),
    "first_last_half_run_stable": differences["all_within_gate"],
    "numerical_width_bound_resolved": feature_bounds["delta_k_robust_bound"]["resolved"],
    "feature_bootstrap_width_coverage": st["delta_k_A^-1"]["valid_fraction"]>=.95,
    "temperature_mean_300_plusminus_5K": abs(thermodynamics["columns"]["Temperature_K"]["mean"]-300)<=5,
    "temperature_first_last_10ns_within_3K": abs(thermodynamics["columns"]["Temperature_K"]["first10ns_mean"]-thermodynamics["columns"]["Temperature_K"]["last10ns_mean"])<=3,
    "npt_and_production_density_in_preregistered_range": all(.90<=v<=1.10 for v in thermodynamics["density_g_cm3"].values()),
  }
  def ci_obj(key):
    ci=boot[key]["ci95"]
    return ({"low_95":ci[0],"high_95":ci[1],"valid_bootstrap_fraction":boot[key]["valid_fraction"],"conditional_on_valid_draws":boot[key]["valid_fraction"]<1} if ci else {"low_95":None,"high_95":None,"valid_bootstrap_fraction":0.0,"conditional_on_valid_draws":True})
  obs={"case":"Case 001, SPC/E water (corrected native exclusions)","scientific_status":"COMPLETE" if all(gates.values()) else "PARTIAL","scientific_acceptance":"PASS" if all(gates.values()) else "FAIL","gates":gates,
    "source":{"trajectory_frames":20001,"sampled_frames":2000,"sampling_interval_ps":10,"blocks":20,"block_length_ns":1},
    "method":{"mesh":[256,256,256],"assignment":"independent periodic CIC","power_deconvolution":"divide by squared CIC assignment amplitude, then average per-mode power/k^2","bin_width_A^-1":0.05,"bootstrap":"10,000 resamples of contiguous 1 ns blocks; percentile 95% CI","bootstrap_seed":SEED,"k_min_window_A^-1":[0.05,2.5],"k_max_window_A^-1":[2.5,6.0]},
    "observables":{"eps_w":{"estimate":st["epsilon_w"]["estimate"],"ci_95":st["epsilon_w"]["ci95"],"bootstrap_SE":st["epsilon_w"]["se"],"method":"total molecular dipole fluctuation"},
      "chi_parallel_k0":{"estimate":float(1-1/eps),"ci_95":np.quantile(chi0_boot,[.025,.975]).tolist(),"method":"1 - 1/eps_w from same block bootstrap"},
      "k_min_A^-1":{"estimate":s1["point"]["k_min_A^-1"],"ci_95":ci_obj("k_min_A^-1"),"resolved":st["strict_interior_minimum_support"]>=.95,"bootstrap_strict_local_minimum_fraction":st["strict_interior_minimum_support"]},
      "chi_min":{"estimate":s1["point"]["chi_min"],"ci_95":ci_obj("chi_min")},
      "k_max_A^-1":{"estimate":s1["point"]["k_max_A^-1"],"ci_95":ci_obj("k_max_A^-1"),"bin_resolution_half_width_A^-1":.025},
      "chi_max":{"estimate":s1["point"]["chi_max"],"ci_95":ci_obj("chi_max")},
      "delta_k_A^-1":{"estimate":s1["point"]["delta_k_A^-1"],"ci_95":ci_obj("delta_k_A^-1"),"half_height_k_minus_A^-1":s1["point"]["half_height_k_minus_A^-1"],"half_height_k_plus_A^-1":s1["point"]["half_height_k_plus_A^-1"],"numerical_bound":feature_bounds["delta_k_robust_bound"]}},
    "numerical_systematic_envelope":result["numerical_envelope"],"reblocking":stability,"first_last_half_run":differences,
    "feature_resolution":{"k_min_resolved":st["strict_interior_minimum_support"]>=.95,"k_min_support":st["strict_interior_minimum_support"],"status_if_unresolved":"report point estimate, bootstrap interval, and resolution; do not claim a resolved minimum"},
    "summary_file":"../science-validation/science_summary.json"}
  (final/"observables.json").write_text(json.dumps(obs,indent=2)+"\n")
  # Replicate provenance is emitted separately after all scientific outputs exist.
  print(json.dumps({"output":str(OUT/"science_summary.json"),"256v384_over_gate":result["mesh_256_vs384"]["bins_over_gate"],"directv384_over_1pct":result["direct_vs384"]["bins_over_1pct"],"reblock":stability},indent=2))

if __name__=="__main__": main()
