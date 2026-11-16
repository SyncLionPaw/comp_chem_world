#!/usr/bin/env python3
"""Fair D03 verifier draft: replay all reported numeric outputs against public data.

This draft deliberately keeps only public numeric criteria machine-enforced.
Protocol description, provenance scope narrative, uncertainty interpretation and
sampling decision remain visible to the host scientific reviewer.
"""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
import numpy as np

REF = None
ASSET = None
TRUSTED_PUBLIC_SHA = None
def configure_trusted_paths(ref_path=None, source_path=None, submission_root=None):
    global REF, ASSET, TRUSTED_PUBLIC_SHA
    here=Path(__file__).resolve().parent
    candidates=[Path(ref_path)] if ref_path else [here/'refs.json', Path.cwd()/'tests/refs.json', Path.cwd()/'refs.json']
    candidates += [Path('/tests/refs.json')]
    rp=next((p for p in candidates if p.is_file() and not p.is_symlink()),None)
    if rp is None: raise TrustedInputError('trusted refs.json is missing')
    try: REF=json.loads(rp.read_text(encoding='utf-8'))
    except Exception as e: raise TrustedInputError(f'trusted refs.json cannot be decoded: {e}') from e
    src=REF.get('source') if isinstance(REF,dict) else None
    rel=src.get('path') if isinstance(src,dict) else None
    TRUSTED_PUBLIC_SHA=src.get('public_input_sha256') if isinstance(src,dict) else None
    if not isinstance(rel,str):
        # D07's public refs use source_hashes rather than the D03 refs schema.
        hashes=REF.get('source_hashes') if isinstance(REF,dict) else None
        if isinstance(hashes,dict):
            rel=next((k for k in ('environment/assets/g4-native-traces.npz','environment/assets/g4-thermodynamic-records.npz') if k in hashes),None)
            if rel: TRUSTED_PUBLIC_SHA=hashes[rel]
    if not isinstance(rel,str) or not isinstance(TRUSTED_PUBLIC_SHA,str): raise TrustedInputError('trusted refs lack a pinned thermodynamic NPZ path/hash')
    candidates=[Path(source_path)] if source_path else ([Path(submission_root)/rel] if submission_root else [])+[Path.cwd()/rel, rp.parent.parent/rel, Path('/app')/rel]
    ap=next((p for p in candidates if p.is_file() and not p.is_symlink()),None)
    if ap is None: raise TrustedInputError('trusted public NPZ is missing')
    ASSET=ap
KB, TEMP, KCAL = 0.00831446261815324, 300.0, 4.184

class CandidateFail(ValueError): pass
class TrustedInputError(RuntimeError): pass
class UnsupportedSensitivity(CandidateFail): pass

def bad(msg): raise CandidateFail(msg)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def number(x,label):
    if isinstance(x,bool): bad(f'{label}: boolean is not numeric')
    try: v=float(x)
    except (TypeError,ValueError): bad(f'{label}: not numeric')
    if not math.isfinite(v): bad(f'{label}: nonfinite')
    return v
def match(got,want,tol,label):
    g=number(got,label)
    if not math.isclose(g,float(want),rel_tol=0,abs_tol=tol): bad(f'{label}: {g} differs from recomputed {want} by > {tol}')
def load_source(path=None):
    path=ASSET if path is None else path
    if path is None or not path.is_file() or path.is_symlink(): raise TrustedInputError('trusted public NPZ missing/unsafe')
    expected=TRUSTED_PUBLIC_SHA
    if sha(path)!=expected: raise TrustedInputError('trusted public NPZ SHA-256 mismatch')
    try:
        with np.load(path,allow_pickle=False) as z:
            d={k:np.asarray(z[k],dtype=np.float64) for k in z.files}
    except Exception as e: raise TrustedInputError(f'trusted NPZ decode failure: {e}') from e
    need={'time_ps','cyl_z_nm','bias_kJ_mol','funnelwall_bias_kJ_mol'}
    if not need.issubset(d): raise TrustedInputError('trusted NPZ lacks required arrays')
    n=len(d['time_ps'])
    if any(len(v)!=n or not np.isfinite(v).all() for v in d.values()): raise TrustedInputError('trusted NPZ arrays malformed')
    if not np.all(np.diff(d['time_ps'])>0): raise TrustedInputError('trusted NPZ time is not strictly increasing')
    return d

