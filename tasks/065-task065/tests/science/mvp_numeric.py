"""Independent fixed-path NumPy replay for the G4 02/04/07 outputs."""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
import numpy as np
from g4_model_numpy import MODEL_IDS, forward_and_gradient, load_weights

R_KJ=0.00831446261815324; T_K=300.0; KJ_TO_KCAL=1/4.184
TABLE_SHA='8382f7bfb0356e5ee63ecb38337509a4f2df9674ae55af6fc121a5dfbf38744f'
class CandidateError(ValueError): pass
class TrustedInputError(RuntimeError): pass


def _sha(p):
    h=hashlib.sha256()
    try:
        with p.open('rb') as f:
            for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    except OSError as e: raise TrustedInputError(f'trusted input unreadable: {p}: {e}') from e
    return h.hexdigest()

def _asset(app,refs,rel):
    p=app/'environment/assets'/Path(rel)
    if p.is_symlink() or not p.is_file(): raise TrustedInputError(f'trusted input missing/unsafe: {rel}')
    pins=refs.get('source_hashes') if isinstance(refs,dict) else None
    key='environment/assets/'+str(rel)
    expected=pins.get(key) if isinstance(pins,dict) else None
    if not isinstance(expected,str) or len(expected)!=64: raise TrustedInputError(f'trusted source pin missing: {key}')
    actual=_sha(p)
    if actual!=expected: raise TrustedInputError(f'trusted input SHA mismatch: {key}')
    return p,actual

def _csv(p,expected_header=None):
    try:
        with p.open(newline='',encoding='utf-8') as f:
            r=csv.DictReader(f)
            if not r.fieldnames or len(set(r.fieldnames))!=len(r.fieldnames): raise CandidateError(f'duplicate/missing CSV header: {p.name}')
            if expected_header and r.fieldnames!=expected_header: raise CandidateError(f'{p.name} header mismatch')
            rows=list(r)
            for i,row in enumerate(rows,2):
                if None in row or any(v is None for v in row.values()):
                    raise CandidateError(f'{p.name} row {i} has overflow or missing CSV cells')
    except CandidateError: raise
    except Exception as e: raise CandidateError(f'invalid candidate CSV {p.name}: {e}') from e
    return rows

def _trusted_csv(p,expected_header=None):
    try: return _csv(p,expected_header)
    except Exception as e:
        if isinstance(e,TrustedInputError): raise
        raise TrustedInputError(f'invalid trusted CSV {p.name}: {e}') from e

def _npz(p,required):
    try:
        with np.load(p,allow_pickle=False) as z:
            if len(z.files)!=len(set(z.files)) or not set(required).issubset(z.files): raise TrustedInputError(f'trusted NPZ keys invalid: {p.name}')
            d={k:np.asarray(z[k]) for k in z.files}
    except TrustedInputError: raise
    except Exception as e: raise TrustedInputError(f'trusted NPZ decode failed: {p.name}: {e}') from e
    return d

def _number(row,key):
    try:
        v=float(row[key])
    except Exception as e: raise CandidateError(f'candidate field {key} is not numeric') from e
    if not math.isfinite(v): raise CandidateError(f'candidate field {key} is non-finite')
    return v

def _near(a,b,tol=2e-5): return abs(float(a)-float(b))<=tol+tol*max(abs(float(a)),abs(float(b)))
def _near_abs_rel(a,b,abs_tol,rel_tol):
    """Compare finite numeric claims with separately controlled absolute/relative error."""
    a=float(a); b=float(b)
    return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=abs_tol+rel_tol*abs(b)

def _summary_tolerance(field):
    # Probabilities and masses can be small; a generic 2e-5 absolute tolerance
    # would allow materially incorrect state support to be reported as zero.
    if any(token in field for token in ('normalized_weight_mass','weight_mass','bound_weight','unbound_weight','fraction','distribution.')):
        return (1e-8,1e-5)
    return None

def _check_cavity_summary_fields(analysis,cavity,w,errors,check_numeric):
    """Accept canonical weighted_states fields and legacy top-level aliases.

    If both locations are present, validate each independently against the
    source replay so disagreement (or a jointly wrong value) remains an error.
    """
    wm=analysis.get('weighted_states')
    expected_range=[int(cavity.min()),int(cavity.max())]
    expected_dist={str(n):float(w[cavity==n].sum()) for n in range(expected_range[0],expected_range[1]+1)}
    expected_mean=float(np.dot(w,cavity))
    fields=('cavity_water_count_range','cavity_occupancy_weighted_distribution','cavity_occupancy_weighted_mean')
    for name in fields:
        locations=[]
        if isinstance(wm,dict) and name in wm: locations.append(('weighted_states',wm[name]))
        if name in analysis: locations.append(('top_level',analysis[name]))
        if not locations:
            errors.append({'field':f'weighted_states.{name}','reported':'missing','recomputed':{'cavity_water_count_range':expected_range,'cavity_occupancy_weighted_distribution':expected_dist,'cavity_occupancy_weighted_mean':expected_mean}[name]})
            continue
        for location,reported in locations:
            path=f'{location}.{name}'
            if name=='cavity_water_count_range':
                # Accept either a range object or the published [min,max] form.
                normalized=reported
                if isinstance(reported,dict) and {'min','max'}.issubset(reported):
                    normalized=[reported.get('min'),reported.get('max')]
                    if 'observed_zero' in reported and reported['observed_zero'] is not (expected_range[0] <= 0 <= expected_range[1]):
                        normalized=None
                if normalized!=expected_range:
                    errors.append({'field':path,'reported':reported,'recomputed':expected_range})
            elif name=='cavity_occupancy_weighted_distribution':
                if not isinstance(reported,dict):
                    errors.append({'field':path,'reported':reported,'recomputed':expected_dist})
                    continue
                for key,value in expected_dist.items():
                    check_numeric(f'{path}.{key}',reported.get(key),value)
                if set(reported)!=set(expected_dist):
                    errors.append({'field':f'{path}.keys','reported':sorted(reported),'expected':sorted(expected_dist)})
            else:
                check_numeric(path,reported,expected_mean)

