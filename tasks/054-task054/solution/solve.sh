#!/usr/bin/env bash
set -euo pipefail
OUT="${OUTPUT_DIR:-/app}"
ASSETS="${ASSETS:-/app/environment/assets}"
mkdir -p "$OUT"
python3 "$ASSETS/statistics_builder.py" "$OUT/statistics.json"
python3 - "$OUT" "$ASSETS" <<'PY'
import hashlib, importlib.util, json, math, pathlib, re, sys
out, a=map(pathlib.Path,sys.argv[1:])
stats=json.loads((out/'statistics.json').read_text())
meta=json.loads((a/'metadata.json').read_text())
src=a/'NeuralNetworkVes.cpp'; source=src.read_text(); sh=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source_lines=source.splitlines()
def source_anchor(pattern):
    hits=[i+1 for i,line in enumerate(source_lines) if re.search(pattern,line)]
    if len(hits)!=1: raise ValueError(f'expected one source anchor for {pattern!r}, found {len(hits)}')
    return hits[0]
cond=source_anchor(r'if\s*\(c_lr_scaling\s*<\s*5\.e-5\)\s*static_bias\s*=\s*true')
guard=source_anchor(r'if\s*\(!static_bias\)')
marker=source_anchor(r'//if static bias:')
static_branch=next((i+1 for i in range(marker, len(source_lines)) if source_lines[i].strip()),None)
if static_branch is None or source_lines[static_branch-1].strip() != '} else {': raise ValueError('static source marker is not followed by the static else entry')
step=source_anchor(r'nn_opt->step\(\)')
grid=source_anchor(r'bias_pot\s*=\s*grid_bias->getValueAndDerivatives\(cv,der\)')
decay=source_anchor(r'c_lr_scaling\s*\*=\s*o_decay')
if not cond<guard<step<decay or not decay<marker<static_branch<grid: raise ValueError('audited source anchors violate the expected control-flow order')
behavior={'source_sha256':sh(src),'comparison':'<','threshold':5e-5,'condition_line':cond,'optimizer_guard_line':guard,'optimizer_step_line':step,'static_branch_line':static_branch,'grid_read_line':grid,'lr_decay_line':decay,'boundary_semantics':'first_logged_below; static branch starts on next calculate call','inference_limit':'source/logs do not identify actual per-run PLUMED ARG configuration'}
metrics={}
def walk(o,p=''):
    if isinstance(o,dict):
        for k,v in o.items(): walk(v,p+'.'+k if p else k)
    elif isinstance(o,(int,float)) and not isinstance(o,bool): metrics[p]=o
walk(stats)
metrics['source_behavior.threshold']=behavior['threshold']
for run, rr in stats['runs'].items():
    for key, value in rr['reweight']['correlation_g'].items():
        if value is not None: metrics[f'runs.{run}.reweight.correlation_g.{key}']=value['g']
def evidence(run,window,path,op='eq',value=None):
    if window=='source': return {'input_sha256':behavior['source_sha256'],'run_id':'source','window':'source','metric_ref':path,'operator':'eq','value':behavior['threshold'],'row_start':604,'row_end':866,'time_start':None,'time_end':None}
    rr=stats['runs'][run]
    if window=='strict_static':
        start=rr['phase']['strict_static_first_below_index']+1; end=rr['frames']-1; t0=rr['phase']['logged_boundary_time']+rr['sample_interval']; t1=rr['time_range'][1]
    else:
        w=rr['windows'][window]; start=round((w['start']-rr['time_range'][0])/rr['sample_interval']); end=round((w['end']-rr['time_range'][0])/rr['sample_interval']); t0=w['start'];t1=w['end']
    v=metrics[path] if value is None else value
    return {'input_sha256':rr['input_sha256'],'run_id':run,'window':window,'metric_ref':path,'operator':op,'value':v,'row_start':int(start),'row_end':int(end),'time_start':t0,'time_end':t1}
def claim(cid,run,window,observable,unit,path,win_evidence=None):
    ref=evidence(run,window,path) if win_evidence is None else win_evidence
    return {'id':cid,'kind':'observation','scope':{'run_id':run,'window':window,'observable':observable,'unit':unit,'scope_limit':'single_trace_association_only'},'evidence':[ref],'assertion':{'left':path,'operator':'eq','right':{'metric_ref':path}},'inference':'observed'}
