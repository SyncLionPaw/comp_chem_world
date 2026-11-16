"""Independent scalar reference for the finite 006 analysis contract."""
from __future__ import annotations
import math

QE=1.602176634e-19
KB=1.380649e-23
EPS0=8.8541878128e-12
NA=6.02214076e23

def f(row,key):
    x=float(row[key])
    if not math.isfinite(x): raise ValueError(f'non-finite {key}')
    return x

def deriv3(points, x0):
    (x0a,y0),(x1,y1),(x2,y2)=points
    if len({x0a,x1,x2})!=3: raise ValueError('duplicate derivative coordinates')
    return (y0*(2*x0-x1-x2)/((x0a-x1)*(x0a-x2)) +
            y1*(2*x0-x0a-x2)/((x1-x0a)*(x1-x2)) +
            y2*(2*x0-x0a-x1)/((x2-x0a)*(x2-x1)))

def five(stencil,h):
    return (stencil[-2]-8*stencil[-1]+8*stencil[1]-stencil[2])/(12*h)

def fit(points):
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    n=len(xs); xm=sum(xs)/n; ym=sum(ys)/n
    # Independent centered scalar OLS; no NumPy/polyfit candidate reuse.
    den=sum((x-xm)**2 for x in xs)
    if den==0: raise ValueError('singular line fit')
    slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/den
    intercept=ym-slope*xm
    rms=math.sqrt(sum((y-(slope*x+intercept))**2 for x,y in zip(xs,ys))/n)
    return {'slope':slope,'intercept_m2_per_F':intercept,'rms_residual_m2_per_F':rms}

def gc(c_mM,T,eps_b,phi=0.0):
    n=c_mM*NA # 1 mM = 1 mol/m^3
    k=math.sqrt(2*QE*QE*n/(EPS0*eps_b*KB*T))
    cd=EPS0*eps_b*k
    vt=KB*T/QE
    return cd*math.cosh(phi/(2*vt))

