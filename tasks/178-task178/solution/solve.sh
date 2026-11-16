#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
mkdir -p "$APP_DIR/final"
APP="$APP_DIR" python3 - <<'PYCODE'
import json, math, os, re
from pathlib import Path
import numpy as np
root = Path(os.environ['APP']); a = root / 'environment/assets'
def load_numeric(name, delimiter=None): return np.loadtxt(a/name, delimiter=delimiter, comments='#')
def unique_mean(x,y):
 o=np.argsort(x,kind='stable'); x,y=x[o],y[o]; ux,inv=np.unique(x,return_inverse=True)
 return ux,np.bincount(inv,weights=y)/np.bincount(inv)
rdf=load_numeric('li_li_rdf_this_work.csv',';'); r,g=rdf[:,0]/100,rdf[:,1]
mask=(r>2.2)&(r<2.8); contact_r=float(r[mask][np.argmax(g[mask])])
v=g>1e-8; rv=r[v]; pmf=-np.log(g[v]); barrier=float(pmf[(rv>2.7)&(rv<3.3)].max()-pmf[(rv>2.2)&(rv<2.7)].min())
pops={n:load_numeric('populations/'+n+'.dat')[:,1] for n in ('pop_a','pop_b','pop_c')}; cs='pop_b'; fraction=float(pops[cs].mean())
def mode(fname,col):
 h=load_numeric(fname); return int(h[np.argmax(h[:,col]),0])
cn_i,cn_iii=mode('window_blue.dat',1),mode('window_red.dat',1)
def read_xyz(path):
 lines=path.read_text().splitlines(); n=int(lines[0]); m=re.search(r'box\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)',lines[1]); box=np.array([float(m.group(i)) for i in range(1,4)])
 return [(x[0],np.array(list(map(float,x[1:4])))) for line in lines[2:2+n] if (x:=line.split())],box,lines[1]
atoms,box,note=read_xyz(a/'frame_late.xyz'); li=[i for i,x in enumerate(atoms) if x[0]=='Li']; oxy=[i for i,x in enumerate(atoms) if x[0]=='O']; hyd=[i for i,x in enumerate(atoms) if x[0]=='H']
def dist(i,j):
 d=atoms[i][1]-atoms[j][1]; d-=box*np.round(d/box); return float(np.linalg.norm(d))
adj={i:set() for i in li}
for k,i in enumerate(li):
 for j in li[k+1:]:
  if dist(i,j)<=3: adj[i].add(j); adj[j].add(i)
seen=set(); largest=0
for i in li:
 if i in seen: continue
 stack=[i]; seen.add(i); n=0
 while stack:
  k=stack.pop(); n+=1
  for j in adj[k]-seen: seen.add(j); stack.append(j)
 largest=max(largest,n)
water={o for o in oxy if any(dist(o,h)<1.25 for h in hyd)}
o_shells={i:{o for o in oxy if dist(i,o)<=2.6} for i in li}
shared=False
for i in li:
 for j in adj[i]:
  if i<j and (o_shells[i]&o_shells[j]&water): shared=True
