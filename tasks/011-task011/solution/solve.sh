#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'CCB_SOLVE_PY'
#!/usr/bin/env python3
"""Solve the declared conditional crack-tip thermodynamics from public inputs."""
import argparse,csv,hashlib,json,math
from pathlib import Path
import numpy as np

KB=8.617333262145e-5; EV_A2=16.02176634; MPA_A3_EV=6.241509074e-6
WIDTHS={'printed_formula_scale':1.0,'caption_standard_deviation':math.sqrt(2)}
CONDITIONS=[('fig1b_ss304_2600appm_300K',('SS304',),.0026,300),('fig2b_reference_5800appm_300K_assumed','ALL',.0058,300),('fig3_ss304_4000appm_300K',('SS304',),.004,300),('fig3_ss304_4000appm_400K',('SS304',),.004,400)]

def read(p):
 with p.open(newline='',encoding='utf8') as f:return list(csv.DictReader(f))
def write(p,rs):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',newline='',encoding='utf8') as f:w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def nu_hill(c11,c12,c44):
 gv=(c11-c12+3*c44)/5; gr=5*(c11-c12)*c44/(4*c44+3*(c11-c12));g=(gv+gr)/2;b=(c11+2*c12)/3
 return (3*b-2*g)/(2*(3*b+g))
def entropy(cs,cb,T,a0):
 cs=min(1.,max(0.,float(cs))); f=0.
 if cs>0:f+=-cs*math.log(cb)+cs*math.log(cs)
 if cs<1:f+=(1-cs)*math.log(1-cs)
 return KB*T/(math.sqrt(3)*a0*a0/4)*f*EV_A2
def grid(order=192):
 z,w=np.polynomial.legendre.leggauss(order);x=8*z;return x,8*w*np.exp(-x*x)/math.sqrt(math.pi)
X,W=grid()
def occ(E,eta,T):return 1/(1+np.exp(np.clip((E-eta)/(KB*T),-700,700)))
def eta_bulk(cb,sigma,T,energy_offset=0.0):
 lo,hi=-5.,5.
 for _ in range(100):
  mid=(lo+hi)/2
  if float(np.dot(W,occ(sigma*X+energy_offset,mid,T)))<cb:lo=mid
  else:hi=mid
 return (lo+hi)/2
def interp(x,points):
 points=sorted(points)
 if x<points[0][0]-1e-12 or x>points[-1][0]+1e-12:raise ValueError('coverage outside sourced anchors')
 for (x0,y0),(x1,y1) in zip(points,points[1:]):
  if x0<=x<=x1:return y0+(y1-y0)*(x-x0)/(x1-x0)
 return points[-1][1]