def reweight(d,burn=20000.0,bins=72,window=None,edge='histogram',block_weight_scope='wall',block_origin='first_postburn'):
    """One coherent method choice. edge=histogram, floor, or floor_width; block weights use
    postburn wall-eligible rows or their z-histogram subset. The FES itself always
    uses the public wall and z ranges. Public docs do not define these numerical
    tie/weight-population details, so all reasonable combinations are replayed.
    """
    if type(bins) is not int or not 1<=bins<=144: bad('bin count outside public resource cap')
    t,x,bias,wall=(d[k] for k in ('time_ps','cyl_z_nm','bias_kJ_mol','funnelwall_bias_kJ_mol'))
    post=t>=burn
    if window is not None:
        lo,hi=window
        if not (0<=lo<hi<=t[-1]): bad('sensitivity window outside source interval')
        post &= (t>=lo)&(t<=hi)
    wallmask=post&(wall<=10.0)
    hmask=wallmask&(x>=0.0)&(x<1.8)
    if not hmask.any(): bad('no records in public histogram range')
    beta=1/(KB*TEMP); edges=np.linspace(0.,1.8,bins+1); centers=(edges[:-1]+edges[1:])/2
    def fes(mask):
        xx=x[mask]; ww=np.exp(beta*bias[mask]-float(np.max(beta*bias[mask])))
        if edge=='histogram': hist,_=np.histogram(xx,bins=edges,weights=ww)
        elif edge=='floor':
            ix=np.floor((xx/1.8)*bins).astype(np.int64); ix=np.clip(ix,0,bins-1)
            hist=np.bincount(ix,weights=ww,minlength=bins)
        elif edge=='floor_width':
            ix=np.floor(xx/(1.8/bins)).astype(np.int64); ix=np.clip(ix,0,bins-1)
            hist=np.bincount(ix,weights=ww,minlength=bins)
        else: raise ValueError(edge)
        probs=hist/hist.sum(); free=np.full(bins,np.nan)
        occupied=probs>0; free[occupied]=-np.log(probs[occupied])/beta; free[occupied]-=np.min(free[occupied])
        unbound=(centers>=1.5)&(centers<1.8); bound=(centers>=.3)&(centers<.8)
        if not unbound.any() or not occupied[unbound].all(): raise UnsupportedSensitivity('required unbound bins are empty')
        if not (bound & occupied).any(): raise UnsupportedSensitivity('no occupied bound bins support the integral')
        wu=float(free[unbound].mean()); dz=1.8/bins
        integral=(1/1.660)*math.pi*.2**2*float(np.nansum(dz*np.exp(-beta*(free[bound]-wu))))
        dg=-math.log(integral)/beta
        return probs,free,dg
    probs,free,dg=fes(hmask)
    # Elapsed-time equal blocks: public method names five post-burn intervals;
    # origin at first acquired post-burn point or requested burn time are both
    # reasonable when the protocol does not define the convention.
    t0=(float(t[post][0]) if block_origin=='first_postburn' else (float(max(burn,window[0])) if block_origin=='analysis_start' and window is not None else float(burn)))
    t1=float(min(t[-1],window[1])) if window is not None else float(t[-1]); block_edges=np.linspace(t0,t1,6)
    bmask=wallmask if block_weight_scope=='wall' else hmask
    blocks=[]
    for i in range(5):
        interval=(t>=block_edges[i])&((t<=block_edges[i+1]) if i==4 else (t<block_edges[i+1]))
        wm=bmask&interval; fm=hmask&interval
        if not wm.any() or not fm.any(): bad('empty time block under selected public analysis')
        _,_,b_dg=fes(fm)
        raw=bias[wm]*beta; m=float(raw.max()); scaled=float(np.exp(raw-m).sum())
        observed_start=float(t[wm][0]); observed_end=float(t[wm][-1])
        blocks.append({'block':i,'time_start_ps':float(block_edges[i]),'time_end_ps':float(block_edges[i+1]),
                       'eligible_rows':int(wm.sum()),'weight_sum_scaled':scaled,'max_log_weight':m,
                       '_observed_time_start_ps':observed_start,'_observed_time_end_ps':observed_end,
                       'deltaG_kJ_mol':b_dg,'deltaG_kcal_mol':b_dg/KCAL})
    maxlog=max(q['max_log_weight'] for q in blocks)
    bw=np.array([q['weight_sum_scaled']*math.exp(q['max_log_weight']-maxlog) for q in blocks]); vals=np.array([q['deltaG_kcal_mol'] for q in blocks])
    p=bw/bw.sum(); mean=float((p*vals).sum()); neff=float(1/(p*p).sum()); sd=math.sqrt(float((p*(vals-mean)**2).sum())*neff/(neff-1)); se=sd/math.sqrt(neff)
    weights=np.exp(beta*bias[wallmask]-float(np.max(beta*bias[wallmask]))); fess=float(weights.sum()**2/np.sum(weights*weights))
    return {'centers':centers,'probabilities':probs,'F_kJ':free,'deltaG_kJ':dg,'deltaG_kcal':dg/KCAL,'blocks':blocks,
            'block_mean_kcal':mean,'block_ess':neff,'block_sd_kcal':sd,'block_formal_se_kcal':se,'frame_ess':fess,
            'rows_after_burn_in':int(post.sum()),'rows_after_burn_and_wall':int(wallmask.sum()),'rows_hist':int(hmask.sum()),
            'method':{'bin_edge_assignment':edge,'block_weight_population':block_weight_scope,'block_time_origin':block_origin}}