def _numeric_matches(field,reported,expected,tol=2e-5):
    if not isinstance(reported,(int,float)) or isinstance(reported,bool) or not math.isfinite(float(reported)):
        return False
    tight=_summary_tolerance(field)
    return _near_abs_rel(reported,expected,*tight) if tight else _near(reported,expected,tol)
def _corr(a,b): return float(np.corrcoef(a,b)[0,1])

def _status(criteria):
    if any(v['status']=='INFRA' for v in criteria.values()): return 'INFRA'
    if any(v['status']=='FAIL' for v in criteria.values()): return 'FAIL'
    return 'NEEDS_JUDGE'

def _result(criteria): return {'status':_status(criteria),'criteria':criteria}

def verify_case02(app_root,candidate_root,protocol,refs):
    app=Path(app_root); cand=Path(candidate_root); crit={}
    try:
        descp,_=_asset(app,refs,'g4-descriptors.csv'); weightp,wsha=_asset(app,refs,'g4-model-weights.npz'); tracep,tsha=_asset(app,refs,'g4-native-traces.npz')
        desc=_trusted_csv(descp); dhead=['frame_index','time_ps']+[f'd{i}_normalized' for i in range(1,13)]
        # Preserve the exact public header while allowing declared auxiliary columns.
        if not set(dhead).issubset(desc[0] if desc else {}): raise TrustedInputError('trusted descriptor input schema invalid')
        x=np.asarray([[float(r[f'd{i}_normalized']) for i in range(1,13)] for r in desc],dtype=np.float32)
        trace=_npz(tracep,['time_ps','node0','node1','node2','sw','swb','swc'])
        ti=np.searchsorted(trace['time_ps'],np.asarray([float(r['time_ps']) for r in desc])); ti=np.clip(ti,0,len(trace['time_ps'])-1); left=np.maximum(ti-1,0); targets=np.asarray([float(r['time_ps']) for r in desc]); ti=np.where(np.abs(trace['time_ps'][left]-targets)<np.abs(trace['time_ps'][ti]-targets),left,ti)
        if np.max(np.abs(trace['time_ps'][ti]-targets))>0.01 or len(np.unique(ti))!=len(ti): raise TrustedInputError('trusted descriptor/native trace time join invalid')
        expected={}; gradient={}; pair_fits=[]
        nat=[('node0','s_raw'),('node1','s_raw'),('node2','s_raw'),('sw','sw'),('swb','sw'),('swc','sw')]
        for mid in MODEL_IDS:
            w=load_weights(weightp,mid); s,sw,ds,dsw=forward_and_gradient(x,w,mid)
            for nc,kind in nat:
                y=np.asarray(trace[nc][ti],dtype=float); v=np.asarray(s if kind=='s_raw' else sw,dtype=float); den=np.dot(v-v.mean(),v-v.mean()); slope=float(np.dot(v-v.mean(),y-y.mean())/den) if den>0 else 0.; intercept=float(y.mean()-slope*v.mean()); res=y-(slope*v+intercept)
                corr=_corr(v,y) if np.std(v)>0 and np.std(y)>0 else 0.0
                pair_fits.append({'model_id':mid,'native_column':nc,'model_output_kind':kind,'pearson_r':corr,'slope':slope,'intercept':intercept,'rmse':float(np.sqrt(np.mean(res*res)))})
                for i,r in enumerate(desc): expected[(str(r['frame_index']),mid,nc)]=(float(s[i]),float(sw[i]),float(y[i]),float(res[i]))
            for j in range(12):
                g=np.abs(dsw[:,j]); gradient[(mid,f'd{j+1}')]=(float(np.median(g)),float(np.quantile(g,.1)),float(np.quantile(g,.9)),float(np.mean(dsw[:,j]>0)),float(np.mean(dsw[:,j]<0)),len(desc))
        output_header=['frame_index','time_ps','model_id','s_raw','sw','native_column','native_value','affine_residual']
        outrows=_csv(cand/'model-output-audit.csv',output_header); seen=set(); bad=[]
        frame_times={str(r['frame_index']):float(r['time_ps']) for r in desc}
        for r in outrows:
            k=(r['frame_index'],r['model_id'],r['native_column'])
            if k in seen or k not in expected: raise CandidateError('model-output-audit has duplicate or unsupported frame/model/column row')
            seen.add(k); e=expected[k]
            if abs(_number(r,'time_ps')-frame_times[r['frame_index']])>1e-6: bad.append({'row':k,'field':'time_ps','reported':_number(r,'time_ps'),'recomputed':frame_times[r['frame_index']]})
            for name,val in zip(('s_raw','sw','native_value','affine_residual'),e):
                if not _near(_number(r,name),val,2e-5): bad.append({'row':k,'field':name,'reported':_number(r,name),'recomputed':val})
        if seen!=set(expected): bad.append({'missing_rows':len(set(expected)-seen)})
        crit['published_model_forward_and_native_comparison']={'status':'FAIL' if bad else 'PASS','summary':'Recomputed source-pinned NumPy s/sw, affine gauge residuals, Pearson correlation, slope, intercept and RMSE for all 18 model/native output pairs over the 64-frame excerpt. These diagnostics do not assert a model-to-column identity.','checked_values':{'rows_checked':len(seen),'expected_rows':len(expected),'mismatches':bad[:20],'weights_sha256':wsha,'native_trace_sha256':tsha,'model_native_affine_diagnostics':pair_fits}}
        gh=['model_id','descriptor','median_abs_dsw_dd','p10_abs_dsw_dd','p90_abs_dsw_dd','fraction_positive','fraction_negative','n_frames']; grows=_csv(cand/'model-gradient-audit.csv',gh); gs=set(); gbad=[]
        for r in grows:
            k=(r['model_id'],r['descriptor'])
            if k in gs or k not in gradient: raise CandidateError('model-gradient-audit has duplicate or unsupported key')
            gs.add(k); vals=gradient[k]
            for name,val in zip(gh[2:],vals):
                if name=='n_frames':
                    try: got=int(r[name])
                    except Exception as e: raise CandidateError('model-gradient-audit n_frames is not an integer') from e
                    if str(got)!=r[name]: raise CandidateError('model-gradient-audit n_frames must be an exact integer')
                else: got=_number(r,name)
                if not _near(got,val,2e-5): gbad.append({'key':k,'field':name,'reported':got,'recomputed':val})
        if gs!=set(gradient): gbad.append({'missing_rows':len(set(gradient)-gs)})
        crit['descriptor_gradient_statistics']={'status':'FAIL' if gbad else 'PASS','summary':'Recomputed descriptor-level gradients and summaries; these are local sensitivities, not coordinate forces or causal feature importance.','checked_values':{'rows_checked':len(gs),'expected_rows':len(gradient),'mismatches':gbad[:20]}}
    except TrustedInputError as e:
        return {'status':'INFRA','criteria':crit,'error':str(e)}
    except CandidateError as e:
        return {'status':'FAIL','criteria':crit,'error':str(e)}
    except Exception as e: return {'status':'INFRA','criteria':crit,'error':f'trusted Case02 replay error: {e}'}
    return _result(crit)