sc=load_numeric('sfac_xray_calc.csv',';'); se=load_numeric('saxs_experiment.dat'); qc,yc=unique_mean(sc[:,0]/10,sc[:,1]); qe,ye=unique_mean(se[:,0],se[:,1]); q=np.linspace(.5,8,300); d=np.interp(q,qc,yc)-np.interp(q,qe,ye); shift=d.mean(); xrmse=float(np.sqrt(np.mean((d-shift)**2)))
files={'Li':'msd_Li_#2.csv','H2O':'msd_H2O_#2.csv','TFSI':'msd_C2F6NO4S2_#2.csv'}; msd={s:float(load_numeric(f, delimiter=';')[-1,1]/10000) for s,f in files.items()}; order=sorted(msd,key=msd.get,reverse=True)
# Evaluate what these MSD assets can support: parse each numeric time/MSD series,
# then look for explicit numeric uncertainty data and a documented fit window plus
# fit diagnostic. A single long trajectory may supply block/time-origin statistics;
# the test does not require replicated files, and a header word alone is insufficient.
def msd_evidence(filename):
 lines=(a/filename).read_text().splitlines()
 header=next((line.lstrip('# ').strip().lower() for line in lines if line.lstrip().startswith('#')), '')
 labels=[x.strip() for x in header.split(';')]
 values=load_numeric(filename,delimiter=';')
 time_series=(values.shape[1]>=2 and values.shape[0]>1 and np.all(np.diff(values[:,0])>0) and np.isfinite(values[:,:2]).all())
 error_ids=[i for i,label in enumerate(labels) if any(term in label for term in ('uncertainty','standard error','stderr','sigma','block error','time-origin error'))]
 numeric_error=any(i<values.shape[1] and i>=2 and np.all(np.isfinite(values[:,i])) and np.all(values[:,i]>=0) for i in error_ids)
 start_ids=[i for i,label in enumerate(labels) if 'fit' in label and ('start' in label or 'begin' in label)]
 end_ids=[i for i,label in enumerate(labels) if 'fit' in label and ('end' in label or 'stop' in label)]
 fit_ids=[i for i,label in enumerate(labels) if 'fit' in label and any(term in label for term in ('slope','diffusion','coefficient'))]
 diag_ids=[i for i,label in enumerate(labels) if any(term in label for term in ('r2','r^2','fit residual','fit quality','fit diagnostic'))]
 numeric_fit=(bool(start_ids) and bool(end_ids) and bool(fit_ids) and bool(diag_ids) and all(i<values.shape[1] and np.isfinite(values[:,i]).all() for i in (start_ids+end_ids+fit_ids+diag_ids)))
 return time_series,numeric_error,numeric_fit
evidence={s:msd_evidence(f) for s,f in files.items()}
# This task's supplied tables provide pointwise MSD/time/derivative only. Without
# numerical uncertainty and a reported fit interval/diagnostic, convergence of a
# long-time diffusive regime is unverified, so a quantitative coefficient is unsupported.
diffusion_reportable=all(all(parts) for parts in evidence.values())
ng={}
for s,f in [('Li','nongaussian_Li.dat'),('Ow','nongaussian_Ow.dat'),('N','nongaussian_N_ani.dat')]:
 z=load_numeric(f); m=(z[:,0]/1000>=.1)&(z[:,0]/1000<=30); ng[s]=float(z[m,1].max())
hetero=ng['Li']>.1 and ng['Ow']<=.1 and ng['N']<=.1
vh=load_numeric('vhcf_li_li.csv',';'); times=np.arange(len(vh))*.512772+.256386; ds=(np.arange(vh.shape[1])*17+8.5)/100; small=ds<.5; before=float(vh[np.ix_(times<5,small)].mean()); after=float(vh[np.ix_(times>20,small)].mean())
limits=[]; note=note.lower()
if re.search(r'\b70\s*ps\b',note): limits.append('trajectory_about_70ps')
if 'box' in note: limits.append('finite_cell')
# Count distinct element species in the actual periodic configuration. Their
# symmetric partial structure factors outnumber the single total-S channel.
species_count=len({symbol for symbol,_ in atoms})
partial_count=species_count*(species_count+1)//2
total_channels=se.shape[1]-1
unique_proof=partial_count<=total_channels
result={'nanochains_with_short_contacts':largest>=3,'contact_distance_A':contact_r,'contact_series':cs,'contact_fraction_percent':fraction,'contact_population_is_majority':fraction>50,'barrier_comparable_to_kT':.5<=barrier<=2,'transient_exchange':after>before,'contacts_share_water':shared,'contact_cn_higher_than_isolated':cn_i>cn_iii,'xray_s_agrees':xrmse<=.1,'xray_s_proves_short_chains':unique_proof,'diffusion_coefficients_quantitatively_reportable':diffusion_reportable,'msd_final_A2':msd,'apparent_mobility_order':order,'dynamic_heterogeneity_specific_to_lithium':hetero,'vhcf_small_r_mean_before_5ps':before,'vhcf_small_r_mean_after_20ps':after,'limits':limits}
(root/'final/claim.json').write_text(json.dumps(result,indent=2)+'\n')

PYCODE