def weight_effective_sample_sizes(d,burn,window,block_weight_scope,block_origin):
    """Recompute ESS fields that remain meaningful when a window FES is unsupported."""
    t=d['time_ps']; bias=d['bias_kJ_mol']; wall=d['funnelwall_bias_kJ_mol']
    post=t>=burn
    if window is not None: post &= (t>=window[0])&(t<=window[1])
    wallmask=post&(wall<=10.0)
    hmask=wallmask&(d['cyl_z_nm']>=0.0)&(d['cyl_z_nm']<1.8)
    if not wallmask.any(): bad('unsupported sensitivity has no wall-eligible rows for frame ESS')
    beta=1/(KB*TEMP)
    weights=np.exp(beta*bias[wallmask]-float(np.max(beta*bias[wallmask])))
    frame_ess=float(weights.sum()**2/np.sum(weights*weights))
    t0=(float(t[post][0]) if block_origin=='first_postburn' else
        (float(max(burn,window[0])) if block_origin=='analysis_start' and window is not None else float(burn)))
    t1=float(min(t[-1],window[1])) if window is not None else float(t[-1])
    edges=np.linspace(t0,t1,6); bmask=wallmask if block_weight_scope=='wall' else hmask
    block_weights=[]
    for i in range(5):
        interval=(t>=edges[i])&((t<=edges[i+1]) if i==4 else (t<edges[i+1]))
        selected=bmask&interval
        if not selected.any() or not (hmask&interval).any():
            bad('unsupported sensitivity has an empty time block under the selected analysis')
        logw=beta*bias[selected]; maximum=float(logw.max())
        block_weights.append((float(np.exp(logw-maximum).sum()),maximum))
    maximum=max(value[1] for value in block_weights)
    scaled=np.asarray([weight*math.exp(logmax-maximum) for weight,logmax in block_weights])
    probabilities=scaled/scaled.sum()
    return {'frame_ess':frame_ess,'block_ess':float(1/(probabilities*probabilities).sum())}

def recompute(npz_path, burn_ps, bins=72, window=None):
    """Compatibility API for the D07 cross-case numeric verifier.

    Until D07 itself adopts a method-neutral dispatch, preserve its trusted
    historical reference convention: floor assignment, wall-filtered block
    weights, first-postburn block origin. The D03 fair matcher separately
    enumerates the finite methods that are not specified by D03's public text.
    """
    if REF is None or ASSET is None: configure_trusted_paths(source_path=npz_path)
    d=load_source(Path(npz_path))
    return reweight(d,burn_ps,bins,window,edge='floor',block_weight_scope='wall',block_origin='first_postburn')