# Strict complete state/budget replay replaces the initial bounded draft above.
def verify_case04(app_root,candidate_root,protocol,refs):
    app=Path(app_root); cand=Path(candidate_root); crit={}
    try:
        tablep,h=_asset(app,refs,'g4-trajectory-observables.csv'); rows=_trusted_csv(tablep)
        if _sha(tablep)!=TABLE_SHA or len(rows)!=8834: raise TrustedInputError('pinned full trajectory table identity/count mismatch')
        t=np.asarray([float(r['time_ps']) for r in rows]); z=np.asarray([float(r['native_cyl_z_nm']) for r in rows]); rad=np.asarray([float(r['native_radius_nm']) for r in rows]); bias=np.asarray([float(r['opes_bias_kJ_mol']) for r in rows]); cavity=np.asarray([int(r['cavity_water_count_r045_z0_1p75']) for r in rows]); bridges=np.asarray([int(r['water_bridge_count']) for r in rows]); delta=np.asarray([float(r['native_colvar_time_delta_ps']) for r in rows])
        beta=1/(R_KJ*T_K); logw=beta*bias; logw-=float(logw.max()); w=np.exp(logw);w/=w.sum(); bound=(z<.8)&(rad<=.45);unbound=(z>=1.25)&(rad<=.45); intermediate=~(bound|unbound)
        frame_header=['frame_index','time_ps','native_colvar_time_delta_ps','native_cyl_z_nm','native_radius_nm','opes_bias_kJ_mol','opes_rct_kJ_mol','cavity_water_count_r045_z0_1p75','water_bridge_count','log_weight','normalized_weight','state']
        got=_csv(cand/'state-frames.csv',frame_header); mism=[]; expectedids=set(range(len(rows)));seen=set()
        if len(got)!=len(rows): mism.append({'row_count':len(got),'expected':len(rows)})
        for r in got:
            try:i=int(r['frame_index'])
            except Exception as e: raise CandidateError('state-frames frame_index invalid') from e
            if str(i)!=r['frame_index'] or i not in expectedids or i in seen: raise CandidateError('state-frames IDs must be unique exact integer source indices')
            seen.add(i); src=rows[i]
            # Time axes require absolute tolerance; relative tolerance would admit a half-cadence error at late times.
            for key in ('time_ps','native_colvar_time_delta_ps'):
                if abs(_number(r,key)-float(src[key]))>1e-6:mism.append({'frame':i,'field':key,'reported':_number(r,key),'source':float(src[key])})
            for key in ('native_cyl_z_nm','native_radius_nm','opes_bias_kJ_mol','opes_rct_kJ_mol'):
                if not _near(_number(r,key),float(src[key]),2e-6):mism.append({'frame':i,'field':key,'reported':_number(r,key),'source':float(src[key])})
            for key in ('cavity_water_count_r045_z0_1p75','water_bridge_count'):
                try:v=int(r[key])
                except Exception as e:raise CandidateError(f'{key} must be an integer') from e
                if str(v)!=r[key] or v!=int(src[key]):mism.append({'frame':i,'field':key,'reported':v,'source':int(src[key])})
            if not _near(_number(r,'log_weight'),float(logw[i]),2e-6):mism.append({'frame':i,'field':'log_weight','reported':_number(r,'log_weight'),'recomputed':float(logw[i])})
            if not _near_abs_rel(_number(r,'normalized_weight'),float(w[i]),1e-10,1e-5):mism.append({'frame':i,'field':'normalized_weight','reported':_number(r,'normalized_weight'),'recomputed':float(w[i])})
            state='bound_like' if bound[i] else ('unbound_like' if unbound[i] else 'intermediate')
            if r['state']!=state:mism.append({'frame':i,'field':'state','reported':r['state'],'recomputed':state})
        if seen!=expectedids:mism.append({'missing_frame_count':len(expectedids-seen)})
        time_abs=np.abs(delta)
        crit['full_frame_join_and_OPES_weights']={'status':'FAIL' if mism else 'PASS','summary':'Recomputed every source frame, strict absolute time match, fixed native-CV masks and instantaneous-bias weights.','checked_values':{'source_rows':len(rows),'candidate_rows':len(got),'unique_candidate_frames':len(seen),'max_time_delta_ps':float(time_abs.max()),'p95_time_delta_ps':float(np.quantile(time_abs,.95)),'global_ESS':float(1/np.sum(w*w)),'source_sha256':h,'mismatches':mism[:20]}}
        def summary(mask,ww=w):
            mass=float(ww[mask].sum()); ss=float(np.sum(ww[mask]**2)); ess=float(mass*mass/ss) if ss else 0.0
            return {'frame_count':int(mask.sum()),'normalized_weight_mass':mass,'conditional_weighted_cavity_count_mean':float(np.dot(ww[mask],cavity[mask])/mass) if mass else None,'conditional_weighted_bridge_frame_fraction':float(ww[mask&(bridges>0)].sum()/mass) if mass else None,'effective_sample_size':ess}
        analysis_path=cand/'state-analysis.json'
        try:analysis=json.loads(analysis_path.read_text(encoding='utf-8'))
        except Exception as e:raise CandidateError(f'state-analysis.json malformed: {e}') from e
        if not isinstance(analysis,dict):raise CandidateError('state-analysis.json must be an object')
        errors=[]
        def check_numeric(path,reported,expected,tol=2e-5):
            if isinstance(expected,bool):
                if reported is not expected: errors.append({'field':path,'reported':reported,'recomputed':expected})
            elif isinstance(expected,float) or isinstance(expected,int):
                if not _numeric_matches(path,reported,expected,tol): errors.append({'field':path,'reported':reported,'recomputed':expected})
            elif reported!=expected:errors.append({'field':path,'reported':reported,'recomputed':expected})
        join=analysis.get('join_counts')
        if not isinstance(join,dict):errors.append({'field':'join_counts','reported':'missing'})
        else:
            for k,v in {'matched_frames':8834,'unmatched_frames':0,'unique_time_join':True,'tolerance_ps':.01}.items():check_numeric('join_counts.'+k,join.get(k),v,1e-6)
            check_numeric('join_counts.max_abs_delta_ps',join.get('max_abs_delta_ps'),float(time_abs.max()),1e-6)
            check_numeric('join_counts.p95_abs_delta_ps',join.get('p95_abs_delta_ps'),float(np.quantile(time_abs,.95)),1e-6)
        wm=analysis.get('weighted_states');
        if not isinstance(wm,dict):errors.append({'field':'weighted_states','reported':'missing'})
        else:
            for name,mask in [('bound_like',bound),('unbound_like',unbound),('intermediate',intermediate)]:
                rep=wm.get(name)
                if not isinstance(rep,dict):errors.append({'field':'weighted_states.'+name,'reported':'missing'});continue
                ex=summary(mask)
                for k,v in ex.items():check_numeric(f'weighted_states.{name}.{k}',rep.get(k),v)
            _check_cavity_summary_fields(analysis,cavity,w,errors,check_numeric)
        essobj=analysis.get('ESS')
        ex_ess={'all_frames':float(1/np.sum(w*w)),'bound_like':summary(bound)['effective_sample_size'],'unbound_like':summary(unbound)['effective_sample_size']}
        if not isinstance(essobj,dict):errors.append({'field':'ESS','reported':'missing'})
        else:
            for k,v in ex_ess.items():check_numeric('ESS.'+k,essobj.get(k),v)
        sensitivity=analysis.get('sensitivity'); expected_sens=[]
        for burn in (0.,20000.,40000.):
            m=t>=burn; lw=logw[m]; ww=np.exp(lw-lw.max());ww/=ww.sum(); expected_sens.append({'burn_in_ps':burn,'frame_count':int(m.sum()),'weight_ess':float(1/np.sum(ww*ww)),'bound_like_weight_mass':float(ww[bound[m]].sum()),'unbound_like_weight_mass':float(ww[unbound[m]].sum()),'weighted_cavity_count_mean':float(np.dot(ww,cavity[m])),'weighted_bridge_frame_fraction':float(ww[bridges[m]>0].sum())})
        if not isinstance(sensitivity,list) or len(sensitivity)!=3:errors.append({'field':'sensitivity','reported':'missing/wrong row count'})
        else:
            for i,(rep,exp) in enumerate(zip(sensitivity,expected_sens)):
                if not isinstance(rep,dict):errors.append({'field':f'sensitivity[{i}]','reported':'not object'});continue
                for k,v in exp.items():check_numeric(f'sensitivity[{i}].{k}',rep.get(k),v)
        crit['state_analysis_scope_and_summary']={'status':'FAIL' if errors else 'JUDGE_REQUIRED','summary':'Recomputed each reported per-state mass/count mean/bridge fraction/ESS, cavity occupancy distribution, and burn-in sensitivity; restrained-ensemble interpretation remains open for scientific review.','checked_values':{'errors':errors[:50],'cavity_count_min_max':[int(cavity.min()),int(cavity.max())],'occupancy_distribution_bins':int(cavity.max()-cavity.min()+1) if isinstance(wm,dict) else 0}}
        # Public block weights may be normalized independently within each block.
        # Honor that explicit declaration; keep every original numerical tolerance.
        weighting_method=analysis.get('weighting_method',{})
        window_description=weighting_method.get('windows','') if isinstance(weighting_method,dict) else ''
        block_local=isinstance(window_description,str) and 'each block independently normalized' in window_description.casefold()
        bh=['block_index','time_start_ps','time_end_ps','frame_count','effective_sample_size','bound_weight','unbound_weight','deltaG_kcal_mol']; br=_csv(cand/'state-blocks.csv',bh); berrors=[]
        expected_starts=np.arange(0.,float(t[-1])+1.,4000.); seen_blocks=[]
        if len(br)!=len(expected_starts):berrors.append({'field':'row_count','reported':len(br),'expected':len(expected_starts)})
        for bi,(r,start) in enumerate(zip(br,expected_starts)):
            try:idx=int(r['block_index'])
            except Exception as e:raise CandidateError('block_index must be integer') from e
            if str(idx)!=r['block_index'] or idx!=bi:berrors.append({'block':bi,'field':'block_index','reported':r['block_index']})
            end=min(start+4000.,float(t[-1])+1.);m=(t>=start)&(t<end);seen_blocks.extend(np.flatnonzero(m).tolist());ww=w[m];ess=float(ww.sum()**2/np.dot(ww,ww));pb=float(w[m&bound].sum());pu=float(w[m&unbound].sum());dg=-R_KJ*T_K*math.log(pb/pu)*KJ_TO_KCAL if pb>0 and pu>0 else None
            if block_local:
                block_mass=float(ww.sum())
                if block_mass<=0:raise CandidateError('block-local weights have zero total mass')
                pb/=block_mass;pu/=block_mass
            for k,v in [('time_start_ps',start),('time_end_ps',end)]:
                if abs(_number(r,k)-v)>1e-6:berrors.append({'block':bi,'field':k,'reported':_number(r,k),'expected':v})
            for k,v in [('frame_count',int(m.sum())),('effective_sample_size',ess),('bound_weight',pb),('unbound_weight',pu)]:
                if k=='frame_count':
                    try:got=int(r[k])
                    except Exception as e:raise CandidateError('block frame_count must be integer') from e
                    if str(got)!=r[k] or got!=v:berrors.append({'block':bi,'field':k,'reported':r[k],'expected':v})
                elif not _numeric_matches(k,_number(r,k),v):berrors.append({'block':bi,'field':k,'reported':_number(r,k),'expected':v})
            field=r['deltaG_kcal_mol']
            if dg is None:
                if field!='':berrors.append({'block':bi,'field':'deltaG_kcal_mol','reported':field,'expected':'blank'})
            elif not _near(_number(r,'deltaG_kcal_mol'),dg,2e-5):berrors.append({'block':bi,'field':'deltaG_kcal_mol','reported':_number(r,'deltaG_kcal_mol'),'expected':dg})
        if len(seen_blocks)!=len(rows) or sorted(seen_blocks)!=list(range(len(rows))):berrors.append({'field':'coverage','frame_occurrences':len(seen_blocks),'unique':len(set(seen_blocks)),'expected':len(rows)})
        crit['contiguous_block_statistics']={'status':'FAIL' if berrors else 'PASS','summary':'Recomputed exact 45-window contiguous coverage, IDs, endpoints, frame counts, ESS, bound/unbound masses and restrained log-mass ratios.','checked_values':{'blocks':len(br),'expected_blocks':len(expected_starts),'weight_normalization':'per_block' if block_local else 'global','mismatches':berrors[:50]}}
    except TrustedInputError as e:return {'status':'INFRA','criteria':crit,'error':str(e)}
    except CandidateError as e:return {'status':'FAIL','criteria':crit,'error':str(e)}
    except Exception as e:return {'status':'INFRA','criteria':crit,'error':f'trusted Case04 replay error: {e}'}
    return _result(crit)


