#!/usr/bin/env python3
"""Candidate-native L3 scorer for Case01.

The scorer hash-verifies native inputs through native_audit, independently
recomputes the response from TPR+trajectory in an isolated scratch tree, and
compares candidate deliverables with that recomputation. Candidate summary
fields/checkpoints are never used as recomputation inputs.
"""
from __future__ import annotations
import argparse, csv, json, math, os, shutil, subprocess, tempfile, hashlib, sys
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
REFERENCE=HERE/'reference'
PLAN=REFERENCE/'science-plan-2026-10-06.md'
PLAN_SHA256='f075a15c82b625a22a1b37a3548075ff8e483ed824a5554fe083f549e0875dac'

def _entry(obs,name):
    x=obs.get(name)
    if not isinstance(x,dict): raise ValueError(f'missing observable {name}')
    est=float(x['estimate'])
    if 'ci_95' in x:
        ci=x['ci_95']; lo,hi=(ci['low_95'],ci['high_95']) if isinstance(ci,dict) else ci
        lo,hi=float(lo),float(hi); se=float(x.get('bootstrap_SE',x.get('SE',x.get('standard_error',0.0))))
    elif 'interval' in x:
        lo,hi=map(float,x['interval']); level=float(x['confidence_level'])
        if not 0<level<1: raise ValueError(f'invalid confidence for {name}')
        # Never convert percentile-interval width into an SE for scoring.
        se=float(x.get('bootstrap_SE',x.get('SE',x.get('standard_error',0.0))))
    else:
        se=float(x.get('bootstrap_SE',x.get('SE',x.get('standard_error'))))
        declared=x.get('uncertainty_method',x.get('se_method'))
        outer=obs.get('method',{}) if isinstance(obs.get('method'),dict) else {}
        if not declared: declared=outer.get('uncertainty_method',outer.get('bootstrap'))
        if not declared:
            raise ValueError(f'{name} standard error lacks uncertainty_method')
        # An SE alone does not imply a normal 95% interval. The uncertainty
        # audit checks this declared SE against independently reconstructed
        # native blocks; keep point comparison separate here.
        lo=hi=est
    if not all(math.isfinite(v) for v in (est,lo,hi,se)) or lo>hi or se<0:
        raise ValueError(f'invalid estimate/interval for {name}')
    return est,lo,hi,se