def try_matching_modes(d,sub):
    """Require all baseline artifact numbers to match one coherent method tuple."""
    fesrows=list(csv.DictReader((sub/'FES.csv').open(newline='',encoding='utf-8')))
    blockrows=list(csv.DictReader((sub/'blocks.csv').open(newline='',encoding='utf-8')))
    if len(fesrows)!=72 or len(blockrows)!=5: bad('baseline FES must contain 72 bins and blocks.csv five rows')
    therm=json.loads((sub/'thermodynamics.json').read_text())
    if not isinstance(therm,dict): bad('thermodynamics.json must be an object')
    tc=therm.get('thermodynamics')
    if not isinstance(tc,dict): bad('thermodynamics.thermodynamics object missing')
    matches=[]; failures=[]
    for edge in ('histogram','floor','floor_width'):
      for scope in ('wall','histogram'):
       for origin in ('first_postburn','burn_time'):
        try: r=reweight(d,edge=edge,block_weight_scope=scope,block_origin=origin)
        except (CandidateFail,ValueError,OverflowError,ZeroDivisionError): continue
        for weight_scale in ('local','global'):
         for time_representation in ('interval_edges','observed_eligible'):
          try:
            for i,(row,c,p,f) in enumerate(zip(fesrows,r['centers'],r['probabilities'],r['F_kJ'])):
              match(row.get('z_nm'),c,1e-12,f'z_nm[{i}]'); match(row.get('probability'),p,1e-8,f'FES probability[{i}]')
              for col,want in [('F_kJ_mol',f),('F_kcal_mol',f/KCAL if math.isfinite(f) else math.nan)]:
                val=(row.get(col) or '').strip()
                if math.isfinite(want): match(val,want,1e-4,f'FES {col}[{i}]')
                elif val: bad(f'FES {col}[{i}] must be blank for empty bin')
            # Public tolerance for thermodynamic scalar fields is 1e-6 kcal/kJ in their units.
            for k,w,tol in [('deltaG_kcal_mol',r['deltaG_kcal'],1e-6),('deltaG_kJ_mol',r['deltaG_kJ'],1e-6),
              ('weighted_block_mean_kcal_mol',r['block_mean_kcal'],1e-6),('weighted_block_mean_kJ_mol',r['block_mean_kcal']*KCAL,1e-6),
              ('weighted_block_sd_kcal_mol',r['block_sd_kcal'],1e-6),('weighted_block_formal_se_kcal_mol',r['block_formal_se_kcal'],1e-6),
              ('frame_effective_sample_size',r['frame_ess'],1e-6),('block_effective_sample_size',r['block_ess'],1e-6)]: match(tc.get(k),w,tol,k)
            block_ids=[number(row.get('block'),f'block id[{i}]') for i,row in enumerate(blockrows)]
            if block_ids not in ([0.,1.,2.,3.,4.],[1.,2.,3.,4.,5.]): bad('block IDs must be sequential and zero- or one-based')
            max_log_weight=max(q['max_log_weight'] for q in r['blocks'])
            for i,(row,want) in enumerate(zip(blockrows,r['blocks'])):
              expected_sum=want['weight_sum_scaled']
              if weight_scale=='global': expected_sum*=math.exp(want['max_log_weight']-max_log_weight)
              if time_representation=='interval_edges':
                time_start,time_end=want['time_start_ps'],want['time_end_ps']
              else:
                time_start,time_end=want['_observed_time_start_ps'],want['_observed_time_end_ps']
              match(row.get('time_start_ps'),time_start,1e-6,f'block {i} time_start_ps ({time_representation})')
              match(row.get('time_end_ps'),time_end,1e-6,f'block {i} time_end_ps ({time_representation})')
              for k,tol in [('eligible_rows',0),('max_log_weight',1e-8),('deltaG_kJ_mol',1e-5),('deltaG_kcal_mol',1e-5)]: match(row.get(k),want[k],tol,f'block {i} {k}')
              match(row.get('weight_sum_scaled'),expected_sum,1e-6,f'block {i} weight_sum_scaled ({weight_scale}-scaled)')
            matches.append(r)
          except (CandidateFail,ValueError,OverflowError,ZeroDivisionError) as exc:
            failures.append(f'edge={edge}, population={scope}, origin={origin}, weight_scale={weight_scale}, time={time_representation}: {exc}')
    if not matches:
        bad('baseline outputs are not self-consistent with a supported public analysis method. '+'; '.join(failures))
    return matches