claims=[]
# Bind observations to the statistics produced from the current input files.
for run in ('run-A.csv','run-B.csv'):
    for win in ('pre_freeze','post_freeze'):
        path=f'runs.{run}.windows.{win}.crossing_proxy_rate_per_time'
        claims.append(claim(f'{run}-{win}-rate',run,win,'crossing_proxy_rate_per_time',f"1/{stats['runs'][run]['time_unit']}",path))
claims.append(claim('source-threshold','source','source','threshold','optimizer-scale','source_behavior.threshold',evidence('source','source','source_behavior.threshold')))
claims.append(claim('run-A-static-correlation','run-A.csv','strict_static','correlation_g.cv1','frames','runs.run-A.csv.reweight.correlation_g.cv1'))
claims.append(claim('run-A-pre-freeze-cv2-spread','run-A.csv','pre_freeze','cv2_sd','native-CV-unit','runs.run-A.csv.windows.pre_freeze.cv2_sd'))
def mref(run,key): return f'runs.{run}.{key}'
def intervention(iid,run,variable):
    rr=stats['runs'][run]; md=meta['runs'][run]; change='cv_definition' if variable=='cv' else 'freeze_rule'
    token=('add_predeclared_orthogonal_cv2' if run=='run-A.csv' else 'add_predeclared_complementary_periodic_cv2') if variable=='cv' else 'later_pre_registered_objective_gradient_trigger'
    freeze='same_pre_registered_objective_gradient_rule' if variable=='cv' else 'pre_registered_later_objective_gradient_rule'
    unit=f"1/{rr['time_unit']}"; primary=mref(run,'windows.post_freeze.crossing_proxy_rate_per_time')
    max_rate=1.0/(20*rr['sample_interval'])
    observed=rr['windows']['pre_freeze']['crossing_proxy_rate_per_time']
    effect=min(max(observed*0.5,max_rate*1e-6),max_rate*0.5)
    return {'id':iid,'run_id':run,'controls':{'temperature':md['temperature_K_or_natural'],'energy_unit':md['energy_unit'],'forcefield':'same_archived_forcefield_fingerprint_within_pair_exact_value_resolve_before_run','initial_state_protocol':'paired_same_coordinates_velocities_checkpoint','integrator_dt':'same_archived_timestep_within_pair_exact_value_resolve_before_run','target_distribution':'same_physical_target_and_thermostat','exposure':'equal_simulation_time_per_paired_seed','output_interval':'same_output_interval_per_paired_seed'},'arms':[{'id':'baseline','changed_variable':'baseline','value':'recover_source_ARG_config_before_execution'},{'id':'treatment','changed_variable':change,'value':token}],'cv_plan':{'baseline_status':'unidentified_until_original_input_recovered','coordinate_mapping':'source_native_cv2','periodic_embedding':'none' if run=='run-A.csv' else 'sin_cos','treatment_token':token},'freeze_criterion':{'metric':'relative_objective_gradient_norm','operator':'le','threshold':0.01,'persistence_evaluations':3,'baseline_time_fraction':0.5,'treatment_time_fraction':0.5 if variable=='cv' else 0.75},'paired_seed_ids':['paired-seed-1','paired-seed-2','paired-seed-3'],'freeze_rule':freeze,'window_rule':'equal_exposure_predefined_windows_with_late_sensitivity','primary_metric_ref':primary,'estimand':{'formula':'paired_mean_delta','unit':unit,'minimum_effect':0.0},'uncertainty':{'method':'paired_t_interval','alpha':0.05,'serial_block_rule':'block_within_seed_before_paired_seed_summary','minimum_independent_seeds':3},'prediction':{'direction':'increase','expected_effect':effect,'unit':unit},'decision':{'support_if':'95% paired interval clears expected_effect in predicted direction','refute_if':'95% paired interval lies inside the minimum-effect region','otherwise':'inconclusive'}}