def _thermo_replay(data,burn,bins=72):
    time=np.asarray(data['time_ps'],float);z=np.asarray(data['cyl_z_nm'],float);bias=np.asarray(data['bias_kJ_mol'],float);wall=np.asarray(data['funnelwall_bias_kJ_mol'],float);mask=(time>=burn)&(wall<=10)&(z>=0)&(z<1.8)
    beta=1/(R_KJ*T_K); edges=np.linspace(0,1.8,bins+1); lw=beta*bias[mask]; ww=np.exp(lw-lw.max()); hist,_=np.histogram(z[mask],bins=edges,weights=ww);prob=hist/hist.sum();cent=(edges[:-1]+edges[1:])/2;f=np.full(bins,np.inf);ok=prob>0;f[ok]=-R_KJ*T_K*np.log(prob[ok]);f[ok]-=f[ok].min();u=(cent>=1.5)&(cent<1.8);b=(cent>=.3)&(cent<.8);wu=f[u].mean();integ=float(np.sum(np.exp(-beta*(f[b]-wu))*np.diff(edges)[0]));dg=-math.log((1/1.660)*math.pi*.2**2*integ)/beta
    frame_lw=beta*bias[(time>=burn)&(wall<=10)]; fw=np.exp(frame_lw-frame_lw.max()); ess=float(fw.sum()**2/np.dot(fw,fw))
    return {'burn_in_ps':float(burn),'bins':bins,'eligible_frames':int(mask.sum()),'frame_ESS':ess,'deltaG_kcal_mol':float(dg*KJ_TO_KCAL),'empty_bins':int(np.count_nonzero(~ok)),'bound_empty_bins':int(np.count_nonzero(b&~ok)),'unbound_empty_bins':int(np.count_nonzero(u&~ok))}