def replay_sensitivities(d,sens,chosen):
    verified=[]; alternatives=0
    for j,row in enumerate(sens):
      choice=(row.get('changed_choice') or '').strip().lower(); unit=(row.get('parameter_unit') or '').strip().lower()
      variant=(row.get('variant') or '').strip().lower()
      burn=20000.0; bins=72; window=None
      if variant in ('baseline','reference') or choice in ('baseline','reference'):
        # A reference row is a comparison point, not a changed sensitivity.
        # Recompute it explicitly and still require at least one distinct row below.
        if unit=='ps':
          parameter=number(row.get('parameter_value'),f'reference parameter[{j}]')
          if not math.isclose(parameter,20000.0,rel_tol=0,abs_tol=1e-12): bad(f'sensitivity reference row {j} must use the 20000 ps baseline')
        elif unit=='bins':
          parameter=number(row.get('parameter_value'),f'reference bins[{j}]')
          if parameter!=72: bad(f'sensitivity reference row {j} must use the 72-bin baseline')
        else: bad(f'sensitivity reference row {j} must declare baseline bins or ps')
        start=(row.get('window_start_ps') or '').strip(); end=(row.get('window_end_ps') or '').strip()
        if bool(start)!=bool(end): bad(f'sensitivity reference row {j} must declare both window endpoints')
        if start:
          match(start,20000.0,1e-6,f'reference window start[{j}]')
          match(end,float(d['time_ps'][-1]),1e-6,f'reference window end[{j}]')
        if (row.get('support_status') or '').strip().lower()=='unsupported': bad(f'sensitivity reference row {j} cannot be unsupported')
        baseline=reweight(d,20000.0,72,None,chosen['bin_edge_assignment'],chosen['block_weight_population'],chosen['block_time_origin'])
        for k,v in [('deltaG_kcal_mol',baseline['deltaG_kcal']),('block_sd_kcal_mol',baseline['block_sd_kcal']),
                    ('block_formal_se_kcal_mol',baseline['block_formal_se_kcal']),('frame_ess',baseline['frame_ess']),
                    ('block_ess',baseline['block_ess'])]: match(row.get(k),v,1e-5,f'sensitivity {k}[{j}]')
        verified.append({'status':'baseline_reference','method':baseline['method'],'deltaG_kcal_mol':baseline['deltaG_kcal']})
        continue
      elif 'burn' in choice and unit=='ps':
        burn=number(row.get('parameter_value'),f'sensitivity burn[{j}]')
        alternatives += not math.isclose(burn,20000,abs_tol=1e-12)
      elif 'bin' in choice and unit=='bins':
        raw=number(row.get('parameter_value'),f'sensitivity bins[{j}]')
        if raw!=int(raw) or not 1<=int(raw)<=144: bad('sensitivity bin count must be integer <=144')
        bins=int(raw); alternatives += bins!=72
      elif 'window' in choice and unit=='ps':
        lo=number(row.get('window_start_ps'),f'window start[{j}]'); hi=number(row.get('window_end_ps'),f'window end[{j}]')
        window=(lo,hi); alternatives += not (math.isclose(lo,20000,abs_tol=1e-12) and math.isclose(hi,float(d['time_ps'][-1]),abs_tol=1e-6))
      else: bad(f'sensitivity row {j} must declare burn-in, bins, or a time window with unit')
      found=[]
      # An explicitly unsupported sensitivity cannot simultaneously publish
      # numeric values that replay as supported. Keep this contradiction a
      # deterministic candidate failure, independent of the chosen method.
      unsupported_claim=(row.get('support_status') or '').strip().lower()=='unsupported'
      if unsupported_claim:
        free_energy_values=[row.get(k,'') for k in ('deltaG_kcal_mol','block_sd_kcal_mol','block_formal_se_kcal_mol')]
        if not (row.get('unsupported_reason') or '').strip() or any(v not in ('',None) for v in free_energy_values):
          bad(f'sensitivity row {j} declares unsupported but has no reason or contains free-energy/uncertainty results')
      origins=[chosen['block_time_origin']]
      # For an explicit window, elapsed blocks may start at the requested window
      # start. This is the only additional clock convention considered.
      if window is not None and 'analysis_start' not in origins: origins.append('analysis_start')
      for origin in origins:
         try: a=reweight(d,burn,bins,window,chosen['bin_edge_assignment'],chosen['block_weight_population'],origin)
         except UnsupportedSensitivity as exc:
          if unsupported_claim and (row.get('unsupported_reason') or '').strip():
            ess=weight_effective_sample_sizes(d,burn,window,chosen['block_weight_population'],origin)
            for field in ('frame_ess','block_ess'):
             if (row.get(field) or '').strip(): match(row[field],ess[field],1e-5,f'sensitivity {field}[{j}]')
            found.append({'status':'unsupported','reason':str(exc),'method':{**chosen,'block_time_origin':origin},'effective_sample_sizes':ess}); break
          continue
         except (CandidateFail,ValueError,OverflowError,ZeroDivisionError): continue
         if unsupported_claim: bad(f'sensitivity row {j} declares unsupported but an independently recomputed analysis is supported')
         try:
          for k,v in [('deltaG_kcal_mol',a['deltaG_kcal']),('block_sd_kcal_mol',a['block_sd_kcal']),('block_formal_se_kcal_mol',a['block_formal_se_kcal']),('frame_ess',a['frame_ess']),('block_ess',a['block_ess'])]: match(row.get(k),v,1e-5,f'sensitivity {k}[{j}]')
          found.append({'status':'supported','choice':choice,'method':a['method'],'deltaG_kcal_mol':a['deltaG_kcal']})
         except (CandidateFail,ValueError,OverflowError,ZeroDivisionError): pass
      if not found: bad(f'sensitivity row {j} does not match a supported independently recomputed method')
      verified.append(found[0])
    if alternatives<1: bad('no distinct sensitivity alternative declared')
    return verified