def compute(rows,refrows,manifest):
    params=manifest['parameters']; T=float(params['temperature_K'])
    eps_b=1+1/float(params['K11'])+1/float(params['K21'])
    branches={b['branch_id']:(float(b['concentration_mM']),float(b['Pbar_C_m2'])) for b in manifest['branch_matrix']}
    by={bid:{'coarse':[],'near_pzc_h':{},'near_pzc_h2':{},'near_pzc_h4':{}} for bid in branches}
    for r in rows:
        bid=r['branch_id']; lev=r['grid_level']; s=f(r,'sigma0_C_m2'); phi=f(r,'phi0_V')
        if lev=='coarse_curve': by[bid]['coarse'].append((s,phi))
    # read near stencils directly into simple dictionaries
    near={bid:{lev:{} for lev in ('near_pzc_h','near_pzc_h2','near_pzc_h4')} for bid in branches}
    for r in rows:
        lev=r['grid_level']
        if lev!='coarse_curve': near[r['branch_id']][lev][f(r,'sigma0_C_m2')]=f(r,'phi0_V')
    refined={bid:{lev:{} for lev in ('curve_h','curve_h2','curve_h3')} for bid in branches}
    for r in refrows:
        refined[r['branch_id']][r['derivative_level']].setdefault(f(r,'center_sigma0_C_m2'),{})[int(r['offset_multiple'])]=f(r,'phi0_V')
    branch_result=[]; pzc_map={}
    for bid,(c,pbar) in branches.items():
        coarse=sorted(by[bid]['coarse'])
        sig=[x for x,y in coarse]; ph=[y for x,y in coarse]
        cv=[]; ds=[]
        for i,(s,v) in enumerate(coarse):
            start=max(0,min(i-1,len(sig)-3)); points=coarse[start:start+3]
            d=deriv3(points,s)
            if not math.isfinite(d) or d==0: raise ValueError('singular coarse dphi/dsigma')
            signed=1/d; ds.append(d)
            cv.append({'sigma0_C_m2':s,'phi0_V':v,'d_sigma_d_phi_F_m2':signed,'C_F_m2':abs(signed)})
        turns=[]
        for i,(a,b) in enumerate(zip(ds,ds[1:])):
            if a*b<0:
                turns.append({'bracket_sigma0_C_m2':[sig[i],sig[i+1]],'derivative_sign':[1 if a>0 else -1,1 if b>0 else -1],
                              'interpretation':'coarse-grid diagnostic interval only; does not locate the refined physical fold or imply stability'})
        if sig.count(0.0)!=1: raise ValueError('exact sigma zero missing')
        phi0=ph[sig.index(0.0)]
        cvals={}
        hs={'h':.001,'h2':.0005,'h4':.00025}
        levels={'h':'near_pzc_h','h2':'near_pzc_h2','h4':'near_pzc_h4'}
        for name,lev in levels.items():
            st=near[bid][lev]
            h=hs[name]
            vals={int(round(s/h)):v for s,v in st.items()}
            d=five(vals,h)
            cvals[name]=1/abs(d)
        h8der=five(refined[bid]['curve_h3'][0.0],.000125)
        cvals['h8']=1/abs(h8der)
        diffs=[abs(cvals['h2']-cvals['h']),abs(cvals['h4']-cvals['h2']),abs(cvals['h8']-cvals['h4'])]
        pz_rel=[x/cvals['h8'] for x in diffs]
        a,b=diffs[-2:]
        observed=None if min(a,b)<=1e-14 else math.log(a/b,2)
        physical=[]
        for s,_ in coarse:
            item={'sigma0_C_m2':s,'phi0_V':dict(coarse)[s]}
            for name,h in (('curve_h',.0005),('curve_h2',.00025),('curve_h3',.000125)):
                d=five(refined[bid][name][s],h); signed=1/d
                item[f'd_sigma_d_phi_{name}_F_m2']=signed
                item[f'C_{name}_F_m2']=abs(signed)
            coarse_item=next(x for x in cv if x['sigma0_C_m2']==s)
            fine=item['C_curve_h3_F_m2']
            item['coarse_diagnostic_C_F_m2']=coarse_item['C_F_m2']
            item['coarse_relative_bias_vs_curve_h3']=(coarse_item['C_F_m2']-fine)/fine
            item['relative_change_h_to_h2']=(item['C_curve_h2_F_m2']-item['C_curve_h_F_m2'])/fine
            item['relative_change_h2_to_h3']=(item['C_curve_h3_F_m2']-item['C_curve_h2_F_m2'])/fine
            item['d_phi_d_sigma_curve_h_V_per_C_m2']=1/item['d_sigma_d_phi_curve_h_F_m2']
            item['d_phi_d_sigma_curve_h2_V_per_C_m2']=1/item['d_sigma_d_phi_curve_h2_F_m2']
            item['d_phi_d_sigma_curve_h3_V_per_C_m2']=1/item['d_sigma_d_phi_curve_h3_F_m2']
            d1=item['d_phi_d_sigma_curve_h_V_per_C_m2'];d2=item['d_phi_d_sigma_curve_h2_V_per_C_m2'];d3=item['d_phi_d_sigma_curve_h3_V_per_C_m2']
            item['abs_d_phi_change_h_to_h2_V_per_C_m2']=abs(d2-d1)
            item['abs_d_phi_change_h2_to_h3_V_per_C_m2']=abs(d3-d2)
            item['d_phi_sign_consistent']=(d1>0)==(d2>0)==(d3>0)
            delta=2*abs(d3-d2)
            lo,hi=d3-delta,d3+delta
            contains=lo<=0<=hi
            item['estimated_delta_d_phi_V_per_C_m2']=delta
            item['d_phi_interval_h3_V_per_C_m2']=[lo,hi]
            item['d_phi_interval_contains_zero']=contains
            item['C_magnitude_interval_F_m2']=[1/max(abs(lo),abs(hi)),None if contains else 1/min(abs(lo),abs(hi))]
            physical.append(item)
        max_d3=max(abs(x['d_phi_d_sigma_curve_h3_V_per_C_m2']) for x in physical)
        for item in physical:
            item['relative_derivative_scale_h3']=abs(item['d_phi_d_sigma_curve_h3_V_per_C_m2'])/max_d3
            rel=abs(item['relative_change_h2_to_h3'])
            item['numerical_resolution']=('unresolved' if not item['d_phi_sign_consistent'] or item['d_phi_interval_contains_zero'] else
                'ill_conditioned' if rel>.01 else 'resolved')
        fine_turns=[]; conflicts=[]
        for left,right in zip(physical,physical[1:]):
            sl=int(math.copysign(1,left['d_phi_d_sigma_curve_h3_V_per_C_m2']))
            sr=int(math.copysign(1,right['d_phi_d_sigma_curve_h3_V_per_C_m2']))
            if sl!=sr:
                fine_turns.append({'bracket_sigma0_C_m2':[left['sigma0_C_m2'],right['sigma0_C_m2']],
                    'derivative_sign_h3':[sl,sr],
                    'endpoint_resolution':[left['numerical_resolution'],right['numerical_resolution']],
                    'interpretation':'refined-center sign-change bracket; not an interpolated fold location'})
            cl=int(math.copysign(1,next(x for x in cv if x['sigma0_C_m2']==left['sigma0_C_m2'])['d_sigma_d_phi_F_m2']))
            cr=int(math.copysign(1,next(x for x in cv if x['sigma0_C_m2']==right['sigma0_C_m2'])['d_sigma_d_phi_F_m2']))
            if cl!=sl or cr!=sr:
                conflicts.append({'interval_sigma0_C_m2':[left['sigma0_C_m2'],right['sigma0_C_m2']],
                    'coarse_derivative_sign':[cl,cr],'h3_derivative_sign':[sl,sr]})
        deriv_c={name:five({int(round(s/hs[name])):v for s,v in near[bid][lev].items()},hs[name]) for name,lev in levels.items()}
        signed_c={name:1/deriv for name,deriv in deriv_c.items()}
        deriv_c['h8']=h8der; signed_c['h8']=1/h8der
        signs={name:(1 if deriv>0 else -1) for name,deriv in deriv_c.items()}
        pz={'phi_pzc_V':phi0,'C_by_level_F_m2':cvals,'signed_d_sigma_d_phi_by_level_F_m2':signed_c,
            'd_phi_d_sigma_by_level_V_per_C_m2':deriv_c,'sign_by_level':signs,
            'signed_response_sign_consistent':len(set(signs.values()))==1,
            'has_negative_response':any(x<0 for x in signed_c.values()),
            'pzc_response_diagnostic':'signed differential response is reported; its sign alone does not establish fixed-voltage thermodynamic stability',
            'chosen_level':'h8','C_pzc_F_m2':cvals['h8'],
            'absolute_differences_F_m2':diffs,'relative_differences':pz_rel,'observed_order_or_null':observed}
        branch_result.append({'branch_id':bid,'concentration_mM':c,'Pbar_C_m2':pbar,'coarse_curve':cv,
                              'turning_intervals':turns,'fine_center_turning_brackets_h3':fine_turns,
                              'coarse_fine_sign_conflicts':conflicts,'pzc':pz,'physical_capacitance_curve':physical})
        pzc_map[(c,pbar)]=pz
    pz_results=[]
    fit_cs=[float(c) for c in manifest['fit']['primary_concentrations_mM']]
    for pbar in sorted({x[1] for x in branches.values()}):
        pts=[]
        for c in fit_cs:
            pp=pzc_map[(c,pbar)]; C=pp['C_pzc_F_m2']; phi=pp['phi_pzc_V']
            cd0=gc(c,T,eps_b); cdphi=gc(c,T,eps_b,phi)
            pts.append({'c_mM':c,'phi_pzc_V':phi,'C_pzc_F_m2':C,
                        'signed_C_pzc_F_m2':pp['signed_d_sigma_d_phi_by_level_F_m2']['h8'],
                        'd_phi_d_sigma_pzc_V_per_C_m2':pp['d_phi_d_sigma_by_level_V_per_C_m2']['h8'],
                        'C_D_F_m2':cd0,
                        'x_m2_per_F':1/cd0,'y_m2_per_F':1/C,
                        'C_D_at_model_pzc_F_m2':cdphi,'x_at_model_pzc_m2_per_F':1/cdphi})
        primary=fit([(x['x_m2_per_F'],x['y_m2_per_F']) for x in pts])
        loo=[]
        for i,point in enumerate(pts):
            loo.append({'omitted_c_mM':point['c_mM'],**fit([(x['x_m2_per_F'],x['y_m2_per_F']) for j,x in enumerate(pts) if i!=j])})
        windows=[]
        for cs in manifest['fit']['neighbor_windows']:
            subset=[x for x in pts if x['c_mM'] in cs]
            windows.append({'concentrations_mM':cs,**fit([(x['x_m2_per_F'],x['y_m2_per_F']) for x in subset])})
        alt=[{**point,'x_m2_per_F':point['x_at_model_pzc_m2_per_F']} for point in pts]
        pz_results.append({'Pbar_C_m2':pbar,'reference_convention':'gc_own_pzc_phi0_zero','points':pts,'primary_fit':primary,
                           'leave_one_out':loo,'neighbor_windows':windows,
                           'alternative_gc_at_model_pzc':{'reference_convention':'gc_at_model_phi_pzc','points':alt,
                              'fit':fit([(x['x_m2_per_F'],x['y_m2_per_F']) for x in alt])}})
    allphysical=[p for b in branch_result for p in b['physical_capacitance_curve']]
    return {'schema_version':'006-analysis-output/v1','dataset':manifest['dataset'],
            'source_dataset_schema':manifest['schema_version'],'temperature_K':T,
            'alpha':float(params['alpha']),'cell_length_nm':float(params['cell_length_nm']),
            'eps_b':eps_b,'branches':branch_result,'parsons_zobel':pz_results,
            'resolution_summary':{'curve_point_count':len(allphysical),
                'resolved_count':sum(p['numerical_resolution']=='resolved' for p in allphysical),
                'ill_conditioned_count':sum(p['numerical_resolution']=='ill_conditioned' for p in allphysical),
                'unresolved_count':sum(p['numerical_resolution']=='unresolved' for p in allphysical),
                'delta_d_estimate':'2*abs(d_phi_d_sigma_h3-d_phi_d_sigma_h2); heuristic grid-difference indicator, not a rigorous bound',
                'zero_containment_rule':'unresolved if the indicated d_phi/d_sigma interval includes zero or signs disagree across h levels',
                'capacitance_interval':'reciprocal magnitude interval; upper is null/unbounded if the indicated derivative interval contains zero',
                'resolved_threshold_relative_C_change_h2_to_h3':0.01},
            'method':{'coarse_curve_derivative':'invert local three-point quadratic dphi0/dsigma0 at each sigma sample; retain signed and absolute d_sigma_d_phi, and do not sort through a turning point',
                      'pzc':'use the exact sigma0=0 row on each fixed-(concentration,Pbar) branch',
                      'pzc_derivative':'five-point central dphi0/dsigma0 at h=.001,.0005,.00025,.000125 C/m^2; C0=1/abs(dphi0/dsigma0); h8=.000125 is the finest public estimate',
                      'primary_pz_axis':'x=1/C_GC at its own PZC phi0=0; y=1/C_model at sigma0=0; unweighted OLS at fixed Pbar',
                      'secondary_pz_axis':'diagnostic x=1/C_GC evaluated at the model\'s physical phi_pzc',
                      'paper_figure_slopes':'not score targets; no claim of paper-exact Figure 8 fitting'}}