def calculate(assets,outdir):
 density={r['alloy']:r for r in read(assets/'absorption_distribution_fig2a.csv')}
 elastic={r['alloy']:r for r in read(assets/'elastic_constants_fig2a.csv')}
 A0={r['alloy']:float(r['A0_A2']) for r in read(assets/'lattice_parameters_A0.csv')}
 gf={}
 for r in read(assets/'gamma_f_fig2b_digitized.csv'):gf.setdefault(r['alloy'],[]).append(r)
 coords={}
 for r in read(assets/'task11_crack_site_coordinates.csv'):coords.setdefault(r['alloy'],[]).append(r)
 if set(density)!=set(A0) or len(density)!=6:raise ValueError('expected six matching source alloys')
 anchors={}; anchor_rows=[]
 for alloy,rs in gf.items():
  if len(rs)!=3:raise ValueError(alloy+': need three gammaF anchors')
  anchors[alloy]=[]
  for r in sorted(rs,key=lambda x:float(x['C_surface'])):
   cs=float(r['C_surface']); cb=float(r['Cb_context_appm'])/1e6
   if abs(cb-.0058)>1e-12:raise ValueError('Fig2b gammaF reference concentration is not 5800 appm')
   a0=math.sqrt(A0[alloy]*4/math.sqrt(3))
   gs=entropy(cs,cb,300,a0); gm=float(r['gamma_F_mean_J_m2'])-gs; gl=float(r['gamma_F_low_J_m2'])-gs; gh=float(r['gamma_F_high_J_m2'])-gs
   anchors[alloy].append((cs,gm,gl,gh))
   anchor_rows.append({'alloy':alloy,'C_surface':cs,'Cb_reference_fraction':cb,'T_reference_assumed_K':300,'gamma_F_source_mean_J_m2':r['gamma_F_mean_J_m2'],'gamma_F_source_low_J_m2':r['gamma_F_low_J_m2'],'gamma_F_source_high_J_m2':r['gamma_F_high_J_m2'],'gamma_S_recomputed_J_m2':gs,'gamma_E_conditional_mean_J_m2':gm,'gamma_E_conditional_low_J_m2':gl,'gamma_E_conditional_high_J_m2':gh,'source_relation':'conditional gamma_E = digitized gamma_F minus gamma_S at Cb=5800 appm and assumed Tref=300 K; not independent raw P3 gamma_E'})
 occ_rows=[]; gf_rows=[]; maxres=0.; shift_res=0.; width_summary={}; comparisons=[]
 for condition,selected,cb,T in CONDITIONS:
  alloys=sorted(density) if selected=='ALL' else list(selected)
  for alloy in alloys:
   p=density[alloy]; sigma=float(p['sigma_eV']); mean=float(p['Ebar_eV']); er=elastic[alloy]
   nu=nu_hill(float(er['C11_GPa']),float(er['C12_GPa']),float(er['C44_GPa']))
   cr=sorted(coords.get(alloy,[]),key=lambda r:int(r['site_column']))
   if len(cr)!=12:raise ValueError(alloy+': need 12 public registered model coordinates')
   anchors_a=anchors[alloy]
   e_pts=[(x,gm) for x,gm,_,_ in anchors_a];lo_pts=[(x,gl) for x,gm,gl,_ in anchors_a];hi_pts=[(x,gh) for x,gm,_,gh in anchors_a]
   a0=math.sqrt(A0[alloy]*4/math.sqrt(3))
   for width,factor in WIDTHS.items():
    sw=sigma*factor; eta=eta_bulk(cb,sw,T); bulk=float(np.dot(W,occ(sw*X,eta,T)));maxres=max(maxres,abs(bulk-cb))
    shifted=eta_bulk(cb,sw,T,.731) # solve again after shifting the full distribution
    shift_res=max(shift_res,abs((shifted-.731)-eta))
    for K in [i/10 for i in range(13)]:
     cis=[]
     for r in cr:
      x=float(r['x_A']); y=float(r['y_A']); rad=math.hypot(x,y); theta=math.atan2(y,x)
      press=2*(1+nu)/3*K/math.sqrt(2*math.pi*rad*1e-10)*math.cos(theta/2)
      shift=press*2.8*MPA_A3_EV
      cis.append(float(np.dot(W,occ(sw*X-shift,eta,T))))
     cc=sum(cis[:9])/9; ce=sum(cis[9:])/3; cs=min(1.,1.5*cc)
     ge=interp(cs,e_pts); gl=interp(cs,lo_pts); gh=interp(cs,hi_pts); gs=entropy(cs,cb,T,a0); gf=ge+gs
     common={'condition':condition,'alloy':alloy,'Cb_fraction':cb,'T_K':T,'Kapp_MPa_sqrt_m':K,'width_interpretation':width,'eta_eV_mu_minus_Ebar_minus_EZP':eta,'Cb_recomputed':bulk,'C_cleave':cc,'C_emit':ce,'C_S':cs,'nu_hill':nu,'DeltaV_A3':2.8,'geometry_source':'public topology-registered coordinates; model coordinates, not author-published crack-tip sites'}
     for i,ci in enumerate(cis,1):occ_rows.append({**common,'site_column':i,'c_i':ci})
     gf_rows.append({**common,'A0_A2':A0[alloy],'gamma_E_J_m2':ge,'gamma_E_low_J_m2':gl,'gamma_E_high_J_m2':gh,'gamma_S_J_m2':gs,'gamma_F_J_m2':gf,'gamma_F_low_J_m2':gl+gs,'gamma_F_high_J_m2':gh+gs,'gamma_E_input':'conditional Fig2b gammaF minus recomputed gammaS; assumed Tref=300K','gammaF_source_interval_J_m2':'±0.05 digitization interval propagated unchanged'})
     width_summary.setdefault((condition,alloy,K),{})[width]={'eta_eV':eta,'C_cleave':cc,'C_emit':ce,'C_S':cs,'gamma_S_J_m2':gs,'gamma_F_J_m2':gf}
 # Fig1b is retained as a comparator. Report actual center-registration interval overlap for both width readings.
 fig=read(assets/'task11_fig1b_occupancy_reference.csv'); ref={(float(r['Kapp_MPa_sqrt_m']),r['curve']):r for r in fig}
 for width in WIDTHS:
  hits=0; n=0
  for (cond,alloy,K),vals in width_summary.items():
   if cond!='fig1b_ss304_2600appm_300K':continue
   v=vals[width]
   for label,pred in [('C_cleave',v['C_cleave']),('C_emit',v['C_emit'])]:
    r=ref.get((K,label))
    if r:
     lo=float(r['occupancy_low_pixel_interval']);hi=float(r['occupancy_high_pixel_interval']);hits+=int(lo<=pred<=hi);n+=1
  comparisons.append({'width_interpretation':width,'SS304_Fig1b_center_registration_interval_hits':hits,'available_pixel_intervals':n,'assessment':'source readout comparator; mismatch is reported and not used to fit the model'})
 # One-at-a-time numerical model sensitivities around the declared SS304 midpoint case.
 er=elastic['SS304']; c11,c12,c44=(float(er[k]) for k in ('C11_GPa','C12_GPa','C44_GPa'))
 bulk=(c11+2*c12)/3; gv=(c11-c12+3*c44)/5; gr=5*(c11-c12)*c44/(4*c44+3*(c11-c12))
 nus={'Voigt':(3*bulk-2*gv)/(2*(3*bulk+gv)),'Hill':nu_hill(c11,c12,c44),'Reuss':(3*bulk-2*gr)/(2*(3*bulk+gr))}
 sscoords=sorted(coords['SS304'],key=lambda r:int(r['site_column'])); mean=float(density['SS304']['Ebar_eV']); sig=float(density['SS304']['sigma_eV']); alat=math.sqrt(A0['SS304']*4/math.sqrt(3)); dx=alat*math.sqrt(6)/4
 def sens_cover(K,width,nu,dv,origin):
  sw=sig*WIDTHS[width]; eta=eta_bulk(.0026,sw,300); vals=[]
  for r in sscoords:
   xx=float(r['x_A'])-origin*dx; yy=float(r['y_A']); rad=math.hypot(xx,yy); th=math.atan2(yy,xx)
   if rad<=1e-12:raise ValueError('origin sensitivity reaches singular site')
   press=2*(1+nu)/3*K/math.sqrt(2*math.pi*rad*1e-10)*math.cos(th/2)
   vals.append(float(np.dot(W,occ(sw*X-press*dv*MPA_A3_EV,eta,300))))
  cc=sum(vals[:9])/9; ce=sum(vals[9:])/3; return {'C_cleave':cc,'C_emit':ce,'C_S':min(1,1.5*cc)}
 sensitivity=[]
 for width in WIDTHS:
  for K in (.6,.8):
   base=sens_cover(K,width,nus['Hill'],2.8,0)
   sensitivity.append({'width':width,'Kapp':K,'variant':'baseline','parameters':{'nu':'Hill','DeltaV_A3':2.8,'origin_delta_over_dx':0},'coverages':base})
   for label,nv in nus.items():
    if label!='Hill':sensitivity.append({'width':width,'Kapp':K,'variant':'nu_'+label,'parameters':{'nu':label,'DeltaV_A3':2.8,'origin_delta_over_dx':0},'coverages':sens_cover(K,width,nv,2.8,0)})
   for dv in (2.7,2.9):sensitivity.append({'width':width,'Kapp':K,'variant':'DeltaV_'+str(dv),'parameters':{'nu':'Hill','DeltaV_A3':dv,'origin_delta_over_dx':0},'coverages':sens_cover(K,width,nus['Hill'],dv,0)})
   for origin in (-.1,.1):sensitivity.append({'width':width,'Kapp':K,'variant':'origin_'+str(origin),'parameters':{'nu':'Hill','DeltaV_A3':2.8,'origin_delta_over_dx':origin},'coverages':sens_cover(K,width,nus['Hill'],2.8,origin)})
 checks={'schema':'case05-limiting-checks/v1','maximum_bulk_concentration_residual':maxres,'maximum_common_reference_shift_eta_residual_eV':shift_res,'site_occupancy_bounds':[min(float(x['c_i']) for x in occ_rows),max(float(x['c_i']) for x in occ_rows)],'gamma_S_endpoint_checks':{alloy:{'gamma_S_cs0_J_m2':entropy(0,.0058,300,math.sqrt(A0[alloy]*4/math.sqrt(3))),'gamma_S_cs1_J_m2':entropy(1,.0058,300,math.sqrt(A0[alloy]*4/math.sqrt(3)))} for alloy in A0},'temperature_recomputed':[300,400],'fig1b_source_comparison':comparisons,'width_sensitivity':'printed formula scale uses sigma; caption-standard-deviation interpretation uses sqrt(2)*sigma; both retained without selecting by fit.','conditional_energy_family':'Fig2b gammaF anchors minus recomputed gammaS at 5800 appm and assumed Tref 300 K; not independent P3 gammaE evidence.'}
 source_hashes={}
 for name in ('absorption_distribution_fig2a.csv','elastic_constants_fig2a.csv','lattice_parameters_A0.csv','gamma_f_fig2b_digitized.csv','task11_crack_site_coordinates.csv','task11_crack_site_coordinates.provenance.json','task11_fig1b_occupancy_reference.csv','task11_ss304_fig3_temperature_reference.csv'):
  source_hashes['assets/'+name]='sha256:'+hashlib.sha256((assets/name).read_bytes()).hexdigest()
 model={'schema':'case05-conditional-model/v1','density_model':'exp(-x^2)/sqrt(pi), E-Ebar=sigma*x; kB in eV/K','width_interpretations':WIDTHS,'eta_definition':'eta=mu-Ebar-EZP; E_ZP common shift absorbed; no absolute mu claimed','geometry_source_asset':'assets/task11_crack_site_coordinates.csv','geometry_scope':'12 public topology-registered FCC model coordinates; columns 1-9 cleavage mean, 10-12 emission mean; model coordinates, not author-published crack sites.','pressure_equation':'p=2(1+nu)Kapp/(3 sqrt(2*pi*r))*cos(theta/2)','pressure_units_and_sign':'Kapp MPa sqrt(m), r meters; positive tensile pressure lowers occupied-site energy by p DeltaV.','poisson_ratio_closure':'Hill isotropic closure from source C11/C12/C44','DeltaV_A3':2.8,'coverage_definitions':'C_cleave=mean(c1..c9); C_emit=mean(c10..c12); C_S=min(1,1.5*C_cleave).','gamma_S_equation':'kB*T/A0[-Cs ln(Cb)+(1-Cs)ln(1-Cs)+Cs ln(Cs)] *16.02176634; 0ln0=0; A0=sqrt(3)a0^2/4.','gamma_E_condition':'linear interpolation only between source C_surface=0,.5,1 anchors; each gammaE conditional on source gammaF(Cb=5800 appm)-gammaS(Cb=5800,Tref=300K assumed), with ±0.05 J/m2 image interval propagated.','conditional_assumptions':['gamma_E family held fixed away from its 5800 appm, assumed 300 K anchor condition.','nu, DeltaV and crack-column coordinates are registered model choices; numeric sensitivity is reported.','temperature source labels are comparators, not locally reconstructed first crossings.'],'source_inputs_sha256':source_hashes,'sensitivity_summary':{'fig1b_source_comparison':checks['fig1b_source_comparison'],'one_at_a_time_model_sensitivity':sensitivity},'condition_count':len(set(x['condition'] for x in gf_rows)),'condition_alloy_pair_count':len(set((x['condition'],x['alloy']) for x in gf_rows)),'thermodynamic_rows':len(gf_rows),'occupation_rows':len(occ_rows)}
 outdir.mkdir(parents=True,exist_ok=True);write(outdir/'occupation.csv',occ_rows);write(outdir/'fracture_free_energy.csv',gf_rows);(outdir/'thermodynamic_model.json').write_text(json.dumps(model,indent=2,ensure_ascii=False)+'\n');(outdir/'limiting_checks.json').write_text(json.dumps(checks,indent=2,ensure_ascii=False)+'\n')
 (outdir/'mechanism.md').write_text('# Conditional crack-tip thermodynamics\n\nThis deliverable is a conditional model based on the public Fig. 2(a) density, Fig. 2(b) digitized gammaF anchors, source elastic constants, and an explicit topology-registered FCC crack-column model. The twelve coordinates are model coordinates, not author-published crack sites. Both Gaussian width readings and the source image interval are retained.\n\nThe conditional gammaE anchor family is obtained by subtracting recomputed gammaS from digitized gammaF at Cb=5800 appm and assumed Tref=300 K. It is not independent raw P3 gammaE evidence. That family is held fixed at other concentrations and temperatures as a model assumption. The source reports SS304 at 4000 appm as embrittled at 300 K and not embrittled at 400 K; this source label is compared separately from the computed thermodynamic curves.\n\nNo absolute chemical potential is claimed: eta=mu-Ebar-EZP is the solved coordinate. Width convention, Hill nu, DeltaV=2.8 A^3 and origin registration are model choices; the conditional scope and Fig.1(b) digitization comparison are stated in the JSON deliverables.\n',encoding='utf8')
 return {'occupation_rows':len(occ_rows),'fracture_free_energy_rows':len(gf_rows),'gamma_E_anchors':len(anchor_rows),'maximum_bulk_residual':maxres,'max_shift_residual':shift_res}
def main():
 p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,default=Path('/app/assets'));p.add_argument('--outdir',type=Path,default=Path('/app/final'));a=p.parse_args();result=calculate(a.assets,a.outdir)
 source=Path(__file__).resolve();source_out=a.outdir/'calculation_source.py';source_out.write_bytes(source.read_bytes())
 input_hashes={x.name:'sha256:'+hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(a.assets.iterdir()) if x.is_file()}
 output_hashes={x.name:'sha256:'+hashlib.sha256(x.read_bytes()).hexdigest() for x in a.outdir.iterdir() if x.is_file() and x.name not in {'run_metadata.json'}}
 meta={'schema':'compchemworld-calculation-run/v1','calculation_sources':[{'name':'calculation_source.py','sha256':'sha256:'+hashlib.sha256(source_out.read_bytes()).hexdigest()}],'inputs':input_hashes,'outputs':output_hashes,'python':__import__('platform').python_version(),'execution_context':'local CPU thermodynamic model; no DFT execution'}
 (a.outdir/'run_metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf8')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
CCB_SOLVE_PY
python3 "$work_dir/solve.py" --assets /app/assets --outdir /app/final