def _read_candidate(root):
    for rel in ('final','final/chi_k.csv','final/observables.json','final/provenance.json','final/md_production.log'):
        p=root/rel
        if p.is_symlink(): raise ValueError(f'candidate output path may not be a symlink: {rel}')
    if not (root/'final').is_dir(): raise ValueError('final output directory is missing')
    data=json.loads((root/'final/observables.json').read_text()); obs=data.get('observables',data)
    if isinstance(data.get('method'),dict): obs=dict(obs,method=data['method'])
    curve=[]
    with (root/'final/chi_k.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            k=float(row['k_A^-1']); y=float(row['chi_parallel'])
            if 'chi_95_low' in row and 'chi_95_high' in row:
                lo,hi=float(row['chi_95_low']),float(row['chi_95_high']); se=0.0
            elif 'chi_interval_low' in row and 'chi_interval_high' in row:
                if 'confidence_level' not in row: raise ValueError('curve interval lacks confidence_level')
                level=float(row['confidence_level'])
                if not 0<level<1: raise ValueError('curve confidence_level must be in (0,1)')
                lo,hi=float(row['chi_interval_low']),float(row['chi_interval_high']); se=0.0
            elif 'chi_SE' in row:
                se=float(row['chi_SE']); lo=hi=y
            elif 'chi_bootstrap_SE' in row:
                se=float(row['chi_bootstrap_SE']); lo=hi=y
            else: raise ValueError('chi curve has no supported uncertainty column')
            if not all(math.isfinite(v) for v in (k,y,lo,hi,se)) or k<0 or lo>hi or se<0:
                raise ValueError('chi curve contains invalid values')
            curve.append((k,y,lo,hi,se))
    a=np.asarray(curve,float)
    if len(a)<2 or abs(a[0,0])>1e-10 or np.any(np.diff(a[:,0])<=0): raise ValueError('curve k grid must start at k=0 and be strictly increasing')
    return data,obs,a

def _curve_features(curve,extremum_method='bin'):
    k,y=curve[:,0],curve[:,1]
    low=np.flatnonzero((k>=.05)&(k<=2.5)); high=np.flatnonzero((k>=2.5)&(k<=6.0))
    if len(low)<3 or len(high)<3: raise ValueError('curve does not resolve both feature-search windows')
    imin=int(low[np.argmin(y[low])]); imax=int(high[np.argmax(y[high])])
    kmin=float(k[imin]); ymin=float(y[imin]); kmax=float(k[imax]); ymax=float(y[imax])
    if extremum_method in ('quadratic','local_quadratic','parabolic'):
        def quadratic(i,sign):
            if i<=0 or i>=len(k)-1: return None
            xx=k[i-1:i+2]-k[i]; yy=y[i-1:i+2]
            aa,bb,cc=np.polyfit(xx,yy,2)
            if not math.isfinite(float(aa)) or abs(aa)<1e-15 or (sign=='min' and aa<=0) or (sign=='max' and aa>=0): return None
            xv=-bb/(2*aa)
            if not xx[0]<=xv<=xx[-1]: return None
            return float(k[i]+xv),float(aa*xv*xv+bb*xv+cc)
        qmin=quadratic(imin,'min'); qmax=quadratic(imax,'max')
        if qmin is None or qmax is None: raise ValueError('declared quadratic extremum cannot be reconstructed from neighboring curve points')
        kmin,ymin=qmin; kmax,ymax=qmax
    elif extremum_method not in ('bin','bin_center','discrete'):
        raise NotImplementedError(f'extremum method {extremum_method!r} is not supported by the independent curve evaluator')
    half=ymax/2
    left=np.flatnonzero(y[:imax]<=half); right=np.flatnonzero(y[imax+1:]<=half)
    if not len(left) or not len(right): raise ValueError('curve does not bracket both zero-baseline half-height crossings')
    a=int(left[-1]); b=int(imax+1+right[0])
    xleft=float(k[a]+(half-y[a])*(k[a+1]-k[a])/(y[a+1]-y[a]))
    xright=float(k[b-1]+(half-y[b-1])*(k[b]-k[b-1])/(y[b]-y[b-1]))
    return {'k_min_A^-1':kmin,'chi_min':ymin,'k_max_A^-1':kmax,'chi_max':ymax,
      'delta_k_A^-1':xright-xleft,'half_height_k_minus_A^-1':xleft,'half_height_k_plus_A^-1':xright,
      'min_bracket_spacing_A^-1':float(max(k[imin]-k[imin-1],k[min(imin+1,len(k)-1)]-k[imin])),
      'max_bracket_spacing_A^-1':float(max(k[imax]-k[imax-1],k[min(imax+1,len(k)-1)]-k[imax])),
      'left_width_crossing_spacing_A^-1':float(k[a+1]-k[a]),'right_width_crossing_spacing_A^-1':float(k[b]-k[b-1]),
      'width_crossing_spacing_A^-1':float(max(k[a+1]-k[a],k[b]-k[b-1]))}

def _check_candidate_semantics(data,obs,curve):
    errors=[]; notes={}; unsupported=[]; method=obs.get('method',{})
    extremum_method=method.get('extremum_method','bin') if isinstance(method,dict) else 'bin'
    try: f=_curve_features(curve,extremum_method)
    except NotImplementedError as e: return {'unsupported_evidence':[str(e)]},errors
    except Exception as e: return {'unsupported_evidence':[]},[f'candidate extremum interpolation is invalid: {e}']
    for key in ('k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1'):
        est=_entry(obs,key)[0]; val=f[key]
        # A reported discrete extremum may be at most half its local reporting
        # interval from the curve-derived bin; widths use both crossing bins.
        tol=.5*f['min_bracket_spacing_A^-1'] if key.startswith('k_min') else .5*f['max_bracket_spacing_A^-1'] if key.startswith('k_max') else .5*f['width_crossing_spacing_A^-1'] if key=='delta_k_A^-1' else 1e-8
        if abs(est-val)>tol+1e-10: errors.append(f'{key} is inconsistent with the submitted curve')
    if f['max_bracket_spacing_A^-1']>.10: unsupported.append('candidate peak reporting grid is too coarse for the evaluator peak-location comparison')
    if .5*(f['left_width_crossing_spacing_A^-1']+f['right_width_crossing_spacing_A^-1'])>.05:
        unsupported.append('candidate half-height crossing grid is too coarse for the evaluator width comparison')
    if 'chi_max' in obs:
        if abs(_entry(obs,'chi_max')[0]-f['chi_max'])>1e-8: errors.append('chi_max is inconsistent with submitted curve')
    eps=_entry(obs,'eps_w')[0]
    k0=curve[0,1]
    if abs(k0-(1-1/eps))>max(1e-6,1e-5*abs(k0)): errors.append('k=0 response does not equal 1-1/eps_w')
    km=obs.get('k_min_A^-1',{})
    if not isinstance(km.get('resolved'),bool): errors.append('low-k feature must declare whether the minimum is resolved')
    if km.get('resolved') is True:
        support=km.get('bootstrap_strict_local_minimum_fraction',km.get('strict_interior_support'))
        try: support=float(support)
        except (TypeError,ValueError): support=float('nan')
        threshold=method.get('low_k_resolution_threshold') if isinstance(method,dict) else None
        if not math.isfinite(support) or not 0<=support<=1: errors.append('resolved low-k minimum has invalid support fraction')
        elif threshold is None: unsupported.append('resolved low-k claim omits its decision threshold')
        elif not math.isfinite(float(threshold)) or not 0<float(threshold)<=1: errors.append('low-k resolution threshold is invalid')
        elif support<float(threshold): errors.append('resolved low-k support is below the declared decision threshold')
    if not isinstance(method,dict): errors.append('observable method metadata is missing')
    else:
        width=obs.get('delta_k_A^-1',{}); baseline=width.get('baseline_chi',method.get('fwhm_baseline_chi'))
        half=width.get('half_height_fraction',method.get('half_height_fraction'))
        definition=' '.join(str(width.get(x,'')) for x in ('definition','half_height_definition')).lower()
        interp=str(width.get('crossing_method',method.get('crossing_interpolation',''))).lower()
        if baseline is not None:
            if not math.isfinite(float(baseline)): errors.append('FWHM baseline must be finite')
            elif abs(float(baseline))>1e-12: unsupported.append('declared nonzero width baseline is not supported by the current independent feature evaluator')
        elif not ('zero' in definition or '0' in definition): errors.append('width definition does not state zero baseline')
        if half is not None:
            if not math.isfinite(float(half)) or not 0<float(half)<1: errors.append('width half-height fraction must be between zero and one')
            elif abs(float(half)-.5)>1e-12: unsupported.append('declared nonstandard width fraction is not supported by the current independent feature evaluator')
        elif 'half' not in definition and 'chi_max/2' not in definition.replace(' ',''): errors.append('width definition omits chi_max/2')
        if interp:
            if 'linear' not in interp: unsupported.append(f'declared width interpolation {interp!r} is not supported by the current independent feature evaluator')
        elif 'linear' not in str(width.get('crossing_method','')).lower(): errors.append('crossing interpolation method is missing')
    source=data.get('source',{})
    if not isinstance(source,dict): source={}
    for key in ('trajectory_frames','sampled_frames','sampling_interval_ps','blocks','block_length_ns'):
        try:
            if not math.isfinite(float(source[key])) or float(source[key])<=0: raise ValueError
        except (KeyError,TypeError,ValueError): errors.append(f'source metadata lacks a valid {key}')
    method=obs.get('method',{})
    kmax=obs.get('k_max_A^-1',{})
    kres=kmax.get('bin_resolution_half_width_A^-1', kmax.get('reporting_resolution_half_width_A^-1'))
    if kres is None or not math.isfinite(float(kres)) or float(kres)<=0: errors.append('k_max must disclose nonzero reporting-bin resolution separately from its CI')
    else:
        bin_width=method.get('reporting_bin_width_A^-1',method.get('bin_width_A^-1')) if isinstance(method,dict) else None
        if bin_width is not None:
            bw=float(bin_width)
            if not math.isfinite(bw) or bw<=0 or abs(float(kres)-bw/2)>max(1e-10,1e-8*bw):
                errors.append('k_max resolution half-width must equal half the declared reporting-bin width')
        else:
            required=.5*f['max_bracket_spacing_A^-1']
            if float(kres)+1e-10<required:
                errors.append('k_max resolution is finer than the local reciprocal-grid spacing supports')
    kmin=obs.get('k_min_A^-1',{})
    if kmin.get('resolved') is False:
        fres=kmin.get('finite_size_resolution_A^-1',kmin.get('reciprocal_resolution_A^-1'))
        if fres is None:
            method=obs.get('method',{})
            vals=method.get('fundamental_reciprocal_spacing_A^-1_per_box_axis',[])
            vals=vals if isinstance(vals,list) else [vals]
            fres=method.get('first_nonzero_reciprocal_shell_A^-1',max(vals) if vals else None)
        if fres is None or not math.isfinite(float(fres)) or float(fres)<=0: errors.append('unresolved k_min lacks finite-size/reciprocal resolution disclosure')
    notes.update(curve_features=f,zero_baseline='chi_max/2 above zero chi; crossings linearly interpolated between reported k points',candidate_uncertainty_not_used_as_tolerance=True,unsupported_evidence=unsupported)
    return notes,errors

def _curve_reference_band(recomputed):
    summary=json.loads((recomputed/'science-validation/science_summary.json').read_text())
    native=json.loads((recomputed/'science-validation/independent_validation.json').read_text())
    with np.load(recomputed/'science-validation/checkpoint.npz') as z:
        ps=np.asarray(z['p256strict'],float); counts=np.asarray(z['mframes'],float)
        deg=np.asarray(z['deg'],float); k=np.asarray(z['kbin'],float)
    if ps.shape[0]!=40 or counts.shape!=(40,) or np.any(counts<=0): raise ValueError('independent evaluator lacks 40 half-ns sufficient-statistic blocks')
    box=np.asarray(native['native']['box_A'],float); volume=float(np.prod(box))*1e-30
    norm=(1.602176634e-19**2)/(volume*8.8541878128e-12*1.380649e-23*300.)
    curves=ps.reshape(20,2,len(deg)).sum(axis=1)/(counts.reshape(20,2).sum(axis=1)[:,None]*deg[None,:])*norm
    mean=curves.mean(axis=0); se=curves.std(axis=0,ddof=1)/np.sqrt(20)
    rng=np.random.default_rng(20261006); maxstats=[]; bootcurves=[]
    for start in range(0,10000,100):
        size=min(100,10000-start); ids=rng.integers(0,20,(size,20)); boot=curves[ids].mean(axis=1)
        maxstats.extend(np.max(np.abs((boot-mean)/np.maximum(se,1e-15)),axis=1).tolist())
        bootcurves.append(boot)
    crit=float(np.quantile(maxstats,.95))
    bootcurves=np.concatenate(bootcurves,axis=0); ci=np.quantile(bootcurves,[.025,.975],axis=0)
    numerical=np.asarray(summary['numerical_envelope']['per_bin_chi_absolute'],float)
    if numerical.shape!=mean.shape: raise ValueError('independent numerical envelope does not align with reciprocal bins')
    return k,mean,crit*se,numerical,{'maxstat_critical_95':crit,'blocks':20,'bootstrap_draws':10000,'standard_error':se.tolist(),'pointwise_ci95_low':ci[0].tolist(),'pointwise_ci95_high':ci[1].tolist()}

def _epsilon_bootstrap(recomputed):
    native=json.loads((recomputed/'science-validation/independent_validation.json').read_text())
    box=np.asarray(native['native']['box_A'],float); volume=float(np.prod(box))*1e-30
    with np.load(recomputed/'science-validation/checkpoint.npz') as z:
        mu=np.asarray(z['mdip'],float).reshape(20,2,3).sum(axis=1)
        mu2=np.asarray(z['mdip2'],float).reshape(20,2).sum(axis=1)
        count=np.asarray(z['mframes'],float).reshape(20,2).sum(axis=1)
    rng=np.random.default_rng(20261006); values=[]
    for start in range(0,10000,250):
        ids=rng.integers(0,20,(min(250,10000-start),20)); sm=mu[ids].sum(axis=1); s2=mu2[ids].sum(axis=1); nn=count[ids].sum(axis=1)
        values.extend((1+(s2/nn-np.sum((sm/nn[:,None])**2,axis=1))/(3*8.8541878128e-12*volume*1.380649e-23*300.)).tolist())
    values=np.asarray(values,float)
    return float(values.std(ddof=1)),np.quantile(values,[.025,.975]).tolist()

def _compare_curve(curve,recomputed):
    errors=[]; k,mean,statband,numenv,meta=_curve_reference_band(recomputed)
    ck,cy=curve[:,0],curve[:,1]
    gaps=np.diff(ck)
    maxgap=float(np.max(gaps))
    if maxgap>.10:
        return {'evaluated_nonzero_bins':0,'max_reference_reporting_grid_gap_A^-1':maxgap,'pass':None,'unsupported_evidence':['candidate curve reporting grid is too coarse for a bounded interpolation comparison']},errors
    if ck[0]>1e-10 or ck[-1]<k[-1]: errors.append('candidate curve does not span the full independently evaluated reciprocal range')
    # A piecewise-linear interpolation receives a local curvature error bound;
    # if there are not enough neighbors to estimate curvature, the comparison
    # fails closed. This bound is separately reported from statistical and
    # numerical estimator bands.
    interp=np.interp(k,ck,cy); bound=np.zeros(len(k)); second=np.zeros(len(k))
    for i in range(1,len(k)-1):
        h0=k[i]-k[i-1]; h1=k[i+1]-k[i]
        second[i]=2*((mean[i+1]-mean[i])/h1-(mean[i]-mean[i-1])/h0)/(h0+h1)
    for j,x in enumerate(k):
        if np.min(np.abs(ck-x))<=1e-10: continue
        i=int(np.clip(np.searchsorted(ck,x)-1,0,len(ck)-2)); h=ck[i+1]-ck[i]
        ri=int(np.clip(np.searchsorted(k,x),1,len(k)-2))
        curv=max(abs(second[ri-1]),abs(second[ri]),abs(second[ri+1]))
        bound[j]=curv*h*h/8
    tol=statband+numenv+bound
    diff=np.abs(interp-mean)
    z=diff/np.maximum(tol,1e-15)
    passed=bool(len(k)>0 and np.all(z<=1.0))
    if not passed: errors.append('candidate chi(k) is outside the independent simultaneous statistical + numerical + interpolation band')
    return {'evaluated_nonzero_bins':len(k),'max_standardized_difference':float(np.max(z)) if len(z) else None,
      'max_reference_reporting_grid_gap_A^-1':maxgap,'max_candidate_interpolation_bound':float(np.max(bound)),
      'statistical_band':'20 contiguous 1 ns blocks; 10,000-draw 95% max-stat bootstrap',
      'numerical_envelope_separate':True,'candidate_interpolation_bound_method':'piecewise-linear interpolation with local finite-difference curvature estimate',
      'uncertainty_width_pass':'delegated to candidate-method native bootstrap audit','candidate_CI_width_uses_candidate_SE_as_tolerance':False,
      'pass':passed,'bootstrap':meta},errors

def _compare_candidate(root, recomputed):
    data,obs,cand=_read_candidate(root); errors=[]; comparisons={}
    semantic,semantic_errors=_check_candidate_semantics(data,obs,cand); comparisons['candidate_semantics']=semantic; errors.extend(semantic_errors)
    if semantic.get('unsupported_evidence'):
        comparisons['unsupported_evidence']=list(semantic['unsupported_evidence'])
        return comparisons,errors
    # Trusted reference point estimates and bootstrap intervals came from the
    # scorer's fresh native recomputation, not candidate JSON.
    ref=json.loads((recomputed/'science-validation/independent_validation.json').read_text())
    rp=ref['features_1ns']['point']; rb=ref['features_1ns']['bootstrap']
    ref_obs={'eps_w':{'estimate':ref['independent_reproduction']['epsilon_w'],'ci_95':ref['features_1ns']['epsilon_w_ci95']}}
    for name in ('k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1'):
        stat=rb[name]
        ref_obs[name]={'estimate':rp[name],'ci_95':stat['ci95']}
    if 'chi_max' in rb: ref_obs['chi_max']={'estimate':rp['chi_max'],'ci_95':rb['chi_max']['ci95']}
    ro=ref_obs
    eps_se,eps_ci=_epsilon_bootstrap(recomputed)
    feature_bounds=json.loads((recomputed/'science-validation/science_summary.json').read_text())['numerical_envelope']['extremum_position_and_height_bounds']
    for name in ('eps_w','k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1')+((('chi_max',) if 'chi_max' in obs else ())):
        ce=_entry(obs,name); re_=_entry(ro,name)
        # Candidate-declared uncertainty never widens this comparison. Use the
        # verifier's own block-bootstrap SE and the separately computed numeric
        # bound; do not infer an SE from percentile interval width.
        ref_result=json.loads((recomputed/'science-validation/independent_validation.json').read_text())
        ref_se=rb.get(name,{}).get('se')
        num_bound=0.0
        if name=='delta_k_A^-1':
            wb=feature_bounds['delta_k_robust_bound'].get('delta_k_A^-1_bounds')
            if wb: num_bound=max(abs(float(wb[0])-re_[0]),abs(float(wb[1])-re_[0]))
        if name=='chi_min': num_bound=max(abs(x-re_[0]) for x in feature_bounds['possible_minimum_chi_range'])
        if name=='chi_max': num_bound=max(abs(x-re_[0]) for x in feature_bounds['possible_maximum_chi_range'])
        if name=='eps_w': ref_se=float(eps_se)
        if name=='k_max_A^-1': ref_se=float('nan')
        tol=(3*ref_se+num_bound) if math.isfinite(ref_se) else (.05 if name=='k_max_A^-1' else 0.0)
        # For an unresolved low-k minimum, only the reported unresolved status
        # and finite-size interval are meaningful; point-bin equality is not.
        ref_unresolved=(name=='k_min_A^-1' and float(rb.get('strict_interior_minimum_support',0))<.95)
        if ref_unresolved:
            cmin=obs.get('k_min_A^-1',{})
            passed=(cmin.get('resolved') is False)
            z=None
        else:
            z=abs(ce[0]-re_[0])/max(tol,1e-15); passed=z<=1.0
        # Confidence/SE declarations are audited separately by uncertainty_audit,
        # which reconstructs the candidate's declared procedure from trusted
        # native blocks. Do not infer an SE from interval width here.
        ref_interval=eps_ci if name=='eps_w' else re_[1:3]
        comparisons[name]={'candidate_estimate':ce[0],'reference_estimate':re_[0],
          'candidate_uncertainty_claim':{k:v for k,v in obs[name].items() if k in ('ci_95','interval','confidence_level','bootstrap_SE','SE','standard_error','uncertainty_method','se_method')},
          'reference_interval_95':[re_[1],re_[2]],
          'verifier_only_tolerance':tol,'tolerance_fraction_used':z,'candidate_SE_used_for_tolerance':False,'reference_lowk_unresolved':ref_unresolved,
          'reference_interval_95':list(map(float,ref_interval)),'interval_claim_evaluated_by':'uncertainty_audit.py','pass':passed}
        if not passed: errors.append(f'{name} disagrees with independent native recomputation')
    # Compare on the independent reporting grid. Candidate-declared uncertainty
    # never appears in this acceptance tolerance.
    cc,curve_errors=_compare_curve(cand,recomputed)
    comparisons['curve']=cc; errors.extend(curve_errors)
    return comparisons,errors

def evaluate_candidate_reextraction(root:Path,audit:dict,reextract_dir:Path,audit_output:Path|None=None)->dict:
    """Score outputs against a fresh evaluator re-extraction on their schedule/grid."""
    root=Path(root).resolve(); reextract_dir=Path(reextract_dir).resolve()
    result={'L1':'PASS','L2':'NOT_EVALUATED','L3':'NOT_EVALUATED','scientific_acceptance':'NOT_EVALUATED','native_audit':audit,'errors':[]}
    if not isinstance(audit,dict) or audit.get('status')!='PASS':
        result['L2']='BLOCKED_NATIVE_AUDIT'; result['L3']='NOT_EVALUATED'
        result['errors']=['native audit did not pass; independent science evaluation is fail-closed']
        return result
    result['L2']='PASS'
    try:
        summary=json.loads((reextract_dir/'trusted_candidate_method.json').read_text())
        if summary.get('status')!='REEXTRACTED':
            result['L3']='ERROR'; result['scientific_acceptance']='NOT_EVALUATED'
            result['errors']=summary.get('errors',[]); result['unsupported_evidence']=summary.get('unsupported_evidence',[])
            return result
        checkpoint=reextract_dir/'trusted_candidate_method.npz'
        if (checkpoint.is_symlink() or not checkpoint.is_file() or
            Path(summary.get('trusted_checkpoint','')).resolve()!=checkpoint.resolve() or
            summary.get('trusted_checkpoint_sha256')!=__import__('candidate_reextract')._sha(checkpoint)):
            result['L3']='ERROR'; result['errors']=['trusted evaluator checkpoint path/hash does not match the generated file']; return result
        # REEXTRACTED is only a state label. Require the evaluator's numerical
        # evidence to be finite and within its preregistered accuracy budget.
        rel=float(summary.get('max_relative_systematic',float('nan')))
        env=np.asarray(summary.get('numerical_systematic_absolute_per_bin',[]),dtype=float)
        ng=summary.get('numerical_gate',{})
        gate_values=[ng.get('max_mesh_relative_upper'),ng.get('max_selected_probe_relative_upper'),
          ng.get('max_all_selected_probe_relative_upper'),ng.get('max_high_k_direct_relative_upper')]
        if (not math.isfinite(rel) or rel<0 or env.ndim!=1 or not len(env) or
            not np.all(np.isfinite(env)) or np.any(env<0) or ng.get('passed') is not True or
            ng.get('mesh_per_bin_pass') is not True or ng.get('selected_direct_probe_pass') is not True or
            ng.get('high_k_direct_accuracy_claimed') is not False or
            not isinstance(ng.get('high_k_direct_precision_unresolved'),bool) or
            not all(isinstance(v,(int,float)) and math.isfinite(float(v)) and float(v)>=0 for v in gate_values)):
            result['L3']='ERROR'; result['errors']=['trusted re-extraction numerical validation is missing, non-finite, or failed its preregistered mesh/direct limits']; return result
        data,obs,candidate=_read_candidate(root)
        semantic,semantic_errors=_check_candidate_semantics(data,obs,candidate)
        result['candidate_semantics']=semantic
        if semantic_errors: result['errors'].extend(semantic_errors)
        unsupported=list(semantic.get('unsupported_evidence',[]))
        if semantic_errors:
            result['L3']='FAIL'; result['scientific_acceptance']='FAIL'; return result
        from uncertainty_audit import audit_candidate_reextracted_uncertainty
        uncertainty=audit_candidate_reextracted_uncertainty(root,reextract_dir/'trusted_candidate_method.npz',reextract_dir/'trusted_candidate_method.json',audit_output)
        result['uncertainty_audit']=uncertainty
        if uncertainty.get('status')=='ERROR':
            result['L3']='ERROR'; result['scientific_acceptance']='NOT_EVALUATED'; result['errors'].extend(uncertainty.get('errors',[])); return result
        if uncertainty.get('status')=='UNSUPPORTED_EVIDENCE':
            result['L3']='UNSUPPORTED_EVIDENCE'; result['scientific_acceptance']='NOT_EVALUATED'
            result['unsupported_evidence']=list(unsupported)+list(uncertainty.get('unsupported_evidence',[])); return result
        if uncertainty.get('status')=='FAIL':
            result['L3']='FAIL'; result['scientific_acceptance']='FAIL'
            result['errors'].append('candidate uncertainty claims do not reproduce from evaluator native blocks'); return result
        facts=uncertainty.get('uncertainty_facts',{})
        ref=np.asarray(facts.get('point_curve',[]),float)
        stat=np.asarray(facts.get('curve_simultaneous_statistical_band_95',[]),float)
        env=np.r_[0.,env]
        if ref.shape!=candidate[:,1].shape or stat.shape!=ref.shape or env.shape!=ref.shape:
            raise ValueError('trusted curve, statistical band, numerical envelope, and candidate grid have incompatible shapes')
        tol=stat+env
        curve_diff=np.abs(candidate[:,1]-ref)
        curve_pass=bool(np.all(np.isfinite(tol)) and np.all(curve_diff<=tol+1e-12))
        result['curve_comparison']={'max_abs_candidate_minus_trusted':float(np.max(curve_diff)),'max_simultaneous_statistical_band':float(np.max(stat)),'max_numerical_envelope':float(np.max(env)),'tolerance_components_separate':True,'pass':curve_pass}
        if not curve_pass: result['errors'].append('candidate curve exceeds evaluator simultaneous statistical plus numerical envelope')
        method=obs.get('method',{}) if isinstance(obs.get('method'),dict) else {}
        widths=float(method.get('reporting_bin_width_A^-1',method.get('bin_width_A^-1')))
        grid=np.r_[0.,np.asarray(summary['reporting']['bin_centers_A^-1'],float)]
        from importlib.util import spec_from_file_location,module_from_spec
        smspec=spec_from_file_location('case01_trusted_summarize',REFERENCE/'summarize.py')
        sm=module_from_spec(smspec); smspec.loader.exec_module(sm)
        numwidth=sm.numerical_width_bounds(ref,env,grid)
        pointfeat=facts.get('point_features',{})
        ses=facts.get('feature_bootstrap_SE',{})
        checks={}
        for name in ('eps_w','chi_min','k_min_A^-1','k_max_A^-1','delta_k_A^-1'):
            claim=obs.get(name,{})
            if not isinstance(claim,dict) or 'estimate' not in claim: raise ValueError(f'missing candidate estimate for {name}')
            value=float(claim['estimate']); se=float(facts.get('epsilon_bootstrap_SE') if name=='eps_w' else ses.get(name,0.0) or 0.0)
            if not math.isfinite(value) or not math.isfinite(se): raise ValueError(f'non-finite trusted/candidate estimate for {name}')
            if name=='eps_w':
                expected=float(facts['epsilon_point']); allowed=3*se
                passed=abs(value-expected)<=allowed+1e-12
            elif name=='k_min_A^-1':
                low=np.flatnonzero((grid>=.05)&(grid<=2.5)); lower=ref-env; upper=ref+env
                possible=low[lower[low]<=np.min(upper[low])]
                unresolved=float(pointfeat.get('strict_interior_minimum_support',0.0))<.95
                if unresolved:
                    passed=claim.get('resolved') is False
                    expected=None; allowed=None
                else:
                    expected=float(pointfeat[name]); possible_k=grid[possible] if len(possible) else np.asarray([expected])
                    allowed=3*se+widths/2
                    passed=float(np.min(possible_k))-allowed<=value<=float(np.max(possible_k))+allowed
            elif name=='k_max_A^-1':
                high=np.flatnonzero((grid>=2.5)&(grid<=6.0)); lower=ref-env; upper=ref+env
                possible=high[upper[high]>=np.max(lower[high])]
                expected=float(pointfeat[name]); possible_k=grid[possible] if len(possible) else np.asarray([expected])
                allowed=3*se+widths/2
                passed=float(np.min(possible_k))-allowed<=value<=float(np.max(possible_k))+allowed
            elif name=='delta_k_A^-1':
                expected=float(pointfeat[name]); bounds=numwidth.get('delta_k_A^-1_bounds')
                if not numwidth.get('resolved') or not isinstance(bounds,list) or len(bounds)!=2:
                    unsupported.append('evaluator numerical envelope cannot rigorously bound the half-height width'); passed=False; allowed=None
                else:
                    allowed=3*se; passed=float(bounds[0])-allowed<=value<=float(bounds[1])+allowed
            else:
                expected=float(pointfeat[name]); lower=ref-env; upper=ref+env
                low=np.flatnonzero((grid>=.05)&(grid<=2.5)); high=np.flatnonzero((grid>=2.5)&(grid<=6.0))
                lo=float(np.min(lower[low])) if name=='chi_min' else float(np.max(lower[high]))
                hi=float(np.min(upper[low])) if name=='chi_min' else float(np.max(upper[high]))
                allowed=3*se; passed=lo-allowed<=value<=hi+allowed
            checks[name]={'candidate_estimate':value,'trusted_estimate':expected,'bootstrap_SE':se,'numeric_width_bound':numwidth if name=='delta_k_A^-1' else None,'pass':bool(passed)}
            if not passed and not (name=='delta_k_A^-1' and unsupported): result['errors'].append(f'{name} is outside independently reconstructed feature bounds')
        if 'chi_max' in obs and isinstance(obs['chi_max'],dict):
            checks['chi_max']={'reported':float(obs['chi_max']['estimate']),'curve_derived':float(pointfeat['chi_max']),'consistent_with_curve':abs(float(obs['chi_max']['estimate'])-float(pointfeat['chi_max']))<=3*float(ses.get('chi_max') or 0)+1e-10}
            if not checks['chi_max']['consistent_with_curve']: result['errors'].append('chi_max differs from the evaluator-derived curve feature')
        result['feature_comparison']=checks
        result['candidate_method_reextraction']=summary
        result['independent_method_diagnostic']={'status':'NOT_APPLICABLE','used_as_candidate_acceptance_gate':False}
        if result['errors']:
            result['L3']='FAIL'; result['scientific_acceptance']='FAIL'
        elif unsupported:
            result['L3']='UNSUPPORTED_EVIDENCE'; result['scientific_acceptance']='NOT_EVALUATED'; result['unsupported_evidence']=unsupported
        else:
            result['L3']='PASS'; result['scientific_acceptance']='PASS'
        return result
    except Exception as e:
        result['L3']='ERROR'; result['scientific_acceptance']='NOT_EVALUATED'; result['errors'].append(f'{type(e).__name__}: {e}')
        return result

def evaluate_recomputed(root:Path, audit:dict, recomputed:Path, kernel_only:bool=False, audit_output:Path|None=None)->dict:
    """Apply the shared decision logic to already produced native evidence.

    Live scoring calls this only after trusted native audit and fresh
    recomputation. Private regression calibration may replay a hash-verified
    archived recomputation through the same function; this function itself
    never claims that such replay performed a new L2 audit or recomputation.
    """
    root=Path(root).resolve(); tmp=Path(recomputed).resolve()
    result={'L3':'NOT_EVALUATED','scientific_acceptance':'FAIL','native_audit':audit,'errors':[]}
    if audit.get('status')!='PASS':
        result['L3']='BLOCKED_NATIVE_AUDIT'; result['errors']=['native audit did not pass; independent science evaluation is fail-closed']; return result
    gates=json.loads((tmp/'science-validation/science-gates.json').read_text())
    result['independently_recomputed_gates']=gates
    result['independent_method_diagnostic']={'status':gates.get('scientific_status'),'passed':gates.get('passed'),'total':gates.get('total'),'used_as_candidate_acceptance_gate':False}
    result['independent_validation']=json.loads((tmp/'science-validation/independent_validation.json').read_text())
    result['science_summary']=json.loads((tmp/'science-validation/science_summary.json').read_text())
    result['recomputation_output_directory']=str(tmp)
    if kernel_only:
        result['L3']='NOT_EVALUATED'; result['scientific_acceptance']='NOT_EVALUATED'
        result['candidate_scoring']='NOT_EVALUATED'; result['kernel_status']='COMPLETE'
        return result
    candidate_comparison,compare_errors=_compare_candidate(root,tmp)
    result['candidate_comparison']=candidate_comparison
    result['candidate_comparison_errors']=compare_errors
    result['candidate_comparison_pass']=not compare_errors
    result['errors'].extend(compare_errors)
    comparison_unsupported=list(candidate_comparison.get('unsupported_evidence',[]))
    curve_unsupported=candidate_comparison.get('curve',{}).get('unsupported_evidence',[])
    if isinstance(curve_unsupported,list): comparison_unsupported.extend(curve_unsupported)
    if comparison_unsupported and not compare_errors:
        result['L3']='UNSUPPORTED_EVIDENCE'; result['scientific_acceptance']='NOT_EVALUATED'
        result['unsupported_evidence']=comparison_unsupported
        result['uncertainty_audit']={'status':'NOT_EVALUATED','reason':'candidate output semantics/grid are outside the current independent comparator'}
        return result
    from uncertainty_audit import audit_uncertainty
    uncertainty=audit_uncertainty(root,tmp/'science-validation/checkpoint.npz',tmp/'science-validation/independent_validation.json',audit_output)
    result['uncertainty_audit']=uncertainty
    unsupported=comparison_unsupported
    if uncertainty.get('status')=='UNSUPPORTED_EVIDENCE': unsupported.extend(uncertainty.get('unsupported_evidence',[]))
    elif uncertainty.get('status')=='ERROR':
        result['L3']='ERROR'; result['scientific_acceptance']='NOT_EVALUATED'
        result['errors'].append('independent uncertainty evaluation could not complete: '+'; '.join(map(str,uncertainty.get('errors',[]))))
        return result
    elif uncertainty.get('status')=='FAIL': result['errors'].append('candidate uncertainty claims failed independent reconstruction')
    elif uncertainty.get('status')!='PASS':
        result['L3']='ERROR'; result['scientific_acceptance']='NOT_EVALUATED'
        result['errors'].append(f"unexpected uncertainty verifier state: {uncertainty.get('status')!r}")
        return result
    if result['errors']:
        result['L3']='FAIL'; result['scientific_acceptance']='FAIL'
    elif unsupported:
        result['L3']='UNSUPPORTED_EVIDENCE'; result['scientific_acceptance']='NOT_EVALUATED'
        result['unsupported_evidence']=unsupported
    else:
        result['L3']='PASS'; result['scientific_acceptance']='PASS'
    return result

def score_submission(root:Path, gmx='gmx', workdir:Path|None=None, trusted_execution_receipt:Path|None=None,
                     kernel_only=False, historical_archive:dict|None=None):
    root=Path(root)
    if root.is_symlink(): return {'L3':'ERROR','scientific_acceptance':'FAIL','errors':['candidate root is a symlink']}
    root=root.resolve()
    from native_audit import audit_native
    audit=audit_native(root,gmx,trusted_execution_receipt=trusted_execution_receipt,
                       historical_archive=historical_archive)
    result={'L3':'NOT_EVALUATED','scientific_acceptance':'FAIL','native_audit':audit,'errors':[]}
    if audit.get('status')!='PASS':
        result['L3']='BLOCKED_NATIVE_AUDIT'; result['errors']=['native audit did not pass; independent science evaluation is fail-closed']; return result
    if workdir is None: tmp=Path(tempfile.mkdtemp(prefix='case01-independent-'))
    else:
        raw=Path(workdir)
        if raw.is_symlink() or raw.exists() and (not raw.is_dir() or any(raw.iterdir())):
            return {'L3':'ERROR','scientific_acceptance':'FAIL','errors':['scorer workdir must be a new empty non-symlink directory']}
        tmp=raw.resolve()
        if tmp==root or root in tmp.parents or tmp in root.parents:
            return {'L3':'ERROR','scientific_acceptance':'FAIL','errors':['scorer workdir must be isolated from candidate tree']}
        tmp.mkdir(parents=True,exist_ok=True)
    if tmp==root or root in tmp.parents or tmp in root.parents:
        return {'L3':'ERROR','scientific_acceptance':'FAIL','errors':['scorer workdir must be isolated from candidate tree']}
    candidate=audit['resolved_artifacts']
    # Read-only staging: native files remain in the submission. All scorer
    # outputs are disposable and isolated from candidate final/.
    for key,name in [('tpr','production.tpr'),('xtc','production.xtc'),('edr','production.edr'),('production_log','production.log'),('npt_gro','npt.gro'),('nvt_log','nvt.log'),('npt_log','npt.log')]:
        (tmp/name).symlink_to(Path(candidate[key]).resolve())
    (tmp/'final').mkdir(exist_ok=True); (tmp/'science-validation').mkdir(exist_ok=True); (tmp/'logs').mkdir(exist_ok=True)
    shutil.copy2(tmp/'production.log',tmp/'final/md_production.log'); shutil.copy2(tmp/'npt.gro',tmp/'final/npt.gro')
    if not kernel_only:
        from candidate_reextract import reextract_candidate_method
        extraction_dir=tmp/'candidate-method-reextraction'
        extraction=reextract_candidate_method(root,candidate,extraction_dir)
        if extraction.get('status') not in ('REEXTRACTED','UNSUPPORTED_EVIDENCE'):
            return {'L1':'PASS','L2':'PASS','L3':'ERROR','scientific_acceptance':'NOT_EVALUATED','native_audit':audit,'candidate_method_reextraction':extraction,'errors':extraction.get('errors',[])}
        if extraction.get('status')=='UNSUPPORTED_EVIDENCE':
            return {'L1':'PASS','L2':'PASS','L3':'UNSUPPORTED_EVIDENCE','scientific_acceptance':'NOT_EVALUATED','native_audit':audit,'candidate_method_reextraction':extraction,'unsupported_evidence':extraction.get('unsupported_evidence',[]),'errors':[]}
        return evaluate_candidate_reextraction(root,audit,extraction_dir,extraction_dir/'uncertainty-audit.json')
    # Supply actual independently obtained native audit results to the legacy
    # summary's native-gate adapter. The JSON is generated here from audit facts.
    checks=audit['native_facts'].get('checks',{})
    for n,keyset in [('production-tpr-settings.json',['production_duration','temperature_coupling','periodic_spme_cutoffs','potential_shift']),('production-tpr-exclusions.json',['intramolecular_exclusions','molecule_count_and_charges'])]:
        ok=all(checks.get(k) is True for k in keyset)
        (tmp/'logs'/n).write_text(json.dumps({'status':'PASS' if ok else 'FAIL','checks':{k:checks.get(k) for k in keyset}}))
    # Plan is fixed public acceptance methodology. No candidate-supplied plan
    # or author checkpoint is loaded.
    plan=PLAN
    if not plan.is_file() or hashlib.sha256(plan.read_bytes()).hexdigest()!=PLAN_SHA256:
        result['L3']='ERROR'; result['errors']=['bundled frozen science plan missing or hash mismatch']; return result
    env=os.environ.copy(); env.update(CASE01_DIR=str(tmp),OUTDIR=str(tmp/'science-validation'),PLAN_FILE=str(plan),GMX=str(gmx),VERIFIER_MODE='1')
    for script in ('recompute.py','summarize.py'):
        p=subprocess.run([sys.executable,str(REFERENCE/script)],env=env,text=True,capture_output=True)
        if p.returncode:
            result['L3']='ERROR'; result['errors']=[f'{script} failed: {(p.stderr or p.stdout)[-3000:]}']; return result
    evaluated=evaluate_recomputed(root,audit,tmp,kernel_only,audit_output=tmp/'science-validation/uncertainty-audit.json')
    return evaluated

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('submission',type=Path); ap.add_argument('--gmx',default='gmx'); ap.add_argument('--workdir',type=Path); ap.add_argument('--trusted-execution-receipt',type=Path); ap.add_argument('--kernel-only',action='store_true',help='Run native audit and independent science recomputation without scoring candidate outputs.')
    a=ap.parse_args(); r=score_submission(a.submission,a.gmx,a.workdir,a.trusted_execution_receipt,a.kernel_only); print(json.dumps(r,indent=2)); raise SystemExit(0 if r.get('kernel_status')=='COMPLETE' or r['L3']=='PASS' else 2)