def check(sub):
    if REF is None or ASSET is None: configure_trusted_paths(submission_root=sub)
    d=load_source()
    need=('FES.csv','blocks.csv','thermodynamics.json','sensitivity.csv','sampling-decision.json','audit-report.md','provenance.json')
    missing=[x for x in need if not (sub/x).is_file() or (sub/x).is_symlink()]
    if missing: bad('missing/unsafe required outputs: '+', '.join(missing))
    methods=try_matching_modes(d,sub)
    therm=json.loads((sub/'thermodynamics.json').read_text()); source=therm.get('source',{})
    accepted_source_paths={REF['source'].get('path'),REF['source'].get('raw_source_path')}
    if source.get('path') not in accepted_source_paths or source.get('public_input_sha256')!=REF['source']['public_input_sha256'] or source.get('raw_source_sha256')!=REF['source']['raw_source_sha256']:
        bad('thermodynamic source path/hash does not identify public input')
    # Sensitivity variants must preserve the same coherent numerical conventions
    # as the baseline; only their declared analysis parameter changes.
    sens=list(csv.DictReader((sub/'sensitivity.csv').open(newline='',encoding='utf-8')))
    if not sens: bad('sensitivity.csv has no rows')
    checked=[]
    for method in methods:
        try: checked.append((method,replay_sensitivities(d,sens,method['method'])))
        except CandidateFail: pass
    if not checked: bad('sensitivity rows do not replay under any single baseline method tuple')
    method,verified=checked[0]
    prov=json.loads((sub/'provenance.json').read_text())
    if not isinstance(prov,dict): bad('provenance.json must be an object')
    if prov.get('public_input_sha256')!=REF['source']['public_input_sha256'] or prov.get('raw_source_sha256')!=REF['source']['raw_source_sha256']:
        bad('provenance.json must identify both public NPZ and raw COLVAR hashes')
    if not (sub/'audit-report.md').read_text().strip(): bad('audit-report.md is empty')
    # Scope and uncertainty semantics are purposely not brittle hidden JSON keys;
    # assess the actual public-visible audit and decision in open scientific review.
    return {'status':'PASS_NUMERIC_RECOMPUTED','method':method['method'],'baseline_deltaG_kcal_mol':method['deltaG_kcal'],
            'baseline_block_sd_kcal_mol':method['block_sd_kcal'],'baseline_formal_se_kcal_mol':method['block_formal_se_kcal'],
            'baseline_rows':{'postburn':method['rows_after_burn_in'],'wall_eligible':method['rows_after_burn_and_wall'],'histogram':method['rows_hist']},
            'sensitivities':verified,'scope':'numerical replay passed; scope/uncertainty and sampling claims remain open host-review criteria'}

if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser(); ap.add_argument('submission',type=Path,nargs='?'); ap.add_argument('--refs',type=Path); ap.add_argument('--source',type=Path); ap.add_argument('--runner',action='store_true'); a=ap.parse_args()
 if a.runner:
  import os
  from review_status import run_case
  raise SystemExit(run_case(Path(os.environ.get('APP','/app')).resolve(),Path(os.environ.get('TESTS','/tests')).resolve(),Path(os.environ.get('LOGS','/logs/verifier')).resolve()))
 if a.submission is None: ap.error('submission is required unless --runner is used')
 try: configure_trusted_paths(a.refs,a.source); print(json.dumps(check(a.submission),indent=2))
 except TrustedInputError as e:
  print(json.dumps({'status':'INFRA','error':str(e)},indent=2)); raise SystemExit(2)
 except Exception as e:
  print(json.dumps({'status':'FAIL','error':str(e)},indent=2)); raise SystemExit(1)