ints=[intervention('add-cv2','run-A.csv','cv'),intervention('delay-freeze-A','run-A.csv','freeze'),intervention('delay-freeze-B','run-B.csv','freeze')]
preds=[('freeze-removes-adaptation','freeze_removes_adaptation','compatible','delay-freeze-A','delay_freeze','run-A.csv','crossing_proxy_rate_per_time','increase'),('orthogonal-slow-coordinate','orthogonal_slow_coordinate','not_identified','add-cv2','add_orthogonal_cv','run-A.csv','cv2_sd','increase'),('finite-sampling-correlation','finite_sampling_correlation','compatible','delay-freeze-A','delay_freeze','run-A.csv','correlation_g.cv1','increase'),('system-specific-dynamics','system_specific_dynamics','not_identified','delay-freeze-B','delay_freeze','run-B.csv','crossing_proxy_rate_per_time','either')]
hyp=[]
for hid,mech,status,iid,change,run,obs,direction in preds:
    if mech=='freeze_removes_adaptation':
        p1=mref(run,'windows.pre_freeze.crossing_proxy_rate_per_time'); p2=mref(run,'windows.post_freeze.crossing_proxy_rate_per_time')
        measure={p1:metrics[p1],p2:metrics[p2]}
    elif mech=='orthogonal_slow_coordinate':
        p=mref(run,'windows.pre_freeze.cv2_sd'); measure={p:metrics[p]}
    elif mech=='finite_sampling_correlation':
        p=mref('run-A.csv','reweight.correlation_g.cv1'); measure={p:metrics[p]}
    else:
        pa=mref('run-A.csv','windows.pre_freeze.crossing_proxy_rate_per_time'); pb=mref('run-B.csv','windows.pre_freeze.crossing_proxy_rate_per_time'); measure={pa:metrics[pa],pb:metrics[pb]}
    ci='source-threshold' if mech=='freeze_removes_adaptation' else f'{run}-pre_freeze-rate'
    linked=[ci]
    if mech=='freeze_removes_adaptation': linked=['source-threshold','run-A.csv-pre_freeze-rate','run-A.csv-post_freeze-rate']
    if mech=='orthogonal_slow_coordinate': linked=['run-A-pre-freeze-cv2-spread']
    if mech=='finite_sampling_correlation': linked=['run-A-static-correlation']
    if mech=='system_specific_dynamics': linked=['run-A.csv-pre_freeze-rate','run-B.csv-pre_freeze-rate']
    if mech=='freeze_removes_adaptation':
        status='compatible' if measure[p2] < measure[p1] else 'not_identified'
    elif mech=='finite_sampling_correlation':
        status='compatible' if stats['runs']['run-A.csv']['reweight']['support_status']=='insufficient' else 'not_identified'
    outcome={'freeze_removes_adaptation':'supports','orthogonal_slow_coordinate':'supports','finite_sampling_correlation':'weakens','system_specific_dynamics':'remains_unresolved'}[mech]
    hyp.append({'id':hid,'mechanism':mech,'status':status,'evidence_claim_ids':linked,'competes_with':[x[0] for x in preds if x[0]!=hid],'measurement_ref':measure,'prediction':{'intervention_id':iid,'change_factor':change,'observable_ref':next(i['primary_metric_ref'] for i in ints if i['id']==iid),'direction':direction,'discriminating_outcome':outcome}})
# Recompute legal event/window sensitivities from each CSV through the public builder API.
spec=importlib.util.spec_from_file_location('builder',a/'statistics_builder.py'); b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
alts=[]
for run,threshold,dwell,scale in [('run-A.csv',0.6,20,1.0),('run-B.csv',0.5,30,1.0)]:
    arr,dt=b.read_trace(a/run); alt={'id':run.replace('.csv','')+'-sensitivity','run_id':run,'event_core_threshold':threshold,'dwell_frames':dwell,'window_scale':scale}
    alt.update(b.alternative_sensitivity(run,arr,alt)); alts.append(alt)
contract={'schema':'deepves-case06-analysis/v2','input_sha256':{r:stats['runs'][r]['input_sha256'] for r in ('run-A.csv','run-B.csv')},'source_behavior':behavior,'claims':claims,'hypotheses':hyp,'interventions':ints,'alternative_sensitivities':alts,'renderer_version':'case06-canonical-md/v2'}
(out/'analysis-contract.json').write_text(json.dumps(contract,indent=2,allow_nan=False)+'\n')
PY
python3 "$ASSETS/render_contract.py" "$OUT/analysis-contract.json" --diagnosis "$OUT/diagnosis.md" --intervention "$OUT/intervention.md"