def verify_case07(app_root,candidate_root,protocol,refs):
    app=Path(app_root);cand=Path(candidate_root);crit={}
    try:
        names=('g4-descriptors.csv','g4-model-weights.npz','g4-native-traces.npz','g4-trajectory-observables.csv','g4-trajectory-observables.provenance.json','g4-thermodynamic-records.npz','water-model-observations.csv')
        assets={n:_asset(app,refs,n)[0] for n in names}
        # Independently replay source-bound model outputs and trajectory weights.
        desc=_trusted_csv(assets['g4-descriptors.csv']); x=np.asarray([[float(r[f'd{i}_normalized']) for i in range(1,13)] for r in desc],np.float32); weights_path=assets['g4-model-weights.npz']; trace=_npz(assets['g4-native-traces.npz'],['time_ps','sw','swb','swc','node0','node1','node2'])
        model_grad={}
        for mid in MODEL_IDS:
            w=load_weights(weights_path,mid); s,sw,ds,dsw=forward_and_gradient(x,w,mid)
            # Case07 reports the median of the twelve per-feature medians,
            # matching the fixed Case02 model-gradient audit aggregation.
            model_grad[mid]=float(np.median([np.median(np.abs(dsw[:,j])) for j in range(12)]))
        pairs={f'{a}:{b}':float(np.corrcoef(trace[a],trace[b])[0,1]) for a,b in [('sw','swb'),('sw','swc'),('swb','swc')]}
        table=_trusted_csv(assets['g4-trajectory-observables.csv']); bias=np.asarray([float(r['opes_bias_kJ_mol']) for r in table]); beta=1/(R_KJ*T_K);lw=beta*bias;lw-=lw.max();wt=np.exp(lw);wt/=wt.sum();cavity=np.asarray([int(r['cavity_water_count_r045_z0_1p75']) for r in table]);bridge=np.asarray([int(r['water_bridge_count']) for r in table]);z=np.asarray([float(r['native_cyl_z_nm']) for r in table]);rad=np.asarray([float(r['native_radius_nm']) for r in table]);bound=(z<.8)&(rad<=.45);unbound=(z>=1.25)&(rad<=.45);states={'all_frames':float(1/np.sum(wt*wt)),'bound_weight_mass':float(wt[bound].sum()),'unbound_weight_mass':float(wt[unbound].sum()),'occupancy_weighted_mean':float(np.dot(wt,cavity)),'bridge_frame_fraction':float(wt[bridge>0].sum())}
        with np.load(assets['g4-thermodynamic-records.npz'],allow_pickle=False) as nz: thermo={k:np.asarray(nz[k]) for k in nz.files}
        th20=_thermo_replay(thermo,20000.);th30=_thermo_replay(thermo,30000.)
        _,wr=_csv(assets['water-model-observations.csv']) if False else (None,None)
        with assets['water-model-observations.csv'].open(newline='',encoding='utf-8') as f: wr=list(csv.DictReader(f))
        if len(wr)!=6:raise TrustedInputError('trusted water-model source must have 6 rows')
        exp=np.asarray([float(r['experimental_kcal_mol']) for r in wr]);water={}
        for key,col in [('TIP3P','TIP3P_mean_kcal_mol'),('TIP4P_EW','TIP4P_EW_mean_kcal_mol')]:
            err=np.asarray([float(r[col]) for r in wr])-exp;water[key]={'mean_error_kcal_mol':float(err.mean()),'mae_kcal_mol':float(np.mean(np.abs(err))),'rmse_kcal_mol':float(np.sqrt(np.mean(err*err)))}
        p=cand/'g4-mechanism-synthesis.json'
        try:d=json.loads(p.read_text(encoding='utf-8'))
        except Exception as e:raise CandidateError(f'g4-mechanism-synthesis.json malformed: {e}') from e
        if not isinstance(d,dict):raise CandidateError('g4-mechanism-synthesis.json must be an object')
        errors=[]; binds=d.get('source_bindings');cc=d.get('computed_cross_checks')
        if not isinstance(binds,dict):raise CandidateError('source_bindings must be an object')
        for name,path in assets.items():
            actual=_sha(path)
            if binds.get(name)!=actual:errors.append({'field':'source_bindings.'+name,'reported':binds.get(name),'expected':actual})
        if not isinstance(cc,dict):raise CandidateError('computed_cross_checks must be an object')
        if type(cc.get('native_trace_rows')) is not int or cc.get('native_trace_rows')!=len(trace['time_ps']):errors.append({'field':'native_trace_rows','reported':cc.get('native_trace_rows'),'expected':len(trace['time_ps'])})
        c2=cc.get('case02')
        if not isinstance(c2,dict): raise CandidateError('computed_cross_checks.case02 must be an object')
        models=c2.get('models',{})
        if not isinstance(models,dict): raise CandidateError('computed_cross_checks.case02.models must be an object')
        for mid,val in model_grad.items():
            item=models.get(mid,{}) if isinstance(models,dict) else {}
            if not isinstance(item,dict): raise CandidateError(f'computed_cross_checks.case02.models.{mid} must be an object')
            if type(item.get('frame_count')) is not int or item.get('frame_count')!=64 or not isinstance(item.get('median_abs_descriptor_gradient'),(int,float)) or isinstance(item.get('median_abs_descriptor_gradient'),bool) or not math.isfinite(float(item['median_abs_descriptor_gradient'])) or not _near(item['median_abs_descriptor_gradient'],val,2e-5):errors.append({'field':f'case02.models.{mid}','reported':item,'expected_median_abs_gradient':val})
        pair_section=c2.get('native_pairwise_pearson',{})
        if not isinstance(pair_section,dict): raise CandidateError('computed_cross_checks.case02.native_pairwise_pearson must be an object')
        for k,v in pairs.items():
            got=pair_section.get(k)
            if not isinstance(got,(int,float)) or isinstance(got,bool) or not math.isfinite(float(got)) or not _near(got,v,1e-6):errors.append({'field':'case02.native_pairwise_pearson.'+k,'reported':got,'expected':v})
        c4=cc.get('case04')
        if not isinstance(c4,dict): raise CandidateError('computed_cross_checks.case04 must be an object')
        j=c4.get('join_counts',{})
        if not isinstance(j,dict): raise CandidateError('computed_cross_checks.case04.join_counts must be an object')
        expected_delta=np.asarray([abs(float(r['native_colvar_time_delta_ps'])) for r in table])
        for k,v in {'matched_frames':8834,'unmatched_frames':0,'unique_time_join':True}.items():
            valid=(j.get(k) is v) if isinstance(v,bool) else (type(j.get(k)) is int and j.get(k)==v)
            if not valid:errors.append({'field':'case04.join_counts.'+k,'reported':j.get(k),'expected':v})
        for k,v in [('max_abs_delta_ps',float(expected_delta.max())),('p95_abs_delta_ps',float(np.quantile(expected_delta,.95)))]:
            got=j.get(k)
            if not isinstance(got,(int,float)) or isinstance(got,bool) or not math.isfinite(float(got)) or not _near(got,v,1e-6):errors.append({'field':'case04.join_counts.'+k,'reported':got,'expected':v})
        essobj=c4.get('ESS',{})
        if not isinstance(essobj,dict): raise CandidateError('computed_cross_checks.case04.ESS must be an object')
        for k,v in {'all_frames':states['all_frames'],'bound_like':float(wt[bound].sum()**2/np.sum(wt[bound]**2)),'unbound_like':float(wt[unbound].sum()**2/np.sum(wt[unbound]**2))}.items():
            got=essobj.get(k)
            if not isinstance(got,(int,float)) or isinstance(got,bool) or not math.isfinite(float(got)) or not _near(got,v,2e-5):errors.append({'field':'case04.ESS.'+k,'reported':got,'expected':v})
        c4ws=c4.get('weighted_states',{}) if isinstance(c4,dict) else {}
        if not isinstance(c4ws,dict): raise CandidateError('computed_cross_checks.case04.weighted_states must be an object')
        state_masks={'bound_like':bound,'unbound_like':unbound,'intermediate':~(bound|unbound)}
        for name,mask in state_masks.items():
            rep=c4ws.get(name,{}) if isinstance(c4ws,dict) else {}
            mass=float(wt[mask].sum()); den=float(np.sum(wt[mask]**2))
            expected_state={'frame_count':int(mask.sum()),'normalized_weight_mass':mass,
                'conditional_weighted_cavity_count_mean':float(np.dot(wt[mask],cavity[mask])/mass) if mass else None,
                'conditional_weighted_bridge_frame_fraction':float(wt[mask&(bridge>0)].sum()/mass) if mass else None,
                'effective_sample_size':float(mass*mass/den) if den else 0.0}
            if not isinstance(rep,dict): errors.append({'field':f'case04.weighted_states.{name}','reported':'missing'}); continue
            for k,v in expected_state.items():
                if v is None:
                    if rep.get(k) is not None: errors.append({'field':f'case04.weighted_states.{name}.{k}','reported':rep.get(k),'expected':None})
                elif not _numeric_matches(f'case04.weighted_states.{name}.{k}',rep.get(k),v):
                    errors.append({'field':f'case04.weighted_states.{name}.{k}','reported':rep.get(k),'expected':v})
        if c4ws.get('cavity_water_count_range')!=[int(cavity.min()),int(cavity.max())]: errors.append({'field':'case04.weighted_states.cavity_water_count_range','expected':[int(cavity.min()),int(cavity.max())]})
        dist=c4ws.get('cavity_occupancy_weighted_distribution',{})
        expdist={str(n):float(wt[cavity==n].sum()) for n in range(int(cavity.min()),int(cavity.max())+1)}
        if not isinstance(dist,dict) or set(dist)!=set(expdist): errors.append({'field':'case04.weighted_states.cavity_occupancy_weighted_distribution.keys','expected':sorted(expdist)})
        else:
            for k,v in expdist.items():
                if not _numeric_matches(f'case04.weighted_states.cavity_occupancy_weighted_distribution.{k}',dist[k],v): errors.append({'field':f'case04.weighted_states.cavity_occupancy_weighted_distribution.{k}','reported':dist[k],'expected':v})
        expected_mean=float(np.dot(wt,cavity))
        if not isinstance(c4ws.get('cavity_occupancy_weighted_mean'),(int,float)) or isinstance(c4ws.get('cavity_occupancy_weighted_mean'),bool) or not _near(c4ws.get('cavity_occupancy_weighted_mean'),expected_mean,2e-5): errors.append({'field':'case04.weighted_states.cavity_occupancy_weighted_mean','expected':expected_mean})
        sens=c4.get('sensitivity')
        if not isinstance(sens,list) or len(sens)!=3: errors.append({'field':'case04.sensitivity','reported':'missing/wrong row count'})
        else:
            for si,burn in enumerate((0.,20000.,40000.)):
                mask=np.asarray([float(r['time_ps'])>=burn for r in table]); lw=beta*np.asarray([float(r['opes_bias_kJ_mol']) for r in table])[mask]; swt=np.exp(lw-lw.max()); swt/=swt.sum(); row=sens[si]
                if not isinstance(row,dict): errors.append({'field':f'case04.sensitivity[{si}]','reported':'not object'}); continue
                exp_s={'burn_in_ps':burn,'frame_count':int(mask.sum()),'weight_ess':float(1/np.sum(swt*swt)),'bound_like_weight_mass':float(swt[bound[mask]].sum()),'unbound_like_weight_mass':float(swt[unbound[mask]].sum()),'weighted_cavity_count_mean':float(np.dot(swt,cavity[mask])),'weighted_bridge_frame_fraction':float(swt[bridge[mask]>0].sum())}
                for k,v in exp_s.items():
                    got=row.get(k)
                    if not _numeric_matches(f'case04.sensitivity[{si}].{k}',got,v): errors.append({'field':f'case04.sensitivity[{si}].{k}','reported':got,'expected':v})
        # Verify the same three preregistered burn-in rows as Case04.
        sens=c4.get('sensitivity') if isinstance(c4,dict) else None
        if not isinstance(sens,list) or len(sens)!=3: errors.append({'field':'case04.sensitivity','reported':'missing/wrong row count'})
        else:
            for si,burn in enumerate((0.,20000.,40000.)):
                m=np.asarray([float(r['time_ps'])>=burn for r in table]); lw=beta*np.asarray([float(r['opes_bias_kJ_mol']) for r in table])[m]; ww=np.exp(lw-lw.max()); ww/=ww.sum()
                exp_s={'burn_in_ps':burn,'frame_count':int(m.sum()),'weight_ess':float(1/np.sum(ww*ww)),'bound_like_weight_mass':float(ww[bound[m]].sum()),'unbound_like_weight_mass':float(ww[unbound[m]].sum()),'weighted_cavity_count_mean':float(np.dot(ww,cavity[m])),'weighted_bridge_frame_fraction':float(ww[bridge[m]>0].sum())}
                row=sens[si]
                if not isinstance(row,dict): errors.append({'field':f'case04.sensitivity[{si}]','reported':'not object'}); continue
                for k,v in exp_s.items():
                    got=row.get(k)
                    if not _numeric_matches(f'case04.sensitivity[{si}].{k}',got,v): errors.append({'field':f'case04.sensitivity[{si}].{k}','reported':got,'expected':v})
        th=cc.get('thermodynamics',{})
        if not isinstance(th,dict): errors.append({'field':'thermodynamics','reported':'non-object'}); th={}
        for name,expected in [('baseline_20ns',th20),('burn_in_sensitivity_30ns',th30)]:
            reported=th.get(name,{}) if isinstance(th,dict) else {}
            if not isinstance(reported,dict): raise CandidateError(f'computed_cross_checks.thermodynamics.{name} must be an object')
            for k,v in expected.items():
                got=reported.get(k)
                if not isinstance(got,(int,float)) or isinstance(got,bool) or not math.isfinite(float(got)) or not _near(got,v,2e-5):errors.append({'field':f'thermodynamics.{name}.{k}','reported':got,'expected':v})
        wm=cc.get('water_model_metrics',{})
        if not isinstance(wm,dict): raise CandidateError('computed_cross_checks.water_model_metrics must be an object')
        for key,expected in water.items():
            metrics=wm.get(key,{})
            if not isinstance(metrics,dict): raise CandidateError(f'computed_cross_checks.water_model_metrics.{key} must be an object')
            for k,v in expected.items():
                got=metrics.get(k)
                if not isinstance(got,(int,float)) or isinstance(got,bool) or not math.isfinite(float(got)) or not _near(got,v,2e-5):errors.append({'field':f'water_model_metrics.{key}.{k}','reported':got,'expected':v})
        crit['integrated_case02_case04_thermo_and_water_numeric_replay']={'status':'FAIL' if errors else 'JUDGE_REQUIRED','summary':'Recomputed source bindings, all three models’ descriptor-gradient summary, full-trace correlations, 8,834-frame constrained weights/ESS, 72-bin thermodynamic baseline and burn-in sensitivity, and six-ligand water-model metrics. Scientific stop/go remains open for review.','checked_values':{'mismatches':errors[:50],'model_gradient_medians':model_grad,'native_pairwise_pearson':pairs,'case04_summary':states,'thermo_baseline':th20,'thermo_sensitivity':th30,'water_model_metrics':water}}
        source_errors=[e for e in errors if e.get('field','').startswith('source_bindings.') or e.get('field')=='native_trace_rows']
        thermo_errors=[e for e in errors if e.get('field','').startswith('thermodynamics.')]
        geometry_errors=[e for e in errors if e.get('field','').startswith('case04.') or e.get('field','').startswith('water_model_metrics.')]
        crit['actual_bounded_analysis_and_source_provenance']={'status':'FAIL' if source_errors else 'PASS','summary':'Checked exact source bindings and native trace row count for the bounded archived analysis.','checked_values':{'errors':source_errors[:20],'source_bindings_checked':len(assets)}}
        crit['integrated_water_cv_decision_and_validation_limits']={'status':'JUDGE_REQUIRED','summary':'The integrated stop/hold and validation-limit interpretation remains for scientific review; numeric trace relationships were independently replayed.','checked_values':{'native_pairwise_pearson':pairs,'model_gradient_medians':model_grad}}
        crit['thermodynamic_sensitivity_units_and_sampling_scope']={'status':'FAIL' if thermo_errors else 'PASS','summary':'Recomputed the 72-bin baseline and declared 30 ns burn-in sensitivity from the trusted thermodynamic record; physical interpretation remains constrained to the declared protocol.','checked_values':{'errors':thermo_errors[:20],'baseline':th20,'sensitivity_30ns':th30}}
        crit['mechanism_geometry_and_water_model_uncertainty']={'status':'FAIL' if geometry_errors else 'PASS','summary':'Recomputed full-table constrained state/occupancy/bridge summaries and six-ligand water-model error metrics; scientific uncertainty interpretation remains open.','checked_values':{'errors':geometry_errors[:20],'case04_summary':states,'water_model_metrics':water}}
        crit['next_experiment_budget_stop_go_rationale']={'status':'JUDGE_REQUIRED','summary':'The next-experiment budget, ordered gates, stop/go rationale and falsifiers require scientific review.','checked_values':{'decision':d.get('scope_and_decision',{}).get('decision') if isinstance(d.get('scope_and_decision'),dict) else None}}
        # Accept a public-contract supporting-analysis script under its chosen
        # name. Never execute candidate code in the verifier.
        support=cand/'supporting-analysis'
        if support.is_symlink() or not support.is_dir():raise CandidateError('supporting-analysis directory missing/unsafe')
        scripts=[]
        for path in support.iterdir():
            if path.suffix.lower() not in {'.py','.sh','.r'}: continue
            if path.is_symlink() or not path.is_file():raise CandidateError(f'unsafe supporting analysis file: {path.name}')
            try: path.read_text(encoding='utf-8')
            except Exception as e:raise CandidateError(f'supporting analysis is not UTF-8 text: {path.name}: {e}') from e
            scripts.append(path)
        if not scripts:raise CandidateError('supporting-analysis must contain a UTF-8 .py, .sh, or .r script')
    except TrustedInputError as e:return {'status':'INFRA','criteria':crit,'error':str(e)}
    except CandidateError as e:return {'status':'FAIL','criteria':crit,'error':str(e)}
    except Exception as e:return {'status':'INFRA','criteria':crit,'error':f'trusted Case07 replay error: {e}'}
    return _result(crit)
