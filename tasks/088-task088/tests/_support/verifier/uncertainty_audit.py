#!/usr/bin/env python3
"""Audit declared Case01 uncertainty against trusted half-ns sufficient statistics.

This module reads no trajectory and never trusts candidate-supplied checkpoints.
It reconstructs the candidate-declared bootstrap/SE procedure from an evaluator
checkpoint containing the 40 contiguous half-nanosecond blocks.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, re
from decimal import Decimal
from pathlib import Path
import numpy as np

E=1.602176634e-19; EPS0=8.8541878128e-12; KB=1.380649e-23; TEMP=300.0

class _LexicalFloat(float):
    def __new__(cls,token):
        obj=super().__new__(cls,token); obj.token=str(token); return obj

def _loads_json_with_tokens(text:str):
    return json.loads(text,parse_float=_LexicalFloat,parse_int=_LexicalFloat)

def _has_private_serialization_claim(value)->bool:
    if isinstance(value,dict):
        return any(str(k).startswith('_serialized') or _has_private_serialization_claim(v) for k,v in value.items())
    if isinstance(value,list): return any(_has_private_serialization_claim(v) for v in value)
    return False

def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def _outside_candidate(path:Path,root:Path,label:str)->Path:
    raw=Path(path).absolute()
    if raw.is_symlink(): raise ValueError(f'trusted {label} may not be a symlink')
    p=raw.resolve()
    if p.is_relative_to(root): raise ValueError(f'trusted {label} must be outside candidate root')
    if not p.is_file(): raise ValueError(f'trusted {label} is missing')
    return p

def _confidence(obj:dict)->float|None:
    if 'ci_95' in obj: return .95
    if 'interval' in obj:
        if 'confidence_level' not in obj: raise ValueError('interval lacks confidence_level')
        c=float(obj['confidence_level'])
        if not 0<c<1: raise ValueError('confidence_level must be in (0,1)')
        return c
    return None

def _interval(obj:dict)->tuple[float,float]|None:
    key='ci_95' if 'ci_95' in obj else 'interval' if 'interval' in obj else None
    if key is None: return None
    ci=obj[key]
    if isinstance(ci,dict):
        if key=='ci_95':
            lo=ci.get('low_95'); hi=ci.get('high_95')
        else: lo=ci.get('low',ci.get('low_95')); hi=ci.get('high',ci.get('high_95'))
    else:
        if not isinstance(ci,(list,tuple)) or len(ci)!=2: raise ValueError(f'{key} must have two endpoints')
        lo,hi=ci
    lo=float(lo); hi=float(hi)
    if not (math.isfinite(lo) and math.isfinite(hi) and lo<=hi): raise ValueError('invalid interval endpoints')
    return lo,hi

def _decimal_half_ulp(value)->float|None:
    """Return half the last serialized decimal place, preserving trailing zeros."""
    if isinstance(value,_LexicalFloat):
        try: value=Decimal(value.token)
        except Exception: return None
    elif isinstance(value,str):
        try: value=Decimal(value)
        except Exception: return None
    if not isinstance(value,Decimal): return None
    exponent=value.as_tuple().exponent
    if not isinstance(exponent,int): return None
    return float(Decimal(5).scaleb(exponent-1))

def _serialized_interval_bounds(obj:dict)->tuple[float,float]|None:
    key='ci_95' if 'ci_95' in obj else 'interval' if 'interval' in obj else None
    if key is None: return None
    ci=obj[key]
    if isinstance(ci,dict):
        lo=ci.get('low_95') if key=='ci_95' else ci.get('low',ci.get('low_95'))
        hi=ci.get('high_95') if key=='ci_95' else ci.get('high',ci.get('high_95'))
    else: lo,hi=ci
    return _decimal_half_ulp(lo),_decimal_half_ulp(hi)

def _method_plan(data:dict,observables:dict)->dict:
    method=data.get('method')
    if not isinstance(method,dict): raise NotImplementedError('method metadata is absent')
    spec=method.get('bootstrap')
    text=''
    if isinstance(spec,str): text=spec.lower()
    elif isinstance(spec,dict): text=' '.join(str(x).lower() for x in spec.values())
    elif spec is not None: raise NotImplementedError('bootstrap method metadata has an unsupported format')
    else:
        # Support a plainly declared SE procedure even when no CI is claimed.
        text=' '.join([str(method.get('uncertainty_method','')).lower()]+[str(v.get('uncertainty_method','')).lower() for v in observables.values() if isinstance(v,dict)])
    draws_match=re.search(r'([\d,]+)\s*(?:bootstrap\s*)?(?:resamples|draws|replicates)',text)
    draws=int(draws_match.group(1).replace(',','')) if draws_match else None
    seed=method.get('bootstrap_seed',method.get('seed'))
    if isinstance(spec,dict):
        draws=spec.get('resamples',spec.get('draws',draws)); seed=spec.get('seed',seed)
    block_match=re.search(r'([\d.]+)\s*ns\s+blocks?',text)
    block_ns=float(block_match.group(1)) if block_match else None
    if isinstance(spec,dict): block_ns=spec.get('block_length_ns',spec.get('block_ns',block_ns))
    if 'percentile' in text: kind='percentile'
    elif 'bootstrap' in text and ('standard error' in text or re.search(r'\bse\b',text)): kind='bootstrap_sd'
    elif 'bootstrap' in text and 'normal' in text: kind='bootstrap_normal'
    elif 'block standard error' in text or 'sd/sqrt(n)' in text or 'standard deviation divided by sqrt' in text:
        kind='block_sem_t' if ('student' in text or ' t interval' in text) else 'block_sem_normal'
    else: kind=None
    if kind is None: raise NotImplementedError('declared uncertainty method is not a supported bootstrap percentile/SE procedure')
    if kind.startswith('block_sem'):
        # Bootstrap draws are still used internally for nonlinear feature
        # diagnostics; reported SEM claims are checked from observed blocks.
        draws=int(draws or 1000); seed=int(seed if seed is not None else 20261008)
    else:
        if draws is None or int(draws)<100: raise NotImplementedError('bootstrap resample count must be declared and at least 100')
        if int(draws)>50000: raise NotImplementedError('declared bootstrap count exceeds the evaluator memory/time budget')
        if seed is None: raise NotImplementedError('bootstrap seed must be declared for reproducible verification')
    declared_conf=None
    if isinstance(spec,dict): declared_conf=spec.get('confidence_level',spec.get('confidence'))
    if declared_conf is None:
        cm=re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:confidence\s*)?ci',text)
        if cm: declared_conf=float(cm.group(1))/100
    if declared_conf is not None:
        declared_conf=float(declared_conf)
        if not 0<declared_conf<1: raise ValueError('declared bootstrap confidence must be in (0,1)')
    return {'kind':kind,'draws':int(draws) if draws is not None else None,'seed':int(seed) if seed is not None else None,'block_length_ns':float(block_ns) if block_ns is not None else None,'confidence_level':declared_conf,'text':text}

def _candidate_matches_trusted_curve_reconstruction(method:dict,trusted_primary_mesh:int=256)->tuple[bool,str]:
    """Whether all-frame CI/SE can be recomputed for the declared curve method.

    The candidate re-extractor retains all-frame blocks for its explicitly
    declared 256^3, 384^3, or 512^3 periodic-CIC primary mesh. The 256/384 and
    direct-mode calculations remain separate evaluator diagnostics.
    """
    assignment=str(method.get('charge_assignment',method.get('assignment',''))).lower()
    deconv=str(method.get('reciprocal_estimator',method.get('power_deconvolution',method.get('averaging','')))).lower()
    mesh=method.get('mesh',method.get('mesh_pair'))
    if not ('cic' in assignment and 'periodic' in assignment):
        return False,'declared charge assignment is not the evaluator all-frame periodic-CIC reconstruction'
    if not any(token in deconv for token in ('power/k^2','power_over_k2','mean_power_over_k2')):
        return False,'declared reciprocal estimator is not the evaluator per-mode power/k^2 reconstruction'
    rawdims=[mesh]*3 if isinstance(mesh,(int,float)) and not isinstance(mesh,bool) else list(mesh) if isinstance(mesh,(list,tuple)) and len(mesh)==3 else None
    if rawdims is None or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(float(x)) or not float(x).is_integer() for x in rawdims):
        return False,'declared mesh is absent or not three finite integer dimensions; uncertainty cannot be tied to the all-frame checkpoint'
    dims=[int(x) for x in rawdims]
    if dims not in ([256,256,256],[384,384,384],[512,512,512]):
        return False,'declared mesh is outside supported all-frame periodic-CIC uncertainty reconstruction'
    if dims[0] != int(trusted_primary_mesh):
        return False,'declared mesh differs from the evaluator checkpoint primary mesh'
    return True,''

def audit_block_correlation(z:dict,fine_se_curve:np.ndarray|None=None,fine_se_eps:float|None=None,alpha:float=.05)->dict:
    """Bound possible block-SE underestimation at longer balanced scales.

    This approximate one-sided chi-square diagnostic applies to linear curve
    mode-power means and the global centered-dipole influence for epsilon only.
    It cannot prove independence; a finite-power PASS means no tested longer
    scale demonstrated a larger SE at the declared simultaneous confidence.
    """
    from scipy.stats import chi2
    p=np.asarray(z['p256strict'],float); mu=np.asarray(z['mdip'],float); mu2=np.asarray(z['mdip2'],float)
    count=np.asarray(z['mframes'],float); deg=np.asarray(z['deg'],float); box=np.asarray(z.get('box_A'),float)
    # Fine and coarse estimates must use the same global centering. In
    # particular epsilon's per-block nonlinear estimates are locally centered
    # and are not interchangeable with the coarse global influence function.
    fine=np.asarray([],float) if fine_se_curve is None else np.asarray(fine_se_curve,float)
    if p.ndim!=2 or mu.shape!=(len(count),3) or mu2.shape!=count.shape or p.shape[0]!=len(count) or deg.shape!=(p.shape[1],):
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'trusted blocks have inconsistent sufficient-statistic shapes'}
    if box.shape!=(3,) or not np.all(np.isfinite(box)) or np.any(box<=0):
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'valid box volume is required for centered-dipole influence'}
    if not math.isfinite(alpha) or not 0<alpha<1:
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'familywise alpha must lie strictly between zero and one'}
    if (len(count)<16 or (fine.size and len(fine)!=p.shape[1]) or deg.shape!=(p.shape[1],) or not np.all(np.isfinite(deg)) or np.any(deg<=0) or not np.all(np.isfinite(p)) or
        not np.all(np.isfinite(mu)) or not np.all(np.isfinite(mu2)) or np.any(count<=0) or
        (fine.size and (not np.all(np.isfinite(fine)) or np.any(fine<0)))):
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'insufficient or invalid fine-block uncertainty evidence'}
    if not np.allclose(count,count[0],rtol=0,atol=1e-12):
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'unequal source-frame counts prevent the balanced-block chi-square diagnostic'}
    nbase=len(count)
    # Include every admissible integer coarsening, not just powers of two.
    # Otherwise a short-block declaration (for example 200 x 0.1 ns) could
    # avoid the meaningful 2 ns comparison simply because 10 is not 2**k.
    scales=[m for m in range(2,nbase//8+1) if nbase%m==0]
    if not scales:
        return {'status':'UNSUPPORTED_EVIDENCE','reason':'no balanced coarser scale leaves at least eight blocks'}
    n_total=float(count.sum())
    norm=E**2/(float(np.prod(box))*1e-30*EPS0*KB*TEMP)
    epsden=3*EPS0*float(np.prod(box))*1e-30*KB*TEMP
    fine_a=norm*p/deg[None,:]; fine_theta=fine_a.sum(axis=0)/n_total
    fine_h=fine_a-fine_theta[None,:]*count[:,None]
    fine=np.sqrt(nbase/(nbase-1)*np.sum(fine_h*fine_h,axis=0))/n_total
    fine_mu=mu.sum(axis=0)/n_total; fine_m2=float(mu2.sum()/n_total)
    fine_influence=(mu2-fine_m2*count-2*np.sum(fine_mu[None,:]*(mu-fine_mu[None,:]*count[:,None]),axis=1))/epsden
    fineeps=math.sqrt(nbase/(nbase-1)*float(np.sum(fine_influence*fine_influence)))/n_total
    # One family covers every finite-k bin plus epsilon at every scale, and
    # each comparison uses a coarse-scale lower and fine-scale upper bound.
    # Splitting alpha across both tails avoids treating a noisy fine-SE point
    # estimate as if it were known exactly.
    J=(p.shape[1]+1)*len(scales); tail=float(alpha)/(2*J)
    results=[]; exceeded=[]
    for factor in scales:
        n=nbase//factor
        pc=p.reshape((n,factor,p.shape[1])).sum(axis=1)
        mc=mu.reshape((n,factor,3)).sum(axis=1)
        m2c=mu2.reshape((n,factor)).sum(axis=1)
        cc=count.reshape((n,factor)).sum(axis=1)
        if not np.allclose(cc,cc[0],rtol=0,atol=1e-12):
            return {'status':'UNSUPPORTED_EVIDENCE','reason':f'coarse {factor}-block aggregation has unequal frame counts'}
        total=float(cc.sum())
        A=norm*pc/deg[None,:]; theta=A.sum(axis=0)/total
        H=A-theta[None,:]*cc[:,None]
        se=np.sqrt(n/(n-1)*np.sum(H*H,axis=0))/total
        mu_mean=mc.sum(axis=0)/total; s2=float(m2c.sum()/total)
        influence=(m2c-s2*cc-2*np.sum(mu_mean[None,:]*(mc-mu_mean[None,:]*cc[:,None]),axis=1))/epsden
        se_eps=math.sqrt(n/(n-1)*float(np.sum(influence*influence)))/total
        quant=float(chi2.ppf(1-tail,n-1))
        fine_quant=float(chi2.ppf(tail,nbase-1))
        if not math.isfinite(quant) or quant<=0 or not math.isfinite(fine_quant) or fine_quant<=0:
            return {'status':'UNSUPPORTED_EVIDENCE','reason':'chi-square interval quantile is unavailable'}
        factor_lb=math.sqrt((n-1)/quant)
        factor_fine_ub=math.sqrt((nbase-1)/fine_quant)
        lb_curve=se*factor_lb; lb_eps=se_eps*factor_lb
        fine_ub_curve=fine*factor_fine_ub; fine_ub_eps=fineeps*factor_fine_ub
        bad=np.flatnonzero(lb_curve>fine_ub_curve+np.finfo(float).eps*np.maximum(1.,np.abs(fine_ub_curve))*16)
        eps_bad=lb_eps>fine_ub_eps+np.finfo(float).eps*max(1.,abs(fine_ub_eps))*16
        exceeded.extend({'scale_factor':factor,'curve_bin':int(i),'coarse_SE_lower_bound':float(lb_curve[i]),'fine_SE_upper_bound':float(fine_ub_curve[i])} for i in bad)
        if eps_bad: exceeded.append({'scale_factor':factor,'observable':'eps_w','coarse_SE_lower_bound':float(lb_eps),'fine_SE_upper_bound':float(fine_ub_eps)})
        results.append({'scale_factor':factor,'blocks':n,'simultaneous_tail_alpha_per_comparison':tail,
          'curve_SE_lower_bound':lb_curve.tolist(),'fine_curve_SE':fine.tolist(),'fine_curve_SE_upper_bound':fine_ub_curve.tolist(),'epsilon_SE_lower_bound':lb_eps,
          'fine_epsilon_SE':fineeps,'fine_epsilon_SE_upper_bound':fine_ub_eps,'underestimated_curve_bins':bad.astype(int).tolist(),'epsilon_underestimated':bool(eps_bad),
          'approximation':'normal independent fine/coarse block influence values; Bonferroni two-sided chi-square variance bounds'})
    return {'status':'FAIL' if exceeded else 'PASS_WITH_FINITE_POWER','familywise_alpha':alpha,
      'comparisons':J,'scales':results,'underestimation_evidence':exceeded,
      'scope':'linear finite-k curve means and global epsilon influence only; nonlinear extrema/width are not certified independent',
      'interpretation':'PASS_WITH_FINITE_POWER means tested longer scales did not demonstrate an SE exceeding the simultaneous fine-scale upper bound; approximate normal/independent-block assumptions apply and this does not prove independence'}

def _feature(row:np.ndarray,k:np.ndarray,extremum_method='bin')->dict:
    lo=np.flatnonzero((k>=.05)&(k<=2.5)); hi=np.flatnonzero((k>=2.5)&(k<=6.0))
    if len(lo)<2 or len(hi)<2: return {'k_min_A^-1':None,'chi_min':None,'k_max_A^-1':None,'chi_max':None,'delta_k_A^-1':None}
    i=int(lo[np.argmin(row[lo])]); j=int(hi[np.argmax(row[hi])]); kmin=float(k[i]); ymin=float(row[i]); kmax=float(k[j]); ymax=float(row[j])
    if extremum_method in ('quadratic','local_quadratic','parabolic'):
        def quad(ix,kind):
            if ix<=0 or ix>=len(k)-1: return None
            xx=k[ix-1:ix+2]-k[ix]; yy=row[ix-1:ix+2]; aa,bb,cc=np.polyfit(xx,yy,2)
            if not math.isfinite(float(aa)) or abs(aa)<1e-15 or (kind=='min' and aa<=0) or (kind=='max' and aa>=0): return None
            xv=-bb/(2*aa)
            if not xx[0]<=xv<=xx[-1]: return None
            return float(k[ix]+xv),float(aa*xv*xv+bb*xv+cc)
        qm=quad(i,'min'); qx=quad(j,'max')
        if qm is None or qx is None: return {'k_min_A^-1':None,'chi_min':None,'k_max_A^-1':None,'chi_max':None,'delta_k_A^-1':None}
        kmin,ymin=qm; kmax,ymax=qx
    elif extremum_method not in ('bin','bin_center','discrete'):
        raise NotImplementedError(f'extremum method {extremum_method!r} is unsupported')
    half=float(ymax)/2
    left=np.flatnonzero(row[:j]<=half); right=np.flatnonzero(row[j+1:]<=half)
    width=None
    if len(left) and len(right):
        a=int(left[-1]); b=int(j+1+right[0])
        kl=k[a]+(half-row[a])*(k[a+1]-k[a])/(row[a+1]-row[a])
        kr=k[b-1]+(half-row[b-1])*(k[b]-k[b-1])/(row[b]-row[b-1])
        width=float(kr-kl)
    return {'k_min_A^-1':kmin,'chi_min':ymin,'k_max_A^-1':kmax,'chi_max':ymax,'delta_k_A^-1':width}

def _make_scale(z,box:np.ndarray,g:int,draws:int,seed:int,deg:np.ndarray,kbin:np.ndarray,extremum_method='bin')->dict:
    nbase=len(z['mframes'])
    if nbase % g:
        raise ValueError('half-ns checkpoint blocks do not divide evenly at requested scale')
    n=nbase//g
    def agg(key):
        a=np.asarray(z[key],float)
        return a.reshape((n,g)+a.shape[1:]).sum(axis=1)
    p=agg('p256strict'); mu=agg('mdip'); mu2=agg('mdip2'); count=agg('mframes')
    if np.any(count<=0): raise ValueError('checkpoint contains an empty source block')
    volume=float(np.prod(box))*1e-30; norm=E**2/(volume*EPS0*KB*TEMP)
    rng=np.random.default_rng(seed); ids=rng.integers(0,n,(draws,n))
    nn=count[ids].sum(axis=1)
    # Weight unequal/partial final blocks by their actual sampled-frame count.
    # Equal-duration author blocks reduce exactly to the original block mean.
    curves=np.sum(p[ids]/deg[None,None,:],axis=1)/nn[:,None]*norm
    block_curves=p/(count[:,None]*deg[None,:])*norm
    sm=mu[ids].sum(axis=1); s2=mu2[ids].sum(axis=1)
    eps=1+(s2/nn-np.sum((sm/nn[:,None])**2,axis=1))/(3*EPS0*volume*KB*TEMP)
    block_eps=1+(mu2/count-np.sum((mu/count[:,None])**2,axis=1))/(3*EPS0*volume*KB*TEMP)
    allcurve=np.column_stack((1-1/eps,curves)); k=np.r_[0.,kbin]
    features=[_feature(row,k,extremum_method) for row in allcurve]
    block_features=[_feature(row,k,extremum_method) for row in np.column_stack((1-1/block_eps,block_curves))]
    valid={name:np.asarray([f[name] for f in features if f[name] is not None],float) for name in ('k_min_A^-1','chi_min','k_max_A^-1','chi_max','delta_k_A^-1')}
    fixed={str(target):int(np.argmin(abs(kbin-target))) for target in (.23,3.02,5.5)}
    return {'block_length_ns':.5*g,'blocks':n,'sampled_frames_per_block':int(np.median(count)),
      'bootstrap_ids':ids,'curves':curves,'chi0':1-1/eps,'eps':eps,'features':valid,
      'bootstrap_SE':{'eps_w':float(eps.std(ddof=1)),'chi_parallel_k0':float((1-1/eps).std(ddof=1)),
        'curve':curves.std(axis=0,ddof=1),'features':{key:float(vals.std(ddof=1)) if len(vals)>1 else None for key,vals in valid.items()}},
      'bootstrap_ci':{'eps_w':{},'chi_parallel_k0':{},'curve':[],'features':{}},'fixed_bin_block_SE':{},
      'block_estimates':{'eps_w':block_eps,'chi_parallel_k0':1-1/block_eps,'curve':block_curves,
        'features':{key:np.asarray([f[key] for f in block_features],float) for key in ('k_min_A^-1','chi_min','k_max_A^-1','chi_max','delta_k_A^-1') if all(f[key] is not None for f in block_features)}}}

def _fill_intervals(scale:dict,conf:float):
    alpha=(1-conf)/2
    quant=lambda x: [float(v) for v in np.quantile(x,[alpha,1-alpha])]
    scale['bootstrap_ci']['eps_w']=quant(scale['eps'])
    scale['bootstrap_ci']['chi_parallel_k0']=quant(scale['chi0'])
    scale['bootstrap_ci']['curve']=np.quantile(scale['curves'],[alpha,1-alpha],axis=0).tolist()
    scale['bootstrap_ci']['features']={key:(quant(vals) if len(vals) else None) for key,vals in scale['features'].items()}

def _charge_scaled_scale(scale:dict,charge_factor:float,kbin:np.ndarray,extremum_method:str,confidence:float)->dict:
    """Recompute uncertainty under one uniform native↔nominal charge scaling."""
    out=dict(scale); out['bootstrap_ci']={'eps_w':{},'chi_parallel_k0':{},'curve':[],'features':{}}; f=float(charge_factor); k=np.r_[0.,np.asarray(kbin,float)]
    curves=np.asarray(scale['curves'],float)*f
    eps=1.+(np.asarray(scale['eps'],float)-1.)*f
    chi0=1.-1./eps
    block_curves=np.asarray(scale['block_estimates']['curve'],float)*f
    block_eps=1.+(np.asarray(scale['block_estimates']['eps_w'],float)-1.)*f
    block_chi0=1.-1./block_eps
    allrows=np.column_stack((chi0,curves)); blockrows=np.column_stack((block_chi0,block_curves))
    featrows=[_feature(row,k,extremum_method) for row in allrows]
    blockfeat=[_feature(row,k,extremum_method) for row in blockrows]
    names=('k_min_A^-1','chi_min','k_max_A^-1','chi_max','delta_k_A^-1')
    features={name:np.asarray([r[name] for r in featrows if r[name] is not None],float) for name in names}
    block_features={name:np.asarray([r[name] for r in blockfeat],float) for name in names if all(r[name] is not None for r in blockfeat)}
    out.update(curves=curves,eps=eps,chi0=chi0,features=features)
    out['bootstrap_SE']={'eps_w':float(eps.std(ddof=1)),'chi_parallel_k0':float(chi0.std(ddof=1)),
      'curve':curves.std(axis=0,ddof=1),'features':{key:float(vals.std(ddof=1)) if len(vals)>1 else None for key,vals in features.items()}}
    out['block_estimates']={'eps_w':block_eps,'chi_parallel_k0':block_chi0,'curve':block_curves,'features':block_features}
    _fill_intervals(out,confidence)
    return out

def _validate_scale_counts(data:dict,scale:dict,checkpoint:dict)->list[str]:
    errors=[]; source=data.get('source')
    if not isinstance(source,dict): return ['candidate source/sample/block-count metadata is absent']
    expected={'trajectory_frames':checkpoint['trajectory_frames'],'sampled_frames':checkpoint['sampled_frames'],
      'sampling_interval_ps':checkpoint['sampling_interval_ps'],'blocks':scale['blocks'],'block_length_ns':scale['block_length_ns']}
    for key,value in expected.items():
        got=source.get(key)
        if not isinstance(got,(int,float)) or not math.isclose(float(got),float(value),rel_tol=0,abs_tol=1e-9): errors.append(f'source.{key} does not match trusted checkpoint counts')
    return errors

def _compare_interval(obj:dict,expected:np.ndarray,plan:dict,name:str,errors:list,unsupported:list):
    interval=_interval(obj); conf=_confidence(obj)
    if interval is None: return
    if conf is None: unsupported.append(f'{name}: no confidence level for interval'); return
    if plan.get('confidence_level') is not None and not math.isclose(conf,plan['confidence_level'],rel_tol=0,abs_tol=1e-12):
        errors.append(f'{name}: reported confidence conflicts with the declared method confidence')
        return
    if plan['kind']=='percentile':
        # A candidate-declared seed and draw count make this comparison
        # deterministic; tolerate only JSON serialization precision.
        lo,hi=np.quantile(expected,[((1-conf)/2),1-(1-conf)/2])
    elif plan['kind']=='bootstrap_normal':
        from statistics import NormalDist
        z=NormalDist().inv_cdf((1+conf)/2); sd=float(np.std(expected,ddof=1)); est=float(obj['estimate'])
        lo,hi=est-z*sd,est+z*sd
    elif plan['kind'] in ('block_sem_normal','block_sem_t'):
        values=np.asarray(expected,float)
        if values.ndim!=1 or len(values)<2 or not np.all(np.isfinite(values)):
            unsupported.append(f'{name}: block-level estimates do not support a standard error interval'); return
        sem=float(values.std(ddof=1)/math.sqrt(len(values))); est=float(obj['estimate'])
        if plan['kind']=='block_sem_t':
            from scipy.stats import t as student_t
            q=float(student_t.ppf((1+conf)/2,len(values)-1))
        else:
            from statistics import NormalDist
            q=NormalDist().inv_cdf((1+conf)/2)
        lo,hi=est-q*sem,est+q*sem
    else:
        unsupported.append(f'{name}: declared SE-only method cannot substantiate an interval'); return
    bounds=obj.get('_serialized_interval_half_ulp') if obj.get('_evaluator_csv_tokens') is True else _serialized_interval_bounds(obj)
    if bounds is None or any(v is None or not math.isfinite(float(v)) for v in bounds):
        unsupported.append(f'{name}: serialized interval precision is unavailable'); return
    exact_match=(abs(interval[0]-float(lo))<=1e-10 and abs(interval[1]-float(hi))<=1e-10)
    if exact_match: return
    center_rounding=0.0
    center_too_coarse=False
    if plan['kind'] in ('bootstrap_normal','block_sem_normal','block_sem_t'):
        center_rounding=obj.get('_serialized_estimate_half_ulp') if obj.get('_evaluator_csv_tokens') is True else _decimal_half_ulp(obj.get('estimate'))
        if center_rounding is None:
            unsupported.append(f'{name}: serialized estimate precision is unavailable for the declared centered interval'); return
        if center_rounding>5e-7:
            center_too_coarse=True
    deltas=(abs(interval[0]-float(lo)),abs(interval[1]-float(hi)))
    limits=(float(bounds[0])+float(center_rounding or 0.0)+1e-10,float(bounds[1])+float(center_rounding or 0.0)+1e-10)
    if any(d>lim for d,lim in zip(deltas,limits)):
        errors.append(f'{name}: interval does not match the declared method at confidence {conf:g}')
    elif any(float(v)>5e-7 for v in bounds) or center_too_coarse:
        unsupported.append(f'{name}: serialized interval precision is too coarse to distinguish supported charge representations')

def _compare_se(obj:dict,expected:float,name:str,plan:dict,errors:list,unsupported:list,default_bootstrap_se:bool=False,outer_method:str|None=None):
    sekey=next((k for k in ('bootstrap_SE','SE','standard_error','chi_bootstrap_SE','chi_SE') if k in obj),None)
    if sekey is None: return
    try: got=float(obj[sekey])
    except (ValueError,TypeError): errors.append(f'{name}: invalid standard error'); return
    if not math.isfinite(got) or got<0: errors.append(f'{name}: invalid standard error'); return
    # Method specificity is intentional: a CSV row can document a different
    # estimator from the file-level default. Only use a bootstrap fallback
    # when the candidate actually declared a reproducible bootstrap plan.
    method=obj.get('uncertainty_method') or obj.get('se_method') or outer_method or ''
    method=str(method).lower()
    if plan['kind'].startswith('block_sem') and (sekey.startswith('bootstrap_') or 'bootstrap' in method):
        errors.append(f'{name}: bootstrap-labelled SE conflicts with the declared block-mean SEM method'); return
    if not method and plan.get('kind') in ('percentile','bootstrap_sd','bootstrap_normal') and plan.get('draws') and plan.get('seed') is not None:
        method='bootstrap standard deviation'
    if sekey.startswith('bootstrap_') or sekey == 'chi_bootstrap_SE' or 'bootstrap' in method or (default_bootstrap_se and sekey in ('bootstrap_SE','chi_bootstrap_SE')):
        reference=float(expected)
    elif 'block standard error' in method or 'sd/sqrt(n)' in method or 'standard deviation divided by sqrt' in method:
        reference=float(expected)
    else:
        unsupported.append(f'{name}: standard-error definition is not supported or not stated'); return
    tol=obj.get('_serialized_se_half_ulp') if obj.get('_evaluator_csv_tokens') is True else None
    if tol is None: tol=_decimal_half_ulp(obj.get(sekey))
    if tol is None or not math.isfinite(float(tol)):
        unsupported.append(f'{name}: serialized standard-error precision is unavailable'); return
    delta=abs(got-reference)
    if delta<=1e-10: return
    rounding=float(tol)+1e-10
    if delta>rounding: errors.append(f'{name}: reported standard error does not match its declared definition')
    elif float(tol)>5e-7: unsupported.append(f'{name}: serialized standard-error precision is too coarse to audit')

def audit_uncertainty(root:Path,trusted_checkpoint:Path,trusted_native_json:Path,output:Path|None=None)->dict:
    """Check candidate-declared uncertainty from evaluator-only checkpoint blocks."""
    root_arg=Path(root).absolute(); errors=[]; unsupported=[]; facts={}; resolved={}
    try:
        if root_arg.is_symlink(): raise ValueError('candidate root is a symlink')
        root=root_arg.resolve()
        checkpoint_path=_outside_candidate(Path(trusted_checkpoint),root,'checkpoint')
        native_path=_outside_candidate(Path(trusted_native_json),root,'native validation JSON')
        resolved.update(trusted_checkpoint=str(checkpoint_path),trusted_native_validation=str(native_path))
        for rel in ('final','final/chi_k.csv','final/observables.json'):
            p=root/rel
            if p.is_symlink(): raise ValueError(f'candidate path may not be a symlink: {rel}')
        data=_loads_json_with_tokens((root/'final/observables.json').read_text()); obs=data.get('observables',data)
        if not isinstance(obs,dict): raise ValueError('candidate observables are malformed')
        if _has_private_serialization_claim(data): raise ValueError('candidate observables may not supply evaluator-private serialization bounds')
        resolved.update(candidate_observables=str((root/'final/observables.json').resolve()),candidate_curve=str((root/'final/chi_k.csv').resolve()))
        candidate_method=data.get('method');
        if not isinstance(candidate_method,dict): raise NotImplementedError('candidate method metadata is absent')
        plan=_method_plan(data,obs)
        block_ns=data.get('source',{}).get('block_length_ns',plan['block_length_ns'])
        if block_ns is None: raise NotImplementedError('source block length is not declared')
        block_ns=float(block_ns)
        if plan['block_length_ns'] is not None and not math.isclose(block_ns,plan['block_length_ns'],abs_tol=1e-9):
            errors.append('method block length conflicts with source block length')
        g=round(block_ns/.5)
        if g not in (1,2,4) or not math.isclose(block_ns,.5*g,abs_tol=1e-9):
            raise NotImplementedError('candidate block schedule is not represented by the trusted half-ns sufficient statistics')
        plan['block_length_ns']=block_ns
        with np.load(checkpoint_path,allow_pickle=False) as z:
            needed=('p256strict','mdip','mdip2','mframes','deg','kbin')
            if any(key not in z.files for key in needed): raise ValueError('trusted checkpoint is missing sufficient-statistic arrays')
            arrays={key:np.asarray(z[key]) for key in needed}
            checkpoint_meta={key:np.asarray(z[key]) for key in ('sampled_frame_ids','sampled_times_ps','sample_period_ps','native_box_A','scheduled_target_count') if key in z.files}
        if arrays['p256strict'].shape!=(40,119) or arrays['mdip'].shape!=(40,3) or arrays['mdip2'].shape!=(40,) or arrays['mframes'].shape!=(40,) or arrays['deg'].shape!=(119,) or arrays['kbin'].shape!=(119,):
            raise ValueError('trusted checkpoint array shapes do not match 40 half-ns blocks and 119 bins')
        native=json.loads(native_path.read_text()); n=native.get('native',native)
        box=np.asarray(n.get('box_A'),float)
        if box.shape!=(3,) or not np.all(np.isfinite(box)) or np.any(box<=0): raise ValueError('trusted native JSON lacks a valid three-axis box')
        # Bind resampling to the evaluator's actual schedule and native cell.
        # Older trusted snapshots lack these fields; they remain usable only
        # for the frozen 9136 calibration and are labeled as such.
        if 'sampled_frame_ids' in checkpoint_meta:
            ids=np.asarray(checkpoint_meta['sampled_frame_ids']).reshape(-1)
            times=np.asarray(checkpoint_meta.get('sampled_times_ps',[]),float).reshape(-1)
            period=float(np.asarray(checkpoint_meta.get('sample_period_ps',np.nan)).reshape(-1)[0])
            scheduled_targets=int(np.asarray(checkpoint_meta.get('scheduled_target_count',np.nan)).reshape(-1)[0])
            if len(ids)!=len(times) or len(ids)==0 or not math.isfinite(period) or period<=0:
                raise ValueError('trusted checkpoint sampling schedule metadata is malformed')
            frame_steps=np.diff(ids); time_steps=np.diff(times)
            if np.any(frame_steps<=0) or np.any(time_steps<=0): raise ValueError('trusted checkpoint sampling schedule is not strictly increasing')
            if not np.allclose(frame_steps,np.median(frame_steps),rtol=0,atol=0) or not np.allclose(time_steps,np.median(time_steps),rtol=0,atol=.01):
                raise NotImplementedError('nonuniform evaluator sampling schedule is not supported')
            actual_period=float(np.median(time_steps))
            nominal_ratio=actual_period/period
            if nominal_ratio<1-1e-9 or not math.isclose(nominal_ratio,round(nominal_ratio),rel_tol=0,abs_tol=.002):
                raise NotImplementedError('saved sample-time cadence cannot be reconciled with the declared nominal schedule')
            if not math.isclose(float(ids[0]),0.,abs_tol=0) or not math.isclose(float(times[0]),0.,abs_tol=.01): raise NotImplementedError('evaluator schedule does not start at production time zero')
            trajectory_frames=n.get('trajectory_frames')
            if not isinstance(trajectory_frames,(int,float)) or trajectory_frames<2:
                raise NotImplementedError('trusted native validation does not report the trajectory frame count')
            if scheduled_targets<len(ids) or scheduled_targets<1:
                raise ValueError('checkpoint scheduled-target count is inconsistent with sampled frame identifiers')
            if int(ids[-1])>=int(trajectory_frames): raise ValueError('sampled frame identifier exceeds the trusted trajectory frame count')
            if 'native_box_A' in checkpoint_meta and not np.allclose(np.asarray(checkpoint_meta['native_box_A'],float).reshape(3),box,rtol=0,atol=1e-8):
                raise ValueError('trusted checkpoint cell differs from independently audited native cell')
            checkpoint_counts={'trajectory_frames':int(trajectory_frames),'sampled_frames':len(ids),'sampling_interval_ps':actual_period}
            facts['schedule_binding']={'sampled_frames':len(ids),'scheduled_target_count':scheduled_targets,'trajectory_frames':int(trajectory_frames),'first_frame_id':int(ids[0]),'last_frame_id':int(ids[-1]),'first_time_ps':float(times[0]),'last_time_ps':float(times[-1]),'nominal_period_ps':period,'actual_period_ps':actual_period,'native_box_A':box.tolist()}
        else:
            checkpoint_counts={'trajectory_frames':20001,'sampled_frames':2000,'sampling_interval_ps':10}
            facts['schedule_binding']={'status':'legacy calibration metadata; not a production freshness receipt'}
        source=data.get('source')
        if not isinstance(source,dict): raise NotImplementedError('candidate source/sampling metadata is absent')
        actual_frames=n.get('trajectory_frames')
        if not isinstance(actual_frames,(int,float)) or not math.isfinite(float(actual_frames)):
            raise NotImplementedError('independent native audit does not establish trajectory frame count')
        if not isinstance(source.get('trajectory_frames'),(int,float)) or int(source['trajectory_frames'])!=int(actual_frames):
            raise ValueError('source.trajectory_frames conflicts with the independently audited trajectory')
        for key,label in (('sampled_frames','sample count'),('sampling_interval_ps','sampling interval')):
            got=source.get(key); expected=checkpoint_counts[key]
            if not isinstance(got,(int,float)) or not math.isfinite(float(got)) or not math.isclose(float(got),float(expected),rel_tol=0,abs_tol=1e-9):
                raise NotImplementedError(f'candidate {label} differs from the trusted evaluator sampling schedule; a candidate-schedule re-extraction adapter is required')
        if np.any(arrays['mframes']<=0) or int(np.sum(arrays['mframes']))!=checkpoint_counts['sampled_frames']:
            raise ValueError('trusted source block counts do not match the evaluator sampling schedule')
        zview={k:arrays[k] for k in needed}; plan['draws']=int(plan['draws']); plan['seed']=int(plan['seed'])
        scales={}
        for group in (1,2,4):
            s=_make_scale(zview,box,group,plan['draws'],plan['seed'],arrays['deg'].astype(float),arrays['kbin'].astype(float))
            _fill_intervals(s,.95)
            scales[s['block_length_ns']]=s
        selected=scales[block_ns]; facts['source_counts']={str(k):{'blocks':v['blocks'],'sampled_frames_per_block':v['sampled_frames_per_block'],'total_sampled_frames':v['blocks']*v['sampled_frames_per_block']} for k,v in scales.items()}
        facts['bootstrap_plan']=plan; facts['checkpoint_sha256']=_sha(checkpoint_path); facts['native_validation_sha256']=_sha(native_path)
        errors.extend(_validate_scale_counts(data,selected,checkpoint_counts))
        # Compare all declared observables using the selected block size and the
        # confidence level attached to each field (ci_95 means exactly 95%).
        mapping={'eps_w':('eps_w','eps_w'),'chi_parallel_k0':('chi_parallel_k0','chi_parallel_k0'),
          'k_min_A^-1':('k_min_A^-1','k_min_A^-1'),'chi_min':('chi_min','chi_min'),
          'k_max_A^-1':('k_max_A^-1','k_max_A^-1'),'chi_max':('chi_max','chi_max'),
          'delta_k_A^-1':('delta_k_A^-1','delta_k_A^-1')}
        checked={}
        for name,(key,distkey) in mapping.items():
            obj=obs.get(name)
            if not isinstance(obj,dict):
                if name in ('eps_w','k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1'): errors.append(f'missing required uncertainty object {name}')
                continue
            dist=selected['eps'] if distkey=='eps_w' else selected['chi0'] if distkey=='chi_parallel_k0' else selected['features'][distkey]
            if isinstance(dist, np.ndarray) and dist.size == 0:
                unsupported.append(f'{name}: no valid bootstrap draws for estimator'); continue
            prior=(len(errors),len(unsupported)); _compare_interval(obj,dist,plan,name,errors,unsupported)
            expected_se=(selected['bootstrap_SE']['eps_w'] if key=='eps_w' else selected['bootstrap_SE']['chi_parallel_k0'] if key=='chi_parallel_k0' else selected['bootstrap_SE']['features'].get(key))
            if expected_se is not None: _compare_se(obj,float(expected_se),name,plan,errors,unsupported,default_bootstrap_se=True,outer_method=str(candidate_method.get('uncertainty_method','')))
            if key in selected['features'] and 'valid_bootstrap_fraction' in obj:
                got=float(obj['valid_bootstrap_fraction']); exp=len(selected['features'][key])/plan['draws']
                if not math.isclose(got,exp,abs_tol=1e-12): errors.append(f'{name}: valid bootstrap fraction mismatch')
            checked[name]={'confidence_level':_confidence(obj),'interval':_interval(obj),'expected_bootstrap_SE':expected_se,'status':'UNSUPPORTED_EVIDENCE' if len(unsupported)>prior[1] else 'FAIL' if len(errors)>prior[0] else 'PASS'}
        # Check every per-k reported curve uncertainty against the trusted
        # bootstrap draws, including k=0 derived from the same epsilon blocks.
        curve_path=root/'final/chi_k.csv'; rows=list(csv.DictReader(curve_path.open(newline='')))
        if not rows: raise ValueError('candidate susceptibility curve is empty')
        expected_k=np.r_[0.,arrays['kbin'].astype(float)]; candidate_k=np.asarray([float(r['k_A^-1']) for r in rows])
        if candidate_k.shape!=expected_k.shape or np.max(np.abs(candidate_k-expected_k))>1e-9:
            unsupported.append('curve uncertainty grid differs from trusted fixed-bin checkpoint grid; a candidate-grid native re-extraction adapter is required'); curve_rows=[]
        else:
            curves=np.column_stack((selected['chi0'],selected['curves']))
            lows=np.quantile(curves,.025,axis=0); highs=np.quantile(curves,.975,axis=0); ses=curves.std(axis=0,ddof=1)
            curve_rows=[]
            for j,row in enumerate(rows):
                obj={'estimate':_LexicalFloat(row['chi_parallel']),'_evaluator_csv_tokens':True,'_serialized_estimate_half_ulp':_decimal_half_ulp(row['chi_parallel'])}
                if 'chi_95_low' in row and 'chi_95_high' in row:
                    obj['ci_95']=[float(row['chi_95_low']),float(row['chi_95_high'])]
                    obj['_serialized_interval_half_ulp']=(_decimal_half_ulp(row['chi_95_low']),_decimal_half_ulp(row['chi_95_high']))
                elif 'chi_interval_low' in row and 'chi_interval_high' in row:
                    obj['interval']=[float(row['chi_interval_low']),float(row['chi_interval_high'])]
                    obj['_serialized_interval_half_ulp']=(_decimal_half_ulp(row['chi_interval_low']),_decimal_half_ulp(row['chi_interval_high']))
                    if 'confidence_level' in row: obj['confidence_level']=float(row['confidence_level'])
                if 'chi_bootstrap_SE' in row:
                    obj['chi_bootstrap_SE']=float(row['chi_bootstrap_SE']); obj['_serialized_se_half_ulp']=_decimal_half_ulp(row['chi_bootstrap_SE'])
                elif 'chi_SE' in row:
                    obj['chi_SE']=float(row['chi_SE']); obj['_serialized_se_half_ulp']=_decimal_half_ulp(row['chi_SE'])
                if 'uncertainty_method' in row: obj['uncertainty_method']=row['uncertainty_method']
                elif 'uncertainty_method' in candidate_method: obj['uncertainty_method']=candidate_method['uncertainty_method']
                ci_before=len(errors); uns_before=len(unsupported)
                _compare_interval(obj,np.asarray(curves[:,j]),plan,f'chi_k[{j}]',errors,unsupported)
                if 'chi_bootstrap_SE' in obj: _compare_se(obj,float(ses[j]),f'chi_k[{j}]',plan,errors,unsupported,default_bootstrap_se=True,outer_method=str(candidate_method.get('uncertainty_method','')))
                elif 'chi_SE' in obj: _compare_se(obj,float(ses[j]),f'chi_k[{j}]',plan,errors,unsupported,default_bootstrap_se=True,outer_method=str(candidate_method.get('uncertainty_method','')))
                elif 'ci_95_low' not in row and 'ci_95_high' not in row: unsupported.append(f'chi_k[{j}]: curve lacks a supported uncertainty column')
                curve_rows.append({'index':j,'confidence_level':.95 if 'ci_95' in obj else None,'expected_bootstrap_SE':float(ses[j]),'status':'UNSUPPORTED_EVIDENCE' if len(unsupported)>uns_before else 'FAIL' if len(errors)>ci_before else 'PASS'})
        facts['checked_observables']=checked; facts['curve_rows_checked']=len(curve_rows); facts['curve_row_results']=curve_rows
        # Candidate-declared reblocking SEs are checked independently at all
        # three scales; no pass/fail heuristic about the SE ratios is imposed.
        reblock=data.get('reblocking')
        rb_results={}
        if reblock is not None:
            if not isinstance(reblock,dict): errors.append('reblocking metadata is malformed')
            else:
                for name,distkey in (('epsilon_w','eps_w'),('delta_k_A^-1','delta_k_A^-1'),('chi_0.23','chi_0.23'),('chi_3.02','chi_3.02'),('chi_5.5','chi_5.5')):
                    obj=reblock.get(name)
                    if not isinstance(obj,dict) or not isinstance(obj.get('se_by_blocking_ns'),list):
                        unsupported.append(f'reblocking.{name}: scale-specific SE series is absent'); continue
                    expected=[]
                    for length in (.5,1.,2.):
                        s=scales[length]
                        if distkey=='eps_w': v=s['bootstrap_SE']['eps_w']
                        elif distkey=='delta_k_A^-1': v=s['bootstrap_SE']['features']['delta_k_A^-1']
                        else:
                            target=float(distkey.removeprefix('chi_')); ix=int(np.argmin(abs(arrays['kbin']-target)))
                            # Conventional standard error of the equally weighted
                            # block mean, explicitly permitted for linear chi bins.
                            grouped=np.asarray(zview['p256strict']).reshape((40//int(length/.5),int(length/.5),119)).sum(axis=1)
                            gc=np.asarray(zview['mframes']).reshape((40//int(length/.5),int(length/.5))).sum(axis=1)
                            blockvals=grouped/(gc[:,None]*arrays['deg'][None,:])*((E**2)/(float(np.prod(box))*1e-30*EPS0*KB*TEMP))
                            v=float(blockvals[:,ix].std(ddof=1)/math.sqrt(len(blockvals)))
                        expected.append(float(v))
                    got=np.asarray(obj['se_by_blocking_ns'],float)
                    if got.shape!=(3,) or np.any(~np.isfinite(got)):
                        errors.append(f'reblocking.{name}: expected three finite SEs for 0.5/1/2 ns')
                    else:
                        tol=np.maximum(1e-10,1e-9*np.maximum(1,np.abs(expected)))
                        if np.any(abs(got-np.asarray(expected))>tol): errors.append(f'reblocking.{name}: SEs do not match declared definitions at 0.5/1/2 ns')
                    rb_results[name]={'block_lengths_ns':[.5,1.,2.],'reported':got.tolist() if got.shape==(3,) else None,'recomputed':expected}
        facts['reblocking_checked']=rb_results
        status='FAIL' if errors else 'UNSUPPORTED_EVIDENCE' if unsupported else 'PASS'
        result={'status':status,'errors':errors,'unsupported_evidence':unsupported,'uncertainty_facts':facts,'resolved_artifacts':resolved}
    except NotImplementedError as e:
        result={'status':'UNSUPPORTED_EVIDENCE','errors':[],'unsupported_evidence':[str(e)],'uncertainty_facts':facts,'resolved_artifacts':resolved}
    except Exception as e:
        result={'status':'ERROR','errors':[str(e)],'unsupported_evidence':unsupported,'uncertainty_facts':facts,'resolved_artifacts':resolved}
    if output:
        out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+'\n')
    return result

def _audit_candidate_reextracted_branch(root:Path,trusted_checkpoint:Path,reextract_json:Path,output:Path|None=None,charge_branch:str='native')->dict:
    """Validate uncertainty claims against evaluator blocks on the candidate schedule.

    The checkpoint must have been produced by candidate_reextract.py from the
    audited native TPR/XTC. Candidate-supplied statistics are never read.
    """
    root=Path(root).resolve(); errors=[]; unsupported=[]; facts={}; resolved={}
    try:
        cp=_outside_candidate(Path(trusted_checkpoint),root,'candidate-schedule checkpoint')
        meta_path=_outside_candidate(Path(reextract_json),root,'candidate-schedule re-extraction summary')
        resolved.update(trusted_checkpoint=str(cp),trusted_reextraction=str(meta_path))
        for rel in ('final','final/chi_k.csv','final/observables.json'):
            if (root/rel).is_symlink(): raise ValueError(f'candidate path may not be a symlink: {rel}')
        data=_loads_json_with_tokens((root/'final/observables.json').read_text()); obs=data.get('observables',data)
        if not isinstance(obs,dict): raise ValueError('candidate observables are malformed')
        if _has_private_serialization_claim(data): raise ValueError('candidate observables may not supply evaluator-private serialization bounds')
        native=json.loads(meta_path.read_text())
        if native.get('status')!='REEXTRACTED': raise ValueError('candidate-schedule native re-extraction did not complete')
        with np.load(cp,allow_pickle=False) as z:
            needed=('p256strict','primary_power_sums','primary_mesh','primary_mode_degeneracy','mdip','mdip2','mframes','deg','kbin','sampled_frame_ids','sampled_times_ps','sample_period_ps','box_A','native_charges')
            if any(k not in z.files for k in needed): raise ValueError('trusted candidate-schedule checkpoint lacks sufficient statistics')
            arrays={k:np.asarray(z[k]) for k in needed}
            arrays['p256strict']=arrays['primary_power_sums']
            arrays['deg']=arrays['primary_mode_degeneracy']
            trusted_primary_mesh=int(np.asarray(arrays['primary_mesh']).reshape(-1)[0])
            if trusted_primary_mesh not in (256,384,512): raise NotImplementedError('trusted candidate checkpoint primary mesh is unsupported')
            block_length=float(np.asarray(z['block_length_ns']).reshape(-1)[0])
            scheduled_targets=int(np.asarray(z['scheduled_target_count']).reshape(-1)[0]) if 'scheduled_target_count' in z.files else len(arrays['sampled_frame_ids'])
        nb=arrays['p256strict'].shape[1] if arrays['p256strict'].ndim==2 else 0
        nblock=arrays['p256strict'].shape[0] if arrays['p256strict'].ndim==2 else 0
        if nblock<10 or nb<2 or arrays['mdip'].shape!=(nblock,3) or arrays['mdip2'].shape!=(nblock,) or arrays['mframes'].shape!=(nblock,) or arrays['deg'].shape!=(nb,) or arrays['kbin'].shape!=(nb,):
            raise ValueError('trusted candidate-schedule checkpoint dimensions are inconsistent or statistically insufficient')
        if np.any(arrays['mframes']<=0) or int(arrays['mframes'].sum())!=len(arrays['sampled_frame_ids']):
            raise ValueError('trusted candidate-schedule frame counts do not reconcile')
        source=data.get('source')
        if not isinstance(source,dict): raise ValueError('candidate source metadata is absent')
        sampling=native.get('sampling',{})
        expected={'trajectory_frames':sampling.get('native_frames'),'sampled_frames':sampling.get('selected_frames'),
          'sampling_interval_ps':sampling.get('sample_period_ps_declared'),'blocks':nblock,'block_length_ns':block_length}
        for key,value in expected.items():
            got=source.get(key)
            if not isinstance(got,(int,float)) or not math.isclose(float(got),float(value),rel_tol=0,abs_tol=1e-8):
                errors.append(f'source.{key} does not match trusted native re-extraction')
        method=data.get('method')
        if not isinstance(method,dict): raise NotImplementedError('candidate method metadata is absent')
        method_matches,method_reason=_candidate_matches_trusted_curve_reconstruction(method,trusted_primary_mesh)
        if not method_matches: raise NotImplementedError(method_reason)
        reporting=native.get('reporting',{})
        if reporting.get('primary_mesh')!=trusted_primary_mesh:
            raise ValueError('trusted re-extraction metadata primary mesh does not match its checkpoint')
        plan=_method_plan(data,obs)
        if not math.isclose(float(plan['block_length_ns']),block_length,rel_tol=0,abs_tol=1e-9):
            errors.append('bootstrap block length differs from the independently accumulated candidate blocks')
        box=np.asarray(arrays['box_A'],float).reshape(3)
        zview={k:arrays[k] for k in ('p256strict','mdip','mdip2','mframes','deg','kbin')}
        zview['box_A']=box
        extremum_method=method.get('extremum_method','bin')
        scale=_make_scale(zview,box,1,plan['draws'],plan['seed'],arrays['deg'].astype(float),arrays['kbin'].astype(float),extremum_method)
        _fill_intervals(scale,.95)
        nominal_scale=float(native.get('nominal_charge_scale',1.0))
        if charge_branch=='nominal': scale=_charge_scaled_scale(scale,nominal_scale**2,arrays['kbin'],extremum_method,.95)
        elif charge_branch!='native': raise ValueError('unknown trusted charge representation branch')
        scale['block_length_ns']=block_length; scale['blocks']=nblock
        correlation=audit_block_correlation(zview)
        correlation['fine_uncertainty_definition']='evaluator recomputed linear influence SEM at the declared fine schedule; same global centering at each coarser scale'
        facts['block_correlation_audit']=correlation
        if correlation.get('status')=='FAIL':
            errors.append('candidate block length materially underestimates linear-observable uncertainty under the trusted longer-scale diagnostic')
        elif correlation.get('status')=='UNSUPPORTED_EVIDENCE':
            unsupported.append('block-correlation reliability could not be evaluated: '+str(correlation.get('reason','insufficient evidence')))
        volume=float(np.prod(box))*1e-30; norm=E**2/(volume*EPS0*KB*TEMP)
        point_curve=np.sum(arrays['p256strict'],axis=0)/(float(arrays['mframes'].sum())*arrays['deg'])*norm
        total_n=float(arrays['mframes'].sum()); sm=np.sum(arrays['mdip'],axis=0); s2=float(np.sum(arrays['mdip2']))
        eps_native=1+(s2/total_n-float((sm/total_n)@(sm/total_n)))/(3*EPS0*volume*KB*TEMP)
        if charge_branch=='nominal':
            point_curve=point_curve*nominal_scale**2
            eps_point=1+(eps_native-1)*nominal_scale**2
        else: eps_point=eps_native
        chi0_point=1-1/eps_point
        expected_curve=np.r_[chi0_point,point_curve]; curve_draws=np.column_stack((scale['chi0'],scale['curves']))
        curve_se=curve_draws.std(axis=0,ddof=1); curve_mean=expected_curve
        maxima=[]
        for start in range(0,len(curve_draws),128):
            bdraw=curve_draws[start:start+128]
            maxima.extend(np.max(np.abs((bdraw-curve_mean)/np.maximum(curve_se,1e-15)),axis=1).tolist())
        curve_critical=float(np.quantile(maxima,.95))
        from science_score import _curve_features
        point_features=_curve_features(np.column_stack((np.r_[0.,arrays['kbin']],expected_curve)),extremum_method)
        low=np.flatnonzero((np.r_[0.,arrays['kbin']]>=.05)&(np.r_[0.,arrays['kbin']]<=2.5)); support=0
        for draw in curve_draws:
            idx=int(low[np.argmin(draw[low])])
            if idx not in (int(low[0]),int(low[-1])) and draw[idx]<draw[idx-1] and draw[idx]<draw[idx+1]: support+=1
        point_features['strict_interior_minimum_support']=support/len(curve_draws)
        checked={}
        mapping={'eps_w':'eps_w','chi_parallel_k0':'chi_parallel_k0','k_min_A^-1':'k_min_A^-1','chi_min':'chi_min','k_max_A^-1':'k_max_A^-1','delta_k_A^-1':'delta_k_A^-1'}
        for name,key in mapping.items():
            obj=obs.get(name)
            if not isinstance(obj,dict):
                if name in ('eps_w','k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1'): errors.append(f'missing required uncertainty object {name}')
                continue
            dist=scale['eps'] if name=='eps_w' else scale['chi0'] if name=='chi_parallel_k0' else scale['features'].get(key)
            if plan['kind'].startswith('block_sem'):
                dist=scale['block_estimates'].get(key,scale['block_estimates'].get('features',{}).get(key))
                if dist is None:
                    unsupported.append(f'{name}: block-level estimates do not support the declared SEM method'); continue
                dist=np.asarray(dist,float)
            if isinstance(dist,np.ndarray) and not dist.size: unsupported.append(f'{name}: no valid bootstrap draws')
            before=(len(errors),len(unsupported)); _compare_interval(obj,np.asarray(dist),plan,name,errors,unsupported)
            if plan['kind'].startswith('block_sem'):
                expected_se=float(np.std(dist,ddof=1)/math.sqrt(len(dist))) if len(dist)>1 else None
            else:
                expected_se=scale['bootstrap_SE']['eps_w'] if name=='eps_w' else scale['bootstrap_SE']['chi_parallel_k0'] if name=='chi_parallel_k0' else scale['bootstrap_SE']['features'].get(key)
            if expected_se is not None: _compare_se(obj,float(expected_se),name,plan,errors,unsupported,default_bootstrap_se=True,outer_method=str(method.get('uncertainty_method','')))
            checked[name]={'expected_SE':expected_se,'uncertainty_kind':plan['kind'],'confidence_level':_confidence(obj),'status':'UNSUPPORTED_EVIDENCE' if len(unsupported)>before[1] else 'FAIL' if len(errors)>before[0] else 'PASS'}
        rows=list(csv.DictReader((root/'final/chi_k.csv').open(newline='')))
        ck=np.asarray([float(r['k_A^-1']) for r in rows],float); expected_k=np.r_[0.,arrays['kbin']]
        if ck.shape!=expected_k.shape or not np.allclose(ck,expected_k,rtol=0,atol=1e-8):
            raise ValueError('curve k points differ from independently reconstructed candidate reporting bins')
        curves=np.column_stack((scale['chi0'],scale['curves'])); block_curves=np.column_stack((scale['block_estimates']['chi_parallel_k0'],scale['block_estimates']['curve'])); curve_check=[]
        if len(rows)!=curves.shape[1]: raise ValueError('candidate curve rows do not match trusted bootstrap curve')
        for i,row in enumerate(rows):
            obj={'estimate':_LexicalFloat(row['chi_parallel']),'_evaluator_csv_tokens':True,'_serialized_estimate_half_ulp':_decimal_half_ulp(row['chi_parallel'])}
            if 'chi_95_low' in row and 'chi_95_high' in row:
                obj['ci_95']=[float(row['chi_95_low']),float(row['chi_95_high'])]
                obj['_serialized_interval_half_ulp']=(_decimal_half_ulp(row['chi_95_low']),_decimal_half_ulp(row['chi_95_high']))
            elif 'chi_interval_low' in row and 'chi_interval_high' in row:
                obj['interval']=[float(row['chi_interval_low']),float(row['chi_interval_high'])]
                obj['_serialized_interval_half_ulp']=(_decimal_half_ulp(row['chi_interval_low']),_decimal_half_ulp(row['chi_interval_high']))
                if 'confidence_level' in row: obj['confidence_level']=float(row['confidence_level'])
            if 'chi_bootstrap_SE' in row:
                obj['chi_bootstrap_SE']=float(row['chi_bootstrap_SE']); obj['_serialized_se_half_ulp']=_decimal_half_ulp(row['chi_bootstrap_SE'])
            elif 'chi_SE' in row:
                obj['chi_SE']=float(row['chi_SE']); obj['_serialized_se_half_ulp']=_decimal_half_ulp(row['chi_SE'])
            if 'uncertainty_method' in row: obj['uncertainty_method']=row['uncertainty_method']
            elif 'uncertainty_method' in method: obj['uncertainty_method']=method['uncertainty_method']
            values=block_curves[:,i] if plan['kind'].startswith('block_sem') else curves[:,i]
            prior=(len(errors),len(unsupported)); _compare_interval(obj,values,plan,f'chi_k[{i}]',errors,unsupported)
            se=float(values.std(ddof=1)/math.sqrt(len(values))) if plan['kind'].startswith('block_sem') else float(curves[:,i].std(ddof=1))
            if 'chi_bootstrap_SE' in obj or 'chi_SE' in obj: _compare_se(obj,se,f'chi_k[{i}]',plan,errors,unsupported,default_bootstrap_se=True,outer_method=str(method.get('uncertainty_method','')))
            elif 'ci_95' not in obj and 'interval' not in obj: unsupported.append(f'chi_k[{i}]: no declared uncertainty')
            curve_check.append({'index':i,'expected_SE':se,'status':'UNSUPPORTED_EVIDENCE' if len(unsupported)>prior[1] else 'FAIL' if len(errors)>prior[0] else 'PASS'})
        facts.update({'schedule':sampling,'block_length_ns':block_length,'blocks':nblock,'bins':nb,'bootstrap_plan':plan,'charge_representation':charge_branch,'nominal_charge_scale':nominal_scale,'checked_observables':checked,'curve_rows':curve_check,
          'point_curve':expected_curve.tolist(),'curve_simultaneous_statistical_band_95':(curve_critical*curve_se).tolist(),'curve_maxstat_critical_95':curve_critical,
          'point_features':point_features,'epsilon_point':eps_point,'chi0_point':chi0_point,
          'feature_bootstrap_SE':scale['bootstrap_SE']['features'],'epsilon_bootstrap_SE':scale['bootstrap_SE']['eps_w'],
          'checkpoint_sha256':_sha(cp),'reextraction_sha256':_sha(meta_path)})
        result={'status':'FAIL' if errors else 'UNSUPPORTED_EVIDENCE' if unsupported else 'PASS','errors':errors,'unsupported_evidence':unsupported,'uncertainty_facts':facts,'resolved_artifacts':resolved}
    except NotImplementedError as e: result={'status':'UNSUPPORTED_EVIDENCE','errors':[],'unsupported_evidence':[str(e)],'uncertainty_facts':facts,'resolved_artifacts':resolved}
    except Exception as e: result={'status':'ERROR','errors':[f'{type(e).__name__}: {e}'],'unsupported_evidence':unsupported,'uncertainty_facts':facts,'resolved_artifacts':resolved}
    if output:
        out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+'\n')
    return result

def _trusted_spce_charge_scale(checkpoint:Path)->float:
    """Validate exact nominal or native-float32 SPC/E charge representation."""
    with np.load(checkpoint,allow_pickle=False) as z:
        if 'native_charges' not in z.files: raise NotImplementedError('trusted checkpoint does not retain native per-atom charges')
        q=np.asarray(z['native_charges'],float).reshape(-1)
    if q.size==0 or q.size%3 or not np.all(np.isfinite(q)):
        raise NotImplementedError('trusted checkpoint SPC/E charge vector is malformed')
    nominal=np.tile(np.asarray([-.8476,.4238,.4238],float),q.size//3)
    f32=nominal.astype(np.float32).astype(float)
    if np.array_equal(q,nominal): return 1.0
    if np.array_equal(q,f32):
        ratios=nominal/q
        if not np.allclose(ratios,ratios[0],rtol=0,atol=1e-12): raise NotImplementedError('TPR charge rounding is not one uniform nominal SPC/E representation')
        return float(ratios[0])
    raise NotImplementedError('trusted native charges are neither nominal SPC/E nor its exact float32 representation')

def audit_candidate_reextracted_uncertainty(root:Path,trusted_checkpoint:Path,reextract_json:Path,output:Path|None=None)->dict:
    """Require one globally consistent native or nominal SPC/E uncertainty branch."""
    root=Path(root).resolve(); cp=Path(trusted_checkpoint).resolve()
    try:
        ratio=_trusted_spce_charge_scale(cp)
        native=json.loads(Path(reextract_json).read_text())
        declared=native.get('nominal_charge_scale')
        if declared is None or not math.isclose(float(declared),ratio,rel_tol=0,abs_tol=1e-12):
            raise ValueError('trusted re-extraction charge representation does not match checkpoint charges')
        branches=['native']+(['nominal'] if ratio!=1.0 else [])
        results={name:_audit_candidate_reextracted_branch(root,cp,reextract_json,None,name) for name in branches}
        passing=[name for name,r in results.items() if r.get('status')=='PASS']
        if passing:
            chosen=passing[0]
            result=dict(results[chosen]); result['uncertainty_facts']=dict(result.get('uncertainty_facts',{}))
            result['uncertainty_facts'].update({'charge_branch_selection':'one globally consistent branch matched all claims','charge_branch_statuses':{k:v.get('status') for k,v in results.items()},'charge_branch_candidates':branches})
        elif any(r.get('status')=='UNSUPPORTED_EVIDENCE' for r in results.values()):
            result={'status':'UNSUPPORTED_EVIDENCE','errors':[],'unsupported_evidence':['no supported global charge branch could audit all declared uncertainty claims'],'uncertainty_facts':{'charge_branch_statuses':{k:v.get('status') for k,v in results.items()},'charge_branch_details':{k:{'errors':v.get('errors',[]),'unsupported_evidence':v.get('unsupported_evidence',[])} for k,v in results.items()}},'resolved_artifacts':{}}
        elif any(r.get('status')=='ERROR' for r in results.values()):
            result={'status':'ERROR','errors':['uncertainty branch audit encountered an evaluator error'],'unsupported_evidence':[],'uncertainty_facts':{'charge_branch_statuses':{k:v.get('status') for k,v in results.items()}},'resolved_artifacts':{}}
        else:
            result={'status':'FAIL','errors':['uncertainty claims match neither globally consistent native-float32 nor nominal SPC/E charge reconstruction'],'unsupported_evidence':[],'uncertainty_facts':{'charge_branch_statuses':{k:v.get('status') for k,v in results.items()},'charge_branch_errors':{k:v.get('errors',[]) for k,v in results.items()}},'resolved_artifacts':{}}
    except NotImplementedError as e:
        result={'status':'UNSUPPORTED_EVIDENCE','errors':[],'unsupported_evidence':[str(e)],'uncertainty_facts':{},'resolved_artifacts':{}}
    except Exception as e:
        result={'status':'ERROR','errors':[f'{type(e).__name__}: {e}'],'unsupported_evidence':[],'uncertainty_facts':{},'resolved_artifacts':{}}
    if output:
        out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('submission',type=Path); ap.add_argument('--trusted-checkpoint',type=Path,required=True); ap.add_argument('--trusted-native-json',type=Path,required=True); ap.add_argument('--output',type=Path)
    a=ap.parse_args(); r=audit_uncertainty(a.submission,a.trusted_checkpoint,a.trusted_native_json,a.output); print(json.dumps(r,indent=2)); raise SystemExit(0 if r['status']=='PASS' else 2)
